import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from typing import List, Optional, TypedDict

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.vectorstores import InMemoryVectorStore, VectorStore
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import START, StateGraph

from .crawler import ApifyCrawler

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration constants
DEFAULT_RETRIEVAL_COUNT = 3
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_TEMPERATURE = 0.0
DEFAULT_DOC_SEPARATOR = "\n\n"

# Error messages
NO_CONTEXT_MESSAGE = "I don't have enough information to answer this question."
GENERATION_ERROR_MESSAGE = "I'm unable to generate an answer at this time."
TECHNICAL_ERROR_MESSAGE = (
    "I'm unable to process your question due to a technical issue. Please try again."
)

# Prompt templates
SYSTEM_PROMPT_TEMPLATE = """Use the following pieces of context to answer the question at the end.
If you don't know the answer, just say that you don't know, don't try to make up an answer.
Keep the answer as concise as possible. Make your response in {lang}.
------------
Context: 
{context}
------------
Question:
{question}
------------
"""


# Define State type at module level
class QAState(TypedDict):
    question: str
    context: List[Document]
    answer: str
    urls: List[str]


class QA(ABC):
    """
    Abstract base class for question-answering systems.

    This class provides a common interface for different QA implementations,
    defining the basic structure and required methods.
    """

    def __init__(self, llm: BaseChatModel, emb: Embeddings) -> None:
        """
        Initialize the QA system with language model and embeddings.

        Args:
            llm: The language model for generating responses
            emb: The embeddings model for vector operations
        """
        super().__init__()
        self.llm = llm
        self.emb = emb

    @abstractmethod
    async def query(self, query: str, lang: str) -> dict:
        """
        Process a query and return an answer.

        Args:
            query: The question to be answered
            lang: The language for the response

        Returns:
            Dictionary containing the query result with question, answer, and source URLs

        Raises:
            NotImplementedError: This method must be implemented by subclasses
        """
        raise NotImplementedError


class QAWithContext(QA):
    """
    Question-answering system with context-based retrieval.

    This implementation uses vector similarity search to find relevant context
    and generates answers based on the retrieved documents.
    """

    def __init__(self, llm: BaseChatModel, emb: Embeddings) -> None:
        """
        Initialize the context-based QA system.

        Args:
            llm: The language model for generating responses
            emb: The embeddings model for vector operations
        """
        super().__init__(llm, emb)
        self._qa_prompt = self._create_qa_prompt()

    def _create_qa_prompt(self) -> ChatPromptTemplate:
        """
        Create the prompt template for question answering.

        Returns:
            ChatPromptTemplate: The configured prompt template
        """
        return ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT_TEMPLATE)])

    async def _setup_vectordb(
        self, docs: Optional[List[Document]], vectordb: Optional[VectorStore]
    ) -> tuple[VectorStore, Optional[dict]]:
        """
        Set up the vector database for document retrieval.

        Args:
            docs: List of documents to add to the vector database
            vectordb: Existing vector database (optional)

        Returns:
            Tuple of (vectordb, filter) where filter is None if vectordb was created

        Raises:
            ValueError: If both docs and vectordb are None
        """
        if not docs and not vectordb:
            raise ValueError("At least one of 'docs' or 'vectordb' must be provided.")

        if not vectordb:
            logger.info("Creating new InMemoryVectorStore")
            vectordb = InMemoryVectorStore(self.emb)
            if docs:
                await vectordb.aadd_documents(docs)
            return vectordb, None

        return vectordb, {}

    def _create_retrieve_function(
        self,
        vectordb: VectorStore,
        filter_dict: Optional[dict],
        k: Optional[int] = None,
    ):
        """
        Create the retrieve function for the workflow.

        Args:
            vectordb: The vector database to search
            filter_dict: Optional filter for search
            k: Number of documents to retrieve

        Returns:
            Function that retrieves relevant documents
        """
        if k is None:
            k = DEFAULT_RETRIEVAL_COUNT

        async def retrieve(state: QAState):
            try:
                # Use async version of vector search if available
                if hasattr(vectordb, "amax_marginal_relevance_search"):
                    retrieved_docs = await vectordb.amax_marginal_relevance_search(
                        state["question"], k=k, filter=filter_dict
                    )
                else:
                    # Fallback to sync version in thread pool
                    retrieved_docs = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: vectordb.max_marginal_relevance_search(
                            state["question"], k=k, filter=filter_dict
                        ),
                    )
                
                # Extract unique URLs from document metadata
                urls = []
                seen_urls = set()
                for doc in retrieved_docs:
                    # Try different common metadata keys for URL
                    url = (
                        doc.metadata.get("source") or 
                        doc.metadata.get("url") or 
                        doc.metadata.get("link") or
                        doc.metadata.get("source_url")
                    )
                    if url and url not in seen_urls:
                        urls.append(url)
                        seen_urls.add(url)
                
                logger.info(f"Retrieved {len(retrieved_docs)} documents from {len(urls)} unique sources")
                return {"context": retrieved_docs, "urls": urls}
            except Exception as e:
                logger.error(f"Error during document retrieval: {e}")
                return {"context": [], "urls": []}

        return retrieve

    def _create_generate_function(self, lang: str):
        """
        Create the generate function for the workflow.

        Args:
            lang: The language for the response

        Returns:
            Function that generates answers from context
        """
        qa_prompt = self._qa_prompt.partial(lang=lang)

        async def generate(state: QAState):
            try:
                if not state["context"]:
                    logger.warning("No context available for generation")
                    return {"answer": NO_CONTEXT_MESSAGE}

                docs_content = DEFAULT_DOC_SEPARATOR.join(
                    doc.page_content for doc in state["context"]
                )
                messages = qa_prompt.invoke(
                    {
                        "question": state["question"],
                        "context": docs_content,
                    }
                )

                # Use async version of LLM invoke if available
                if hasattr(self.llm, "ainvoke"):
                    response = await self.llm.ainvoke(messages)
                else:
                    # Fallback to sync version in thread pool
                    response = await asyncio.get_event_loop().run_in_executor(
                        None, self.llm.invoke, messages
                    )

                logger.info("Successfully generated response")
                return {"answer": response.content}
            except Exception as e:
                logger.error(f"Error during answer generation: {e}")
                return {"answer": GENERATION_ERROR_MESSAGE}

        return generate

    async def query(
        self,
        query: str,
        lang: str,
        docs: Optional[List[Document]] = None,
        vectordb: Optional[VectorStore] = None,
        filter_dict: Optional[dict] = None,
        k: Optional[int] = None,
    ) -> dict:
        """
        Process a query with context-based retrieval and generation.

        Args:
            query: The question to be answered
            lang: The language for the response
            docs: Optional list of documents to use as context
            vectordb: Optional pre-existing vector database
            filter_dict: Optional filter for document retrieval
            k: Number of documents to retrieve (default: from config)

        Returns:
            Dictionary containing question, context, answer, and source URLs

        Raises:
            ValueError: If both docs and vectordb are None
        """
        logger.info(f"Processing query: {query[:50]}...")

        if k is None:
            k = DEFAULT_RETRIEVAL_COUNT

        try:
            # Set up vector database
            vectordb, filter_dict = await self._setup_vectordb(docs, vectordb)

            # Create workflow functions
            retrieve_func = self._create_retrieve_function(vectordb, filter_dict, k)
            generate_func = self._create_generate_function(lang)

            # Build and compile the graph
            graph_builder = StateGraph(QAState)
            graph_builder.add_node("retrieve", retrieve_func)
            graph_builder.add_node("generate", generate_func)
            graph_builder.add_edge(START, "retrieve")
            graph_builder.add_edge("retrieve", "generate")
            graph = graph_builder.compile()

            # Execute the workflow
            response = await graph.ainvoke(
                {"question": query, "context": [], "answer": "", "urls": []}
            )
            logger.info("Query processed successfully")
            return response

        except ValueError as e:
            logger.error(f"Validation error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during query processing: {e}")
            return {
                "question": query,
                "context": [],
                "answer": TECHNICAL_ERROR_MESSAGE,
                "urls": [],
            }


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    def main():
        """Main function to demonstrate the QA system functionality."""
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

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=100
        )
        all_chunks = text_splitter.split_documents(doc)

        qa = QAWithContext(llm, emb)
        response = asyncio.run(
            qa.query("Why Theranos closed in 2018?", lang="Chinese", docs=all_chunks)
        )
        # Debug output - uncomment for testing
        print("Answer:", response["answer"])
        print("Sources:", response["urls"])

        # Result available for testing
        _ = response

    main()
