# atelier-quant — motor de backtesting & validação

Framework pessoal de pesquisa quantitativa. A ideia central: **testar rápido
e julgar com rigor**. O [freqtrade](https://www.freqtrade.io) faz o backtesting
vetorizado (o que na plataforma gráfica levaria horas sai em segundos); por
cima dele vive uma camada própria de **validação estatística** e **análise de
risco** que decide, com critérios objetivos, se uma estratégia merece seguir
adiante — ou morrer na prancheta.

## O que este repositório é (e o que não é)

Isto é uma **vitrine da engenharia** — o motor de validação, não as
estratégias. As regras operacionais reais ficam **fora** deste repositório, de
propósito. A estratégia incluída aqui
([`CruzamentoEMA`](user_data/strategies/exemplo_cruzamento_ema.py)) é um
cruzamento de médias de manual, presente só para deixar o pipeline concreto e
rodável: gerar um backtest que a régua consiga ler e julgar.

O valor está em **como as estratégias são julgadas**, não em qual estratégia.

## A régua

Toda estratégia passa pela mesma régua, sempre do mesmo jeito — sem torcer
para o resultado bonito:

1. **Consistência por ano** — quantos anos fecham positivos? Um número anual
   bom não vale se veio de um único ano fora da curva.
2. **Out-of-sample (holdout)** — os últimos 25% do período ficam de fora do
   olhar. A expectância sobrevive fora da amostra ou era só ajuste ao passado?
3. **Monte Carlo** — 2.000 embaralhamentos da sequência de trades desenham a
   distribuição de drawdown (p50/p95/p99) e a probabilidade de terminar no
   vermelho. A ordem histórica foi só uma amostra de sorte; isto mede as outras.
4. **Gates** — critérios objetivos (amostra mínima, profit factor, holdout
   positivo, anos positivos) → veredito **APROVADA / ATENÇÃO / REPROVADA**, com
   o motivo de cada gate.

## Disciplina de capital (regra inegociável)

Aprovada na régua = pode ir para **dry-run** (paper trading). Nada de dinheiro
real antes de:

- forward em dry-run com trades reais registrados (não só backtest);
- tracking error medido (fills reais × modelo do backtest) dentro do tolerável;
- risco por trade definido e sizing conferido (ver `analysis/risco.py`).

O backtest aprova a hipótese; o dry-run aprova a execução. São gates
diferentes.

## Estrutura

```
config.json                              config pública do freqtrade (sem segredos)
analysis/
  risco.py       NÍVEL 3 — analytics de risco: expectância, R-múltiplos,
                 payoff, PF e win rate por setup/par/ano/saída, DD, Kelly/sizing
  harness.py     NÍVEL 4 — régua de validação: consistência, holdout,
                 Monte Carlo e gates → veredito padronizado
user_data/strategies/
  exemplo_cruzamento_ema.py              estratégia de exemplo (placeholder)
```

## Como rodar

```bash
# 1. ambiente
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. baixar dados e rodar um backtest da estratégia de exemplo
freqtrade download-data --exchange binance --pairs BTC/USDT ETH/USDT SOL/USDT \
    --timeframe 4h --timerange 20220101-
freqtrade backtesting --strategy CruzamentoEMA --timeframe 4h --timerange 20220101-

# 3. julgar o resultado na régua e no módulo de risco
python analysis/harness.py     # veredito APROVADA/ATENÇÃO/REPROVADA
python analysis/risco.py       # expectância, R-múltiplos, sizing
```

Os dados (`user_data/data/`) e os resultados de backtest
(`user_data/backtest_results/`) são regeneráveis e ficam fora do versionamento.
