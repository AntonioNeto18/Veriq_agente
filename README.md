# agent-veriq

Agente de IA (Google ADK) que analisa especificações OpenAPI (JSON/YAML), explica endpoints,
identifica autenticação declarada, planeja testes e gera collections Postman v2.1.0.
**O agente não executa requisições HTTP** — apenas analisa o contrato e gera artefatos.

> Projeto em desenvolvimento. Concluído: Fase 0 (fundação) e Fase 1 (carregamento e parsing).

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
  toolset e será removida via `tool_filter`, pois o projeto não executa scripts.

## Limitações atuais

- Referências externas não são resolvidas.
- Em OpenAPI 3.1, `$ref` com campos irmãos é mesclado apenas na expansão de schemas.
- O agente identifica o que está **declarado** no contrato; não comprova o comportamento do servidor.
