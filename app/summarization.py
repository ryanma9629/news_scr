import asyncio
import logging
import operator
import sys
from abc import ABC, abstractmethod
from typing import Annotated, List, Literal, TypedDict

from dotenv import load_dotenv
from langchain.chains.combine_documents.reduce import acollapse_docs, split_list_of_docs
from langchain_community.document_transformers.embeddings_redundant_filter import (
    EmbeddingsClusteringFilter,
)
from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .crawler import ApifyCrawler

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Type definitions for Map-Reduce summarization
class MapReduceOverallState(TypedDict):
    contents: List[str]
    summaries: Annotated[list, operator.add]
    collapsed_summaries: List[Document]
    final_summary: str


class MapReduceSummaryState(TypedDict):
    content: str


# Type definitions for Refinement summarization
class RefinementState(TypedDict):
    contents: List[str]
    index: int
    summary: str


# Template constants
MAP_PROMPT_TEMPLATE = """Write a concise summary in {lang} of the following:
------------
{context}
------------
"""

REDUCE_PROMPT_TEMPLATE = """The following is a set of summaries:
------------
{docs}
------------
Take these and distill it into a final, consolidated summary of the main themes in {lang}. Make the summary {summary_level}: {summary_description}.
"""

INITIAL_SUMMARY_TEMPLATE = """Write a {summary_level} summary in {lang} of the following:
------------
{context}
------------
Summary style: {summary_description}
"""

REFINE_SUMMARY_TEMPLATE = """Produce a {summary_level} summary in {lang}.

Existing summary up to this point:
------------
{existing_answer}
------------

New context:
------------
{context}
------------
Given the new context, refine the original summary. Summary style: {summary_description}
"""

# Default constants
DEFAULT_MAX_WORDS = 200
DEFAULT_MAX_TOKENS = 2000

# Summary level mappings
SUMMARY_LEVELS = {
    "brief": {
        "description": "provide a concise overview focusing on the most essential points and key takeaways"
    },
    "moderate": {
        "description": "provide a balanced summary with sufficient detail to understand the main themes and important context"
    },
    "detailed": {
        "description": "provide a comprehensive summary covering all significant aspects, background information, and nuanced details"
    },
}

DEFAULT_SUMMARY_LEVEL = "moderate"


def get_summary_description(summary_level: str) -> str:
    """Get the description for a given summary level.

    Args:
        summary_level: The summary level ("brief", "moderate", "detailed")

    Returns:
        Description string for the summary level
    """
    return SUMMARY_LEVELS.get(summary_level, SUMMARY_LEVELS[DEFAULT_SUMMARY_LEVEL])[
        "description"
    ]


class Summarization(ABC):
    """
    Abstract base class for document summarization systems.

    This class provides a common interface for different summarization implementations,
    defining the basic structure and required methods for document summarization.
    """

    def __init__(self, llm: BaseChatModel) -> None:
        """Initialize the summarization system.

        Args:
            llm: Language model for generating summaries
        """
        super().__init__()
        self.llm = llm

    @abstractmethod
    def summarize(
        self,
        docs: List[Document],
        lang: str,
        summary_level: str = DEFAULT_SUMMARY_LEVEL,
        num_cluster: int = 0,
    ) -> str:
        """Generate summary for given documents.

        Args:
            docs: List of documents to summarize
            lang: Target language for the summary
            summary_level: Level of detail for the summary ("brief", "moderate", "detailed")
            num_cluster: Number of clusters for document clustering (0 = no clustering)

        Returns:
            Generated summary text

        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError

    def _cluster_documents(
        self, docs: List[Document], num_cluster: int, embeddings
    ) -> List[Document]:
        """Cluster documents using EmbeddingsClusteringFilter.

        Args:
            docs: List of documents to cluster
            num_cluster: Number of clusters
            embeddings: Embeddings model for clustering

        Returns:
            List of clustered documents (representative documents from each cluster)
        """
        if num_cluster <= 0 or len(docs) <= num_cluster:
            logger.info(
                f"Skipping clustering: num_cluster={num_cluster}, docs={len(docs)}"
            )
            return docs

        try:
            logger.info(f"Clustering {len(docs)} documents into {num_cluster} clusters")
            clustering_filter = EmbeddingsClusteringFilter(
                embeddings=embeddings, num_clusters=num_cluster, sorted=True
            )
            clustered_docs = clustering_filter.transform_documents(docs)
            logger.info(
                f"Clustering completed, reduced to {len(clustered_docs)} documents"
            )
            return list(clustered_docs)
        except Exception as e:
            logger.error(f"Error during document clustering: {str(e)}")
            logger.info("Falling back to original documents")
            return docs

    async def _execute_graph_with_error_handling(
        self, graph, initial_state, method_name: str, summary_key: str = "summary"
    ) -> str:
        """Execute graph with comprehensive error handling.

        Args:
            graph: Compiled StateGraph to execute
            initial_state: Initial state for the graph
            method_name: Name of the summarization method for logging
            summary_key: Key to extract summary from result

        Returns:
            Generated summary text or error message
        """
        try:
            logger.info(f"Starting {method_name} graph execution")
            result = await graph.ainvoke(initial_state)
            final_summary = result.get(summary_key, "")

            if final_summary:
                logger.info(
                    f"{method_name} completed successfully, summary length: {len(final_summary)}"
                )
                return final_summary
            else:
                error_msg = "LLM failed to generate summary: empty result"
                logger.error(error_msg)
                return error_msg

        except ValueError as e:
            error_msg = f"Input parameter error: {str(e)}"
            logger.error(error_msg)
            return error_msg
        except TimeoutError as e:
            error_msg = f"Summary generation timeout: {str(e)}"
            logger.error(error_msg)
            return error_msg
        except Exception as e:
            error_msg = f"Unknown error during {method_name}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return error_msg

    @abstractmethod
    def _create_chains(self, lang: str, summary_level: str) -> tuple:
        """Create and return configured chains for summarization.

        Args:
            lang: Target language for the summary
            summary_level: Level of detail for the summary ("brief", "moderate", "detailed")

        Returns:
            Tuple of configured chains
        """
        raise NotImplementedError

    @abstractmethod
    def _create_graph_functions(self, *args, **kwargs) -> tuple:
        """Create and return all graph node functions.

        Args:
            *args: Variable arguments
            **kwargs: Keyword arguments

        Returns:
            Tuple of graph node functions
        """
        raise NotImplementedError

    @abstractmethod
    def _create_initial_state(self, docs: List[Document]) -> dict:
        """Create initial state for the graph.

        Args:
            docs: List of documents to summarize

        Returns:
            Initial state dictionary
        """
        raise NotImplementedError

    @abstractmethod
    def _build_graph(self, *graph_functions):
        """Build and return the state graph.

        Args:
            *graph_functions: Graph node functions

        Returns:
            Compiled state graph
        """
        raise NotImplementedError


class MapReduceSummarization(Summarization):
    """
    Map-Reduce based document summarization system.

    This class provides document summarization using a Map-Reduce approach,
    processing documents in parallel and then reducing results to a final summary.
    """

    def __init__(self, llm: BaseChatModel, embeddings=None) -> None:
        """Initialize the Map-Reduce summarization system.

        Args:
            llm: Language model for generating summaries
            embeddings: Embeddings model for document clustering (optional)
        """
        super().__init__(llm)
        self.embeddings = embeddings
        self.max_words = DEFAULT_MAX_WORDS
        self.max_token = DEFAULT_MAX_TOKENS

        self.map_prompt = ChatPromptTemplate.from_messages(
            [("system", MAP_PROMPT_TEMPLATE)]
        )
        self.reduce_prompt = ChatPromptTemplate.from_messages(
            [("human", REDUCE_PROMPT_TEMPLATE)]
        )

    def _create_chains(self, lang: str, summary_level: str) -> tuple:
        """Create and return configured chains for Map-Reduce summarization.

        Args:
            lang: Target language for the summary
            summary_level: Level of detail for the summary ("brief", "moderate", "detailed")

        Returns:
            Tuple of (map_chain, reduce_chain)
        """
        map_prompt = self.map_prompt.partial(lang=lang)
        map_chain = map_prompt | self.llm | StrOutputParser()

        summary_description = get_summary_description(summary_level)
        reduce_prompt = self.reduce_prompt.partial(
            lang=lang,
            summary_level=summary_level,
            summary_description=summary_description,
        )
        reduce_chain = reduce_prompt | self.llm | StrOutputParser()

        return map_chain, reduce_chain

    def _create_graph_functions(self, map_chain, reduce_chain, max_token: int):
        """Create and return all graph node functions for Map-Reduce.

        Args:
            map_chain: Chain for mapping phase
            reduce_chain: Chain for reduce phase
            max_token: Maximum token count

        Returns:
            Tuple of graph node functions
        """

        def len_func(documents: List[Document]) -> int:
            """Calculate total tokens for a list of documents."""
            return sum(self.llm.get_num_tokens(doc.page_content) for doc in documents)

        async def generate_summary(state: MapReduceSummaryState) -> dict:
            """Generate summary for a single document."""
            try:
                logger.debug(
                    f"Generating individual document summary, content length: {len(state['content'])}"
                )
                response = await map_chain.ainvoke({"context": state["content"]})
                logger.debug(
                    f"Individual summary generated successfully, length: {len(response)}"
                )
                return {"summaries": [response]}
            except Exception as e:
                logger.error(f"Error generating individual summary: {str(e)}")
                raise

        def map_summaries(state: MapReduceOverallState):
            """Map function to distribute documents for summarization."""
            return [
                Send("generate_summary", {"content": content})
                for content in state["contents"]
            ]

        def collect_summaries(state: MapReduceOverallState) -> dict:
            """Collect individual summaries into documents."""
            return {
                "collapsed_summaries": [
                    Document(summary) for summary in state["summaries"]
                ]
            }

        async def collapse_summaries(state: MapReduceOverallState) -> dict:
            """Collapse multiple summaries into fewer summaries."""
            try:
                logger.debug(
                    f"Starting summary collapse, current summaries: {len(state['collapsed_summaries'])}"
                )
                doc_lists = split_list_of_docs(
                    state["collapsed_summaries"], len_func, max_token
                )
                logger.debug(f"Split into document lists: {len(doc_lists)}")
                results = []
                for i, doc_list in enumerate(doc_lists):
                    logger.debug(f"Processing document list {i + 1}/{len(doc_lists)}")
                    results.append(await acollapse_docs(doc_list, reduce_chain.ainvoke))  # type: ignore

                logger.debug(f"Summary collapse completed, results: {len(results)}")
                return {"collapsed_summaries": results}
            except Exception as e:
                logger.error(f"Error during summary collapse: {str(e)}")
                raise

        def should_collapse(
            state: MapReduceOverallState,
        ) -> Literal["collapse_summaries", "generate_final_summary"]:
            """Determine if further collapse is needed."""
            num_tokens = len_func(state["collapsed_summaries"])
            if num_tokens > max_token:
                return "collapse_summaries"
            else:
                return "generate_final_summary"

        async def generate_final_summary(state: MapReduceOverallState) -> dict:
            """Generate the final summary from collapsed summaries."""
            collapse_summaries = "\n\n".join(
                doc.page_content for doc in state["collapsed_summaries"]
            )
            response = await reduce_chain.ainvoke({"docs": collapse_summaries})
            return {"final_summary": response}

        return (
            generate_summary,
            map_summaries,
            collect_summaries,
            collapse_summaries,
            should_collapse,
            generate_final_summary,
        )

    def _create_initial_state(self, docs: List[Document]) -> MapReduceOverallState:
        """Create initial state for the Map-Reduce graph.

        Args:
            docs: List of documents to summarize

        Returns:
            Initial state dictionary for Map-Reduce
        """
        return {
            "contents": [doc.page_content for doc in docs],
            "summaries": [],
            "collapsed_summaries": [],
            "final_summary": "",
        }

    def _build_graph(
        self,
        generate_summary,
        map_summaries,
        collect_summaries,
        collapse_summaries,
        should_collapse,
        generate_final_summary,
    ):
        """Build and return the Map-Reduce state graph.

        Args:
            generate_summary: Function to generate individual summaries
            map_summaries: Function to map documents to summary tasks
            collect_summaries: Function to collect individual summaries
            collapse_summaries: Function to collapse multiple summaries
            should_collapse: Function to determine if collapse is needed
            generate_final_summary: Function to generate final summary

        Returns:
            Compiled state graph
        """
        graph_builder = StateGraph(MapReduceOverallState)
        graph_builder.add_node("generate_summary", generate_summary)  # type: ignore
        graph_builder.add_node("collect_summaries", collect_summaries)
        graph_builder.add_node("collapse_summaries", collapse_summaries)
        graph_builder.add_node("generate_final_summary", generate_final_summary)

        graph_builder.add_conditional_edges(START, map_summaries, ["generate_summary"])  # type: ignore
        graph_builder.add_edge("generate_summary", "collect_summaries")
        graph_builder.add_conditional_edges("collect_summaries", should_collapse)
        graph_builder.add_conditional_edges("collapse_summaries", should_collapse)
        graph_builder.add_edge("generate_final_summary", END)

        return graph_builder.compile()

    async def summarize(
        self,
        docs: List[Document],
        lang: str,
        summary_level: str = DEFAULT_SUMMARY_LEVEL,
        max_token: int = DEFAULT_MAX_TOKENS,
        num_cluster: int = 0,
    ) -> str:
        """Generate summary using Map-Reduce method.

        Args:
            docs: List of documents to summarize
            lang: Target language for the summary
            summary_level: Level of detail for the summary ("brief", "moderate", "detailed")
            max_token: Maximum token count for intermediate processing
            num_cluster: Number of clusters for document clustering (0 = no clustering)

        Returns:
            Generated summary text
        """
        logger.info(
            f"Starting Map-Reduce summarization, docs: {len(docs)}, lang: {lang}, summary_level: {summary_level}, num_cluster: {num_cluster}"
        )

        # Apply clustering if requested
        if num_cluster > 0:
            if self.embeddings is None:
                logger.warning("Embeddings not provided, skipping clustering")
                processed_docs = docs
            else:
                processed_docs = self._cluster_documents(
                    docs, num_cluster, self.embeddings
                )
        else:
            processed_docs = docs

        map_chain, reduce_chain = self._create_chains(lang, summary_level)
        graph_functions = self._create_graph_functions(
            map_chain, reduce_chain, max_token
        )
        graph = self._build_graph(*graph_functions)
        initial_state = self._create_initial_state(processed_docs)

        return await self._execute_graph_with_error_handling(
            graph, initial_state, "Map-Reduce summarization", "final_summary"
        )


class RefinementSummarization(Summarization):
    """
    Iterative refinement based document summarization system.

    This class provides document summarization using an iterative refinement approach,
    progressively improving the summary by incorporating additional documents.
    """

    def __init__(self, llm: BaseChatModel, embeddings=None) -> None:
        """Initialize the refinement summarization system.

        Args:
            llm: Language model for generating summaries
            embeddings: Embeddings model for document clustering (optional)
        """
        super().__init__(llm)
        self.embeddings = embeddings

        self.initial_prompt = ChatPromptTemplate([("human", INITIAL_SUMMARY_TEMPLATE)])
        self.refine_prompt = ChatPromptTemplate([("human", REFINE_SUMMARY_TEMPLATE)])

    def _create_chains(self, lang: str, summary_level: str) -> tuple:
        """Create and return configured chains for refinement summarization.

        Args:
            lang: Target language for the summary
            summary_level: Level of detail for the summary ("brief", "moderate", "detailed")

        Returns:
            Tuple of (initial_chain, refine_chain)
        """
        summary_description = get_summary_description(summary_level)

        initial_prompt = self.initial_prompt.partial(
            lang=lang,
            summary_level=summary_level,
            summary_description=summary_description,
        )
        initial_chain = initial_prompt | self.llm | StrOutputParser()

        refine_prompt = self.refine_prompt.partial(
            lang=lang,
            summary_level=summary_level,
            summary_description=summary_description,
        )
        refine_chain = refine_prompt | self.llm | StrOutputParser()

        return initial_chain, refine_chain

    def _create_graph_functions(self, initial_chain, refine_chain):
        """Create and return all graph node functions for refinement.

        Args:
            initial_chain: Chain for initial summary generation
            refine_chain: Chain for summary refinement

        Returns:
            Tuple of graph node functions
        """

        async def generate_initial_summary(
            state: RefinementState, config: RunnableConfig
        ) -> dict:
            """Generate initial summary from the first document."""
            try:
                logger.debug(
                    f"Generating initial summary, content length: {len(state['contents'][0])}"
                )
                summary = await initial_chain.ainvoke(
                    {"context": state["contents"][0]},
                    config,
                )
                logger.debug(
                    f"Initial summary generated successfully, length: {len(summary)}"
                )
                return {"summary": summary, "index": 1}
            except Exception as e:
                logger.error(f"Error generating initial summary: {str(e)}")
                raise

        async def refine_summary(
            state: RefinementState, config: RunnableConfig
        ) -> dict:
            """Refine the existing summary with the next document."""
            try:
                content = state["contents"][state["index"]]
                logger.debug(
                    f"Refining summary, document {state['index'] + 1}/{len(state['contents'])}, content length: {len(content)}"
                )
                summary = await refine_chain.ainvoke(
                    {
                        "existing_answer": state["summary"],
                        "context": content,
                    },
                    config,
                )
                logger.debug(
                    f"Summary refinement completed, new summary length: {len(summary)}"
                )
                return {"summary": summary, "index": state["index"] + 1}
            except Exception as e:
                logger.error(f"Error refining summary: {str(e)}")
                raise

        def should_refine(state: RefinementState):
            """Determine if further refinement is needed."""
            if state["index"] >= len(state["contents"]):
                return END
            else:
                return "refine_summary"

        return generate_initial_summary, refine_summary, should_refine

    def _create_initial_state(self, docs: List[Document]) -> RefinementState:
        """Create initial state for the Refinement graph.

        Args:
            docs: List of documents to summarize

        Returns:
            Initial state dictionary for refinement
        """
        return {
            "contents": [doc.page_content for doc in docs],
            "index": 0,
            "summary": "",
        }

    def _build_graph(self, generate_initial_summary, refine_summary, should_refine):
        """Build and return the Refinement state graph.

        Args:
            generate_initial_summary: Function to generate initial summary
            refine_summary: Function to refine the summary
            should_refine: Function to determine if refinement should continue

        Returns:
            Compiled state graph
        """
        graph_builder = StateGraph(RefinementState)
        graph_builder.add_node("generate_initial_summary", generate_initial_summary)
        graph_builder.add_node("refine_summary", refine_summary)

        graph_builder.add_edge(START, "generate_initial_summary")
        graph_builder.add_conditional_edges("generate_initial_summary", should_refine)
        graph_builder.add_conditional_edges("refine_summary", should_refine)

        return graph_builder.compile()

    async def summarize(
        self,
        docs: List[Document],
        lang: str,
        summary_level: str = DEFAULT_SUMMARY_LEVEL,
        num_cluster: int = 0,
    ) -> str:
        """Generate summary using iterative refinement method.

        Args:
            docs: List of documents to summarize
            lang: Target language for the summary
            summary_level: Level of detail for the summary ("brief", "moderate", "detailed")
            num_cluster: Number of clusters for document clustering (0 = no clustering)

        Returns:
            Generated summary text
        """
        logger.info(
            f"Starting iterative refinement summarization, docs: {len(docs)}, lang: {lang}, summary_level: {summary_level}, num_cluster: {num_cluster}"
        )

        # Apply clustering if requested
        if num_cluster > 0:
            if self.embeddings is None:
                logger.warning("Embeddings not provided, skipping clustering")
                processed_docs = docs
            else:
                processed_docs = self._cluster_documents(
                    docs, num_cluster, self.embeddings
                )
        else:
            processed_docs = docs

        initial_chain, refine_chain = self._create_chains(lang, summary_level)
        graph_functions = self._create_graph_functions(initial_chain, refine_chain)
        graph = self._build_graph(*graph_functions)
        initial_state = self._create_initial_state(processed_docs)

        return await self._execute_graph_with_error_handling(
            graph, initial_state, "Iterative refinement summarization", "summary"
        )


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    def main():
        """Main function to demonstrate the summarization functionality."""
        logger.setLevel(logging.DEBUG)

        llm = AzureChatOpenAI(
            azure_deployment="gpt-4o-mini",
            model="gpt-4o-mini",
            temperature=0,
        )

        # Import embeddings for clustering
        embeddings = AzureOpenAIEmbeddings(azure_deployment="text-embedding-3-small")

        apify_crawler = ApifyCrawler()
        doc = asyncio.run(
            apify_crawler.get(
                [
                    "https://www.investopedia.com/articles/investing/020116/theranos-fallen-unicorn.asp"
                ]
            )
        )

        # Debug output - uncomment for testing
        # print("Summarization with map-reduce (no clustering)")
        mrsumm = MapReduceSummarization(llm, embeddings)
        summary = asyncio.run(mrsumm.summarize(doc, "Chinese", num_cluster=0))
        # print(summary)

        # print("\nSummarization with map-reduce (with clustering)")
        summary_clustered = asyncio.run(mrsumm.summarize(doc, "Chinese", num_cluster=2))
        # print(summary_clustered)

        # print("\nSummarization with iterative refinement (no clustering)")
        refsumm = RefinementSummarization(llm, embeddings)
        summary_ref = asyncio.run(refsumm.summarize(doc, "Chinese", num_cluster=0))
        # print(summary_ref)

        # print("\nSummarization with iterative refinement (with clustering)")
        summary_ref_clustered = asyncio.run(
            refsumm.summarize(doc, "Chinese", num_cluster=2)
        )
        # print(summary_ref_clustered)

        # Results available for testing
        _ = summary, summary_clustered, summary_ref, summary_ref_clustered

    main()
