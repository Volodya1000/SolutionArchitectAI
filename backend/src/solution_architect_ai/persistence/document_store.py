from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import ScalarResult, Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.document_dto import (
    DocumentVersionView,
    DocumentView,
    StoredParse,
    UploadDocument,
    UploadOperationView,
    UploadStage,
)
from solution_architect_ai.application.document_errors import DocumentErrorCode, DocumentFailure
from solution_architect_ai.application.documents import PARSED_DOCUMENT
from solution_architect_ai.application.errors import Conflict, Missing
from solution_architect_ai.domain.documents import DocumentFragment, SourceLocator
from solution_architect_ai.persistence.document_models import (
    DocumentFragmentRow,
    DocumentRow,
    DocumentUploadRow,
    DocumentVersionRow,
    MessageDocumentVersionRow,
    ParsedDocumentRow,
)
from solution_architect_ai.persistence.models import ChatRow, MessageRow, TaskRow

LOCATOR: Final[TypeAdapter[SourceLocator]] = TypeAdapter(SourceLocator)


def upload_view(row: DocumentUploadRow) -> UploadOperationView:
    return UploadOperationView(
        operation_id=row.operation_id,
        payload_digest=row.payload_digest,
        stage=UploadStage(row.stage),
        version=DocumentVersionView.model_validate_json(row.version_json, strict=True),
    )


class SqlAlchemyDocumentStore:
    def __init__(self, session: AsyncSession, *, task_id: UUID) -> None:
        self.session: AsyncSession = session
        self.task_id: UUID = task_id

    async def list_documents(self) -> list[DocumentView]:
        rows: ScalarResult[DocumentRow] = await self.session.scalars(
            select(DocumentRow)
            .where(DocumentRow.task_id == self.task_id)
            .order_by(DocumentRow.created_at.desc(), DocumentRow.file_id)
        )
        return [DocumentView.model_validate(row) for row in rows]

    async def document_row(self, file_id: UUID) -> DocumentRow:
        row: DocumentRow | None = await self.session.scalar(
            select(DocumentRow).where(
                DocumentRow.file_id == file_id, DocumentRow.task_id == self.task_id
            )
        )
        if row is None:
            raise Missing("document")
        return row

    async def versions(self, file_id: UUID) -> list[DocumentVersionView]:
        await self.document_row(file_id)
        rows: ScalarResult[DocumentVersionRow] = await self.session.scalars(
            select(DocumentVersionRow)
            .where(
                DocumentVersionRow.file_id == file_id, DocumentVersionRow.task_id == self.task_id
            )
            .order_by(DocumentVersionRow.uploaded_at.desc(), DocumentVersionRow.version_id)
        )
        return [DocumentVersionView.model_validate(row) for row in rows]

    async def version_row(self, version_id: UUID, *, lock: bool = False) -> DocumentVersionRow:
        query: Select[DocumentVersionRow] = select(DocumentVersionRow).where(
            DocumentVersionRow.version_id == version_id, DocumentVersionRow.task_id == self.task_id
        )
        row: DocumentVersionRow | None = await self.session.scalar(
            query.with_for_update() if lock else query
        )
        if row is None:
            raise Missing("document_version")
        return row

    async def version(self, version_id: UUID) -> DocumentVersionView:
        return DocumentVersionView.model_validate(await self.version_row(version_id))

    async def upload_row(self, operation_id: UUID) -> DocumentUploadRow | None:
        return await self.session.scalar(
            select(DocumentUploadRow)
            .where(
                DocumentUploadRow.operation_id == operation_id,
                DocumentUploadRow.task_id == self.task_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def prepare(
        self, command: UploadDocument, size: int, digest: str, payload_digest: str
    ) -> UploadOperationView:
        task: TaskRow | None = await self.session.scalar(
            select(TaskRow).where(TaskRow.id == self.task_id).with_for_update()
        )
        if task is None:
            raise Missing("task")
        existing: DocumentUploadRow | None = await self.upload_row(command.operation_id)
        if existing is not None:
            if existing.payload_digest != payload_digest:
                raise Conflict("upload_payload_mismatch")
            return upload_view(existing)
        file_id: UUID = command.file_id or uuid4()
        if command.file_id is None:
            self.session.add(
                DocumentRow(
                    file_id=file_id,
                    task_id=self.task_id,
                    name=command.filename,
                    created_at=datetime.now(UTC),
                )
            )
            await self.session.flush()
        else:
            await self.document_row(file_id)
        version_id: UUID = uuid4()
        version: DocumentVersionView = DocumentVersionView(
            file_id=file_id,
            version_id=version_id,
            task_id=self.task_id,
            sha256=digest,
            mime_type=command.mime_type,
            size=size,
            original_name=command.filename,
            uploaded_at=datetime.now(UTC),
            storage_key=f"{self.task_id}/{version_id}",
        )
        row: DocumentUploadRow = DocumentUploadRow(
            id=uuid4(),
            task_id=self.task_id,
            operation_id=command.operation_id,
            payload_digest=payload_digest,
            stage=UploadStage.PREPARED.value,
            version_json=version.model_dump_json(),
        )
        self.session.add(row)
        await self.session.flush()
        return upload_view(row)

    async def complete(self, operation_id: UUID) -> DocumentVersionView:
        row: DocumentUploadRow | None = await self.upload_row(operation_id)
        if row is None:
            raise Missing("document_upload")
        operation: UploadOperationView = upload_view(row)
        if operation.stage == UploadStage.COMPLETED:
            return await self.version(operation.version.version_id)
        version: DocumentVersionView = operation.version
        self.session.add(DocumentVersionRow(**version.model_dump()))
        row.stage = UploadStage.COMPLETED.value
        await self.session.flush()
        return version

    async def pending(self) -> list[UploadOperationView]:
        rows: ScalarResult[DocumentUploadRow] = await self.session.scalars(
            select(DocumentUploadRow).where(
                DocumentUploadRow.task_id == self.task_id,
                DocumentUploadRow.stage == UploadStage.PREPARED.value,
            )
        )
        return [upload_view(row) for row in rows]

    async def operation(self, operation_id: UUID) -> UploadOperationView:
        row: DocumentUploadRow | None = await self.upload_row(operation_id)
        if row is None:
            raise Missing("document_upload")
        return upload_view(row)

    async def get_parse(self, version_id: UUID) -> StoredParse | None:
        await self.version_row(version_id)
        row: ParsedDocumentRow | None = await self.session.get(ParsedDocumentRow, version_id)
        if row is None:
            return None
        try:
            return StoredParse(
                document=PARSED_DOCUMENT.validate_json(row.body, strict=True), digest=row.digest
            )
        except ValidationError:
            raise DocumentFailure(DocumentErrorCode.CORRUPT_PARSE) from None

    async def save_parse(self, parsed: StoredParse) -> StoredParse:
        await self.version_row(parsed.document.version_id, lock=True)
        existing: StoredParse | None = await self.get_parse(parsed.document.version_id)
        if existing is not None:
            return existing
        self.session.add(
            ParsedDocumentRow(
                version_id=parsed.document.version_id,
                parser_version=parsed.document.parser_version,
                body=PARSED_DOCUMENT.dump_json(parsed.document).decode(),
                digest=parsed.digest,
            )
        )
        await self.session.flush()
        fragment: DocumentFragment
        for fragment in parsed.document.fragments:
            self.session.add(
                DocumentFragmentRow(
                    fragment_id=fragment.fragment_id,
                    version_id=parsed.document.version_id,
                    text=fragment.text,
                    locator_json=LOCATOR.dump_json(fragment.locator).decode(),
                )
            )
        await self.session.flush()
        return parsed

    async def attach(self, message_id: UUID, version_id: UUID) -> DocumentVersionView:
        message: MessageRow | None = await self.session.scalar(
            select(MessageRow)
            .join(ChatRow, ChatRow.id == MessageRow.chat_id)
            .where(MessageRow.id == message_id, ChatRow.task_id == self.task_id)
            .with_for_update(of=MessageRow)
        )
        if message is None:
            raise Missing("message")
        version: DocumentVersionView = await self.version(version_id)
        row: MessageDocumentVersionRow | None = await self.session.get(
            MessageDocumentVersionRow, (message_id, version_id)
        )
        if row is None:
            self.session.add(
                MessageDocumentVersionRow(message_id=message_id, version_id=version_id)
            )
            await self.session.flush()
        return version

    async def attachments(self, message_id: UUID) -> list[DocumentVersionView]:
        message: MessageRow | None = await self.session.scalar(
            select(MessageRow)
            .join(ChatRow, ChatRow.id == MessageRow.chat_id)
            .where(MessageRow.id == message_id, ChatRow.task_id == self.task_id)
        )
        if message is None:
            raise Missing("message")
        rows: ScalarResult[DocumentVersionRow] = await self.session.scalars(
            select(DocumentVersionRow)
            .join(
                MessageDocumentVersionRow,
                MessageDocumentVersionRow.version_id == DocumentVersionRow.version_id,
            )
            .where(
                MessageDocumentVersionRow.message_id == message_id,
                DocumentVersionRow.task_id == self.task_id,
            )
            .order_by(DocumentVersionRow.uploaded_at, DocumentVersionRow.version_id)
        )
        return [DocumentVersionView.model_validate(row) for row in rows]
