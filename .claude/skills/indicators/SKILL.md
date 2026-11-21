---
name: indicators
description: Calcula e explica os indicadores fundamentalistas de uma empresa a partir do snapshot validado — lucro dos últimos 12 meses, LPA, VPA, ROE, P/L, P/VP, proventos por ação e dividend yield (JCP bruto e líquido), com proventos ajustados por desdobramentos. Use depois do data-validator e antes dos valuations, ou quando o usuário pedir múltiplos ou indicadores de uma ação já carregada.
---

# indicators

## Passos

1. Rode:
   ```bash
   .venv/bin/skillsinvest indicators <TICKER>
   ```
   O comando recusa snapshots sem validação ou com validação bloqueante. Grava `indicators.json`.
2. Leia `analyses/<TICKER>/<data-base>/indicators.json`. Cada indicador tem `note` com a fórmula e as entradas, e `source_ids` com os documentos de origem.
3. Apresente os indicadores ao usuário, sempre com:
   - o período (ex.: lucro dos últimos 12 meses até a data-base);
   - a data do preço usado nos múltiplos;
   - o que estiver em `unavailable`, com o motivo.

## Regras

- Não calcule nenhum indicador de cabeça. Se faltar um indicador, ele precisa ser criado no engine (`engine/indicators/`) com teste.
- O LPA do engine usa as ações em circulação na data-base; o LPA reportado pela empresa usa a média ponderada. Diferenças pequenas são esperadas (o validador confere com tolerância de 2%).
- Para bancos, lembre que P/L e P/VP precisam ser lidos com ROE e com as quebras de série apontadas pelo validador.
