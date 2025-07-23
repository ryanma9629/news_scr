import asyncio
import logging
from typing import List, Literal, Optional

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.vectorstores import InMemoryVectorStore, VectorStore
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration constants
DEFAULT_MAX_CONCURRENCY = 3
DEFAULT_K = 3
MIN_CONTENT_LENGTH = 10
DEFAULT_CRIME_TYPE = "Not suspected"
DEFAULT_PROBABILITY = "low"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 100


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

        self.tagging_llm = self.llm.with_structured_output(FinancialCrime, strict=True)
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
            Dictionary containing crime_type and probability
        """
        # Input validation
        if not doc or not doc.page_content or not doc.page_content.strip():
            logger.warning("Empty or invalid document content")
            return {"crime_type": DEFAULT_CRIME_TYPE, "probability": DEFAULT_PROBABILITY}
        
        if len(doc.page_content.strip()) < MIN_CONTENT_LENGTH:
            logger.warning("Document content too short to analyze")
            return {"crime_type": DEFAULT_CRIME_TYPE, "probability": DEFAULT_PROBABILITY}
        
        try:
            tag = await self.tagging_chain.ainvoke({"input": doc.page_content})
        except Exception as e:
            logger.error(f"Error tagging single document: {e}")
            return {"crime_type": DEFAULT_CRIME_TYPE, "probability": DEFAULT_PROBABILITY}

        if not isinstance(tag, FinancialCrime):
            logger.error("LLM response is not a valid FinancialCrime instance")
            return {"crime_type": DEFAULT_CRIME_TYPE, "probability": DEFAULT_PROBABILITY}

        return tag.model_dump(mode="json")

    async def _tag_batch(self, docs: List[Document], max_concurrency: Optional[int] = None) -> List[dict]:
        """
        Tag multiple documents in batch for financial crime detection.
        
        Args:
            docs: List of documents to analyze
            max_concurrency: Maximum number of concurrent requests
            
        Returns:
            List of dictionaries containing crime_type and probability for each document
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
            return [{"crime_type": DEFAULT_CRIME_TYPE, "probability": DEFAULT_PROBABILITY} for _ in docs]

        try:
            self._validate_tags(tags)
        except ValueError as e:
            logger.error(f"Tag validation failed: {e}")
            return [{"crime_type": DEFAULT_CRIME_TYPE, "probability": DEFAULT_PROBABILITY} for _ in docs]

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
            Dictionary containing combined crime_type and probability assessment
            
        Raises:
            ValueError: If document list is empty
        """
        if not docs:
            logger.warning("Empty document list provided to tagging_combine")
            return {"crime_type": DEFAULT_CRIME_TYPE, "probability": DEFAULT_PROBABILITY}
            
        medium_proba_types = set()
        high_proba_types = set()

        tags = await self._tag_batch(docs)
        for tag in tags:
            crime_type = tag.get("crime_type")
            if crime_type == DEFAULT_CRIME_TYPE:
                continue
                
            probability = tag.get("probability")
            if probability == "medium":
                medium_proba_types.add(crime_type)
            elif probability == "high":
                high_proba_types.add(crime_type)

        if high_proba_types:
            return {"crime_type": ", ".join(sorted(high_proba_types)), "probability": "high"}
        elif medium_proba_types:
            return {
                "crime_type": ", ".join(sorted(medium_proba_types)),
                "probability": "medium",
            }
        else:
            return {"crime_type": DEFAULT_CRIME_TYPE, "probability": DEFAULT_PROBABILITY}

    async def tagging_rag(
        self,
        docs: Optional[List[Document]] = None,
        vectordb: Optional[VectorStore] = None,
        filter: Optional[dict] = None,
        k: Optional[int] = None,
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
            
        Returns:
            Dictionary containing crime_type and probability assessment
            
        Raises:
            ValueError: If neither docs nor vectordb are provided
        """
        if k is None:
            k = DEFAULT_K

        if not docs and not vectordb:
            raise ValueError("At least one of 'docs' or 'vectordb' must be provided.")

        tagging_query = """
Is this company suspected of financial crimes? Such as money laundering,
financial fraud, counterfeiting currency/financial instruments, illegal
absorption of public deposits, illegal granting of loans, insider trading,
manipulation of securities markets?
"""
        if not vectordb:  # not provided, use a temporary in-memory vector db
            if not docs:
                raise ValueError("docs cannot be None when vectordb is not provided")
            vectordb = InMemoryVectorStore(self.emb)
            await vectordb.aadd_documents(docs)
            retriever = vectordb.as_retriever(search_type="mmr", search_kwargs={"k": k})
        else:
            retriever = vectordb.as_retriever(
                search_type="mmr", search_kwargs={"filter": filter, "k": k}
            )

        retrieved_docs = await retriever.ainvoke(tagging_query)

        if retrieved_docs:
            return await self.tagging_combine(retrieved_docs)
        else:  # fallback
            if not docs:
                raise ValueError("docs cannot be None when fallback is needed")
            return await self.tagging_combine(docs)


if __name__ == "__main__":
    import asyncio
    import sys
    from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from crawler import ApifyCrawler

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

        apify_crawler = ApifyCrawler()
        doc = asyncio.run(
            apify_crawler.get(
                [
                    "https://www.investopedia.com/articles/investing/020116/theranos-fallen-unicorn.asp"
                ]
            )
        )

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        all_chunks = text_splitter.split_documents(doc)

        fctagging = FCTagging(llm, emb)

        # Debug output - uncomment for testing
        # print("tagging a single chunk...")
        tag = asyncio.run(fctagging._tag_single(all_chunks[0]))
        # print(tag)

        # print("\ntagging all chunks...")
        tags = asyncio.run(fctagging._tag_batch(all_chunks))
        # print(tags)

        # print("\ntagging all chunks and combine the result...")
        tags = asyncio.run(fctagging.tagging_combine(all_chunks))
        # print(tags)

        # print("\ntagging with RAG...")
        tags = asyncio.run(fctagging.tagging_rag(all_chunks))
        # print(tags)
        
        # Results available for testing
        _ = tag, tags

    main()
