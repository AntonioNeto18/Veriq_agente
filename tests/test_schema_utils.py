from agent_veriq.core.ref_resolver import RefResolver
from agent_veriq.core.schema_utils import (
    DOCUMENTED,
    SUGGESTED,
    ExampleBuilder,
    SchemaSummarizer,
    normalized_type,
)

DOCUMENT = {
    "components": {
        "schemas": {
            "Item": {
                "type": "object",
                "required": ["sku"],
                "properties": {
                    "sku": {"type": "string", "minLength": 12},
                    "qty": {"type": "integer", "minimum": 1, "maximum": 10},
                    "price": {"type": "number", "exclusiveMinimum": 0},
                    "id": {"type": "integer", "readOnly": True},
                    "secret": {"type": "string", "writeOnly": True},
                    "kind": {"type": "string", "enum": ["a", "b"]},
                    "when": {"type": "string", "format": "date-time"},
                    "tags": {"type": "array", "items": {"type": "string", "maxLength": 3}},
                    "note": {"type": ["string", "null"]},
                },
            },
            "Documented": {"type": "object", "example": {"x": 1}},
            "Tree": {"type": "object", "properties": {"child": {"$ref": "#/components/schemas/Tree"}}},
        }
    }
}
ITEM = {"$ref": "#/components/schemas/Item"}


def test_normalized_type_handles_3_0_and_3_1_nullability():
    assert normalized_type({"type": "string", "nullable": True}) == ("string", True)
    assert normalized_type({"type": ["integer", "null"]}) == ("integer", True)
    assert normalized_type({"type": ["integer", "string"]}) == (["integer", "string"], False)
    assert normalized_type({}) == (None, False)


def test_suggested_request_example_respects_constraints():
    value, origin = ExampleBuilder(RefResolver(DOCUMENT)).build(ITEM)
    assert origin == SUGGESTED
    assert len(value["sku"]) >= 12
    assert value["qty"] == 1 and value["price"] == 0.5
    assert value["kind"] == "a"
    assert value["when"] == "2024-01-31T12:00:00Z"
    assert value["tags"] == ["str"]
    assert "id" not in value and "secret" in value


def test_response_example_skips_write_only():
    value, _ = ExampleBuilder(RefResolver(DOCUMENT)).build(ITEM, for_request=False)
    assert "secret" not in value and "id" in value


def test_documented_example_is_preferred():
    value, origin = ExampleBuilder(RefResolver(DOCUMENT)).build({"$ref": "#/components/schemas/Documented"})
    assert (value, origin) == ({"x": 1}, DOCUMENTED)


def test_recursive_example_terminates():
    value, _ = ExampleBuilder(RefResolver(DOCUMENT)).build({"$ref": "#/components/schemas/Tree"})
    assert value == {"child": None}


def test_summary_limits_properties_and_depth():
    summarizer = SchemaSummarizer(RefResolver(DOCUMENT), max_properties=2)
    summary = summarizer.summarize(ITEM)
    assert list(summary["properties"]) == ["sku", "qty"]
    assert summary["properties_omitted"] == 7

    shallow = SchemaSummarizer(RefResolver(DOCUMENT), max_depth=0).summarize(ITEM)
    assert shallow == {"ref": "Item", "truncated": True}
