from sqlalchemy import SQLColumnExpression, case, cast, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.elements import ColumnElement, Grouping


def guarded_json(column: SQLColumnExpression[str]) -> ColumnElement[object]:
    # TEXT records predate JSONB columns. Invalid JSON becomes null for the typed
    # read boundary instead of aborting the transaction before decoding runs.
    return Grouping(
        case((func.pg_input_is_valid(column, "jsonb"), cast(column, JSONB)), else_=None)
    )
