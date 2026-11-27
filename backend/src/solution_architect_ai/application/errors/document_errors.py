from enum import StrEnum


class DocumentErrorCode(StrEnum):
    INVALID_FILENAME = "invalid_filename"
    UNSUPPORTED_FORMAT = "unsupported_format"
    INVALID_MIME = "invalid_mime"
    TOO_LARGE = "document_too_large"
    EMPTY = "empty_document"
    INVALID_TEXT = "invalid_text_encoding"
    MISSING_FILE = "document_file_missing"
    CORRUPT_FILE = "document_file_corrupt"
    FILE_CONFLICT = "immutable_file_conflict"
    INVALID_KEY = "invalid_storage_key"
    STORAGE_UNAVAILABLE = "file_storage_unavailable"
    PARSE_FAILED = "document_parse_failed"
    NO_TEXT = "document_has_no_text_layer"
    UNSUPPORTED_CONTENT = "unsupported_document_content"
    CORRUPT_PARSE = "parsed_document_corrupt"
    CORRUPT_METADATA = "document_metadata_corrupt"


class DocumentFailure(Exception):
    def __init__(self, code: DocumentErrorCode) -> None:
        super().__init__(code)
        self.code: DocumentErrorCode = code
