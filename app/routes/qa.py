"""
Q&A API endpoints.

This module provides the question-answering endpoints (regular, GraphRAG, and streaming).
"""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE
from ..decorators import handle_api_errors, require_session
from ..factories import init_llm_and_embeddings
from ..graph_rag import GraphRAG
from ..logging_config import get_logger
from ..managers import get_contents_from_session_with_validation, validate_llm_deployment_safe, validate_session_and_urls
from ..models import QARequest, QAResponse
from ..query import QAWithContext

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["qa"])


@router.post("/qa", response_model=QAResponse)
@require_session(strict=False)
@handle_api_errors(QAResponse)
async def qa_endpoint(request: QARequest):
    """Process QA request with context from session."""
    try:
        session_id = request.session_id

        # Use safe validation for consistent error handling
        deployment, validation_error = validate_llm_deployment_safe(request.llm_model)
        if validation_error:
            return QAResponse(
                success=False,
                message=validation_error,
                question=request.question,
                answer=None,
                urls=[],
            )

        is_valid, validation_error = validate_session_and_urls(
            session_id, request.urls, "Q&A"
        )
        if not is_valid:
            return QAResponse(
                success=False,
                message=validation_error or "Validation failed",
                question=request.question,
                answer=None,
                urls=[],
            )

        contents, missing_urls, error_msg = get_contents_from_session_with_validation(
            session_id or "", request.urls, "Q&A"
        )
        if error_msg:
            return QAResponse(
                success=False,
                message=error_msg,
                question=request.question,
                answer=None,
                urls=[],
            )

        llm, embeddings = init_llm_and_embeddings(deployment, request.llm_model)
        documents = [
            Document(page_content=content["text"], metadata={"url": content["url"]})
            for content in contents
            if content.get("text")
        ]

        if not documents:
            return QAResponse(
                success=False,
                message="No valid document content found for answering the question",
                question=request.question,
                answer=None,
                urls=[],
            )

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP
        )
        split_docs = text_splitter.split_documents(documents)
        qa_system = QAWithContext(llm=llm, emb=embeddings)
        result = await qa_system.query(
            query=request.question,
            lang=request.lang,
            docs=split_docs,
            thread_id=request.thread_id,
        )

        return QAResponse(
            success=True,
            message="Q&A processing successful",
            question=result.get("question", request.question),
            answer=result.get("answer"),
            urls=result.get("urls", []),
        )

    except Exception as e:
        logger.error(f"Error in QA processing: {str(e)}")
        return QAResponse(
            success=False,
            message=f"Q&A processing failed: {str(e)}",
            question=request.question,
            answer=None,
            urls=[],
        )


@router.post("/qa/graph", response_model=QAResponse)
@require_session(strict=False)
@handle_api_errors(QAResponse)
async def qa_graph_endpoint(request: QARequest):
    """Process QA request using GraphRAG for enhanced entity understanding."""
    try:
        session_id = request.session_id

        # Use safe validation for consistent error handling
        deployment, validation_error = validate_llm_deployment_safe(request.llm_model)
        if validation_error:
            return QAResponse(
                success=False,
                message=validation_error,
                question=request.question,
                answer=None,
                urls=[],
            )

        is_valid, validation_error = validate_session_and_urls(
            session_id, request.urls, "Graph Q&A"
        )
        if not is_valid:
            return QAResponse(
                success=False,
                message=validation_error or "Validation failed",
                question=request.question,
                answer=None,
                urls=[],
            )

        contents, missing_urls, error_msg = get_contents_from_session_with_validation(
            session_id or "", request.urls, "Graph Q&A"
        )
        if error_msg:
            return QAResponse(
                success=False,
                message=error_msg,
                question=request.question,
                answer=None,
                urls=[],
            )

        llm, embeddings = init_llm_and_embeddings(deployment, request.llm_model)
        documents = [
            Document(page_content=content["text"], metadata={"url": content["url"]})
            for content in contents
            if content.get("text")
        ]

        if not documents:
            return QAResponse(
                success=False,
                message="No valid document content found for answering the question",
                question=request.question,
                answer=None,
                urls=[],
            )

        # Use GraphRAG for enhanced QA
        graph_rag = GraphRAG(llm=llm, emb=embeddings)
        result = await graph_rag.answer_with_graph(
            query=request.question,
            docs=documents,
            lang=request.lang,
            company_name=request.company_name,
            thread_id=request.thread_id,
        )

        return QAResponse(
            success=True,
            message="GraphRAG Q&A processing successful",
            question=request.question,
            answer=result.get("answer"),
            urls=request.urls,
        )

    except Exception as e:
        logger.error(f"Error in GraphRAG QA processing: {str(e)}")
        return QAResponse(
            success=False,
            message=f"GraphRAG Q&A processing failed: {str(e)}",
            question=request.question,
            answer=None,
            urls=[],
        )


@router.post("/qa/stream")
@require_session(strict=False)
async def qa_stream_endpoint(request: QARequest):
    """Process QA request with streaming response."""

    def format_event(event_type: str, data: dict) -> str:
        return f"event: {event_type}\n" f"data: {json.dumps(data)}\n\n"

    async def generate_stream():
        try:
            session_id = request.session_id

            yield format_event("status", {"message": "Initializing Q&A..."})

            deployment, validation_error = validate_llm_deployment_safe(request.llm_model)
            if validation_error:
                yield format_event("error", {"message": validation_error})
                return

            is_valid, validation_error = validate_session_and_urls(
                session_id, request.urls, "Q&A"
            )
            if not is_valid:
                yield format_event("error", {"message": validation_error or "Validation failed"})
                return

            yield format_event("status", {"message": "Loading content from session..."})

            contents, missing_urls, error_msg = get_contents_from_session_with_validation(
                session_id or "", request.urls, "Q&A"
            )
            if error_msg:
                yield format_event("error", {"message": error_msg})
                return

            llm, embeddings = init_llm_and_embeddings(deployment, request.llm_model)
            documents = [
                Document(page_content=content["text"], metadata={"url": content["url"]})
                for content in contents
                if content.get("text")
            ]

            if not documents:
                yield format_event("error", {"message": "No valid document content found"})
                return

            yield format_event("status", {
                "message": f"Processing {len(documents)} documents..."
            })

            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP
            )
            split_docs = text_splitter.split_documents(documents)

            yield format_event("status", {
                "message": f"Running RAG on {len(split_docs)} chunks..."
            })

            qa_system = QAWithContext(llm=llm, emb=embeddings)

            # Use native LangGraph streaming
            async for event in qa_system.query_stream(
                query=request.question,
                lang=request.lang,
                docs=split_docs,
                company_name=request.company_name,
                thread_id=request.thread_id,
            ):
                event_type = event.get("event", "update")
                event_data = event.get("data", {})

                if event_type == "update":
                    # Stream node updates from LangGraph
                    for node_name, node_output in event_data.items():
                        if node_name == "retrieve":
                            yield format_event("retrieve", {
                                "message": f"Retrieved {len(node_output.get('context', []))} documents",
                                "urls": node_output.get("urls", []),
                            })
                        elif node_name == "generate":
                            answer = node_output.get("answer", "")
                            yield format_event("complete", {
                                "success": True,
                                "message": "Q&A processing successful",
                                "question": request.question,
                                "answer": answer,
                                "urls": [],
                            })
                elif event_type == "error":
                    yield format_event("error", event_data)

        except Exception as e:
            logger.error(f"Error in streaming QA processing: {str(e)}")
            yield format_event("error", {"message": f"Q&A processing failed: {str(e)}"})

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )