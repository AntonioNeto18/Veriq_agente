# How veriq normalises OpenAPI versions

| Topic | Swagger 2.0 | OpenAPI 3.0 | OpenAPI 3.1 |
|---|---|---|---|
| Servers | `host` + `basePath` + `schemes` | `servers[]` | `servers[]` |
| Body | `in: body` parameter | `requestBody` | `requestBody` |
| Forms | `in: formData` parameters | `requestBody` with a form content type | same as 3.0 |
| Content types | `consumes` / `produces` | `content` keys | same as 3.0 |
| Reusable schemas | `definitions` | `components/schemas` | `components/schemas` |
| Security | `securityDefinitions` (basic, apiKey, oauth2) | `components/securitySchemes` (http, apiKey, oauth2, openIdConnect) | 3.0 + `mutualTLS` |
| Null | `x-nullable` (non-standard) | `nullable: true` | `type: [..., "null"]` |
| Webhooks | — | — | `webhooks` (flagged, not analysed) |

Notes:
- 2.0 without `consumes`: `application/json` is assumed and an `assumed_content_type` issue is recorded.
- 2.0 without `schemes`: the base URL has no protocol (`missing_schemes` issue).
- 3.x without `servers`: the spec default `/` is used (`default_server` issue).
- Swagger 2.0 OAuth flows are renamed: `application` → `clientCredentials`, `accessCode` → `authorizationCode`.
