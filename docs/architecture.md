# Arquitetura — skillsInvest

> Documento vivo com as decisões de arquitetura do projeto (consolidadas em 2026-11-21).
> Quando uma decisão mudar, atualize este arquivo no mesmo commit da mudança.

## 1. Objetivo e escopo

Conjunto de analistas especializados (skills do Claude Code) que, dada **uma empresa listada na B3**, coletam os dados oficiais, aplicam metodologias de valuation, análise setorial e qualitativa, e produzem um relatório HTML **reproduzível e auditável** para apoiar a decisão do investidor.

- **Unidade de trabalho:** uma empresa por análise, mais os pares quando a comparação exigir (ex.: BBAS3 com ITUB4, BBDC4, SANB11).
- **Fora de escopo:** screener de mercado, backtest de estratégias, gestão de carteira, dashboards multiusuário. Ver §11.

## 2. Princípios obrigatórios

1. **Rastreabilidade** — nenhum dado financeiro aparece sem fonte identificável (documento, período, unidade, data de publicação). Nenhuma estimativa é apresentada como dado realizado.
2. **Independência metodológica** — cada especialista apresenta sua própria conclusão. O `stock-analyst` consolida, mas nunca altera o resultado de um especialista para chegar a uma recomendação desejada.
3. **Transparência matemática** — toda metodologia apresenta fórmula, variáveis, dados de entrada, premissas, resultado, limitações e justificativa de aplicabilidade.
4. **Determinismo** — todo cálculo é código Python testado (`engine/`). O modelo decide aplicabilidade, escolhe e justifica premissas, extrai de PDFs o que não é estruturado e interpreta resultados. Ele **nunca** calcula de cabeça nem digita números no relatório.

## 3. Visão geral do fluxo

```
fontes públicas ──sync──▶ data/warehouse.duckdb ──snapshot──▶ analyses/<TICKER>/<data-base>/data.json
                                                                       │
        data-validator ──▶ indicators ──▶ valuation-* · sector-analysis · quality-fisher · research-*
                                                                       │
                                               stock-analyst (consolida) ──▶ report-html
```

| Camada | Responsável | Natureza |
|---|---|---|
| Ingestão, normalização, banco | `engine/ingest`, `engine/db` | Código determinístico (não é skill) |
| Snapshot da análise | `engine/snapshot` + skill `data-extractor` | Código + extração de PDF pelo modelo |
| Validação, indicadores, fórmulas | `engine/validation`, `engine/indicators`, `engine/valuation` | Código determinístico |
| Aplicabilidade, premissas, interpretação | skills | Julgamento do modelo, sempre justificado |
| Relatório | `engine/report` (template Jinja2) + skill `report-html` | Renderização a partir dos JSONs |

As etapas se comunicam **por arquivos**, não pelo contexto da conversa. Isso permite auditar cada etapa, reexecutar só uma parte (ex.: mudar o DY do Bazin sem reextrair) e garante que cada especialista lê os dados, não a conclusão dos outros.

## 4. Estrutura do repositório

```
skillsInvest/
├── CLAUDE.md                # princípios e regras de trabalho (sempre carregado)
├── README.md                # instalação, configuração e execução — sempre atualizado
├── .env.example             # variáveis necessárias, sem valores (o .env real fica fora do git)
├── pyproject.toml
├── config/
│   └── defaults.yaml        # parâmetros do investidor (DY do Bazin, margem de segurança, Ke...)
├── schemas/                 # JSON Schema versionado do contrato de dados
├── engine/                  # pacote Python
│   ├── cli.py               # comando skillsinvest
│   ├── settings.py          # variáveis do .env
│   ├── config.py            # leitura de config/defaults.yaml
│   ├── contract/            # modelos pydantic do contrato (fonte dos JSON Schemas)
│   ├── ingest/              # sync: cvm, b3, bcb, tesouro, brapi
│   ├── db/                  # schema DuckDB, migrações, views
│   ├── snapshot/            # banco → data.json da análise
│   ├── validation/
│   ├── indicators/
│   ├── valuation/           # graham, lynch, bazin, dcf, ddm, multiples, residual_income
│   ├── sectors/             # cálculos de cada perfil setorial
│   └── report/              # renderização + templates HTML
├── tests/
│   └── fixtures/            # BBAS3 e casos de fórmula com resultado conhecido
├── .claude/
│   └── skills/              # uma pasta por skill (ver §5)
├── analyses/                # saídas das análises — versionado no git
└── data/                    # FORA DO GIT — reconstruível via sync
    ├── warehouse.duckdb
    ├── cache/               # downloads temporários (TTL curto)
    └── documents/           # PDFs de RI usados em extração pelo modelo
```

### Configuração, credenciais e README

- **Parâmetros de análise** (não secretos) ficam em `config/defaults.yaml`, versionado.
- **Tokens e credenciais** ficam só no `.env`, que está fora do git. O `.env.example` (versionado) lista todas as variáveis sem valores. O engine lê as variáveis com pydantic-settings, e a falta de uma variável obrigatória gera um erro que diz qual variável configurar.
- **URLs dos serviços externos** também ficam no `.env` (`CVM_BASE_URL`, `B3_COTAHIST_BASE_URL`, `BRAPI_BASE_URL`, `BCB_SGS_BASE_URL`), para deixar explícito de onde vêm os dados. O engine tem os mesmos valores como padrão, e um teste garante que eles coincidem com o `.env.example`. Só `https://` é aceito, e o `skillsinvest doctor` mostra as URLs em uso.
- Variáveis atuais: `BRAPI_TOKEN`, `DATA_DIR` (opcional) e as quatro URLs.
- **README.md** sempre reflete como instalar, configurar e executar o projeto. Toda mudança que afete isso atualiza o README no mesmo commit.

## 5. Catálogo de skills

### Convenções

- Uma pasta por skill em `.claude/skills/<nome>/`, **um nível só** (pastas de categoria aninhadas não são descobertas pelo Claude Code). O grupo é expresso pelo prefixo do nome.
- `SKILL.md` com `name` e `description`. A description diz **quando usar e quando não usar**, porque é ela que decide qual skill é acionada.
- Metodologia detalhada em `references/` (carregada sob demanda). Templates e arquivos estáticos em `assets/`.
- A skill nunca descreve uma fórmula para o modelo calcular: ela chama o `engine`. Se a função não existir, ela é criada com teste antes.

### Core

| Skill | Responsabilidade | Saída |
|---|---|---|
| `data-extractor` | Garante que o banco está atualizado (roda `sync` se preciso), gera o snapshot da empresa e extrai dos PDFs de RI apenas o que não existe estruturado | `data.json` |
| `data-validator` | Consistência, trimestral × acumulado, consolidado × individual, não recorrentes, reapresentações, quebras de série, PDF × CVM. Erro crítico bloqueia o valuation | `validation.json` |
| `indicators` | Rentabilidade, margens, endividamento, eficiência, crescimento, dividendos (payout, cobertura), múltiplos históricos | `indicators.json` |

### Valuation quantitativo

Saída comum: `valuations/<metodo>.json` (formato em §6.3).

| Skill | Conteúdo | Não aplicável quando |
|---|---|---|
| `valuation-graham` | Número de Graham √(22,5 × LPA × VPA); fórmula revisada (1974) LPA × (8,5 + 2g) × 4,4 / Y; adaptação brasileira de Y rotulada como adaptação | LPA ou VPA ≤ 0 |
| `valuation-lynch` | Classificação nas 6 categorias de Lynch; PEG; PEG ajustado por dividendos (g + DY) / P/L | Crescimento negativo ou irregular; categorias em que o PEG não se aplica |
| `valuation-bazin` | Preço-teto = proventos médios por ação / DY desejado (padrão 6%, configurável); exclusão marcada de extraordinários | Histórico de proventos insuficiente ou irregular |
| `valuation-dcf` | FCFF e FCFE; cenários pessimista, base e otimista; sensibilidade g × taxa; peso do valor terminal; consistência real × nominal | FCFF para bancos e seguradoras |
| `valuation-ddm` | Gordon Growth Model | g ≥ Ke; payout instável |
| `valuation-multiples` | P/L, P/VP, EV/EBITDA contra pares e contra o histórico da própria empresa | EV/EBITDA para bancos |
| `valuation-residual-income` | Lucro residual; P/VP justo = (ROE − g) / (Ke − g). Método preferido para bancos | — |
| `valuation-asset-based` | Soma das partes e avaliação patrimonial. Entra junto com o perfil `holdings` | Empresas operacionais sem participações relevantes |

### Qualitativo

| Skill | Conteúdo |
|---|---|
| `quality-fisher` | Os 15 pontos de Philip Fisher → pontuação de qualidade com evidências. **Sem preço-teto** |
| `research-business` | Moat, competição, qualidade da gestão, governança, perspectivas de crescimento |
| `research-risk` | Riscos operacionais, financeiros e regulatórios |

### Setores

Uma única skill, `sector-analysis`, com um perfil por setor em `references/sectors/<setor>.md` e os cálculos em `engine/sectors/<setor>.py`. O `SKILL.md` identifica o setor da empresa e carrega só o perfil correspondente. Adicionar um setor é escrever um perfil e um módulo, sem criar outra skill nem aumentar o contexto fixo.

**Interface de setor** — todo perfil segue o mesmo modelo: (a) indicadores próprios com definição, (b) metodologias preferidas, (c) metodologias vetadas com motivo, (d) critério de escolha dos pares, (e) fontes extras, (f) armadilhas contábeis conhecidas.

**Setor ≠ template contábil.** A CVM tem poucos modelos de demonstração (empresas em geral, instituições financeiras, seguradoras), e são eles que definem o `account_map`. O setor define a análise. Uma varejista e uma mineradora usam o mesmo template contábil, mas perfis setoriais diferentes.

**Setor ainda não implementado:** o `stock-analyst` segue com a análise genérica e o relatório informa que a análise setorial não está disponível. Nunca se improvisa um perfil.

`banking` entra na fase 3. Os demais perfis são implementados quando a primeira empresa do setor for analisada.

| Perfil | Segmentos (exemplos) | Indicadores-chave | Métodos preferidos | Vetados / cautela | Fonte extra gratuita |
|---|---|---|---|---|---|
| `banking` | Bancos (BBAS3, ITUB4, BBDC4, SANB11, BPAC11) | Basileia, CET1, Nível I e II, imobilização, RWA; ROE, ROA, NIM, eficiência, payout; inadimplência 15–90 e 90+, cobertura, custo do crédito, carteira e concentração | Residual income, P/VP justo, DDM, múltiplos entre pares | DCF FCFF, EV/EBITDA | BCB IF.data |
| `insurance` | Seguradoras, resseguradoras, previdência (BBSE3, CXSE3, PSSA3, IRBR3) | Sinistralidade, índice combinado, despesas de comercialização e administrativas, resultado financeiro, solvência (PLA × capital mínimo requerido), reservas técnicas, ROE | Residual income, P/VP justo, DDM | DCF FCFF, EV/EBITDA. Holdings de seguros exigem olhar a equivalência patrimonial | SUSEP (SES) |
| `real-estate` | Incorporadoras, shoppings, lajes e galpões | Incorporação: VSO, lançamentos, landbank, distratos, margem bruta, resultado a apropriar, dívida líquida/PL, consumo de caixa. Propriedades: NOI, FFO, AFFO, vacância, cap rate, SSS/SSR, LTV | P/VP, NAV (propriedades), múltiplos | EV/EBITDA em incorporadoras (receita por avanço de obra distorce) | — |
| `fii` | FIIs de tijolo, papel e híbridos | DY, P/VP, vacância física e financeira, cap rate, LTV, prazo e indexador dos contratos (típico/atípico), concentração de inquilinos; papel: indexador, duration, LTV, inadimplência | Bazin/DY, P/VP, DDM | Graham, Lynch, DCF FCFF. FII não publica DFP/ITR, então exige ingestão própria | CVM (informes de FII) |
| `utilities` | Energia (geração, transmissão, distribuição), saneamento | Dívida líquida/EBITDA, base de remuneração regulatória, WACC regulatório, revisão tarifária, prazo de concessão, perdas, RAP (transmissão), capex | DCF com prazo finito (concessão, sem perpetuidade), DDM | Transmissoras: preferir números regulatórios aos societários (IFRS) | ANEEL |
| `infrastructure` | Rodovias, ferrovias, portos, aeroportos, logística | Tráfego/volume, tarifa média, prazo de concessão, capex obrigatório, alavancagem, reequilíbrios | DCF com prazo finito | Perpetuidade em concessão com prazo definido | ANTT / ANTAQ (a confirmar) |
| `retail` | Varejo físico e digital, farmácias, vestuário | Vendas mesmas lojas, receita/m², margem bruta, giro de estoque, ciclo de caixa, capital de giro, antecipação de recebíveis, EBITDA pré e pós IFRS 16; digital: GMV, take rate | Múltiplos, DCF | Comparar EBITDA pós IFRS 16 com pré sem ajuste | — |
| `consumer` | Alimentos, bebidas, higiene, frigoríficos | Volume, preço/mix, margem bruta, custo de insumos, câmbio; frigoríficos: ciclo do gado, spread | Múltiplos, DCF, DDM | Frigoríficos: lucro de pico do ciclo | — |
| `industrial` | Bens de capital, autopeças, químicos, construção pesada | Margem EBITDA, ROIC × WACC, capex/depreciação, carteira de pedidos, exposição cambial, capital de giro | DCF, múltiplos, Graham | — | — |
| `commodities` | Mineração, siderurgia, papel e celulose, petróleo e gás, agro | Lucro normalizado pelo ciclo, sensibilidade a preço e câmbio, custo caixa, breakeven, dívida líquida/EBITDA no fundo do ciclo; petróleo: reservas provadas, lifting cost | DCF com preço normalizado, múltiplos sobre lucro normalizado | P/L e PEG sobre lucro de pico (Lynch: cíclica) | ANP (a confirmar) |
| `healthcare` | Operadoras de planos, hospitais, laboratórios | Sinistralidade, beneficiários, ticket, ocupação de leitos, receita por leito | DCF, múltiplos | — | ANS |
| `tmt` | Tecnologia, mídia e telecom | Tecnologia: receita recorrente, churn, regra dos 40. Telecom: ARPU, churn, base de clientes, capex/receita | DCF, múltiplos (P/Receita só com justificativa) | Graham em empresa sem lucro | Anatel (a confirmar) |
| `education` | Ensino superior, educação básica | Base de alunos, captação, evasão, ticket, PDD, mix presencial/EAD, exposição ao FIES | DCF, múltiplos | — | — |
| `holdings` | Holdings de participações (ITSA4, BRAP4) | Soma das partes, desconto de holding (atual × histórico), custo da holding, dividendos recebidos × distribuídos | Soma das partes (`valuation-asset-based`), DDM | Múltiplos sobre lucro de equivalência sem olhar as investidas | — |

### Orquestração e relatório

| Skill | Responsabilidade |
|---|---|
| `stock-analyst` | Identifica empresa e tipo, aciona os especialistas aplicáveis, consolida, aponta divergências entre métodos e emite o parecer. Não altera resultados dos especialistas |
| `report-html` | Renderiza o relatório a partir dos JSONs via template. Não calcula, não escreve números, só verifica se todos os resultados esperados estão presentes |

**Valuation consolidado:** nunca média simples entre métodos. O relatório mostra a faixa dos métodos aplicáveis (mínimo, mediana, máximo). Qualquer ponderação precisa ser explícita e justificada.

## 6. Contrato de dados

### 6.1 Regras gerais

- Os modelos pydantic em `engine/contract/` são a fonte única do contrato. Os JSON Schemas em `schemas/` são gerados com `skillsinvest export-schemas`, e um teste falha se estiverem desatualizados.
- Versionamento semver. Todo arquivo carrega `schema_version`.
- Chaves em inglês, `snake_case`.
- Valores monetários em unidade (escala da CVM normalizada na entrada). Percentuais como fração (`0.06`, não `6`).
- Números decimais são serializados como string (`"123.45"`) para não perder precisão.
- Datas em ISO 8601.

### 6.2 Value object

Todo valor financeiro é um objeto, nunca um número solto:

```json
{
  "value": "0",
  "unit": "BRL",
  "period": { "start": "2025-10-01", "end": "2026-09-30", "type": "LTM" },
  "basis": "consolidated",
  "nature": "derived",
  "source_ids": ["cvm-itr-2026-3t-v1", "cvm-dfp-2025-v1", "cvm-itr-2025-3t-v1"],
  "confidence": "high",
  "note": "9M 2026 + FY 2025 − 9M 2025"
}
```

| Campo | Valores |
|---|---|
| `unit` | `BRL`, `BRL/share`, `shares`, `ratio`, `count` |
| `period.type` | `INSTANT` (itens de balanço, só `end`), `3M`, `YTD`, `FY`, `LTM` |
| `basis` | `consolidated`, `individual`, `prudential` (conglomerado prudencial — Basileia), `managerial` (números gerenciais, ex.: lucro ajustado). Nulo para dados de mercado e macro |
| `nature` | `reported`, `derived` (calculado pelo engine a partir de reportados), `estimated` (projeção/premissa) |
| `confidence` | `high`, `medium`, `low` |

Regras validadas pelo contrato:
- Cada id de `source_ids` aponta para uma entrada de `sources[]` (`provider`, `document_type`, `url`, `published_at`, `retrieved_at`, `version`, `page`, `sha256`, `extraction`).
- Valores `reported` e `derived` precisam de fonte. Valores `derived` e `estimated` precisam de `note` explicando como foram obtidos.
- Extração de PDF (`extraction: llm_pdf`) exige URL e página.
- A duração do período é conferida: um acumulado de 9 meses rotulado como `3M` é rejeitado.
- Dados contábeis (`financials`) exigem `basis`.

### 6.3 Arquivos por análise

```
analyses/<TICKER>/<data-base>/
├── data.json              # snapshot: empresa, ações, séries contábeis, preço, macro, proventos, fontes
├── validation.json        # resultado das checagens; erro bloqueia os valuations
├── indicators.json
├── valuations/<metodo>.json
├── sector/<setor>.json
├── qualitative/<nome>.json
├── analyst.json           # consolidação e parecer do stock-analyst
└── report.html
```

`data.json` registra a data da base usada e os ids de ingestão. Atualizar o banco depois não altera uma análise já feita.

**Conteúdo do `data.json` (contrato 0.2.0):**
- `company`, `reference_date` (data do último balanço), `as_of` (momento do snapshot).
- `financials`: séries consolidadas de cada conceito do mapa de contas, sempre o valor mais recente de cada período.
- `market.prices`: a cotação mais recente entre o fechamento do COTAHIST e a cotação da brapi (em empate, o COTAHIST, que é oficial). `market.shares_outstanding`: ações emitidas − ações em tesouraria no último balanço (`derived`).
- `macro`: `selic_target` (meta Selic do dia) e `ipca_12m` (IPCA acumulado em 12 meses, `derived`).
- `corporate_actions`: proventos e eventos de ações exatamente como a B3 publica, sem ajuste.
- `sources`: um item por documento ou arquivo usado, referenciado por todos os valores.

**`validation.json`** — checagens que rodam antes de qualquer valuation (`skillsinvest validate`). `error` bloqueia os valuations; `warning` precisa aparecer no relatório; `info` documenta algo relevante.

| Checagem | Severidade | O que verifica |
|---|---|---|
| `required_inputs` | error | Cotação, ações, 3+ anos de lucro anual, patrimônio na data-base e proventos |
| `balance_sheet_identity` | error | Ativo total = passivo + patrimônio em todos os balanços |
| `quarter_consistency` | warning | Trimestre = acumulado do ano − acumulado anterior (diferença indica revisão de trimestre anterior) |
| `zero_flows` | warning | Valores anuais exatamente zero (conta não preenchida pela empresa) |
| `price_freshness` | warning | Cotação com mais de 7 dias |
| `price_after_statements` | info | Distância entre a data do preço e a do último balanço |
| `accounting_breaks` | warning/info | Layout de bancos de 2020 e Resolução CMN 4.966 (2025) |
| `restatements` | warning | Valores alterados por documentos posteriores |
| `large_price_moves` | warning | Variação diária acima de 15% sem provento ou evento de ações em ±5 dias |
| `reported_eps` | warning | Lucro ÷ ações perto do lucro por ação reportado (tolerância 2%) |

Formato comum de resultado de valuation:

```json
{
  "schema_version": "0.1.0",
  "method": "graham_number",
  "ticker": "BBAS3",
  "reference_date": "2026-09-30",
  "applicable": true,
  "not_applicable_reason": null,
  "formula": "sqrt(22.5 * eps * bvps)",
  "inputs": { "eps": { "...": "value object" }, "bvps": { "...": "value object" } },
  "assumptions": [{ "name": "...", "value": 0, "justification": "..." }],
  "result": {
    "unit": "BRL/share",
    "fair_value": "0",
    "ceiling_price": "0",
    "required_margin_of_safety": "0",
    "margin_of_safety_at_price": "0"
  },
  "limitations": ["..."],
  "applicability_rationale": "...",
  "engine_version": "...",
  "computed_at": "..."
}
```

- `fair_value`: valor intrínseco estimado pelo método.
- `ceiling_price`: preço máximo de compra. No Bazin é o próprio resultado do método. Nos demais, `fair_value × (1 − required_margin_of_safety)`.
- `required_margin_of_safety`: margem exigida (de `config/defaults.yaml`) usada para derivar o preço-teto.
- `margin_of_safety_at_price`: `(fair_value − preço) / fair_value` na cotação do snapshot.
- Método aplicável exige `formula`, `inputs` e `result`. Método não aplicável exige `not_applicable_reason` e não pode ter `result`.
- Resultados qualitativos (Fisher, research) têm pontuação, critérios, evidências e fontes, sem campos de preço.

## 7. Banco de dados local

### 7.1 Decisões

- **DuckDB** em `data/warehouse.duckdb`: arquivo único, sem servidor, colunar (bom para séries históricas), integração direta com Python.
- **Fora do git.** O banco é reconstruível a partir das fontes públicas com `sync`.
- **Escopo:** apenas as empresas analisadas e seus pares, não o mercado inteiro.
- **Arquivos brutos não são guardados.** Fluxo: baixar → filtrar CNPJs/tickers de interesse → normalizar → inserir → descartar. Downloads ficam em `data/cache/` por pouco tempo (para não baixar de novo ao incluir um par na mesma semana) e são limpos pelo `sync`.
- **Manifest de ingestão** no lugar do arquivo: URL, provedor, data de download, sha256, tamanho, `Last-Modified` e linhas carregadas. Junto com as versões no banco, isso garante a rastreabilidade.
- **Exceção — PDFs de RI** usados em extração pelo modelo ficam em `data/documents/` (fora do git): são leves, os sites de RI mudam ou removem links, e são a prova da página citada.

### 7.2 Regras de integridade

- **Nunca sobrescrever fatos.** Reapresentação é uma nova linha com a nova versão do documento. O validador compara versões e sinaliza reapresentações.
- **Normalização na entrada:** escala (`ESCALA_MOEDA`) → unidade; `DECIMAL` para valores monetários, nunca float; encoding dos CSVs da CVM corrigido.
- **Template contábil** (`non_financial`, `bank`, `insurance`) determina o plano de contas usado. Ele é diferente do setor (§5) e é detectado no próprio DFP, pelo nome da primeira linha da DRE (conta 3.01: "Intermediação Financeira" → `bank`).
- **Mapa de contas** ([engine/reference/account_map.csv](../engine/reference/account_map.csv)): liga cada código de conta da CVM (`CD_CONTA`), por template, a um conceito canônico do contrato (`net_income`, `equity`...). A vigência (`valid_from`/`valid_to`) vale para a **data de referência do documento**, não para o período do valor, porque o layout pertence ao documento. Motivo: a CVM mudou o plano de contas dos bancos em 2020, e o mesmo código passou a significar outra coisa (ex.: DRE 3.04.01 era "Receitas de Prestação de Serviços" e virou "Provisão para Perda Esperada"; DRE 3.09.01 era o lucro do controlador e o lucro passou para 3.11.01). O DFP 2020 reapresenta 2019 já no layout novo. A view `v_concept_facts` entrega um valor por conceito e período, sempre do documento mais recente.
- **Contas zeradas no layout antigo também não são mapeadas.** O BB deixou "Receitas de Prestação de Serviços" (3.04.01) zerada até 2019 e lançou a receita em outra linha; mapear essa conta criaria uma série com zeros falsos. A checagem `zero_flows` do validador pega casos novos.
- **Conceitos que mudaram de significado não são mapeados no layout antigo.** Ex.: até 2019, o resultado bruto de intermediação dos bancos já descontava a provisão de crédito; a partir de 2020, não. Para não misturar coisas diferentes na mesma série, `gross_financial_intermediation_result` e `credit_loss_expense` só existem a partir do layout de 2020. `equity` (patrimônio do controlador) também só existe no layout novo; no antigo, ele é derivado como `equity_total − non_controlling_interests`.
- **Setor:** vem do `SETOR_ATIV` do cadastro da CVM, via [engine/reference/cvm_sectors.yaml](../engine/reference/cvm_sectors.yaml) (o prefixo "Emp. Adm. Part. - " é ignorado). Exceções por ticker ficam em `config/sector_overrides.yaml`. Setor sem perfil gera aviso no `sync`.
- **Bancos:** indicadores prudenciais (Basileia, CET1...) são do conglomerado prudencial (`basis = prudential`), não do consolidado IFRS.
- **Dados extraídos de PDF** pelo modelo ficam em `document_facts`, separados dos dados estruturados, com URL, página, confiança e marca de revisão (`reviewed`).

### 7.3 Tabelas principais

| Tabela | Conteúdo |
|---|---|
| `ingestion_runs`, `source_files`, `source_file_scopes` | Manifest de cada carga: URL, ETag, SHA-256 e para quais empresas cada arquivo foi carregado |
| `companies` | CNPJ, código CVM, nome, template contábil, setor |
| `securities` | Ticker, CNPJ, classe (ON/PN/UNIT), vigência |
| `filings` | Documento (DFP/ITR), data-base, versão, data de entrega |
| `financial_facts` | Fatos por documento: conta, conceito, demonstração, base, período, valor, unidade |
| `account_map` | Template contábil + `CD_CONTA` → conceito canônico |
| `shares_outstanding` | Ações por classe e data, total e em tesouraria |
| `prices_daily` | Cotações diárias sem ajuste |
| `market_quotes` | Cotação intradiária (brapi) |
| `corporate_actions` | Proventos (data-com, pagamento, bruto/líquido, tipo), desdobramentos, grupamentos, bonificações |
| `macro_series` | Selic, IPCA, NTN-B |
| `bank_prudential` | Indicadores do IF.data por conglomerado e data-base |
| `document_facts` | Dados extraídos de PDF pelo modelo |

Views existentes: `v_financial_facts_latest` (último valor conhecido de cada conta e período), `v_concept_facts` (o mesmo, já como conceito do contrato) e `v_ingestion_freshness`. Próximas: trimestre isolado (incluindo 4T = DFP − 9M), últimos 12 meses (9M atual + ano anterior − 9M anterior) e preços ajustados por proventos e eventos.

### 7.5 Sync

`skillsinvest sync <TICKER>`:

1. Resolve o ticker para o CNPJ no FCA (valores mobiliários) do ano corrente ou do anterior.
2. Lê o cadastro (nome, setor, controle acionário).
3. Para cada DFP (`sync.history_years`) e ITR (`sync.quarterly_years`): consulta o ETag; se aquele arquivo já foi carregado para a empresa, pula; senão baixa, filtra as linhas do CNPJ e grava documentos, contas e quantidade de ações numa transação por arquivo.
4. Documentos já existentes (mesmo CNPJ, tipo, data e versão) não são regravados. Uma nova versão entra como novo documento.

Depois da CVM, o mesmo comando carrega:

- **Cotações (COTAHIST):** só o mercado à vista (`TPMERC 010`) dos tickers da empresa; preço = valor / 100 / fator de cotação. O ISIN de cada ticker é guardado.
- **Proventos e eventos de ações (B3):** valores exatamente como publicados (até 14 casas decimais), sem ajuste. Desdobramentos e bonificações vêm em percentual (100 = 2 por 1) e grupamentos como razão (0,001 = 1.000 por 1); ambos são guardados como "ações novas por ação antiga". O ajuste de séries por eventos é calculado depois, sem alterar essas linhas.
- **Cotação do dia (brapi):** o token vai no cabeçalho HTTP e nunca aparece na URL gravada no manifest.
- **Selic e IPCA (SGS):** convertidos de percentual para fração. A série da meta Selic traz dias futuros (até a próxima reunião do Copom), que são descartados. Consultas em janelas de 5 anos (o limite da API para séries diárias é 10).

Regras de normalização da CVM: escala `MIL` × 1000, exceto o lucro por ação (DRE 3.99.*), que a CVM já publica em R$/ação; moeda diferente de `REAL` é rejeitada; balanço é `INSTANT`, fluxos do DFP são `FY`, fluxos do ITR que começam em 1º de janeiro são `YTD` (o 1º trimestre fica como `YTD`) e os demais são `3M`.

### 7.4 Atualização

Sob demanda: antes de uma análise, o `sync` verifica quais fontes estão desatualizadas e atualiza só essas. Agendamento fica para depois (no WSL, cron exige systemd habilitado ou o Agendador do Windows).

## 8. Fontes de dados (todas gratuitas)

| Fonte | Uso | Frequência |
|---|---|---|
| CVM Dados Abertos — DFP, ITR, FCA, cadastro | Demonstrações financeiras padronizadas, tickers e classes de ações | Semanal: os arquivos de DFP e ITR são regenerados juntos (ambos com Last-Modified de 15/11/2026). DFP desde 2010, ITR desde 2011 |
| Site de RI da empresa (PDF) | Trimestre ainda não publicado na CVM, lucro recorrente, guidance, dados gerenciais, Pilar 3 dos bancos | No dia da divulgação |
| B3 COTAHIST | Histórico oficial de cotações (sem ajuste) e ISIN de cada ação | Diário; arquivo anual (~100 MB) |
| B3 — API das páginas de empresas listadas | Histórico de proventos (data-com, tipo, valor por ação desde os anos 1990) e desdobramentos, grupamentos e bonificações | A cada evento. É a API pública usada pelo site da B3, sem documentação oficial: o parser rejeita respostas fora do formato esperado |
| brapi.dev (plano grátis, `BRAPI_TOKEN` no `.env`) | Só a cotação do dia (proventos exigem plano pago) | Quase tempo real; 15.000 req/mês, 1 ticker por chamada |
| BCB SGS | Selic, IPCA | Diário / mensal |
| BCB IF.data | Indicadores prudenciais de todos os bancos na mesma data-base | Trimestral (60 dias após mar/jun/set, 90 após dez) |
| Tesouro Direto | Taxas das NTN-B (taxa livre de risco) | Diário |

Prazos legais das empresas: ITR até 45 dias após o trimestre; DFP até 3 meses após o exercício. Quando o trimestre mais recente ainda não estiver na CVM, usa-se o PDF do RI com `confidence: medium` até a confirmação.

## 9. Notas metodológicas já decididas

Detalhes completos irão para o `references/` de cada skill.

- **Validador:** no ITR, a DRE tem trimestre e acumulado; a DFC é só acumulada; o 4T isolado não é publicado. Valor de mercado = soma de (ações da classe × preço da classe), sem tesouraria.
- **Bancos:** "lucro recorrente" e inadimplência têm definições diferentes em cada banco — normalizar antes de comparar. A Resolução CMN 4.966 (vigente desde 2025) mudou a provisão para perda esperada, o que quebra a série histórica e deve ser sinalizado.
- **Bazin:** definir explicitamente dividendos + JCP, bruto ou líquido, critério data-com e janela de anos.
- **DCF:** fluxo e taxa sempre na mesma base (real ou nominal).

## 10. Roadmap

| Fase | Entregas |
|---|---|
| 0 | `CLAUDE.md`, este documento, README com instalação e execução, `.env.example`, schemas v0.1, esqueleto do `engine`, schema do banco, fixture BBAS3 |
| 1 | Fatia ponta a ponta com BBAS3: `sync` (CVM, COTAHIST, SGS, brapi) → `data-extractor` → `data-validator` básico → `indicators` básico → `valuation-graham` + `valuation-bazin` → `report-html` simples |
| 2 | `valuation-lynch`, `valuation-dcf`, `valuation-multiples`, `valuation-ddm`, `valuation-residual-income`; primeira empresa não financeira (valida o contrato e o `account_map` para `non_financial`) |
| 3 | `sector-analysis` com o perfil `banking` completo e comparação entre bancos (IF.data; pares ITUB4, BBDC4, SANB11) |
| 4 | `quality-fisher`, `research-business`, `research-risk`, `stock-analyst` completo |
| 5 | Relatório completo (gráficos, impressão em PDF) |
| Sob demanda | Demais perfis setoriais, quando a primeira empresa do setor for analisada |

Primeira empresa: **BBAS3**. Um banco testa logo o caso mais difícil do contrato (plano de contas de instituição financeira, base prudencial, Resolução CMN 4.966). Também tem uma única classe de ação (ON), paga dividendos e JCP com frequência (bom para o Bazin) e teve desdobramento em 2024 (testa o ajuste de preços e de valores por ação). O template contábil e o `account_map` nascem preparados para os outros modelos, para que a primeira não financeira entre na fase 2 sem refatoração.

## 11. Fora de escopo

- Screener e ranking de mercado.
- Backtest de metodologias (e, por consequência, tratamento de viés de sobrevivência).
- Gestão de carteira e dashboards.
- Uso multiusuário (exigiria trocar DuckDB por Postgres).

## 12. Pendências

- [x] Criar token gratuito da brapi e colocar no `.env` como `BRAPI_TOKEN` (BBAS3 não está entre os tickers liberados sem token).
- [x] Mapear o `SETOR_ATIV` do cadastro da CVM para perfil setorial (o template contábil é detectado no DFP).
- [ ] Mapa de contas para `non_financial` e `insurance` (com a primeira empresa de cada tipo).
- [x] Fonte gratuita de **histórico de proventos por ação**: API das páginas de empresas listadas da B3 (a brapi cobra por esse dado). JCP vem bruto; "RENDIMENTO" (correção do JCP entre a data-com e o pagamento) fica como `other`. Proventos extraordinários ainda precisam ser identificados na validação.
- [x] Confirmar a periodicidade de atualização do conjunto DFP na CVM (semanal, junto com o ITR).
- [ ] Definir valores padrão de `config/defaults.yaml` além do DY de 6% (margem de segurança, janela do Bazin, Ke).
- [ ] **README inicial (fase 0):** instalação, configuração do `.env`, `data/` (banco, cache e PDFs) fora do git e como reconstruir com `sync`. Depois disso, atualizado a cada mudança de execução.
- [ ] Aviso no relatório de que a análise não constitui recomendação de investimento.
