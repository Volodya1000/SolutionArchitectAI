import os
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import yaml
from pydantic import BaseModel
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


def validate_nodes(node: Node | None) -> None:
    if isinstance(node, MappingNode):
        validate_mapping(node)
    elif isinstance(node, SequenceNode):
        for child in node.value:
            validate_nodes(child)


def validate_mapping(node: MappingNode) -> None:
    seen: set[str] = set()
    for key, value in node.value:
        if not isinstance(key, ScalarNode) or key.value in seen:
            raise ValueError("Invalid or duplicate YAML key")
        if key.value in {"password", "api_key"}:
            raise ValueError("Secrets are forbidden in YAML")
        seen.add(key.value)
        validate_nodes(value)


def read_yaml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        source = path.read_text(encoding="utf-8")
        validate_nodes(yaml.compose(source, Loader=yaml.SafeLoader))
        data: object = yaml.safe_load(source)
    except (OSError, yaml.YAMLError):
        raise ValueError("Cannot read application YAML") from None
    if data is None:
        return {}
    if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
        raise ValueError("Application YAML must contain a mapping")
    return cast("dict[str, object]", data)


def validate_keys(data: Mapping[str, object], model: type[BaseModel]) -> None:
    for name, value in data.items():
        field = model.model_fields.get(name)
        if field is None:
            raise ValueError(f"Unknown configuration field: {name}")
        nested = field.annotation
        if isinstance(value, dict) and isinstance(nested, type) and issubclass(nested, BaseModel):
            validate_keys(value, nested)


def validate_environment(model: type[BaseModel]) -> None:
    for key in os.environ:
        if not key.startswith("SAA_") or key in {"SAA_MODE", "SAA_CONFIG_ROOT"}:
            continue
        validate_env_path(model, key[4:].lower().split("__"))


def validate_env_path(model: type[BaseModel], names: list[str]) -> None:
    field = model.model_fields.get(names[0])
    if field is None:
        raise ValueError("Unknown configuration field")
    if len(names) == 1:
        return
    nested = field.annotation
    if not isinstance(nested, type) or not issubclass(nested, BaseModel):
        raise ValueError("Unexpected nested configuration field")
    validate_env_path(nested, names[1:])


def contains_path(data: object, names: list[str]) -> bool:
    if not isinstance(data, Mapping) or names[0] not in data:
        return False
    return len(names) == 1 or contains_path(data[names[0]], names[1:])


def validate_secret_directory(directory: Path, *sources: Mapping[str, object]) -> None:
    permitted = {"SAA_DATABASE__CREDENTIALS__PASSWORD", "SAA_LLM__API_KEY"}
    for path in directory.iterdir():
        key = path.name.upper()
        if not path.is_file() or key not in permitted:
            raise ValueError("Unsupported secret file")
        if secret_conflicts(key, sources):
            raise ValueError("A secret cannot be set in both file and environment")


def secret_conflicts(key: str, sources: tuple[Mapping[str, object], ...]) -> bool:
    return key in os.environ or any(
        contains_path(source, key[4:].lower().split("__")) for source in sources
    )


def contains_secret_override(data: object) -> bool:
    if isinstance(data, BaseModel):
        data = data.model_dump()
    if not isinstance(data, dict):
        return False
    return any(
        name in {"password", "api_key"} or contains_secret_override(value)
        for name, value in data.items()
    )
