# skillsInvest

Skills do Claude Code para análise fundamentalista de empresas da B3: coletam dados oficiais, aplicam metodologias de valuation e análise setorial/qualitativa e geram um relatório HTML auditável. Uma empresa por análise (mais pares quando a comparação exigir).

Arquitetura completa e decisões: [docs/architecture.md](docs/architecture.md). Leia antes de criar ou alterar skills, schemas ou o engine.

## Princípios obrigatórios

1. **Rastreabilidade** — todo dado financeiro tem fonte, período, unidade e data de publicação. Estimativa nunca é apresentada como dado realizado.
2. **Independência metodológica** — cada especialista conclui sozinho; o `stock-analyst` consolida mas nunca altera resultados de especialistas.
3. **Transparência matemática** — todo método expõe fórmula, variáveis, entradas, premissas, resultado, limitações e justificativa de aplicabilidade.
4. **Determinismo** — todo cálculo é código Python testado em `engine/`.

## Regras de trabalho

- Nunca calcule valores de cabeça. Use o `engine`; se a função não existir, crie-a com teste antes de usar.
- Nunca escreva números diretamente no relatório: ele é renderizado a partir dos JSONs.
- Método inaplicável → `applicable: false` com motivo. Não force uma metodologia.
- Philip Fisher é qualitativo: nunca atribua a ele uma fórmula de preço-teto.
- Valuation consolidado mostra a faixa dos métodos aplicáveis; nunca média simples sem ponderação justificada.
- Dados extraídos de PDF vão para `document_facts` com URL, página e confiança, separados dos dados da CVM.
- Fatos no banco nunca são sobrescritos: reapresentação é uma nova versão.
- Valores monetários em unidade (escala normalizada) e `DECIMAL`; percentuais como fração (`0.06`).
- Todo valor no contrato é um `FinancialValue` (`engine/contract/`) com `unit`, `period`, `basis`, `nature`, `source_ids` e `confidence`.

## Convenções

- Código, chaves do contrato, nomes de tabelas e de skills: **inglês**. Documentação e texto do relatório: **português**.
- Skills em `.claude/skills/<nome>/SKILL.md`, um nível só; o grupo vai no prefixo (`valuation-`, `sector-`, `research-`, `quality-`).
- Setores: uma única skill `sector-analysis`, com um perfil por setor em `references/sectors/`. Setor sem perfil → análise genérica, avisando no relatório.
- Stack: Python, DuckDB, pydantic, jinja2, pytest.
- `data/` (banco, cache, PDFs) fica fora do git; `analyses/` é versionado.

## Comandos

- Ambiente: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`
- Testes: `.venv/bin/pytest`
- Lint e formatação: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- Depois de mudar `engine/contract/`: `.venv/bin/skillsinvest export-schemas`
- Mudança no schema do banco: nova migração `engine/db/migrations/NNNN_nome.sql`. Nunca edite uma migração já aplicada.
- Carregar dados de uma empresa: `.venv/bin/skillsinvest sync <TICKER>`; consultar: `.venv/bin/skillsinvest series <TICKER> <conceito>`.
- Pipeline de uma análise: `sync` → `snapshot` → `validate` → `indicators` → `valuate` → `report` (todos via `.venv/bin/skillsinvest`). Cada etapa recusa arquivos de outro snapshot. Nenhum valuation roda se `validation.json` tiver `blocking: true`; todo `warning` aparece no relatório.
- Mapa de contas (`engine/reference/account_map.csv`): a vigência vale para a data de referência do documento, e um conceito nunca mistura contas de significados diferentes (ver docs/architecture.md §7.2). Confira os nomes das contas nos dados reais antes de mapear.
- Testes nunca acessam a rede: use os arquivos sintéticos de `tests/cvm_files.py`.

## Credenciais e README

- Tokens e credenciais ficam **só no `.env`** (fora do git). Nunca em código, em `config/` ou em commits.
- Toda variável nova entra no `.env.example` (sem valor) e no README.
- O **README.md sempre reflete como instalar, configurar e executar** o projeto. Toda mudança que afete isso atualiza o README no mesmo commit.
