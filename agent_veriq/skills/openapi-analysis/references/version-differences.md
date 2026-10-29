# Diferenças entre versões (como o agente normaliza)

| Tema | Swagger 2.0 | OpenAPI 3.0 | OpenAPI 3.1 |
|---|---|---|---|
| Servidores | `host` + `basePath` + `schemes` | `servers[]` | `servers[]` |
| Body | parâmetro `in: body` | `requestBody` | `requestBody` |
| Formulário | parâmetros `in: formData` | `requestBody` com form content type | idem 3.0 |
| Content types | `consumes` / `produces` | chaves de `content` | idem 3.0 |
| Schemas reutilizáveis | `definitions` | `components/schemas` | `components/schemas` |
| Segurança | `securityDefinitions` (basic, apiKey, oauth2) | `components/securitySchemes` (http, apiKey, oauth2, openIdConnect) | idem 3.0 + `mutualTLS` |
| Null | `x-nullable` (não padrão) | `nullable: true` | `type: [..., "null"]` |
| Webhooks | — | — | `webhooks` (sinalizados, não analisados) |

Notas:
- Em 2.0 sem `consumes`, o agente assume `application/json` e registra o issue `assumed_content_type`.
- Em 2.0 sem `schemes`, a URL-base fica sem protocolo (issue `missing_schemes`).
- Em 3.x sem `servers`, o padrão da especificação é `/` (issue `default_server`).
- Fluxos OAuth 2.0 do Swagger 2.0 são renomeados: `application` → `clientCredentials`,
  `accessCode` → `authorizationCode`.
