# Referências e segurança

## `$ref`
- Internas (`#/...`) são resolvidas; ciclos aparecem como `circular: true` no resumo de schemas.
- Externas (`arquivo.yaml#/...`, URLs) **nunca** são acessadas: aparecem com `unresolved` e issue `external_ref`.
- Internas inexistentes geram `broken_ref` (erro).
- Parâmetros de path-level e de operação são mesclados; a operação prevalece por (`name`, `in`).

## Segurança declarada
- `security` da operação substitui o global; ausente → herda o global.
- `security: []` na operação remove explicitamente a segurança global.
- Lista de requisitos = alternativas (OR); esquemas dentro de um mesmo item = combinação (AND).
- Item vazio `{}` torna a autenticação opcional (`optional: true`, status `none_declared`).

## Status
- `declared_required`: há requisito aplicável no contrato.
- `none_declared`: nenhum requisito aplicável no contrato (não significa "público em produção").
- `indeterminate`: `security` inválido, esquema não definido, tipo desconhecido ou API key incompleta.

Sempre diga "declarado na especificação"; o agente não verifica o servidor real.
