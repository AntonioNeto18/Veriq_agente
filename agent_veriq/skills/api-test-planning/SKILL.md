---
name: api-test-planning
description: Sugerir cenários de teste positivos e negativos fundamentados no contrato OpenAPI de uma ou mais operações, separando expectativas documentadas de hipóteses. Use para perguntas sobre quais testes fazer em um endpoint.
---

# Planejamento de testes de API

## Procedimento
1. Uma operação: `planejar_testes_endpoint`. Várias (até 10) ou uma tag: `planejar_testes_conjunto`.
2. Use os cenários retornados como base. Complementar com regras de negócio **somente** se estiverem
   explícitas na description da operação (consulte `obter_detalhes_endpoint` se precisar do texto).
3. Para categorias e critérios, carregue `references/test-catalog.md` apenas se necessário.

## Formato da resposta
Para cada cenário: **ID**, descrição, entradas relevantes, resultado esperado e base:
- `documented`: restrição e status constam no contrato (a associação entre eles é inferida).
- `hypothesis`: status não documentado — rotule explicitamente como **hipótese**.
Agrupe por categoria (positivos, validação, autenticação, respostas documentadas).
Explique que `valid_request` contém valores sugeridos quando `value_origins` indicar `suggested`.

## Regras
- Não presuma validações, permissões ou regras de negócio que não estejam documentadas.
- Cenários que você acrescentar devem ter ID próprio (ex.: `createUser-N01`) e base `hypothesis`
  a menos que a especificação documente a regra.
- Nunca diga que um teste foi executado ou passou. O planejamento não implica execução.
