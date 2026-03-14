"""
Financial crime tagging implementations using LLMs.

This module provides functionality to analyze documents and identify potential
financial crimes using language models and vector search capabilities.
"""

__all__ = ["FinancialCrime", "FCTagging"]

import asyncio
import sys
from typing import List, Literal, Optional

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.vectorstores import VectorStore
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field

from .config import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_K,
    MIN_CONTENT_LENGTH,
    DEFAULT_CRIME_TYPE,
    DEFAULT_PROBABILITY,
    DEFAULT_DESCRIPTION,
    MAX_DESCRIPTION_LENGTH,
)
from .logging_config import get_logger
from .vector_store import get_company_chroma_store, setup_vector_store


# Load environment variables
load_dotenv()

# Initialize logger using shared configuration
logger = get_logger(__name__)

# Default tag values for error/edge cases
DEFAULT_TAG_RESULT = {
    "crime_type": DEFAULT_CRIME_TYPE,
    "probability": DEFAULT_PROBABILITY,
    "description": DEFAULT_DESCRIPTION,
}


def _get_default_tag_result() -> dict:
    """Return a copy of the default tag result for error/edge cases."""
    return DEFAULT_TAG_RESULT.copy()


class FinancialCrime(BaseModel):
    """
    Pydantic model for financial crime classification.

    This model represents the result of financial crime analysis,
    including the type of crime suspected and the probability level.
    """

    crime_type: Literal[
        "Not suspected",
        "Money Laundering",
        "Financial Fraud",
        "Counterfeiting Currency/Financial Instruments",
        "Illegal Absorption of Public Deposits",
        "Illegal Granting of Loans",
        "Insider Trading",
        "Manipulation of Securities Markets",
    ] = Field(
        ...,
        description="""
Describes the specific type of financial crime this company is suspected of
committing, or returns the type 'Not suspected' if not suspected.
""",
    )

    probability: Literal["low", "medium", "high"] = Field(
        ...,
        description="""
Describes the probability that this company is suspected of financial crimes,
This refers specifically to financial crimes and not to other types of crime.
""",
    )

    description: Optional[str] = Field(
        None,
        description="""
A very short description (1-2 sentences) explaining why this document is 
classified as suspected of financial crime. Only provide this when probability 
is 'medium' or 'high'. Leave as None for 'low' probability or 'Not suspected'.
""",
    )


class FCTagging:
    """
    Financial Crime Tagging system using LLM for document classification.

    This class provides methods to analyze documents and identify potential
    financial crimes using language models and vector search capabilities.
    """

    TAGGING_PROMPT = ChatPromptTemplate.from_template(
        """
You are an expert financial crime analyst. Analyze the following passage and determine:
1. Whether the company is suspected of financial crimes
2. The specific type of financial crime (if any)
3. The probability level of the suspicion
4. If probability is 'medium' or 'high', provide a very short description (1-2 sentences) explaining why

Consider the following financial crime types:
- Money Laundering
- Financial Fraud  
- Counterfeiting Currency/Financial Instruments
- Illegal Absorption of Public Deposits
- Illegal Granting of Loans
- Insider Trading
- Manipulation of Securities Markets

Only extract the properties mentioned in the 'FinancialCrime' function.
Provide your analysis based on concrete evidence from the text.

For the description field:
- Only provide a description when probability is 'medium' or 'high'
- Keep it very brief (1-2 sentences maximum)
- Focus on the specific evidence or indicators that led to the classification
- Leave as None/null for 'low' probability or 'Not suspected' cases

Passage:
------------
{input}
------------
"""
    )

    def __init__(
        self,
        llm: BaseChatModel,
        emb: Embeddings,
    ) -> None:
        """
        Initialize the FCTagging system.

        Args:
            llm: Language model for tagging
            emb: Embedding model for vector operations
        """
        self.llm = llm
        self.emb = emb

        # Check if the LLM supports strict mode (Azure OpenAI models do, but Qwen/ChatTongyi doesn't)
        try:
            # Try with strict=True first (for models that support it like Azure OpenAI)
            self.tagging_llm = self.llm.with_structured_output(FinancialCrime, strict=True)
        except (TypeError, ValueError) as e:
            # Fall back to without strict mode for models that don't support it (like Qwen)
            if "strict" in str(e):
                logger.info(f"LLM doesn't support strict mode, falling back to non-strict: {type(self.llm).__name__}")
                self.tagging_llm = self.llm.with_structured_output(FinancialCrime)
            else:
                raise e
        
        self.tagging_chain = self.TAGGING_PROMPT | self.tagging_llm

    def _validate_tags(self, tags: List) -> None:
        """
        Validate that tags are valid FinancialCrime instances.

        Args:
            tags: List of tags to validate

        Raises:
            ValueError: If any tag is not a valid FinancialCrime instance
        """
        if not all(isinstance(tag, FinancialCrime) for tag in tags):
            raise ValueError(
                "LLM response is not a valid Pydantic(Financial Crime) class."
            )

    async def _tag_single(self, doc: Document) -> dict:
        """
        Tag a single document for financial crime detection.

        Args:
            doc: Document to analyze

        Returns:
            Dictionary containing crime_type, probability, and description (if applicable)
        """
        # Input validation
        if not doc or not doc.page_content or not doc.page_content.strip():
            logger.warning("Empty or invalid document content")
            return _get_default_tag_result()

        if len(doc.page_content.strip()) < MIN_CONTENT_LENGTH:
            logger.warning("Document content too short to analyze")
            return _get_default_tag_result()

        try:
            tag = await self.tagging_chain.ainvoke({"input": doc.page_content})
        except Exception as e:
            logger.error(f"Error tagging single document: {e}")
            return _get_default_tag_result()

        if not isinstance(tag, FinancialCrime):
            logger.error("LLM response is not a valid FinancialCrime instance")
            return _get_default_tag_result()

        return tag.model_dump(mode="json")

    async def _tag_batch(
        self, docs: List[Document], max_concurrency: Optional[int] = None
    ) -> List[dict]:
        """
        Tag multiple documents in batch for financial crime detection.

        Args:
            docs: List of documents to analyze
            max_concurrency: Maximum number of concurrent requests

        Returns:
            List of dictionaries containing crime_type, probability, and description for each document
        """
        if not docs:
            logger.warning("Empty document list provided")
            return []

        if max_concurrency is None:
            max_concurrency = DEFAULT_MAX_CONCURRENCY

        try:
            tags = await self.tagging_chain.abatch(
                [{"input": doc.page_content} for doc in docs],
                config={"max_concurrency": max_concurrency},
            )
        except Exception as e:
            logger.error(f"Error tagging batch documents: {e}")
            return [_get_default_tag_result() for _ in docs]

        try:
            self._validate_tags(tags)
        except ValueError as e:
            logger.error(f"Tag validation failed: {e}")
            return [_get_default_tag_result() for _ in docs]

        return [tag.model_dump(mode="json") for tag in tags]  # type: ignore

    async def tagging_combine(
        self,
        docs: List[Document],
    ) -> dict:
        """
        Combine multiple document tagging results into a final assessment.

        Args:
            docs: List of documents to analyze

        Returns:
            Dictionary containing combined crime_type, probability, and description assessment

        Raises:
            ValueError: If document list is empty
        """
        if not docs:
            logger.warning("Empty document list provided to tagging_combine")
            return _get_default_tag_result()

        medium_proba_types = set()
        high_proba_types = set()
        medium_descriptions = []
        high_descriptions = []

        tags = await self._tag_batch(docs)
        for tag in tags:
            crime_type = tag.get("crime_type")
            if crime_type == DEFAULT_CRIME_TYPE:
                continue

            probability = tag.get("probability")
            description = tag.get("description")
            
            if probability == "medium":
                medium_proba_types.add(crime_type)
                if description:
                    medium_descriptions.append(description)
            elif probability == "high":
                high_proba_types.add(crime_type)
                if description:
                    high_descriptions.append(description)

        if high_proba_types:
            # Generate final description using LLM for high probability cases
            combined_description = await self._generate_final_description(
                high_descriptions, high_proba_types, "high"
            ) if high_descriptions else None
            return {
                "crime_type": ", ".join(sorted(high_proba_types)),
                "probability": "high",
                "description": combined_description,
            }
        elif medium_proba_types:
            # Generate final description using LLM for medium probability cases
            combined_description = await self._generate_final_description(
                medium_descriptions, medium_proba_types, "medium"
            ) if medium_descriptions else None
            return {
                "crime_type": ", ".join(sorted(medium_proba_types)),
                "probability": "medium",
                "description": combined_description,
            }
        else:
            return _get_default_tag_result()

    async def tagging_rag(
        self,
        docs: Optional[List[Document]] = None,
        vectordb: Optional[VectorStore] = None,
        filter: Optional[dict] = None,
        k: Optional[int] = None,
        company_name: Optional[str] = None,
        lang: Optional[str] = None,
    ) -> dict:
        """
        Perform financial crime tagging using Retrieval-Augmented Generation (RAG).

        This method uses vector similarity search to find the most relevant documents
        for financial crime detection, then performs tagging on those documents.

        Args:
            docs: Optional list of documents to use for creating temporary vector store
            vectordb: Optional pre-existing vector store to search from
            filter: Optional filter to apply during vector search
            k: Number of documents to retrieve (defaults to DEFAULT_K)
            company_name: Optional company name for persistent vector store scoping
            lang: Optional language for persistent vector store scoping

        Returns:
            Dictionary containing crime_type, probability, and description assessment

        Raises:
            ValueError: If neither docs nor vectordb are provided
        """
        if k is None:
            k = DEFAULT_K

        tagging_query = """
Is this company suspected of financial crimes? Such as money laundering,
financial fraud, counterfeiting currency/financial instruments, illegal
absorption of public deposits, illegal granting of loans, insider trading,
manipulation of securities markets?
"""
        # Set up vector store using shared utility
        vectordb, _ = await setup_vector_store(
            docs=docs,
            embedding_function=self.emb,
            vectordb=vectordb,
            company_name=company_name,
            lang=lang,
        )

        retriever = vectordb.as_retriever(
            search_type="mmr",
            search_kwargs={"filter": filter, "k": k} if filter else {"k": k}
        )

        retrieved_docs = await retriever.ainvoke(tagging_query)

        if retrieved_docs:
            return await self.tagging_combine(retrieved_docs)
        elif docs:
            return await self.tagging_combine(docs)
        else:
            raise ValueError("No documents available for tagging")

    async def _generate_final_description(self, descriptions: List[str], crime_types: set, probability: str) -> Optional[str]:
        """
        Generate a final consolidated description using LLM based on individual descriptions.

        Args:
            descriptions: List of individual descriptions from document analysis
            crime_types: Set of identified crime types
            probability: Probability level (medium or high)

        Returns:
            A short consolidated description (1-2 sentences) or None if no descriptions provided
        """
        if not descriptions:
            return None
        
        # Create a simple prompt for description consolidation
        consolidation_prompt = f"""
You are a financial crime analyst. Based on the following individual analysis results, 
provide a single, concise summary (1-2 sentences maximum) explaining why this entity 
is suspected of {', '.join(sorted(crime_types))} with {probability} probability.

Individual descriptions:
{chr(10).join(f"- {desc}" for desc in descriptions)}

Provide a brief, consolidated explanation that captures the key evidence:
"""
        
        try:
            # Use the LLM directly for text generation instead of structured output
            response = await self.llm.ainvoke(consolidation_prompt)
            
            # Extract text content from the response
            if hasattr(response, 'content'):
                content = response.content
                if isinstance(content, list):
                    # Join list elements if content is a list
                    final_description = ' '.join(str(item) for item in content).strip()
                else:
                    final_description = str(content).strip()
            else:
                final_description = str(response).strip()
            
            # Ensure it's not too long (limit to roughly 2 sentences)
            if len(final_description) > MAX_DESCRIPTION_LENGTH:
                # Take first two sentences approximately
                sentences = final_description.split('. ')
                if len(sentences) >= 2:
                    final_description = '. '.join(sentences[:2]) + '.'
                else:
                    final_description = sentences[0]
            
            return final_description if final_description else None
            
        except Exception as e:
            logger.error(f"Error generating final description: {e}")
            # Fallback to simple concatenation if LLM fails
            return "; ".join(descriptions[:2])  # Take first 2 descriptions as fallback


if __name__ == "__main__":
    import pickle

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    def main():
        """Main function to demonstrate the financial crime tagging functionality."""
        llm = AzureChatOpenAI(
            azure_deployment="gpt-4o-mini",
            model="gpt-4o-mini",
            temperature=0,
        )
        emb = AzureOpenAIEmbeddings(azure_deployment="text-embedding-3-small")

        doc = pickle.load(open("sample_doc.pkl", "rb"))

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=100
        )
        all_chunks = text_splitter.split_documents(doc)

        fctagging = FCTagging(llm, emb)

        # Debug output - uncomment for testing
        print("tagging a single chunk...")
        tag = asyncio.run(fctagging._tag_single(all_chunks[0]))
        print(tag)

        print("\ntagging all chunks...")
        tags = asyncio.run(fctagging._tag_batch(all_chunks))
        print(tags)

        print("\ntagging all chunks and combine the result...")
        tags = asyncio.run(fctagging.tagging_combine(all_chunks))
        print(tags)

        print("\ntagging with RAG...")
        tags = asyncio.run(fctagging.tagging_rag(all_chunks))
        print(tags)


    main()
