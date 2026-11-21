---
name: valuation-graham
description: Avalia uma ação pelo Número de Graham (√(22,5 × LPA × VPA)), com preço-teto para cada margem de segurança configurada, e explica aplicabilidade e limitações. Use quando o usuário pedir valor justo ou preço-teto "pelo Graham", ou dentro de uma análise completa. Não use quando LPA ou VPA não forem positivos (o engine devolve "não aplicável"). A fórmula revisada de 1974, com crescimento, ainda não está implementada.
---

# valuation-graham

Metodologia, origem da fórmula e limitações: [references/methodology.md](references/methodology.md). Leia antes de interpretar um resultado.

## Pré-requisitos

`data.json`, `validation.json` (sem bloqueio) e `indicators.json` do mesmo snapshot. Se faltar algum, use antes as skills `data-extractor`, `data-validator` e `indicators`.

## Passos

1. Rode:
   ```bash
   .venv/bin/skillsinvest valuate <TICKER> --method graham
   ```
2. Leia `analyses/<TICKER>/<data-base>/valuations/graham_number.json`.
3. Se `applicable` for `false`, explique `not_applicable_reason` e pare. Não force o método.
4. Se for aplicável, apresente:
   - a fórmula e as entradas (`inputs`: LPA, VPA, preço), com período e fonte;
   - o valor justo, os preços-teto por margem (`ceiling_prices`) e o preço atual;
   - o desconto do preço ao valor justo (`margin_of_safety_at_price`);
   - todas as `limitations`, mais os avisos do `validation.json` que afetam lucro ou patrimônio (ex.: quebras de série, reapresentações).
5. Dê sua leitura como especialista Graham: o critério sugere compra, neutralidade ou cautela? Justifique só com o que está nos arquivos e na metodologia.

## Regras

- Nunca recalcule nem arredonde de outro jeito: use os números do JSON.
- Não troque premissas (constante 22,5, margens) por conta própria; as margens vêm de `config/defaults.yaml` e são decisão do usuário.
- Sua conclusão é independente dos outros métodos: não a ajuste para concordar com Bazin ou outros.
