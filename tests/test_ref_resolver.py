import pytest

from agent_veriq.core.ref_resolver import (
    CIRCULAR_MARKER,
    UNRESOLVED_MARKER,
    RefResolutionError,
    RefResolver,
)

DOCUMENT = {
    "components": {
        "schemas": {
            "A": {"$ref": "#/components/schemas/B"},
            "B": {"type": "object", "properties": {"self": {"$ref": "#/components/schemas/B"}}},
            "Loop1": {"$ref": "#/components/schemas/Loop2"},
            "Loop2": {"$ref": "#/components/schemas/Loop1"},
            "a/b": {"type": "string"},
        }
    }
}


def test_follows_reference_chain():
    resolved = RefResolver(DOCUMENT).deref({"$ref": "#/components/schemas/A"})
    assert resolved.value["type"] == "object"
    assert resolved.pointer == "/components/schemas/B"
    assert resolved.ref_chain == ("#/components/schemas/A", "#/components/schemas/B")


def test_escaped_pointer_tokens():
    assert RefResolver(DOCUMENT).deref({"$ref": "#/components/schemas/a~1b"}).value == {"type": "string"}


def test_circular_chain_raises():
    with pytest.raises(RefResolutionError, match="circular"):
        RefResolver(DOCUMENT).deref({"$ref": "#/components/schemas/Loop1"})


def test_external_reference_is_not_accessed():
    with pytest.raises(RefResolutionError, match="externa"):
        RefResolver(DOCUMENT).deref({"$ref": "https://example.com/schema.json"})


def test_missing_reference_raises():
    with pytest.raises(RefResolutionError, match="does not exist"):
        RefResolver(DOCUMENT).deref({"$ref": "#/components/schemas/Nope"})


def test_inline_marks_recursive_schemas():
    inlined = RefResolver(DOCUMENT).inline({"$ref": "#/components/schemas/B"})
    assert inlined["properties"]["self"] == {"$ref": "#/components/schemas/B", CIRCULAR_MARKER: True}


def test_inline_marks_unresolved_references():
    inlined = RefResolver(DOCUMENT).inline({"items": {"$ref": "other.yaml#/X"}})
    assert inlined["items"][UNRESOLVED_MARKER]


def test_collect_references_classifies_entries():
    document = {"a": {"$ref": "#/b"}, "b": {}, "c": [{"$ref": "ext.yaml"}], "d": {"$ref": "#/missing"}}
    references = {ref.ref: ref for ref in RefResolver(document).collect_references()}
    assert references["#/b"].resolved and not references["#/b"].external
    assert references["ext.yaml"].external and references["ext.yaml"].pointer == "/c/0/$ref"
    assert not references["#/missing"].resolved
