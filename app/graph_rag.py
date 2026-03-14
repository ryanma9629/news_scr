"""
GraphRAG implementation for enhanced QA capabilities.

This module provides GraphRAG functionality that builds entity relationships
across documents for better context understanding in question answering.
Uses LangGraph StateGraph for structured workflow with parallel processing.
"""

__all__ = [
    "Entity",
    "Relationship",
    "GraphDocument",
    "KnowledgeGraph",
    "GraphRAG",
    "ExtractionState",
    "GraphRAGState",
]

import re
import warnings
from typing import Annotated, Dict, List, Optional, Set, Tuple, TypedDict

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import START, END, StateGraph
from langgraph.constants import Send
from langgraph.checkpoint.memory import MemorySaver
from operator import add
from pydantic import BaseModel, Field

from .config import (
    MIN_WORD_LENGTH_FOR_SEARCH,
    MAX_ENTITIES_IN_CONTEXT,
    MAX_ENTITIES_FOR_ANSWER,
    MAX_RELATIONSHIPS_DISPLAY,
    MAX_DOC_CONTEXT_LENGTH,
    MAX_DOCS_FOR_CONTEXT,
)
from .logging_config import get_logger

# Load environment variables
load_dotenv()

# Initialize logger
logger = get_logger(__name__)

# =============================================================================
# COMPILED REGEX PATTERNS FOR ENTITY EXTRACTION
# =============================================================================

# Pattern for parsing entity: - [Name] (Type): Description
_ENTITY_PATTERN = re.compile(r"- \[([^\]]+)\] \(([^)]+)\):\s*(.+)")

# Pattern for parsing relationship: - [Entity A] -> [Relationship] -> [Entity B]
_RELATIONSHIP_PATTERN = re.compile(r"- \[([^\]]+)\] -> \[([^\]]+)\] -> \[([^\]]+)\]")


# Entity extraction prompt
ENTITY_EXTRACTION_PROMPT = """Extract entities and their relationships from the following text.

Focus on:
- People (names, roles)
- Organizations (companies, institutions)
- Locations (cities, countries)
- Events (incidents, actions)
- Dates and time periods
- Financial crimes (fraud, money laundering, etc.)

For each entity, provide:
1. Entity name
2. Entity type
3. A brief description based on the context

For relationships, describe how entities are connected.

Text:
------------
{text}
------------

Format your response as:
ENTITIES:
- [Entity Name] (Type): Description
...

RELATIONSHIPS:
- [Entity A] -> [Relationship] -> [Entity B]
...
"""


class Entity(BaseModel):
    """Represents an extracted entity."""

    name: str = Field(..., description="Name of the entity")
    entity_type: str = Field(..., description="Type of entity (Person, Organization, Location, Event, etc.)")
    description: str = Field(..., description="Brief description of the entity")


class Relationship(BaseModel):
    """Represents a relationship between entities."""

    source: str = Field(..., description="Source entity name")
    target: str = Field(..., description="Target entity name")
    relationship: str = Field(..., description="Description of the relationship")


class GraphDocument(BaseModel):
    """Represents a document with extracted graph information."""

    doc_id: str
    source_url: str
    entities: List[Entity]
    relationships: List[Relationship]
    summary: str


# LangGraph State definitions
class ExtractionState(TypedDict):
    """State for single document entity extraction."""
    doc_id: str
    doc_content: str
    entities: List[Entity]
    relationships: List[Relationship]


class GraphRAGState(TypedDict):
    """State for the GraphRAG workflow."""
    documents: List[Document]
    # Use Annotated with add for parallel reduction
    all_entities: Annotated[List[Entity], add]
    all_relationships: Annotated[List[Relationship], add]
    doc_ids: List[str]
    query: str
    graph_context: str
    answer: str
    lang: str


class KnowledgeGraph:
    """
    In-memory knowledge graph for entity relationships.

    This class maintains a graph of entities and their relationships
    extracted from documents.
    """

    def __init__(self):
        self.entities: Dict[str, Entity] = {}  # name -> Entity
        self.relationships: List[Tuple[str, str, str]] = []  # (source, relationship, target)
        self.entity_documents: Dict[str, Set[str]] = {}  # entity_name -> set of doc_ids

    def add_entity(self, entity: Entity, doc_id: str) -> None:
        """Add an entity to the graph."""
        key = entity.name.lower()
        if key not in self.entities:
            self.entities[key] = entity
            self.entity_documents[key] = set()
        self.entity_documents[key].add(doc_id)

    def add_relationship(self, source: str, relationship: str, target: str) -> None:
        """Add a relationship to the graph."""
        self.relationships.append((source.lower(), relationship, target.lower()))

    def get_related_entities(self, entity_name: str, max_depth: int = 2) -> Set[str]:
        """Get all entities related to the given entity within max_depth hops."""
        entity_key = entity_name.lower()
        related: Set[str] = {entity_key}
        frontier = {entity_key}

        for _ in range(max_depth):
            new_frontier = set()
            for entity in frontier:
                for src, rel, tgt in self.relationships:
                    if src == entity and tgt not in related:
                        new_frontier.add(tgt)
                        related.add(tgt)
                    elif tgt == entity and src not in related:
                        new_frontier.add(src)
                        related.add(src)
            frontier = new_frontier
            if not frontier:
                break

        return related

    def get_entity_context(self, entity_name: str) -> str:
        """Get context about an entity and its relationships."""
        entity_key = entity_name.lower()
        context_parts = []

        if entity_key in self.entities:
            entity = self.entities[entity_key]
            context_parts.append(f"{entity.name} ({entity.entity_type}): {entity.description}")

        # Add relationships
        related = []
        for src, rel, tgt in self.relationships:
            if src == entity_key:
                related.append(f"  -> {rel} -> {tgt}")
            elif tgt == entity_key:
                related.append(f"  <- {rel} <- {src}")

        if related:
            context_parts.append("Relationships:")
            context_parts.extend(related[:MAX_RELATIONSHIPS_DISPLAY])  # Limit relationships

        return "\n".join(context_parts)

    def search_entities(self, query: str) -> List[str]:
        """Search for entities matching a query."""
        query_lower = query.lower()
        matches = []

        for name, entity in self.entities.items():
            if query_lower in name or query_lower in entity.description.lower():
                matches.append(entity.name)
            elif query_lower in entity.entity_type.lower():
                matches.append(entity.name)

        return matches

    def build_from_results(
        self,
        entities: List[Entity],
        relationships: List[Relationship],
        doc_ids: List[str],
    ) -> None:
        """Build knowledge graph from extraction results."""
        # Create a mapping of entities to their source docs
        entity_doc_map: Dict[str, Set[str]] = {}

        for entity in entities:
            key = entity.name.lower()
            if key not in self.entities:
                self.entities[key] = entity
                self.entity_documents[key] = set()
            # Associate entity with all doc_ids (simplified)
            for doc_id in doc_ids:
                self.entity_documents[key].add(doc_id)

        for rel in relationships:
            self.add_relationship(rel.source, rel.relationship, rel.target)


class GraphRAG:
    """
    GraphRAG implementation using LangGraph StateGraph for structured workflow.

    This class builds a knowledge graph from documents and uses it
    to provide better context for QA. Uses parallel entity extraction
    for improved performance.
    """

    def __init__(self, llm: BaseChatModel, emb: Embeddings):
        """
        Initialize GraphRAG.

        Args:
            llm: Language model for entity extraction
            emb: Embeddings model for vector operations
        """
        self.llm = llm
        self.emb = emb
        self.knowledge_graph = KnowledgeGraph()
        self._extraction_prompt = ChatPromptTemplate.from_template(ENTITY_EXTRACTION_PROMPT)
        self._extraction_chain = self._extraction_prompt | self.llm
        self._checkpointer = MemorySaver()
        self._graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph StateGraph for GraphRAG workflow."""
        graph = StateGraph(GraphRAGState)

        # Add nodes
        graph.add_node("prepare_documents", self._prepare_documents_node)
        graph.add_node("extract_entities", self._extract_entities_node)
        graph.add_node("build_knowledge_graph", self._build_knowledge_graph_node)
        graph.add_node("retrieve_context", self._retrieve_context_node)
        graph.add_node("generate_answer", self._generate_answer_node)

        # Add edges
        graph.add_edge(START, "prepare_documents")

        # Conditional edge for parallel extraction
        graph.add_conditional_edges(
            "prepare_documents",
            self._route_to_extraction,
            ["extract_entities"]
        )
        graph.add_edge("extract_entities", "build_knowledge_graph")
        graph.add_edge("build_knowledge_graph", "retrieve_context")
        graph.add_edge("retrieve_context", "generate_answer")
        graph.add_edge("generate_answer", END)

        return graph.compile(checkpointer=self._checkpointer)

    async def _prepare_documents_node(self, state: GraphRAGState) -> dict:
        """Prepare documents for parallel extraction."""
        documents = state.get("documents", [])
        doc_ids = [doc.metadata.get("source", f"doc_{i}") for i, doc in enumerate(documents)]
        logger.info(f"Prepared {len(documents)} documents for entity extraction")
        return {"doc_ids": doc_ids}

    def _route_to_extraction(self, state: GraphRAGState) -> List[Send]:
        """Route documents to parallel extraction using Send()."""
        documents = state.get("documents", [])
        lang = state.get("lang", "English")

        # Use Send() for parallel processing of each document
        return [
            Send(
                "extract_entities",
                {
                    "documents": [doc],
                    "doc_ids": [doc.metadata.get("source", f"doc_{i}")],
                    "lang": lang,
                    "query": state.get("query", ""),
                    "all_entities": [],
                    "all_relationships": [],
                    "graph_context": "",
                    "answer": "",
                }
            )
            for i, doc in enumerate(documents)
        ]

    def _parse_llm_response(
        self, content: str
    ) -> Tuple[List[Entity], List[Relationship]]:
        """
        Parse LLM response content into entities and relationships.

        Args:
            content: Raw LLM response text to parse

        Returns:
            Tuple of (entities, relationships) extracted from the response
        """
        entities = []
        relationships = []

        in_entities = False
        in_relationships = False

        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("ENTITIES:"):
                in_entities = True
                in_relationships = False
                continue
            elif line.startswith("RELATIONSHIPS:"):
                in_entities = False
                in_relationships = True
                continue

            if in_entities and line.startswith("-"):
                match = _ENTITY_PATTERN.match(line)
                if match:
                    entities.append(Entity(
                        name=match.group(1),
                        entity_type=match.group(2),
                        description=match.group(3)
                    ))

            elif in_relationships and line.startswith("-"):
                match = _RELATIONSHIP_PATTERN.match(line)
                if match:
                    relationships.append(Relationship(
                        source=match.group(1),
                        relationship=match.group(2),
                        target=match.group(3)
                    ))

        return entities, relationships

    async def _extract_entities_node(self, state: GraphRAGState) -> dict:
        """Extract entities and relationships from documents."""
        documents = state.get("documents", [])
        all_entities = []
        all_relationships = []

        for i, doc in enumerate(documents):
            try:
                response = await self._extraction_chain.ainvoke({"text": doc.page_content})
                content = response.content if hasattr(response, "content") else str(response)

                entities, relationships = self._parse_llm_response(content)

                all_entities.extend(entities)
                all_relationships.extend(relationships)
                logger.debug(f"Extracted {len(entities)} entities, {len(relationships)} relationships from doc {i}")

            except Exception as e:
                logger.error(f"Error extracting entities from document {i}: {e}")

        return {"all_entities": all_entities, "all_relationships": all_relationships}

    async def _build_knowledge_graph_node(self, state: GraphRAGState) -> dict:
        """Build knowledge graph from extracted entities and relationships."""
        entities = state.get("all_entities", [])
        relationships = state.get("all_relationships", [])
        doc_ids = state.get("doc_ids", [])

        self.knowledge_graph.build_from_results(entities, relationships, doc_ids)

        logger.info(
            f"Knowledge graph built: {len(self.knowledge_graph.entities)} entities, "
            f"{len(self.knowledge_graph.relationships)} relationships"
        )
        return {}

    async def _retrieve_context_node(self, state: GraphRAGState) -> dict:
        """Retrieve relevant context from the knowledge graph."""
        query = state.get("query", "")

        # Search for entities related to the query
        matching_entities = self.knowledge_graph.search_entities(query)

        if not matching_entities:
            # Try to find entities from the query words
            words = query.lower().split()
            for word in words:
                if len(word) > MIN_WORD_LENGTH_FOR_SEARCH:  # Skip short words
                    matching_entities.extend(self.knowledge_graph.search_entities(word))

        matching_entities = list(set(matching_entities))[:MAX_ENTITIES_IN_CONTEXT]

        if not matching_entities:
            return {"graph_context": ""}

        # Build context from matching entities and their relationships
        context_parts = ["Relevant entities and relationships:"]

        for entity_name in matching_entities[:MAX_ENTITIES_FOR_ANSWER]:  # Limit entities
            entity_context = self.knowledge_graph.get_entity_context(entity_name)
            if entity_context:
                context_parts.append(f"\n{entity_context}")

        graph_context = "\n".join(context_parts)
        return {"graph_context": graph_context}

    async def _generate_answer_node(self, state: GraphRAGState) -> dict:
        """Generate answer using graph context and documents."""
        query = state.get("query", "")
        graph_context = state.get("graph_context", "")
        documents = state.get("documents", [])
        lang = state.get("lang", "English")

        # Combine with document context for answer generation
        doc_context = "\n".join(doc.page_content[:MAX_DOC_CONTEXT_LENGTH] for doc in documents[:MAX_DOCS_FOR_CONTEXT])

        answer_prompt = f"""Use the following context to answer the question.

Knowledge Graph Context:
{graph_context}

Document Context (from relevant documents):
{doc_context}

Question: {query}

Provide a comprehensive answer in {lang}. Include specific entities and relationships mentioned in the context when relevant.
"""

        try:
            response = await self.llm.ainvoke(answer_prompt)
            answer = response.content if hasattr(response, "content") else str(response)
            return {"answer": answer}

        except Exception as e:
            logger.error(f"Error generating answer with GraphRAG: {e}")
            return {"answer": "Unable to generate answer using knowledge graph."}

    async def answer_with_graph(
        self,
        query: str,
        docs: List[Document],
        lang: str = "English",
        company_name: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> dict:
        """
        Answer a question using GraphRAG with LangGraph workflow.

        Args:
            query: Question to answer
            docs: List of documents for context
            lang: Language for the response
            company_name: Optional company name for context
            thread_id: Optional thread ID for conversation continuity

        Returns:
            Dictionary with answer and context information
        """
        # Reset knowledge graph for new query
        self.knowledge_graph = KnowledgeGraph()

        # Initial state
        initial_state: GraphRAGState = {
            "documents": docs,
            "all_entities": [],
            "all_relationships": [],
            "doc_ids": [],
            "query": query,
            "graph_context": "",
            "answer": "",
            "lang": lang,
        }

        # Configure thread for conversation continuity
        config = {"configurable": {"thread_id": thread_id or "default"}}

        try:
            # Execute the workflow
            result = await self._graph.ainvoke(initial_state, config=config)

            return {
                "answer": result.get("answer", ""),
                "graph_context": result.get("graph_context", ""),
                "entities_found": list(self.knowledge_graph.entities.keys())[:10],
            }

        except Exception as e:
            logger.error(f"Error in GraphRAG workflow: {e}")
            return {
                "answer": "Unable to process query with knowledge graph.",
                "graph_context": "",
                "entities_found": [],
            }

    # Legacy methods for backward compatibility
    async def extract_entities(self, doc: Document) -> Tuple[List[Entity], List[Relationship]]:
        """
        Extract entities and relationships from a document (legacy method).

        .. deprecated:: 2.0
            Use answer_with_graph() instead, which handles entity extraction
            internally through the LangGraph workflow.

        Args:
            doc: Document to extract entities from

        Returns:
            Tuple of (entities, relationships)
        """
        warnings.warn(
            "extract_entities() is deprecated and will be removed in a future version. "
            "Use answer_with_graph() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        try:
            response = await self._extraction_chain.ainvoke({"text": doc.page_content})
            content = response.content if hasattr(response, "content") else str(response)

            return self._parse_llm_response(content)

        except Exception as e:
            logger.error(f"Error extracting entities: {e}")
            return [], []

    async def build_graph(
        self,
        docs: List[Document],
        company_name: Optional[str] = None,
        lang: Optional[str] = None,
    ) -> None:
        """
        Build knowledge graph from documents (legacy method).

        .. deprecated:: 2.0
            Use answer_with_graph() instead, which handles graph building
            internally through the LangGraph workflow.

        Args:
            docs: List of documents to process
            company_name: Optional company name for vector store scoping
            lang: Optional language for vector store scoping
        """
        warnings.warn(
            "build_graph() is deprecated and will be removed in a future version. "
            "Use answer_with_graph() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        logger.info(f"Building knowledge graph from {len(docs)} documents")

        for i, doc in enumerate(docs):
            doc_id = doc.metadata.get("source", f"doc_{i}")
            entities, relationships = await self.extract_entities(doc)

            for entity in entities:
                self.knowledge_graph.add_entity(entity, doc_id)

            for rel in relationships:
                self.knowledge_graph.add_relationship(rel.source, rel.relationship, rel.target)

            logger.debug(f"Processed document {i + 1}: {len(entities)} entities, {len(relationships)} relationships")

        logger.info(
            f"Knowledge graph built: {len(self.knowledge_graph.entities)} entities, "
            f"{len(self.knowledge_graph.relationships)} relationships"
        )

    def get_relevant_context(self, query: str, max_entities: int = 10) -> str:
        """
        Get relevant context from the knowledge graph for a query (legacy method).

        .. deprecated:: 2.0
            Use answer_with_graph() instead, which handles context retrieval
            internally through the LangGraph workflow.

        Args:
            query: Query to find relevant context for
            max_entities: Maximum number of entities to include

        Returns:
            Context string from the knowledge graph
        """
        warnings.warn(
            "get_relevant_context() is deprecated and will be removed in a future version. "
            "Use answer_with_graph() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        matching_entities = self.knowledge_graph.search_entities(query)

        if not matching_entities:
            words = query.lower().split()
            for word in words:
                if len(word) > MIN_WORD_LENGTH_FOR_SEARCH:
                    matching_entities.extend(self.knowledge_graph.search_entities(word))

        matching_entities = list(set(matching_entities))[:max_entities]

        if not matching_entities:
            return ""

        context_parts = ["Relevant entities and relationships:"]

        for entity_name in matching_entities[:5]:
            entity_context = self.knowledge_graph.get_entity_context(entity_name)
            if entity_context:
                context_parts.append(f"\n{entity_context}")

        return "\n".join(context_parts)