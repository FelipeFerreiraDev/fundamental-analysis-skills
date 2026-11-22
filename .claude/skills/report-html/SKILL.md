---
name: report-html
description: Gera o relatório HTML de uma análise (analyses/<TICKER>/<data-base>/report.html) a partir dos JSONs já calculados — resumo dos métodos, avisos da validação, indicadores, gráficos de lucro e proventos, cada método com fórmula, entradas, premissas e limitações, e as fontes. Use quando o usuário pedir o relatório, ao final de uma análise completa, ou depois de recalcular algum método. Não calcula nem altera nenhum número.
---

# report-html

## Pré-requisitos

`data.json`, `validation.json` (sem bloqueio), `indicators.json` e ao menos um arquivo em `valuations/`, todos do mesmo snapshot. Se faltar algum, rode antes as skills anteriores (`data-extractor` → `data-validator` → `indicators` → `valuation-*`).

## Passos

1. Rode:
   ```bash
   .venv/bin/skillsinvest report <TICKER>
   ```
2. Informe o caminho do arquivo gerado. Ele é autocontido: abre offline, tem tema claro e escuro e é otimizado para impressão em PDF.
3. Resuma em poucas linhas o que o relatório mostra: métodos aplicáveis e não aplicáveis e os avisos mais relevantes da validação.

## Regras

- O relatório é renderizado pelo template `engine/report/templates/report.html.j2` a partir dos JSONs. Nunca edite o HTML gerado nem escreva números nele: se algo estiver errado, corrija o dado ou o engine e gere de novo.
- Não há valuation consolidado nem parecer final: isso é papel do `stock-analyst` (ainda não implementado). Não faça média entre métodos.
- Todo aviso da validação aparece no relatório; não os omita no resumo.
