"""Input validation schemas for MCP tool arguments.

Lightweight schema validation: define expected types and required fields per
tool, validate before handler execution, and throw ValidationError on failure.
Unknown tool names pass through (no schema = no validation).
"""

from __future__ import annotations

from typing import Any

from mcp_server.errors import ValidationError
from mcp_server.validation.schema_definitions import SCHEMAS

_TYPE_CHECKS: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "boolean": bool,
    "array": list,
}


def _check_array_envelope(
    tool_name: str, field: str, value: list, spec: dict[str, Any]
) -> None:
    """Enforce ``maxItems`` + per-item ``items`` spec for an array field.

    precondition: ``value`` is a list (caller already type-checked).
    postcondition: if the array length exceeds ``maxItems`` or any item
    violates the per-item spec (type / maxLength), raises ValidationError
    with ``details`` carrying the bound and, for item failures, the
    offending index.

    Source: ADR-0045 R2 (fragility sweep E4) — bounded envelopes on all
    array inputs prevent pathological memory / indexing blowups.
    """
    max_items = spec.get("maxItems")
    if max_items is not None and len(value) > max_items:
        raise ValidationError(
            f'Field "{field}" exceeds maxItems ({len(value)} > {max_items})',
            {"tool": tool_name, "field": field, "maxItems": max_items},
        )

    item_spec = spec.get("items")
    if not item_spec:
        return

    item_type_name = item_spec.get("type")
    expected_item_type = _TYPE_CHECKS.get(item_type_name) if item_type_name else None
    item_max_len = item_spec.get("maxLength")

    for i, item in enumerate(value):
        if expected_item_type is not None and not isinstance(item, expected_item_type):
            got = type(item).__name__
            raise ValidationError(
                f'Field "{field}[{i}]" must be a {item_type_name}, got {got}',
                {
                    "tool": tool_name,
                    "field": field,
                    "index": i,
                    "expected": item_type_name,
                    "got": got,
                },
            )
        if (
            item_max_len is not None
            and isinstance(item, str)
            and len(item) > item_max_len
        ):
            raise ValidationError(
                f'Field "{field}[{i}]" exceeds maximum length '
                f"({len(item)} > {item_max_len})",
                {
                    "tool": tool_name,
                    "field": field,
                    "index": i,
                    "maxLength": item_max_len,
                },
            )


def _check_field_type(
    tool_name: str, field: str, value: Any, spec: dict[str, Any]
) -> None:
    """Validate a single field's type, raising ValidationError on mismatch."""
    expected_type = _TYPE_CHECKS.get(spec["type"])
    if expected_type is None:
        return

    # In Python, bool is a subclass of int — reject bools for number type
    if spec["type"] == "number" and isinstance(value, bool):
        raise ValidationError(
            f'Field "{field}" must be a number, got bool',
            {"tool": tool_name, "field": field, "expected": "number", "got": "bool"},
        )
    if not isinstance(value, expected_type):
        got = type(value).__name__
        raise ValidationError(
            f'Field "{field}" must be a {spec["type"]}, got {got}',
            {"tool": tool_name, "field": field, "expected": spec["type"], "got": got},
        )
    max_len = spec.get("maxLength")
    if max_len is not None and isinstance(value, str) and len(value) > max_len:
        raise ValidationError(
            f'Field "{field}" exceeds maximum length ({len(value)} > {max_len})',
            {"tool": tool_name, "field": field, "maxLength": max_len},
        )
    if spec["type"] == "array" and isinstance(value, list):
        _check_array_envelope(tool_name, field, value, spec)


def validate_tool_args(tool_name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """Validate tool arguments against the schema.

    Returns arguments with defaults applied while preserving schema-unknown
    keys for forward-compatible tool wrappers.
    Raises ValidationError for missing required fields or type mismatches.
    Unknown tool names pass through unchanged.
    """
    schema = SCHEMAS.get(tool_name)
    if schema is None:
        return args if args is not None else {}

    safe_args = args if args is not None else {}
    result: dict[str, Any] = dict(safe_args)

    for field in schema["required"]:
        if safe_args.get(field) is None:
            raise ValidationError(
                f"Missing required field: {field}",
                {"tool": tool_name, "field": field},
            )

    for field, spec in schema["properties"].items():
        value = safe_args.get(field)
        if value is None:
            if "default" in spec:
                result[field] = spec["default"]
            continue
        _check_field_type(tool_name, field, value, spec)
        result[field] = value

    return result
