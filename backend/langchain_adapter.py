"""Small LangChain Core adapter around the existing knowledge search service."""

from __future__ import annotations

from typing import Any


def search_items_to_documents(items: list[dict[str, Any]]) -> list[Any]:
    try:
        from langchain_core.documents import Document
    except ImportError as exc:
        raise RuntimeError(
            "LangChain Core is not installed; install the 'rag-langchain' extra"
        ) from exc
    return [
        Document(
            page_content=item.get("context_content", item["content"]),
            metadata={
                **{
                    key: value
                    for key, value in item.items()
                    if key not in {"content", "context_content"}
                },
                "child_content": item["content"],
            },
        )
        for item in items
    ]


def build_search_runnable(
    knowledge_service,
    knowledge_base_id: str,
    **search_options,
):
    """Expose PDF Inspector retrieval as a standard LangChain Runnable."""
    try:
        from langchain_core.runnables import RunnableLambda
    except ImportError as exc:
        raise RuntimeError(
            "LangChain Core is not installed; install the 'rag-langchain' extra"
        ) from exc

    def retrieve(query: str):
        result = knowledge_service.search(
            knowledge_base_id,
            query,
            **search_options,
        )
        return search_items_to_documents(result["items"])

    return RunnableLambda(retrieve)
