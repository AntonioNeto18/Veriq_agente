# Catálogo de categorias de cenário

| Categoria | Gerado quando | Status esperado |
|---|---|---|
| `positive` | sempre (e variante com parâmetros opcionais) | 2xx documentados; sem 2xx → hipótese |
| `missing_required` | parâmetro (não-path), body ou campo obrigatório | 400/422/4XX documentados; senão hipótese |
| `invalid_type` | campo/parâmetro com `type` | idem |
| `invalid_format` | `format` conhecido (email, uuid, date, date-time, uri, ipv4/6) | idem |
| `invalid_enum` | `enum` declarado | idem |
| `out_of_range` | `minimum`/`maximum`/exclusivos | idem |
| `length` | `minLength`/`maxLength`/`minItems`/`maxItems` | idem |
| `invalid_pattern` | `pattern` | idem |
| `null_value` | campo obrigatório não-nullable | idem |
| `content_type` | body sem `text/plain` aceito | 415 se documentado; senão hipótese |
| `authentication` | segurança `declared_required` | 401 se documentado; senão hipótese |
| `authorization` | requisito com scopes | 403 se documentado; senão hipótese |
| `not_found` | parâmetro de path e 404 documentado | 404 |
| `documented_response` | status documentado não coberto | o status; gatilho não especificado |

Limitações conhecidas:
- Campos aninhados do body não geram cenários individuais.
- Valores longos aparecem como placeholders (`<texto com N caracteres>`).
- Segurança `indeterminate` não gera cenários de autenticação.
