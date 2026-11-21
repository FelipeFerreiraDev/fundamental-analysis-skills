# Número de Graham — metodologia

## Origem

Benjamin Graham, *The Intelligent Investor*: para o investidor defensivo, o preço não deveria passar de 15 vezes o lucro médio nem de 1,5 vez o valor patrimonial. Graham admitia compensar um múltiplo com o outro, desde que o produto P/L × P/VP não passasse de 22,5. Isolando o preço:

```
P/L × P/VP ≤ 22,5   →   P ≤ √(22,5 × LPA × VPA)
```

O resultado é o **valor justo** pelo critério. O **preço-teto** aplica a margem de segurança escolhida pelo investidor: `valor justo × (1 − margem)`. O engine calcula um preço-teto para cada margem de `config/defaults.yaml` (`valuation.margins_of_safety`).

## Entradas usadas pelo engine

| Entrada | Definição | Origem |
|---|---|---|
| LPA | Lucro líquido do controlador dos últimos 12 meses ÷ ações em circulação na data-base | `indicators.json` → `eps_ltm` |
| VPA | Patrimônio do controlador na data-base ÷ ações em circulação | `indicators.json` → `bvps` |
| Preço | Cotação mais recente do snapshot | `data.json` → `market.prices` |

Graham usava o lucro **médio** de vários anos. O engine usa os últimos 12 meses (fase 1); a média plurianual entra com o método de Lynch/crescimento.

## Quando não se aplica

- LPA ≤ 0 ou VPA ≤ 0: a raiz não tem significado econômico (o engine devolve `applicable: false`).
- Empresas cujo valor está em ativos intangíveis ou crescimento (o VPA subestima o valor): aplicável, mas pouco informativo — registre como limitação.

## Limitações

- Não considera crescimento, qualidade do lucro, governança nem vantagem competitiva.
- Um período atípico (provisões extraordinárias, ganhos não recorrentes, mudança contábil) distorce o LPA.
- **Bancos:** Graham formulou o critério para empresas não financeiras. Em bancos, o patrimônio é alavancado e regulado (Basileia); o resultado precisa ser lido com ROE, custo do capital e qualidade da carteira. Desde 2025, a Resolução CMN 4.966 muda o cálculo das provisões, o que afeta lucro e patrimônio.

## Fórmula revisada (1974) — ainda não implementada

`V = LPA × (8,5 + 2g) × 4,4 / Y`, com `g` = crescimento esperado e `Y` = rendimento de títulos AAA. Exige uma premissa de crescimento e a adaptação de `Y` ao Brasil (ex.: NTN-B), que deve ser rotulada como adaptação. Entra junto com a skill de Lynch.
