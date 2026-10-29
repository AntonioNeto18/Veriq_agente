---
name: postman-collection
description: Gerar uma collection JSON Postman v2.1.0 validada para os endpoints selecionados, com variáveis de ambiente, autenticação declarada e scripts de teste. Use quando o usuário pedir uma collection Postman.
---

# Geração de collection Postman

## Procedimento
1. Determine o escopo pedido: operações específicas (`operacoes`), `tag`, `metodo`, `autenticacao`
   (ex.: "apenas públicos" → `autenticacao="none_declared"`) ou `texto`. Se o escopo estiver ambíguo,
   use `listar_endpoints` para confirmar antes de gerar.
2. Chame `gerar_postman_collection` **uma vez** com o escopo. Use `incluir_cenarios=true` quando o
   usuário pedir cenários de teste/negativos na collection.
3. Use `retornar_json=true` somente se o usuário pedir o JSON na resposta.

## Resposta
- Padrão: informe o arquivo salvo, a quantidade de requisições, as pastas e as variáveis a preencher
  (credenciais vazias, `baseUrl`). Diga que nada foi executado.
- Se o usuário pedir **somente o JSON**: responda apenas com o conteúdo de `collection`, sem Markdown,
  comentários ou explicações. Se vier `json_omitted`, explique o limite e indique o arquivo.

## Regras
- Nunca invente ou preencha tokens, senhas, chaves ou credenciais; elas ficam em variáveis vazias.
- Não afirme que os testes passaram; a collection não foi executada.
- Não edite o JSON manualmente para acrescentar asserções não documentadas; a ferramenta já valida a
  estrutura contra o schema oficial v2.1.0.
- Se a ferramenta retornar erro, relate-o; não gere uma collection "à mão".
