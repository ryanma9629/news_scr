import logging
import operator
from abc import ABC, abstractmethod
from typing import Annotated, List, Literal, TypedDict

from dotenv import load_dotenv
from langchain.chains.combine_documents.reduce import acollapse_docs, split_list_of_docs
from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

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
Take these and distill it into a final, consolidated summary of the main themes in {lang} within {max_words} words.
"""

INITIAL_SUMMARY_TEMPLATE = """Write a concise summary in {lang} within {max_words} words of the following:
------------
{context}
------------
"""

REFINE_SUMMARY_TEMPLATE = """Produce a final summary in {lang} with no more than {max_words} words.

Existing summary up to this point:
------------
{existing_answer}
------------

New context:
------------
{context}
------------
Given the new context, refine the original summary.
"""

# Default constants
DEFAULT_MAX_WORDS = 200
DEFAULT_MAX_TOKENS = 2000


class Summarization(ABC):
    def __init__(self, llm: BaseChatModel) -> None:
        super().__init__()
        self.llm = llm

    @abstractmethod
    def summarize(self, docs: List[Document], lang: str, max_words: int) -> str:
        raise NotImplementedError

    async def _execute_graph_with_error_handling(
        self, graph, initial_state, method_name: str, summary_key: str = "summary"
    ) -> str:
        """
        Common error handling wrapper for graph execution

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
    def _create_chains(self, lang: str, max_words: int) -> tuple:
        """Create and return configured chains for summarization."""
        raise NotImplementedError

    @abstractmethod
    def _create_graph_functions(self, *args, **kwargs) -> tuple:
        """Create and return all graph node functions."""
        raise NotImplementedError

    @abstractmethod
    def _create_initial_state(self, docs: List[Document]) -> dict:
        """Create initial state for the graph."""
        raise NotImplementedError

    @abstractmethod
    def _build_graph(self, *graph_functions):
        """Build and return the state graph."""
        raise NotImplementedError


class MapReduceSummarization(Summarization):
    def __init__(self, llm: BaseChatModel) -> None:
        super().__init__(llm)
        self.max_words = DEFAULT_MAX_WORDS
        self.max_token = DEFAULT_MAX_TOKENS

        # Pre-create prompt templates and chains
        self.map_prompt = ChatPromptTemplate.from_messages(
            [("system", MAP_PROMPT_TEMPLATE)]
        )
        self.reduce_prompt = ChatPromptTemplate.from_messages(
            [("human", REDUCE_PROMPT_TEMPLATE)]
        )

    def _create_chains(self, lang: str, max_words: int) -> tuple:
        """Create and return configured chains for summarization."""
        map_prompt = self.map_prompt.partial(lang=lang)
        map_chain = map_prompt | self.llm | StrOutputParser()

        reduce_prompt = self.reduce_prompt.partial(lang=lang, max_words=max_words)
        reduce_chain = reduce_prompt | self.llm | StrOutputParser()

        return map_chain, reduce_chain

    def _create_graph_functions(self, map_chain, reduce_chain, max_token: int):
        """Create and return all graph node functions."""

        def len_func(documents: List[Document]) -> int:
            return sum(self.llm.get_num_tokens(doc.page_content) for doc in documents)

        async def generate_summary(state: MapReduceSummaryState) -> dict:
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
            return [
                Send("generate_summary", {"content": content})
                for content in state["contents"]
            ]

        def collect_summaries(state: MapReduceOverallState) -> dict:
            return {
                "collapsed_summaries": [
                    Document(summary) for summary in state["summaries"]
                ]
            }

        async def collapse_summaries(state: MapReduceOverallState) -> dict:
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
            num_tokens = len_func(state["collapsed_summaries"])
            if num_tokens > max_token:
                return "collapse_summaries"
            else:
                return "generate_final_summary"

        async def generate_final_summary(state: MapReduceOverallState) -> dict:
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
        """Create initial state for the Map-Reduce graph."""
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
        """Build and return the Map-Reduce state graph."""
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
        max_words: int = DEFAULT_MAX_WORDS,
        max_token: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """
        Generate summary using Map-Reduce method

        Args:
            docs: List of documents to summarize
            lang: Target language
            max_words: Maximum word count
            max_token: Maximum token count

        Returns:
            Generated summary text
        """
        logger.info(
            f"Starting Map-Reduce summarization, docs: {len(docs)}, lang: {lang}, max_words: {max_words}"
        )

        # Create chains with specific parameters
        map_chain, reduce_chain = self._create_chains(lang, max_words)

        # Create graph functions
        graph_functions = self._create_graph_functions(
            map_chain, reduce_chain, max_token
        )

        # Build graph
        graph = self._build_graph(*graph_functions)

        # Create initial state
        initial_state = self._create_initial_state(docs)

        # Execute graph with error handling
        return await self._execute_graph_with_error_handling(
            graph, initial_state, "Map-Reduce summarization", "final_summary"
        )


class RefinementSummarization(Summarization):
    def __init__(self, llm: BaseChatModel) -> None:
        super().__init__(llm)

        # Pre-create prompt templates
        self.initial_prompt = ChatPromptTemplate([("human", INITIAL_SUMMARY_TEMPLATE)])
        self.refine_prompt = ChatPromptTemplate([("human", REFINE_SUMMARY_TEMPLATE)])

    def _create_chains(self, lang: str, max_words: int) -> tuple:
        """Create and return configured chains for summarization."""
        initial_prompt = self.initial_prompt.partial(lang=lang, max_words=max_words)
        initial_chain = initial_prompt | self.llm | StrOutputParser()

        refine_prompt = self.refine_prompt.partial(lang=lang, max_words=max_words)
        refine_chain = refine_prompt | self.llm | StrOutputParser()

        return initial_chain, refine_chain

    def _create_graph_functions(self, initial_chain, refine_chain):
        """Create and return all graph node functions."""

        async def generate_initial_summary(
            state: RefinementState, config: RunnableConfig
        ) -> dict:
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
            if state["index"] >= len(state["contents"]):
                return END
            else:
                return "refine_summary"

        return generate_initial_summary, refine_summary, should_refine

    def _create_initial_state(self, docs: List[Document]) -> RefinementState:
        """Create initial state for the Refinement graph."""
        return {
            "contents": [doc.page_content for doc in docs],
            "index": 0,
            "summary": "",
        }

    def _build_graph(self, generate_initial_summary, refine_summary, should_refine):
        """Build and return the Refinement state graph."""
        graph_builder = StateGraph(RefinementState)
        graph_builder.add_node("generate_initial_summary", generate_initial_summary)
        graph_builder.add_node("refine_summary", refine_summary)

        graph_builder.add_edge(START, "generate_initial_summary")
        graph_builder.add_conditional_edges("generate_initial_summary", should_refine)
        graph_builder.add_conditional_edges("refine_summary", should_refine)

        return graph_builder.compile()

    async def summarize(
        self, docs: List[Document], lang: str, max_words: int = DEFAULT_MAX_WORDS
    ) -> str:
        """
        Generate summary using iterative refinement method

        Args:
            docs: List of documents to summarize
            lang: Target language
            max_words: Maximum word count

        Returns:
            Generated summary text
        """
        logger.info(
            f"Starting iterative refinement summarization, docs: {len(docs)}, lang: {lang}, max_words: {max_words}"
        )

        # Create chains with specific parameters
        initial_chain, refine_chain = self._create_chains(lang, max_words)

        # Create graph functions
        graph_functions = self._create_graph_functions(initial_chain, refine_chain)

        # Build graph
        graph = self._build_graph(*graph_functions)

        # Create initial state
        initial_state = self._create_initial_state(docs)

        # Execute graph with error handling
        return await self._execute_graph_with_error_handling(
            graph, initial_state, "Iterative refinement summarization", "summary"
        )


if __name__ == "__main__":
    import asyncio

    from langchain_core.documents import Document
    from langchain_openai import AzureChatOpenAI

    from crawler import ApifyCrawler

    # Set log level to DEBUG to see detailed information
    logger.setLevel(logging.DEBUG)

    llm = AzureChatOpenAI(
        azure_deployment="gpt-4o-mini",
        model="gpt-4o-mini",
        temperature=0,
    )

    apify_crawler = ApifyCrawler()
    doc = asyncio.run(
        apify_crawler.get(
            [
                "https://www.investopedia.com/articles/investing/020116/theranos-fallen-unicorn.asp"
            ]
        )
    )
    print("Summarization with map-reduce")
    mrsumm = MapReduceSummarization(llm)
    summary = asyncio.run(mrsumm.summarize(doc, "Chinese"))
    print(summary)

    print("Summarization with iterative refinement")
    refsumm = RefinementSummarization(llm)
    summary = asyncio.run(refsumm.summarize(doc, "Chinese"))
    print("\n" + summary)
