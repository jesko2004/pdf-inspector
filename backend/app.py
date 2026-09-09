"""FastAPI HTTP surface for PDF tasks and extraction profiles."""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import partial
from typing import Annotated

try:
    from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
    from fastapi.responses import FileResponse, Response
except ImportError as exc:
    raise RuntimeError(
        "backend dependencies are missing; install with `pip install -e '.[backend]'`"
    ) from exc

from .config import Settings
from .embeddings import EmbeddingError
from .knowledge_models import (
    KnowledgeBaseCreate,
    KnowledgeBaseReindex,
    KnowledgeBaseUpdate,
    KnowledgeDocumentIngest,
    KnowledgeRetrievalEvaluationRequest,
    KnowledgeSearchRequest,
)
from .knowledge_service import EmbeddingFactory, KnowledgeService
from .knowledge_store import (
    InvalidKnowledgeStateError,
    KnowledgeBaseNotFoundError,
    KnowledgeConflictError,
    KnowledgeDocumentNotFoundError,
    KnowledgeStore,
)
from .ocr import create_ocr_provider
from .processor import process_document
from .profile_store import (
    BuiltinProfileError,
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
)
from .profiles import Profile
from .service import Processor, ResultNotReadyError, TaskService, UploadValidationError
from .table_data import table_to_csv
from .task_store import InvalidTaskStateError, TaskNotFoundError
from .vector_store import VectorStore, create_vector_store


def create_app(
    settings: Settings | None = None,
    *,
    processor: Processor | None = None,
    embedding_factory: EmbeddingFactory | None = None,
    vector_store: VectorStore | None = None,
    start_workers: bool = True,
) -> FastAPI:
    settings = settings or Settings.from_env()
    configured_processor = processor or partial(
        process_document, ocr_provider=create_ocr_provider(settings)
    )
    service = TaskService(
        settings,
        processor=configured_processor,
        start_workers=start_workers,
    )
    knowledge = KnowledgeService(
        settings,
        service,
        KnowledgeStore(settings.knowledge_database_path),
        vector_store or create_vector_store(settings),
        embedding_factory=embedding_factory,
        start_workers=start_workers,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        knowledge.close()
        service.close()

    app = FastAPI(
        title="PDF Inspector Task API",
        version="1.0.0",
        description="PDF 异步解析、任务管理和可配置业务字段提取。",
        lifespan=lifespan,
    )
    app.state.service = service
    app.state.knowledge = knowledge

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/profiles")
    def list_profiles() -> dict:
        return {"items": service.profiles.list()}

    @app.post("/v1/knowledge-bases", status_code=201)
    def create_knowledge_base(payload: KnowledgeBaseCreate) -> dict:
        try:
            return knowledge.create_knowledge_base(
                name=payload.name,
                description=payload.description,
                embedding_provider=payload.embedding_provider,
                embedding_model=payload.embedding_model,
                embedding_dimensions=payload.embedding_dimensions,
            )
        except KnowledgeConflictError as exc:
            raise HTTPException(
                status_code=409, detail="knowledge_base_already_exists"
            ) from exc
        except (ValueError, EmbeddingError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/knowledge-bases")
    def list_knowledge_bases(
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict:
        return {
            "items": knowledge.store.list_knowledge_bases(limit, offset),
            "limit": limit,
            "offset": offset,
        }

    @app.get("/v1/knowledge-bases/{knowledge_base_id}")
    def get_knowledge_base(knowledge_base_id: str) -> dict:
        try:
            return knowledge.store.get_knowledge_base(knowledge_base_id)
        except KnowledgeBaseNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_base_not_found"
            ) from exc

    @app.post("/v1/knowledge-bases/{knowledge_base_id}/search")
    def search_knowledge_base(
        knowledge_base_id: str, payload: KnowledgeSearchRequest
    ) -> dict:
        try:
            return knowledge.search(
                knowledge_base_id,
                payload.query,
                top_k=payload.top_k,
                min_score=payload.min_score,
                document_ids=payload.document_ids,
                page_start=payload.page_start,
                page_end=payload.page_end,
                kinds=payload.kinds,
                section_path_prefix=payload.section_path_prefix,
            )
        except KnowledgeBaseNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_base_not_found"
            ) from exc
        except (EmbeddingError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/v1/knowledge-bases/{knowledge_base_id}/retrieval-evaluations")
    def evaluate_knowledge_retrieval(
        knowledge_base_id: str, payload: KnowledgeRetrievalEvaluationRequest
    ) -> dict:
        try:
            return knowledge.evaluate_retrieval(
                knowledge_base_id,
                [case.model_dump(mode="json") for case in payload.cases],
                top_k=payload.top_k,
                min_score=payload.min_score,
                document_ids=payload.document_ids,
                page_start=payload.page_start,
                page_end=payload.page_end,
                kinds=payload.kinds,
                section_path_prefix=payload.section_path_prefix,
            )
        except KnowledgeBaseNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_base_not_found"
            ) from exc
        except (EmbeddingError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.patch("/v1/knowledge-bases/{knowledge_base_id}")
    def update_knowledge_base(
        knowledge_base_id: str, payload: KnowledgeBaseUpdate
    ) -> dict:
        try:
            current = knowledge.store.get_knowledge_base(knowledge_base_id)
            return knowledge.store.update_knowledge_base(
                knowledge_base_id,
                name=payload.name if payload.name is not None else current["name"],
                description=(
                    payload.description
                    if payload.description is not None
                    else current["description"]
                ),
            )
        except KnowledgeBaseNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_base_not_found"
            ) from exc
        except KnowledgeConflictError as exc:
            raise HTTPException(
                status_code=409, detail="knowledge_base_already_exists"
            ) from exc

    @app.delete("/v1/knowledge-bases/{knowledge_base_id}", status_code=204)
    def delete_knowledge_base(knowledge_base_id: str) -> Response:
        try:
            knowledge.delete_knowledge_base(knowledge_base_id)
        except KnowledgeBaseNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_base_not_found"
            ) from exc
        except InvalidKnowledgeStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(status_code=204)

    @app.post("/v1/knowledge-bases/{knowledge_base_id}/documents", status_code=202)
    def ingest_knowledge_document(
        knowledge_base_id: str, payload: KnowledgeDocumentIngest
    ) -> dict:
        try:
            return knowledge.ingest_task(
                knowledge_base_id, payload.task_id, payload.document_key
            )
        except KnowledgeBaseNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_base_not_found"
            ) from exc
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task_not_found") from exc
        except ResultNotReadyError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "task_result_not_ready", "status": str(exc)},
            ) from exc
        except InvalidKnowledgeStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/knowledge-bases/{knowledge_base_id}/documents")
    def list_knowledge_documents(
        knowledge_base_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict:
        try:
            return {
                "items": knowledge.store.list_documents(
                    knowledge_base_id, limit, offset
                ),
                "limit": limit,
                "offset": offset,
            }
        except KnowledgeBaseNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_base_not_found"
            ) from exc

    @app.get("/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}")
    def get_knowledge_document(knowledge_base_id: str, document_id: str) -> dict:
        try:
            return knowledge.get_document(knowledge_base_id, document_id)
        except KnowledgeDocumentNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_document_not_found"
            ) from exc

    @app.delete(
        "/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}",
        status_code=204,
    )
    def delete_knowledge_document(knowledge_base_id: str, document_id: str) -> Response:
        try:
            knowledge.delete_document(knowledge_base_id, document_id)
        except KnowledgeDocumentNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_document_not_found"
            ) from exc
        except InvalidKnowledgeStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(status_code=204)

    @app.get("/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}/chunks")
    def list_knowledge_chunks(
        knowledge_base_id: str,
        document_id: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict:
        try:
            knowledge.get_document(knowledge_base_id, document_id)
            return {
                "items": knowledge.store.list_chunks(document_id, limit, offset),
                "limit": limit,
                "offset": offset,
            }
        except KnowledgeDocumentNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_document_not_found"
            ) from exc

    @app.get("/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}/batches")
    def list_embedding_batches(knowledge_base_id: str, document_id: str) -> dict:
        try:
            knowledge.get_document(knowledge_base_id, document_id)
            return {"items": knowledge.store.list_batches(document_id)}
        except KnowledgeDocumentNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_document_not_found"
            ) from exc

    @app.post(
        "/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}/retry",
        status_code=202,
    )
    def retry_embedding_batches(knowledge_base_id: str, document_id: str) -> dict:
        try:
            return knowledge.retry_document(knowledge_base_id, document_id)
        except KnowledgeDocumentNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_document_not_found"
            ) from exc
        except InvalidKnowledgeStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/knowledge-bases/{knowledge_base_id}/reindex", status_code=202)
    def reindex_knowledge_base(
        knowledge_base_id: str, payload: KnowledgeBaseReindex
    ) -> dict:
        try:
            return knowledge.reindex_knowledge_base(
                knowledge_base_id,
                embedding_provider=payload.embedding_provider,
                embedding_model=payload.embedding_model,
                embedding_dimensions=payload.embedding_dimensions,
            )
        except KnowledgeBaseNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="knowledge_base_not_found"
            ) from exc
        except InvalidKnowledgeStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, EmbeddingError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/profiles/{profile_id}")
    def get_profile(profile_id: str) -> dict:
        for profile in service.profiles.list():
            if profile["id"] == profile_id:
                return profile
        raise HTTPException(status_code=404, detail="profile_not_found")

    @app.post("/v1/profiles", status_code=201)
    def create_profile(profile: Profile) -> dict:
        try:
            saved = service.profiles.create(profile)
        except ProfileAlreadyExistsError as exc:
            raise HTTPException(
                status_code=409, detail="profile_already_exists"
            ) from exc
        return {**saved.model_dump(mode="json"), "builtin": False}

    @app.put("/v1/profiles/{profile_id}")
    def update_profile(profile_id: str, profile: Profile) -> dict:
        try:
            saved = service.profiles.update(profile_id, profile)
        except ProfileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="profile_not_found") from exc
        except BuiltinProfileError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {**saved.model_dump(mode="json"), "builtin": False}

    @app.post("/v1/tasks", status_code=202)
    def create_task(
        file: Annotated[UploadFile, File(description="PDF file")],
        profile_id: Annotated[str, Form()] = "purchase_quote",
    ) -> dict:
        try:
            return service.create_task(
                file.filename or "document.pdf", file.file, profile_id
            )
        except ProfileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="profile_not_found") from exc
        except UploadValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/tasks")
    def list_tasks(
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict:
        return {
            "items": service.list_tasks(limit, offset),
            "limit": limit,
            "offset": offset,
        }

    @app.get("/v1/tasks/{task_id}")
    def get_task(task_id: str) -> dict:
        try:
            return service.get_task(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task_not_found") from exc

    @app.get("/v1/tasks/{task_id}/result")
    def get_result(task_id: str, download: bool = False):
        try:
            if download:
                path = service.get_result_path(task_id)
                return FileResponse(
                    path,
                    media_type="application/json",
                    filename=f"{task_id}.json",
                )
            return service.get_result(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task_not_found") from exc
        except ResultNotReadyError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "result_not_ready", "status": str(exc)},
            ) from exc

    @app.get("/v1/tasks/{task_id}/tables")
    def get_tables(task_id: str) -> dict:
        try:
            return service.get_result(task_id).get(
                "tables", {"status": "ready", "items": [], "issues": []}
            )
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task_not_found") from exc
        except ResultNotReadyError as exc:
            raise HTTPException(status_code=409, detail="result_not_ready") from exc

    @app.get("/v1/tasks/{task_id}/tables/{table_id}.csv")
    def download_table(task_id: str, table_id: str):
        try:
            result = service.get_result(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task_not_found") from exc
        except ResultNotReadyError as exc:
            raise HTTPException(status_code=409, detail="result_not_ready") from exc
        table = next(
            (
                item
                for item in result.get("tables", {}).get("items", [])
                if item["id"] == table_id
            ),
            None,
        )
        if table is None:
            raise HTTPException(status_code=404, detail="table_not_found")
        return Response(
            content="\ufeff" + table_to_csv(table),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{table_id}.csv"'},
        )

    @app.get("/v1/tasks/{task_id}/chunks")
    def get_chunks(task_id: str) -> dict:
        try:
            result = service.get_result(task_id)
            return {
                "items": result.get("chunks", []),
                "quality": result.get("chunk_quality", {}),
            }
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task_not_found") from exc
        except ResultNotReadyError as exc:
            raise HTTPException(status_code=409, detail="result_not_ready") from exc

    @app.post("/v1/tasks/{task_id}/retry", status_code=202)
    def retry_task(task_id: str) -> dict:
        try:
            return service.retry(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task_not_found") from exc
        except InvalidTaskStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app
