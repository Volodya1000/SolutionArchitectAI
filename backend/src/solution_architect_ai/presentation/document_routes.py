from http import HTTPStatus
from typing import Annotated, Final
from urllib.parse import quote
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from solution_architect_ai.application.document_dto import (
    AttachDocument,
    DocumentErrorView,
    DocumentVersionView,
    DocumentView,
    UploadDocument,
    UploadOperationView,
)
from solution_architect_ai.application.document_errors import DocumentErrorCode, DocumentFailure
from solution_architect_ai.application.documents import DocumentService
from solution_architect_ai.domain.documents import ParsedDocument

router: APIRouter = APIRouter(prefix="/api", route_class=DishkaRoute)
_ERROR_STATUSES: Final[dict[DocumentErrorCode, HTTPStatus]] = {
    DocumentErrorCode.UNSUPPORTED_FORMAT: HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
    DocumentErrorCode.INVALID_MIME: HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
    DocumentErrorCode.TOO_LARGE: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    DocumentErrorCode.MISSING_FILE: HTTPStatus.NOT_FOUND,
    DocumentErrorCode.CORRUPT_FILE: HTTPStatus.CONFLICT,
    DocumentErrorCode.CORRUPT_PARSE: HTTPStatus.CONFLICT,
    DocumentErrorCode.CORRUPT_METADATA: HTTPStatus.INTERNAL_SERVER_ERROR,
    DocumentErrorCode.FILE_CONFLICT: HTTPStatus.CONFLICT,
    DocumentErrorCode.STORAGE_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
}


async def document_error(_request: Request, error: Exception) -> JSONResponse:
    code: DocumentErrorCode = (
        error.code if isinstance(error, DocumentFailure) else DocumentErrorCode.STORAGE_UNAVAILABLE
    )
    status: HTTPStatus = _ERROR_STATUSES.get(code, HTTPStatus.UNPROCESSABLE_ENTITY)
    return JSONResponse(status_code=status, content=DocumentErrorView(code=code.value).model_dump())


@router.get("/documents")
async def documents(service: FromDishka[DocumentService]) -> list[DocumentView]:
    return await service.list_documents()


@router.post("/documents", status_code=201)
async def upload(
    request: Request,
    operation_id: UUID,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    service: FromDishka[DocumentService],
) -> DocumentVersionView:
    command: UploadDocument = UploadDocument(
        operation_id=operation_id,
        filename=filename,
        mime_type=request.headers.get("content-type", ""),
    )
    return await service.upload(command, request.stream())


@router.post("/documents/{file_id}/versions", status_code=201)
async def upload_version(
    file_id: UUID,
    request: Request,
    operation_id: UUID,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    service: FromDishka[DocumentService],
) -> DocumentVersionView:
    command: UploadDocument = UploadDocument(
        operation_id=operation_id,
        file_id=file_id,
        filename=filename,
        mime_type=request.headers.get("content-type", ""),
    )
    return await service.upload(command, request.stream())


@router.get("/documents/{file_id}/versions")
async def versions(
    file_id: UUID, service: FromDishka[DocumentService]
) -> list[DocumentVersionView]:
    return await service.versions(file_id)


@router.get("/document-versions/{version_id}")
async def version(version_id: UUID, service: FromDishka[DocumentService]) -> DocumentVersionView:
    return await service.version(version_id)


@router.get("/document-versions/{version_id}/content")
async def content(version_id: UUID, service: FromDishka[DocumentService]) -> Response:
    metadata: DocumentVersionView = await service.version(version_id)
    data: bytes = await service.read(version_id)
    return Response(
        data,
        media_type=metadata.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(metadata.original_name)}",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{metadata.sha256}"',
        },
    )


@router.get("/document-versions/{version_id}/parsed")
async def parsed(version_id: UUID, service: FromDishka[DocumentService]) -> ParsedDocument:
    return await service.parsed(version_id)


@router.get("/document-uploads/{operation_id}")
async def operation(
    operation_id: UUID, service: FromDishka[DocumentService]
) -> UploadOperationView:
    return await service.operation(operation_id)


@router.post("/document-uploads/recover")
async def recover(service: FromDishka[DocumentService]) -> list[UploadOperationView]:
    return await service.recover()


@router.post("/messages/{message_id}/document-versions")
async def attach(
    message_id: UUID, body: AttachDocument, service: FromDishka[DocumentService]
) -> DocumentVersionView:
    return await service.attach(message_id, body.version_id)


@router.get("/messages/{message_id}/document-versions")
async def attachments(
    message_id: UUID, service: FromDishka[DocumentService]
) -> list[DocumentVersionView]:
    return await service.attachments(message_id)
