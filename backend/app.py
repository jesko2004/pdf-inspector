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
from .ocr import create_ocr_provider
from .processor import process_document
from .profile_store import (
    BuiltinProfileError,
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
)
from .profiles import Profile
from .service import Processor, ResultNotReadyError, TaskService, UploadValidationError
from .task_store import InvalidTaskStateError, TaskNotFoundError
from .table_data import table_to_csv


def create_app(
    settings: Settings | None = None,
    *,
    processor: Processor | None = None,
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

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        service.close()

    app = FastAPI(
        title="PDF Inspector Task API",
        version="1.0.0",
        description="PDF 异步解析、任务管理和可配置业务字段提取。",
        lifespan=lifespan,
    )
    app.state.service = service

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/profiles")
    def list_profiles() -> dict:
        return {"items": service.profiles.list()}

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
            headers={
                "Content-Disposition": f'attachment; filename="{table_id}.csv"'
            },
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
