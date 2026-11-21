# Preço-teto de Bazin — metodologia

## Origem

Décio Bazin, *Faça Fortuna com Ações, Antes que Seja Tarde*: comprar ações que paguem, de forma consistente, ao menos 6% ao ano em proventos sobre o preço pago. Isolando o preço:

```
preço-teto = proventos anuais por ação ÷ dividend yield desejado
```

Bazin também exigia empresas pouco endividadas e com pagamento regular; essas condições não entram na fórmula e devem ser avaliadas na leitura.

## Decisões de cálculo (config/defaults.yaml → `bazin`)

| Parâmetro | Valor atual | Significado |
|---|---|---|
| `target_dividend_yield` | 0,06 | DY mínimo desejado |
| `lookback_years` | 5 | Janela **móvel**: proventos com data-com nos últimos 5 anos até a data do snapshot; a soma é dividida por 5 |
| `include_jcp_correction` | sim | Inclui os "RENDIMENTOS" (correção do JCP entre a data-com e o pagamento) |
| `jcp_withholding_rates` | 15% (Lei 9.249/1995); 17,5% desde 01/01/2026 (LC 224/2025) | Alíquota do IR retido sobre JCP, pela data de pagamento (data-com quando falta); usada na variante líquida |

Regras fixas do engine:

- **Data-com** define a que período o provento pertence.
- **Ajuste por eventos de ações:** um provento é dividido pelo fator acumulado dos desdobramentos, grupamentos e bonificações com data-com igual ou posterior à dele. Assim todos os valores ficam "por ação atual". Ex.: BBAS3 desdobrou 1 para 2 em 2024; proventos anteriores são divididos por 2.
- **Fonte:** API pública das páginas de empresas listadas da B3; JCP vem bruto.
- **Aplicabilidade:** o histórico carregado precisa começar antes do início da janela; sem nenhum provento na janela, o método não se aplica.

## Duas variantes

- `bazin_gross`: JCP bruto, como a B3 publica — comparável entre empresas e com sites de mercado.
- `bazin_net`: JCP líquido do IR retido na fonte — o que a pessoa física recebe. Outras tributações do investidor não são consideradas.

## Limitações

- O método olha para trás: supõe que os proventos da janela se repetirão. O engine compara os proventos dos últimos 12 meses com a média da janela e registra a proporção nas limitações.
- Proventos extraordinários entram na média e inflam o teto.
- Não avalia lucro, payout sustentável, endividamento nem crescimento.
- Em bancos, o payout depende de capital regulatório (Basileia); quedas de lucro tendem a reduzir proventos.
