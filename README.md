# agent-veriq

Agente de IA (Google ADK) que analisa especificações OpenAPI (JSON/YAML), explica endpoints,
identifica autenticação declarada, planeja testes e gera collections Postman v2.1.0.
**O agente não executa requisições HTTP** — apenas analisa o contrato e gera artefatos.

> Projeto em desenvolvimento. Concluído: fases 0 a 7 (núcleo de análise, planejamento de testes,
> collection Postman, ferramentas, Skills e agente ADK).

## Execução

Com o `.env` preenchido (na raiz do projeto; o ADK o procura subindo a partir de `agent_veriq/`):

```bash
.venv/Scripts/adk.exe run agent_veriq    # terminal
.venv/Scripts/adk.exe web                # interface web (selecione "agent_veriq")
```

Exemplos de pedidos:
- "Carregue o arquivo specs/minha-api.yaml e liste todos os endpoints."
- "Quais endpoints exigem autenticação?" / "Quais informações de autenticação estão faltando?"
- "Explique como usar o endpoint de cadastro de usuários."
- "Quais testes positivos e negativos posso fazer em POST /users?"
- "Gere uma collection Postman apenas com os endpoints públicos."

Somente arquivos dentro de `VERIQ_SPEC_DIR` podem ser carregados; collections são gravadas em
`VERIQ_OUTPUT_DIR`.

## Variáveis de ambiente

| Variável | Padrão | Uso |
|---|---|---|
| `GOOGLE_API_KEY` | — | Chave do Gemini (obrigatória para executar o agente; não para os testes) |
| `GOOGLE_GENAI_USE_VERTEXAI` | `FALSE` | Usar Vertex AI em vez da API Gemini |
| `VERIQ_MODEL` | padrão do ADK (`gemini-3.5-flash`) | Modelo do agente |
| `VERIQ_SPEC_DIR` | diretório atual | Único diretório de onde especificações podem ser lidas |
| `VERIQ_OUTPUT_DIR` | `./output` | Destino das collections |
| `VERIQ_MAX_SPEC_MB` | `10` | Tamanho máximo do arquivo OpenAPI |

## Ferramentas e Skills

Ferramentas (FunctionTools, retornam `dict` com `status`): `carregar_especificacao`,
`resumo_especificacao`, `listar_problemas_especificacao`, `listar_schemas`, `obter_schema`,
`listar_referencias`, `listar_endpoints`, `obter_detalhes_endpoint`, `analisar_autenticacao`,
`listar_lacunas_autenticacao`, `planejar_testes_endpoint`, `planejar_testes_conjunto`,
`gerar_postman_collection`.

Skills (carregadas sob demanda via `SkillToolset`): `openapi-analysis`, `endpoint-explanation`,
`api-test-planning`, `postman-collection`. Apenas `list_skills`, `load_skill` e
`load_skill_resource` são expostas; `run_skill_script` é bloqueada por `tool_filter`.

## Collection Postman v2.1.0

- Validada contra o schema oficial versionado em
  `agent_veriq/schemas/postman-collection-v2.1.0.schema.json` (sem acesso à rede) antes de ser entregue.
- Escopo por operationId/`METHOD /path`, tag, método, status de autenticação ou texto.
- Pastas por tag (ou primeiro segmento do path); variável `{{baseUrl}}` a partir do primeiro servidor.
- Autenticação mapeada do esquema declarado (Bearer, Basic, Digest, API key em header/query/cookie,
  OAuth 2.0/OpenID Connect). **Credenciais são sempre variáveis vazias** — nunca valores reais.
- Asserções apenas para o que está documentado: status 2xx, Content-Type e campos obrigatórios do
  schema de resposta. Sem 2xx documentado, nenhuma asserção de status é criada.
- Opcional: pasta de cenários por operação (a partir do planejamento de testes). Cenários
  `hypothesis` usam `pm.test.skip`, sem asserção.
- As requisições nunca são executadas pelo agente.

## Planejamento de testes

Cada cenário tem `id`, `category`, `description`, `inputs`, `expected` e `basis`:

- `documented`: a restrição (ex.: campo obrigatório, `maxLength`) e o status esperado constam no
  contrato; a associação entre eles é inferida.
- `hypothesis`: o status esperado não está documentado (ex.: 415 para content type não aceito).

Os cenários são derivados apenas do contrato (obrigatoriedade, tipos, formatos, limites, enums,
content types, segurança declarada e respostas documentadas) e **nunca são executados**.

## Classificação de autenticação

| Status | Significado |
|---|---|
| `declared_required` | A operação possui requisitos de segurança aplicáveis na especificação |
| `none_declared` | Sem requisitos aplicáveis (inclui `security: []` e autenticação opcional `{}`, sinalizada em `optional`) |
| `indeterminate` | `security` inválido, esquema não definido, tipo desconhecido ou API key incompleta |

O status reflete apenas o contrato; não comprova o comportamento real do servidor.

## Instalação

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # Windows
# .venv/bin/python -m pip install -r requirements-dev.txt         # Linux/macOS
cp .env.example .env   # preencha GOOGLE_API_KEY
```

## Testes

```bash
.venv/Scripts/python.exe -m pytest -q
```

Os testes são totalmente offline e usam fixtures locais em `tests/fixtures/`.

## Estrutura

```text
agent_veriq/
├── core/        # lógica determinística (loader, parser, $ref, modelos, store)
├── tools/       # funções expostas ao agente (FunctionTools do ADK)
├── skills/      # Skills (SKILL.md + references/) carregadas sob demanda
└── schemas/     # schema local da Postman Collection v2.1.0
tests/           # testes unitários e fixtures
```

## Suporte a versões

| Versão | Suporte |
|---|---|
| Swagger 2.0 | Normalizado para o modelo 3.x (`body`/`formData` → requestBody, `securityDefinitions` → securitySchemes, `host`+`basePath`+`schemes` → servers) |
| OpenAPI 3.0.x | Completo |
| OpenAPI 3.1.x | Completo para paths; `webhooks` são apenas sinalizados |

## Segurança no processamento de arquivos

- Tamanho máximo configurável em `VERIQ_MAX_SPEC_MB` (padrão 10 MB).
- YAML lido apenas com `SafeLoader`, limite de aliases, profundidade e nós expandidos (mitiga "billion laughs").
- `$ref` externos **nunca** são acessados; ficam registrados como limitação (`external_ref`).
- Teste de guarda impede a importação de clientes HTTP/rede no pacote.

## Google ADK e Skills (versão validada)

- `google-adk==2.13.0`.
- Skills carregadas com `google.adk.skills.load_skill_from_dir` (o nome no frontmatter deve coincidir
  com o nome da pasta, em kebab-case; recursos lidos de `references/`, `assets/` e `scripts/`).
- Exposição via `google.adk.tools.skill_toolset.SkillToolset` (modo `LAZY`: `list_skills`,
  `load_skill`, `load_skill_resource`). A ferramenta `run_skill_script` também é registrada pelo
  toolset e é removida via `tool_filter`, pois o projeto não executa scripts.

## Limitações atuais

- O fluxo completo com o modelo (`adk run`) depende de `GOOGLE_API_KEY`; os testes automatizados
  cobrem as ferramentas e a montagem do agente, mas não chamam o modelo.
- Referências externas não são resolvidas.
- Em OpenAPI 3.1, `$ref` com campos irmãos é mesclado apenas na expansão de schemas.
- O agente identifica o que está **declarado** no contrato; não comprova o comportamento do servidor.
