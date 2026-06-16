"""Tests for mcp_server.validation.schemas — tool argument validation."""

import pytest

from mcp_server.errors import ValidationError
from mcp_server.validation.schemas import validate_tool_args


class TestValidateToolArgs:
    def test_passes_valid_args(self):
        result = validate_tool_args(
            "record_session_end",
            {
                "session_id": "abc-123",
                "domain": "web",
            },
        )
        assert result["session_id"] == "abc-123"
        assert result["domain"] == "web"

    def test_raises_for_missing_required_field(self):
        with pytest.raises(ValidationError, match="session_id") as exc_info:
            validate_tool_args("record_session_end", {})
        assert exc_info.value.details["tool"] == "record_session_end"
        assert exc_info.value.details["field"] == "session_id"

    def test_raises_when_required_field_is_none(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_tool_args("record_session_end", {"session_id": None})
        assert exc_info.value.details["tool"] == "record_session_end"

    def test_raises_for_string_type_mismatch(self):
        with pytest.raises(ValidationError, match="string") as exc_info:
            validate_tool_args(
                "record_session_end",
                {
                    "session_id": "ok",
                    "domain": 123,
                },
            )
        assert exc_info.value.details["tool"] == "record_session_end"
        assert exc_info.value.details["field"] == "domain"
        assert exc_info.value.details["got"] == "int"

    def test_raises_for_number_type_mismatch(self):
        with pytest.raises(ValidationError, match="number") as exc_info:
            validate_tool_args(
                "record_session_end",
                {
                    "session_id": "ok",
                    "duration": "not-a-number",
                },
            )
        assert exc_info.value.details["tool"] == "record_session_end"
        assert exc_info.value.details["field"] == "duration"
        assert exc_info.value.details["got"] == "str"

    def test_rejects_bool_for_number_with_tool_details(self):
        with pytest.raises(ValidationError, match="number") as exc_info:
            validate_tool_args(
                "record_session_end",
                {
                    "session_id": "ok",
                    "duration": True,
                },
            )
        assert exc_info.value.details["tool"] == "record_session_end"
        assert exc_info.value.details["field"] == "duration"
        assert exc_info.value.details["expected"] == "number"
        assert exc_info.value.details["got"] == "bool"

    def test_rejects_number_below_minimum(self):
        with pytest.raises(ValidationError, match="must be >=") as exc_info:
            validate_tool_args(
                "remember",
                {
                    "content": "ok",
                    "initial_heat": -0.01,
                },
            )

        assert exc_info.value.details["tool"] == "remember"
        assert exc_info.value.details["field"] == "initial_heat"
        assert exc_info.value.details["minimum"] == 0.0
        assert exc_info.value.details["got"] == -0.01

    def test_rejects_number_above_maximum(self):
        with pytest.raises(ValidationError, match="must be <=") as exc_info:
            validate_tool_args(
                "remember",
                {
                    "content": "ok",
                    "initial_heat": 1.01,
                },
            )

        assert exc_info.value.details["tool"] == "remember"
        assert exc_info.value.details["field"] == "initial_heat"
        assert exc_info.value.details["maximum"] == 1.0
        assert exc_info.value.details["got"] == 1.01

    def test_accepts_number_bounds_endpoints(self):
        assert (
            validate_tool_args(
                "remember",
                {
                    "content": "ok",
                    "initial_heat": 0.0,
                },
            )["initial_heat"]
            == 0.0
        )
        assert (
            validate_tool_args(
                "remember",
                {
                    "content": "ok",
                    "initial_heat": 1.0,
                },
            )["initial_heat"]
            == 1.0
        )

    def test_accepts_number_without_maximum_constraint(self):
        result = validate_tool_args(
            "remember",
            {
                "content": "ok",
                "importance": 2.0,
            },
        )

        assert result["importance"] == 2.0

    def test_raises_for_boolean_type_mismatch(self):
        with pytest.raises(ValidationError, match="boolean") as exc_info:
            validate_tool_args("rebuild_profiles", {"force": "yes"})
        assert exc_info.value.details["tool"] == "rebuild_profiles"
        assert exc_info.value.details["field"] == "force"

    def test_raises_for_array_type_mismatch(self):
        with pytest.raises(ValidationError, match="array") as exc_info:
            validate_tool_args(
                "record_session_end",
                {
                    "session_id": "ok",
                    "tools_used": "not-an-array",
                },
            )
        assert exc_info.value.details["tool"] == "record_session_end"
        assert exc_info.value.details["field"] == "tools_used"

    def test_rejects_array_over_max_items(self):
        tags = [f"tag-{i}" for i in range(21)]

        with pytest.raises(ValidationError) as exc_info:
            validate_tool_args("remember", {"content": "ok", "tags": tags})

        assert 'Field "tags" exceeds maxItems (21 > 20)' in str(exc_info.value)
        assert exc_info.value.details["tool"] == "remember"
        assert exc_info.value.details["field"] == "tags"
        assert exc_info.value.details["maxItems"] == 20

    def test_rejects_array_item_over_max_length(self):
        long_tag = "x" * 81

        with pytest.raises(ValidationError) as exc_info:
            validate_tool_args("remember", {"content": "ok", "tags": [long_tag]})

        assert 'Field "tags[0]" exceeds maximum length (81 > 80)' in str(exc_info.value)
        assert exc_info.value.details["tool"] == "remember"
        assert exc_info.value.details["field"] == "tags"
        assert exc_info.value.details["index"] == 0
        assert exc_info.value.details["maxLength"] == 80

    def test_rejects_array_item_type_with_tool_details(self):
        with pytest.raises(ValidationError, match="tags\\[0\\]") as exc_info:
            validate_tool_args("remember", {"content": "ok", "tags": [123]})

        assert exc_info.value.details["tool"] == "remember"
        assert exc_info.value.details["field"] == "tags"
        assert exc_info.value.details["index"] == 0
        assert exc_info.value.details["expected"] == "string"
        assert exc_info.value.details["got"] == "int"

    def test_applies_default_values(self):
        result = validate_tool_args("rebuild_profiles", {})
        assert result["force"] is False

    def test_does_not_override_provided_with_defaults(self):
        result = validate_tool_args("rebuild_profiles", {"force": True})
        assert result["force"] is True

    def test_passes_through_for_unknown_tool(self):
        args = {"foo": "bar", "baz": 42}
        result = validate_tool_args("unknown_tool", args)
        assert result == args

    def test_returns_empty_for_unknown_tool_with_no_args(self):
        result = validate_tool_args("unknown_tool", None)
        assert result == {}

    def test_handles_no_required_fields_no_args(self):
        result = validate_tool_args("list_domains", {})
        assert result == {}

    def test_preserves_unknown_properties_for_tool_wrapper_compatibility(self):
        result = validate_tool_args(
            "rebuild_profiles",
            {
                "domain": "web",
                "force": True,
                "extra_field": "preserved",
            },
        )
        assert result["domain"] == "web"
        assert result["force"] is True
        assert result["extra_field"] == "preserved"
