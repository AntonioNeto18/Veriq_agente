# Test scenario categories

| Category | Generated when | Expected status |
|---|---|---|
| `positive` | always (plus a variant with optional parameters) | documented 2xx; no 2xx → hypothesis |
| `missing_required` | required non-path parameter, body or field | documented 400/422/4XX; otherwise hypothesis |
| `invalid_type` | field/parameter with `type` | same |
| `invalid_format` | known `format` (email, uuid, date, date-time, uri, ipv4/6) | same |
| `invalid_enum` | declared `enum` | same |
| `out_of_range` | `minimum`/`maximum`/exclusive bounds | same |
| `length` | `minLength`/`maxLength`/`minItems`/`maxItems` | same |
| `invalid_pattern` | `pattern` | same |
| `null_value` | required non-nullable field | same |
| `content_type` | body that does not accept `text/plain` | 415 if documented; otherwise hypothesis |
| `authentication` | security `declared_required` | 401 if documented; otherwise hypothesis |
| `authorization` | requirement with scopes | 403 if documented; otherwise hypothesis |
| `not_found` | path parameter and documented 404 | 404 |
| `documented_response` | documented status not covered above | that status; trigger unspecified |

Known limitations:
- Nested body fields do not get individual scenarios.
- Long values appear as placeholders (`<text with N characters>`).
- `indeterminate` security produces no authentication scenarios.
