---
name: endpoint-explanation
description: Explicar como usar uma operação específica da API — finalidade, parâmetros, headers, body, content types, respostas e autenticação declarada. Use quando o usuário perguntar como chamar um endpoint ou o que enviar/receber.
---

# Explicação de endpoint

## Procedimento
1. Identifique a operação. Se o usuário não der o operationId ou `METHOD /path`, use `listar_endpoints`
   com `texto` ou `tag` para encontrá-la; se houver ambiguidade, pergunte.
2. Chame `obter_detalhes_endpoint` para essa operação (uma chamada por operação).
3. Se precisar aprofundar um schema truncado, use `obter_schema` com o nome indicado em `ref`.

## Formato da resposta
1. **Método e path** + finalidade (summary/description).
2. **Parâmetros**: tabela com nome, localização (path/query/header/cookie), obrigatório, tipo/restrições.
3. **Body**: content types aceitos, campos obrigatórios e opcionais, restrições.
4. **Respostas**: status codes com descrição e schema resumido.
5. **Autenticação declarada**: status e esquemas (use a linguagem "declarado na especificação").
6. **Lacunas**: itens de `missing_information` e `issues`.

## Regras
- Diferencie exemplos **documentados** (`documented_examples`) de exemplos que você sugerir; rotule
  os seus como "exemplo sugerido (não documentado)".
- Não invente parâmetros, headers, campos ou respostas ausentes do resultado da ferramenta.
- Não afirme que o endpoint funciona de certa forma em produção; descreva o contrato.
- Não execute nem ofereça executar requisições.
