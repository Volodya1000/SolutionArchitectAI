from pydantic import BaseModel, TypeAdapter, ValidationError


def read_stored_model[ModelT: BaseModel](
    model: type[ModelT], value: object, *, failure: Exception
) -> ModelT:
    try:
        return model.model_validate(value)
    except ValidationError:
        raise failure from None


def read_stored_json[ModelT: BaseModel](
    model: type[ModelT], value: str, *, failure: Exception, strict: bool | None = None
) -> ModelT:
    try:
        return model.model_validate_json(value, strict=strict)
    except ValidationError:
        raise failure from None


def read_stored_json_value[ValueT](
    adapter: TypeAdapter[ValueT], value: str, *, failure: Exception
) -> ValueT:
    try:
        return adapter.validate_json(value)
    except ValidationError:
        raise failure from None


def read_stored_value[ValueT](
    adapter: TypeAdapter[ValueT], value: object, *, failure: Exception, strict: bool = True
) -> ValueT:
    try:
        return adapter.validate_python(value, strict=strict)
    except ValidationError:
        raise failure from None
