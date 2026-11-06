# $ref and declared security

## `$ref`
- Internal refs (`#/...`) are resolved; cycles show up as `circular: true` in schema summaries.
- External refs (`file.yaml#/...`, URLs) are **never** fetched: they appear as `unresolved` with an `external_ref` issue.
- Missing internal targets produce a `broken_ref` error.
- Path-level and operation-level parameters are merged; the operation wins on (`name`, `in`).

## Declared security
- Operation `security` replaces the global one; when absent the operation inherits the global one.
- `security: []` on an operation explicitly removes global security.
- The requirement list is a set of alternatives (OR); schemes inside one item are combined (AND).
- An empty item `{}` makes authentication optional (`optional: true`, status `none_declared`).

## Status values
- `declared_required`: an applicable requirement exists in the contract.
- `none_declared`: no applicable requirement in the contract (this does NOT mean "public in production").
- `indeterminate`: invalid `security`, undefined scheme, unknown type or incomplete API key.

Always say "declared in the specification": veriq never checks the real server.
