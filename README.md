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
- ⏭️ **Fase 1 — primeira análise completa com BBAS3:** sync das fontes, extração, validação, indicadores, Graham, Bazin e relatório.

Ainda não há skills nem carga de dados. Hoje é possível instalar, criar o banco local e verificar a configuração. O roadmap completo está em [docs/architecture.md](docs/architecture.md#10-roadmap).

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
```

Ele termina com código 0 quando está tudo certo e 1 quando encontra algum erro.

## Configuração

### Variáveis de ambiente (`.env`)

Tokens e credenciais ficam **só no `.env`**, que nunca vai para o git. O [.env.example](.env.example) lista todas as variáveis.

| Variável | Descrição | Obrigatória | Padrão |
|---|---|---|---|
| `BRAPI_TOKEN` | Token da brapi.dev para a cotação do dia (BBAS3 não funciona sem token) | ✅ | — |
| `DATA_DIR` | Pasta dos dados locais (banco, cache e PDFs) | ❌ | `data/` |

### Parâmetros de análise

Os parâmetros do investidor ficam em [config/defaults.yaml](config/defaults.yaml), que é versionado e não contém segredos.

- Percentuais são escritos como fração: `0.06` = 6%.
- Um valor `null` ainda não foi definido, e o engine recusa calcular um método que dependa dele.
- Hoje está definido o dividend yield desejado do Bazin (`0.06`).

## Comandos

Com o ambiente ativado (`source .venv/bin/activate`):

| Comando | O que faz |
|---|---|
| `skillsinvest init-db` | Cria `data/warehouse.duckdb`, se não existir, e aplica as migrações pendentes. Pode ser rodado quantas vezes quiser |
| `skillsinvest doctor` | Verifica `.env`, `BRAPI_TOKEN`, `config/defaults.yaml`, schemas e banco |
| `skillsinvest export-schemas` | Regenera os JSON Schemas em `schemas/` a partir de `engine/contract/` |
| `skillsinvest export-schemas --check` | Só verifica se `schemas/` está em dia (termina com código 1 se não estiver) |
| `skillsinvest --version` | Mostra a versão |

`python -m engine <comando>` funciona da mesma forma.

## Dados locais

A pasta `data/` fica **fora do git**:

```
data/
├── warehouse.duckdb   # banco local (DuckDB)
├── cache/             # downloads temporários
└── documents/         # PDFs de RI usados como fonte
```

Ela pode ser reconstruída a qualquer momento. Hoje, `skillsinvest init-db` recria o banco vazio. A partir da fase 1, o `sync` recarrega os dados das fontes públicas. Para recomeçar do zero (isso também apaga os PDFs guardados):

```bash
rm -rf data/
skillsinvest init-db
```

Fontes usadas, todas gratuitas: CVM Dados Abertos (DFP, ITR e cadastro), B3 (COTAHIST), brapi.dev, Banco Central (SGS e IF.data) e Tesouro Direto.

## Desenvolvimento

```bash
pytest                                # testes
ruff check . && ruff format --check . # lint e formatação
skillsinvest export-schemas --check   # contrato e schemas sincronizados
```

- Depois de alterar `engine/contract/`, rode `skillsinvest export-schemas`. Um teste falha se `schemas/` estiver desatualizado.
- Mudanças no banco entram como uma nova migração em `engine/db/migrations/NNNN_nome.sql`. Nunca edite uma migração já aplicada.
- Toda mudança que afete instalação, configuração ou execução atualiza este README no mesmo commit.

As regras completas de trabalho estão no [CLAUDE.md](CLAUDE.md).

## Estrutura do projeto

```
├── CLAUDE.md               # princípios e regras de trabalho (lido pelo Claude Code)
├── docs/architecture.md    # arquitetura e decisões
├── config/defaults.yaml    # parâmetros de análise
├── schemas/                # JSON Schemas do contrato (gerados)
├── engine/                 # pacote Python
│   ├── cli.py              # comando skillsinvest
│   ├── contract/           # modelos do contrato de dados
│   ├── db/                 # conexão e migrações do DuckDB
│   └── ...                 # ingestão, validação, indicadores, valuation, setores, relatório (próximas fases)
├── tests/                  # testes e fixtures (BBAS3)
└── data/                   # dados locais, fora do git
```

As pastas `.claude/skills/` (skills) e `analyses/` (saídas das análises) surgem a partir da fase 1.

## Documentação

- [docs/architecture.md](docs/architecture.md): skills, contrato de dados, banco, fontes, setores e roadmap.
- [CLAUDE.md](CLAUDE.md): princípios obrigatórios e regras de trabalho.

## Aviso

As análises têm caráter educacional e informativo e **não constituem recomendação de investimento**. Cada investidor é responsável pelas próprias decisões.
