---
name: valuation-bazin
description: Calcula o preço-teto de Décio Bazin (média anual de proventos por ação ÷ dividend yield desejado, padrão 6%) com JCP bruto e líquido de IR, proventos ajustados por desdobramentos, e explica a sustentabilidade dos proventos. Use quando o usuário pedir preço-teto "pelo Bazin", preço-teto por dividendos, ou dentro de uma análise completa de empresa pagadora de proventos. Não use para empresas sem histórico de proventos que cubra a janela configurada (o engine devolve "não aplicável").
---

# valuation-bazin

Metodologia e decisões de cálculo: [references/methodology.md](references/methodology.md). Leia antes de interpretar.

## Pré-requisitos

`data.json`, `validation.json` (sem bloqueio) e `indicators.json` do mesmo snapshot. Se faltar algum, use antes `data-extractor`, `data-validator` e `indicators`.

## Passos

1. Rode:
   ```bash
   .venv/bin/skillsinvest valuate <TICKER> --method bazin
   ```
2. Leia `valuations/bazin_gross.json` (JCP bruto) e `valuations/bazin_net.json` (JCP líquido do IR retido na fonte).
3. Se `applicable` for `false`, explique `not_applicable_reason` e pare.
4. Apresente, para as duas variantes:
   - a média anual de proventos por ação (`inputs.average_dividends_per_share`, com a `note` que diz a janela e quantos proventos entraram);
   - o preço-teto e o preço atual;
   - as premissas (`assumptions`): DY desejado, janela, inclusão dos rendimentos de JCP, alíquotas de IR;
   - todas as `limitations`. Dê destaque à comparação entre os proventos dos últimos 12 meses e a média da janela: se os recentes estiverem bem abaixo, o preço-teto reflete um passado que pode não se repetir.
5. Use a série `dividends_per_share_annual_gross` de `indicators.json` para mostrar a regularidade dos proventos ano a ano.
6. Dê sua leitura como especialista Bazin: os proventos são regulares e sustentáveis? O preço está abaixo do teto? Justifique só com os arquivos e a metodologia.

## Regras

- Nunca recalcule a média, o teto ou o ajuste por desdobramento: use os números do JSON.
- Janela, DY desejado, inclusão de rendimentos e alíquotas são decisões do usuário em `config/defaults.yaml`.
- Não identifique proventos como "extraordinários" por conta própria; aponte valores que pareçam fora do padrão e deixe a decisão com o usuário.
- Conclusão independente dos outros métodos.
