---
name: data-extractor
description: Prepara os dados oficiais de uma empresa da B3 para análise fundamentalista. Carrega no banco local os balanços da CVM, cotações e proventos da B3, cotação do dia e Selic/IPCA, e gera o snapshot analyses/<TICKER>/<data-base>/data.json. Use quando o usuário pedir para analisar, avaliar, calcular preço-teto ou atualizar os dados de uma ação (ex.: "analisa BBAS3", "atualiza os dados do ITUB4"), sempre antes de qualquer valuation. Não use para interpretar os números (isso é das skills de validação, indicadores e valuation).
---

# data-extractor

Coloca os dados de uma empresa no banco local e gera o `data.json` que todos os especialistas leem. Arquitetura: `docs/architecture.md` §7 e §6.3.

## Passos

1. Confirme o ticker (ex.: `BBAS3`). Se o usuário deu o nome da empresa, pergunte o ticker em vez de adivinhar.
2. Rode o sync (idempotente: só baixa o que mudou):
   ```bash
   .venv/bin/skillsinvest sync <TICKER>
   ```
   - Primeira vez: baixa ~700 MB e leva alguns minutos. Avise o usuário antes.
   - `ticker não encontrado no FCA` → o ticker não está listado; confirme com o usuário.
   - `aviso: setor da CVM ... sem perfil setorial` → peça ao usuário o perfil e registre em `config/sector_overrides.yaml` (perfis em `docs/architecture.md` §5). Não escolha sozinho.
   - `BRAPI_TOKEN vazio` → o preço virá só do COTAHIST (fechamento do último pregão). Avise.
3. Gere o snapshot:
   ```bash
   .venv/bin/skillsinvest snapshot <TICKER>
   ```
4. Siga para a skill `data-validator`. Nenhum valuation roda sem validação.

## Regras

- Nunca edite `data.json` à mão nem preencha valores faltantes por conta própria.
- Dados que não existem nas fontes estruturadas (ex.: lucro gerencial, Basileia do trimestre ainda não publicado na CVM) só entram por extração de PDF com URL, página e confiança (`document_facts`), e nunca se misturam aos dados da CVM. Essa extração ainda não está implementada: se o usuário pedir, explique isso.
- Informe ao usuário a data-base do balanço e a data do preço que ficaram no snapshot.
