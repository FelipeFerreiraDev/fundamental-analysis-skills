# skillsInvest

> Skills do Claude Code para análise fundamentalista auditável de empresas da B3: cada número com fonte, fórmula e premissas.

## Sobre

O skillsInvest é um conjunto de analistas especializados (skills do Claude Code) que, dada uma empresa listada na B3, coletam os dados oficiais (CVM, B3, Banco Central), aplicam metodologias de valuation (Graham, Lynch, Bazin, fluxo de caixa descontado, entre outras), fazem análise setorial e qualitativa e geram um relatório HTML reproduzível.

- **Uma empresa por análise**, mais os pares quando a comparação exigir.
- **Só fontes de dados gratuitas.**
- **Todo cálculo é código Python testado.** O modelo escolhe e justifica premissas e interpreta resultados, mas nunca calcula de cabeça nem escreve números no relatório.
- **Rastreabilidade:** todo valor carrega fonte, período, unidade e natureza (reportado, derivado ou estimado).

## Status

🚧 Em desenvolvimento.

- ✅ **Fase 0 — fundação:** contrato de dados, banco local, CLI e testes.
- 🚧 **Fase 1 — primeira análise completa com BBAS3:**
  - ✅ sync dos dados da CVM (cadastro, FCA, DFP e ITR) e mapa de contas de bancos
  - ✅ sync de cotações e proventos (B3), cotação do dia (brapi) e Selic/IPCA (Banco Central)
  - ✅ snapshot da análise (`data.json`) e validação dos dados (`validation.json`)
  - ⏭️ indicadores, Graham, Bazin, relatório e as primeiras skills

As skills ainda não foram escritas. Hoje é possível carregar no banco local os balanços, cotações e proventos de uma empresa e consultar as séries históricas. O roadmap completo está em [docs/architecture.md](docs/architecture.md#10-roadmap).

## Pré-requisitos

- Python 3.11 ou superior
- Token gratuito da [brapi.dev](https://brapi.dev), usado para a cotação do dia
- [Claude Code](https://claude.com/claude-code), para usar as skills (a partir da fase 1)

## Instalação

```bash
git clone https://github.com/FelipeFerreiraDev/fundamental-analysis-skills.git
cd fundamental-analysis-skills

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# edite o .env e preencha BRAPI_TOKEN

skillsinvest init-db
skillsinvest doctor
```

Com tudo configurado, o `doctor` mostra:

```
[ok   ] .env encontrado
[ok   ] BRAPI_TOKEN configurado
[ok   ] config/defaults.yaml válido
[ok   ] schemas do contrato em dia
[ok   ] banco em <projeto>/data/warehouse.duckdb
[ok   ] CVM_BASE_URL = https://dados.cvm.gov.br/dados/CIA_ABERTA
[ok   ] B3_COTAHIST_BASE_URL = https://bvmf.bmfbovespa.com.br/InstDados/SerHist
[ok   ] B3_LISTED_BASE_URL = https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall
[ok   ] BRAPI_BASE_URL = https://brapi.dev/api
[ok   ] BCB_SGS_BASE_URL = https://api.bcb.gov.br/dados/serie
```

Ele termina com código 0 quando está tudo certo e 1 quando encontra algum erro.

## Configuração

### Variáveis de ambiente (`.env`)

Tokens e credenciais ficam **só no `.env`**, que nunca vai para o git. O [.env.example](.env.example) lista todas as variáveis.

| Variável | Descrição | Obrigatória | Padrão |
|---|---|---|---|
| `BRAPI_TOKEN` | Token da brapi.dev para a cotação do dia (BBAS3 não funciona sem token) | ✅ | — |
| `DATA_DIR` | Pasta dos dados locais (banco, cache e PDFs) | ❌ | `data/` |
| `CVM_BASE_URL` | Dados abertos da CVM (cadastro, FCA, DFP, ITR) | ❌ | `https://dados.cvm.gov.br/dados/CIA_ABERTA` |
| `B3_COTAHIST_BASE_URL` | Séries históricas de cotações da B3 | ❌ | `https://bvmf.bmfbovespa.com.br/InstDados/SerHist` |
| `B3_LISTED_BASE_URL` | Proventos e desdobramentos (API pública das páginas de empresas listadas da B3) | ❌ | `https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall` |
| `BRAPI_BASE_URL` | API da brapi.dev | ❌ | `https://brapi.dev/api` |
| `BCB_SGS_BASE_URL` | Séries temporais do Banco Central (SGS) | ❌ | `https://api.bcb.gov.br/dados/serie` |

As URLs dos serviços externos ficam no `.env` para deixar claro de onde vêm os dados. Se uma delas não estiver no `.env`, vale o padrão da tabela (o mesmo do `.env.example`). Só `https://` é aceito. O `skillsinvest doctor` mostra as URLs em uso.

### Parâmetros de análise

Os parâmetros do investidor ficam em [config/defaults.yaml](config/defaults.yaml), que é versionado e não contém segredos.

- Percentuais são escritos como fração: `0.06` = 6%.
- Um valor `null` ainda não foi definido, e o engine recusa calcular um método que dependa dele.
- Hoje está definido o dividend yield desejado do Bazin (`0.06`).
- `sync.history_years` (padrão 10) e `sync.quarterly_years` (padrão 2) definem quantos anos de DFP e de ITR o `sync` carrega. Cada documento traz também o ano anterior como comparação.

### Setor da empresa

O perfil setorial vem do setor cadastrado na CVM ([engine/reference/cvm_sectors.yaml](engine/reference/cvm_sectors.yaml)). Quando ele não serve (por exemplo, uma holding cadastrada com o setor da investida), defina o perfil por ticker em [config/sector_overrides.yaml](config/sector_overrides.yaml).

## Comandos

Com o ambiente ativado (`source .venv/bin/activate`):

| Comando | O que faz |
|---|---|
| `skillsinvest init-db` | Cria `data/warehouse.duckdb`, se não existir, e aplica as migrações pendentes. Pode ser rodado quantas vezes quiser |
| `skillsinvest doctor` | Verifica `.env`, `BRAPI_TOKEN`, `config/defaults.yaml`, schemas e banco, e mostra as URLs em uso |
| `skillsinvest sync <TICKER>` | Carrega no banco os dados da empresa: cadastro, ações, DFP e ITR (CVM); cotações diárias e proventos (B3); cotação do dia (brapi); Selic e IPCA (Banco Central). Rodar de novo só baixa o que mudou |
| `skillsinvest snapshot <TICKER>` | Gera `analyses/<TICKER>/<data-base>/data.json` com tudo o que as análises usam, cada valor com sua fonte |
| `skillsinvest validate <TICKER>` | Confere o último `data.json` e grava `validation.json`. Termina com código 1 se algum erro bloquear os valuations. `-v` mostra todos os detalhes |
| `skillsinvest series <TICKER> <conceito>` | Mostra a série histórica de um conceito, com o documento de origem de cada valor. Opções: `--period INSTANT\|3M\|YTD\|FY` e `--basis consolidated\|individual` |
| `skillsinvest export-schemas` | Regenera os JSON Schemas em `schemas/` a partir de `engine/contract/` |
| `skillsinvest export-schemas --check` | Só verifica se `schemas/` está em dia (termina com código 1 se não estiver) |
| `skillsinvest --version` | Mostra a versão |

`python -m engine <comando>` funciona da mesma forma.

Exemplo:

```bash
skillsinvest sync BBAS3                          # ~2 a 5 minutos na primeira vez (baixa ~700 MB)
skillsinvest series BBAS3 net_income --period FY
skillsinvest snapshot BBAS3                      # analyses/BBAS3/2026-09-30/data.json
skillsinvest validate BBAS3                      # analyses/BBAS3/2026-09-30/validation.json
```

Os conceitos disponíveis estão em [engine/reference/account_map.csv](engine/reference/account_map.csv). Por enquanto há mapa de contas só para bancos.

## Dados locais

A pasta `data/` fica **fora do git**:

```
data/
├── warehouse.duckdb   # banco local (DuckDB)
├── cache/             # downloads temporários
└── documents/         # PDFs de RI usados como fonte
```

Ela pode ser reconstruída a qualquer momento a partir das fontes públicas. Para recomeçar do zero (isso também apaga os PDFs guardados):

```bash
rm -rf data/
skillsinvest init-db
skillsinvest sync BBAS3
```

Os downloads ficam em `data/cache/` por até 7 dias e depois são apagados. O que garante a rastreabilidade é o registro de cada arquivo no banco (URL, ETag e SHA-256), não o arquivo em si.

Fontes usadas, todas gratuitas: CVM Dados Abertos (DFP, ITR, FCA e cadastro), B3 (COTAHIST e a API das páginas de empresas listadas, para proventos e desdobramentos), brapi.dev (só a cotação do dia: no plano grátis ela não fornece proventos), Banco Central (SGS; IF.data na fase 3) e Tesouro Direto (fase 2).

## Desenvolvimento

```bash
pytest                                # testes
ruff check . && ruff format --check . # lint e formatação
skillsinvest export-schemas --check   # contrato e schemas sincronizados
```

- Depois de alterar `engine/contract/`, rode `skillsinvest export-schemas`. Um teste falha se `schemas/` estiver desatualizado.
- Mudanças no banco entram como uma nova migração em `engine/db/migrations/NNNN_nome.sql`. Nunca edite uma migração já aplicada.
- Os testes não acessam a rede: a ingestão é testada com arquivos sintéticos no formato da CVM ([tests/cvm_files.py](tests/cvm_files.py)).
- Toda mudança que afete instalação, configuração ou execução atualiza este README no mesmo commit.

As regras completas de trabalho estão no [CLAUDE.md](CLAUDE.md).

## Estrutura do projeto

```
├── CLAUDE.md               # princípios e regras de trabalho (lido pelo Claude Code)
├── docs/architecture.md    # arquitetura e decisões
├── config/                 # parâmetros de análise e overrides de setor
├── schemas/                # JSON Schemas do contrato (gerados)
├── engine/                 # pacote Python
│   ├── cli.py              # comando skillsinvest
│   ├── contract/           # modelos do contrato de dados
│   ├── db/                 # conexão e migrações do DuckDB
│   ├── ingest/             # sync das fontes públicas (CVM, B3, brapi, Banco Central)
│   ├── reference/          # mapa de contas e mapa de setores da CVM
│   ├── snapshot/           # banco → data.json
│   ├── validation/         # checagens → validation.json
│   └── ...                 # validação, indicadores, valuation, setores, relatório (próximas etapas)
├── analyses/               # saídas das análises (versionadas): data.json, validation.json...
├── tests/                  # testes e fixtures (BBAS3)
└── data/                   # dados locais, fora do git
```

A pasta `.claude/skills/` (skills) surge nos próximos passos da fase 1.

## Documentação

- [docs/architecture.md](docs/architecture.md): skills, contrato de dados, banco, fontes, setores e roadmap.
- [CLAUDE.md](CLAUDE.md): princípios obrigatórios e regras de trabalho.

## Aviso

As análises têm caráter educacional e informativo e **não constituem recomendação de investimento**. Cada investidor é responsável pelas próprias decisões.
