---
name: data-validator
description: Valida o snapshot data.json de uma empresa antes de qualquer valuation e explica ao investidor os erros e avisos (balanço que não fecha, trimestres revisados, reapresentações, contas zeradas, quebras de série contábil, quedas de preço sem evento). Use logo depois do data-extractor, ou quando o usuário perguntar se os dados de uma análise são confiáveis. Não calcula indicadores nem preço-teto.
---

# data-validator

Roda as checagens do engine e interpreta o resultado. Lista e severidades das checagens: `docs/architecture.md` §6.3.

## Passos

1. Rode:
   ```bash
   .venv/bin/skillsinvest validate <TICKER> -v
   ```
   Isso grava `analyses/<TICKER>/<data-base>/validation.json`.
2. Se terminar com `BLOQUEADO`, pare: nenhum valuation pode rodar. Explique qual checagem falhou e o que fazer (geralmente rodar o sync de novo, ou o dado não existe nas fontes).
3. Para cada `aviso`, explique em linguagem simples o que significa para a análise. Exemplos:
   - `restatements`: a empresa corrigiu números antigos; a análise usa sempre a versão mais recente.
   - `quarter_consistency`: um trimestre foi revisado dentro do acumulado do ano.
   - `accounting_breaks`: séries antes e depois da quebra não são diretamente comparáveis.
   - `large_price_moves`: o preço caiu ou subiu muito sem provento ou desdobramento. Sugira ao usuário verificar fatos relevantes e notícias da data; você não sabe a causa e não deve inventá-la.
4. Siga para a skill `indicators`.

## Regras

- Não suavize avisos nem os omita: todo `warning` precisa aparecer no relatório final.
- Não "corrija" dados. Se um número parecer errado, aponte a checagem e a fonte (`source_ids`) e deixe a decisão com o usuário.
