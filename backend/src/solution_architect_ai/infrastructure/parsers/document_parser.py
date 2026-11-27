from hashlib import sha256
from uuid import UUID

from markdown_it import MarkdownIt
from markdown_it.token import Token

from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    ParsedDocument,
    SourceLocator,
)
from solution_architect_ai.infrastructure.parsers.document_fragments import (
    PARSER_VERSION,
    fragment,
)
from solution_architect_ai.infrastructure.parsers.document_validator import (
    DOCX_MIME,
    MARKDOWN_MIME,
    PDF_MIME,
    DocumentValidator,
    ValidatedDocument,
)
from solution_architect_ai.infrastructure.parsers.docx_parser import parse_docx
from solution_architect_ai.infrastructure.parsers.pdf_parser import parse_pdf


class DocumentParser:
    def __init__(self) -> None:
        self.validator: DocumentValidator = DocumentValidator()
        self.markdown_parser: MarkdownIt = MarkdownIt()

    def validate(self, content: bytes, filename: str, mime_type: str) -> str:
        return self.validator.validate(content, filename, mime_type).mime_type

    def parse(
        self, file_id: UUID, version_id: UUID, content: bytes, filename: str, mime_type: str
    ) -> ParsedDocument:
        validated: ValidatedDocument = self.validator.validate(content, filename, mime_type)
        mime: str = validated.mime_type
        if mime == PDF_MIME:
            return parse_pdf(file_id, version_id, content)
        if mime == DOCX_MIME:
            return parse_docx(file_id, version_id, content)
        text: str | None = validated.text
        if text is None:
            raise DocumentFailure(DocumentErrorCode.INVALID_TEXT)
        sections: dict[int, str] = self.headings(text) if mime == MARKDOWN_MIME else {}
        section: str = ""
        fragments: list[DocumentFragment] = []
        index: int
        line: str
        for index, line in enumerate(text.splitlines(), 1):
            section = sections.get(index, section)
            if line.strip():
                fragments.append(
                    fragment(
                        version_id, line, SourceLocator(LocatorKind.LINES, index, index, section)
                    )
                )
        return ParsedDocument(
            file_id, version_id, sha256(content).hexdigest(), PARSER_VERSION, text, tuple(fragments)
        )

    def headings(self, text: str) -> dict[int, str]:
        tokens: list[Token] = self.markdown_parser.parse(text)
        headings: dict[int, str] = {}
        index: int
        token: Token
        for index, token in enumerate(tokens):
            if (
                token.type == "heading_open"
                and token.map is not None
                and index + 1 < len(tokens)
                and tokens[index + 1].type == "inline"
            ):
                headings[token.map[0] + 1] = tokens[index + 1].content
        return headings
