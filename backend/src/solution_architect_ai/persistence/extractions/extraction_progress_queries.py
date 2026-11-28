from uuid import UUID

from sqlalchemy import Boolean, Select, and_, case, cast, column, false, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import LateralFromClause

from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionPartRow
from solution_architect_ai.persistence.sql_json import guarded_json


async def read_part_progress(session: AsyncSession, run_id: UUID) -> tuple[int, int]:
    payload: ColumnElement[object] = cast(guarded_json(ExtractionPartRow.result_json), JSONB)
    fragment_ids: ColumnElement[object] = payload.op("->")("fragment_ids")
    is_array: ColumnElement[bool] = func.coalesce(
        func.jsonb_typeof(fragment_ids) == "array", false()
    )
    safe_fragments: ColumnElement[object] = case(
        (is_array, fragment_ids), else_=func.jsonb_build_array()
    )
    identifiers: LateralFromClause = (
        func.jsonb_array_elements(safe_fragments).table_valued(column("value", JSONB)).lateral()
    )
    valid_identifier: ColumnElement[bool] = identifiers.c.value.is_(None) | (
        func.jsonb_typeof(identifiers.c.value) == "string"
    )
    query: Select[int, int, bool] = (
        select(
            func.count(func.distinct(ExtractionPartRow.id)),
            func.count(func.distinct(identifiers.c.value)),
            func.bool_and(and_(is_array, valid_identifier), type_=Boolean),
        )
        .select_from(ExtractionPartRow)
        .outerjoin(identifiers, true())
        .where(ExtractionPartRow.run_id == run_id)
    )
    completed_parts: int
    processed_fragments: int
    valid: bool | None
    completed_parts, processed_fragments, valid = (await session.execute(query)).one()
    if valid is False:
        raise StoredExtractionCorrupt("stored_result_corrupt")
    return completed_parts, processed_fragments
