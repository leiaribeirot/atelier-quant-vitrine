# ═══════════════════════════════════════════════════════════════════
#  NÍVEL 4 — HARNESS DE VALIDAÇÃO ESTATÍSTICA
#
#  A régua que julga qualquer estratégia SEMPRE do mesmo jeito.
#  Recebe um backtest do freqtrade (zip) e emite veredito padronizado:
#
#    1. CONSISTÊNCIA   — quebra por ano (quantos anos positivos?)
#    2. OUT-OF-SAMPLE  — últimos 25% do período como holdout: a
#                        expectância sobrevive fora da amostra?
#    3. MONTE CARLO    — 2.000 embaralhamentos da sequência de trades:
#                        distribuição de drawdown (p50/p95/p99) e
#                        probabilidade de PnL terminal negativo
#    4. GATES          — critérios objetivos → APROVADA / ATENÇÃO /
#                        REPROVADA (com o motivo de cada gate)
#
#  Uso:
#    python analysis/harness.py                → zip mais recente
#    python analysis/harness.py <arquivo.zip>
#    python analysis/harness.py --oos 0.3      → holdout de 30%
#
#  Gates (defaults, ajustáveis por flag):
#    --min-trades 100   amostra mínima
#    --min-pf 1.05      profit factor mínimo no total
#    --min-oos-pf 1.0   PF mínimo no holdout
#    --min-anos-pos 50  % mínimo de anos positivos
# ═══════════════════════════════════════════════════════════════════
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from risco import carregar_trades_zip, linha, metricas, _arg  # noqa: E402

N_MC = 2000
SEMENTE = 42  # fixa: mesmo dado → mesmo relatório (reprodutível)


def monte_carlo(df: pd.DataFrame) -> dict:
    rng = np.random.default_rng(SEMENTE)
    lucros = df["profit_abs"].to_numpy()
    dds, finais = [], []
    for _ in range(N_MC):
        seq = rng.permutation(lucros)
        curva = np.cumsum(seq)
        dds.append((curva - np.maximum.accumulate(curva)).min())
        finais.append(curva[-1])
    dds, finais = np.array(dds), np.array(finais)
    return dict(
        dd_p50=np.percentile(dds, 50), dd_p95=np.percentile(dds, 5),
        dd_p99=np.percentile(dds, 1), prob_neg=(finais < 0).mean() * 100,
    )


def main():
    arqs = [a for a in sys.argv[1:] if a.endswith(".zip")]
    df, origem = carregar_trades_zip(Path(arqs[0]) if arqs else None)
    sem = _arg("--sem")  # ex.: --sem BTC → julga a estratégia sem esse par
    if sem:
        df = df[~df["pair"].str.contains(sem, case=False)]
        origem += f" · SEM {sem}"
    df = df.sort_values("close_date").reset_index(drop=True)

    oos_frac = _arg("--oos", 0.25, float)
    min_trades = _arg("--min-trades", 100, int)
    min_pf = _arg("--min-pf", 1.05, float)
    min_oos_pf = _arg("--min-oos-pf", 1.0, float)
    min_anos_pos = _arg("--min-anos-pos", 50.0, float)

    print("═" * 78)
    print(f" HARNESS DE VALIDAÇÃO — {origem}")
    print("═" * 78)
    m_total = metricas(df)
    print(linha("TOTAL", m_total))

    # 1. consistência por ano
    print("\n 1 · CONSISTÊNCIA POR ANO")
    anos_pos = anos = 0
    for ano, grupo in df.groupby(df["close_date"].dt.year):
        m = metricas(grupo)
        anos += 1
        anos_pos += m["pnl"] > 0
        print(linha(str(ano), m))
    pct_anos = 100 * anos_pos / anos if anos else 0

    # 2. holdout out-of-sample (por tempo, não por contagem de trades)
    ini, fim = df["close_date"].iloc[0], df["close_date"].iloc[-1]
    corte = ini + (fim - ini) * (1 - oos_frac)
    dentro, fora = df[df["close_date"] < corte], df[df["close_date"] >= corte]
    print(f"\n 2 · OUT-OF-SAMPLE (corte {corte:%Y-%m-%d} · holdout {oos_frac:.0%} do período)")
    m_in = metricas(dentro) if len(dentro) else None
    m_oos = metricas(fora) if len(fora) else None
    if m_in:
        print(linha("in-sample", m_in))
    if m_oos:
        print(linha("HOLDOUT", m_oos))

    # 3. monte carlo
    mc = monte_carlo(df)
    print(f"\n 3 · MONTE CARLO ({N_MC} embaralhamentos da sequência)")
    print(f"   DD típico (p50) {mc['dd_p50']:.2f} · DD severo (p95) {mc['dd_p95']:.2f}"
          f" · DD extremo (p99) {mc['dd_p99']:.2f}")
    print(f"   probabilidade de terminar negativo: {mc['prob_neg']:.1f}%")

    # 4. gates
    print("\n 4 · GATES")
    gates = [
        ("amostra", m_total["n"] >= min_trades,
         f"n={m_total['n']} (mín {min_trades})"),
        ("profit factor", m_total["pf"] >= min_pf,
         f"PF={m_total['pf']:.2f} (mín {min_pf})"),
        ("expectância", m_total["exp_abs"] > 0,
         f"{m_total['exp_abs']:+.2f}/trade"),
        ("out-of-sample", bool(m_oos) and m_oos["pf"] >= min_oos_pf,
         f"PF holdout={m_oos['pf']:.2f} (mín {min_oos_pf})" if m_oos else "sem trades no holdout"),
        ("anos positivos", pct_anos >= min_anos_pos,
         f"{anos_pos}/{anos} anos ({pct_anos:.0f}%, mín {min_anos_pos:.0f}%)"),
    ]
    falhas = 0
    for nome, ok, detalhe in gates:
        print(f"   {'✓' if ok else '✗'} {nome:<16} {detalhe}")
        falhas += not ok
    veredito = ("APROVADA" if falhas == 0 else
                "ATENÇÃO (1 gate falhou)" if falhas == 1 else
                f"REPROVADA ({falhas} gates falharam)")
    print("\n" + "─" * 78)
    print(f" VEREDITO: {veredito}")
    print(" Lembrete: aprovada aqui = pode seguir pro dry-run. Dinheiro real")
    print(" só depois do checklist do README — regra inegociável do projeto.")
    print("═" * 78)


if __name__ == "__main__":
    main()
