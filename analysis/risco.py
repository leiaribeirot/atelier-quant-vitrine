# ═══════════════════════════════════════════════════════════════════
#  NÍVEL 3 — MÓDULO DE RISCO QUANTIFICADO
#
#  Lê os trades de um backtest do freqtrade (zip) ou do banco de
#  dry-run e responde as perguntas de risco que importam antes de
#  colocar capital:
#
#    · expectância por trade (% e em R)
#    · R-múltiplos: distribuição dos ganhos/perdas em unidades de risco
#    · payoff, profit factor, win rate — por setup (enter_tag),
#      por par, por ano e por motivo de saída
#    · drawdown máximo realizado da curva
#    · sizing por risco: Kelly, meio-Kelly e tabela de contratos
#      (risco fixo por trade em R$)
#
#  Uso:
#    python analysis/risco.py                     → zip mais recente
#    python analysis/risco.py <arquivo.zip>      → zip específico
#    python analysis/risco.py --dryrun           → banco do dry-run futuros
#    python analysis/risco.py --capital 10000 --risco-pct 1 --stop-pts 6
#                                                → tabela de sizing
# ═══════════════════════════════════════════════════════════════════
import json
import math
import sys
import zipfile
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

RAIZ = Path(__file__).resolve().parent.parent
BT_DIR = RAIZ / "user_data" / "backtest_results"

# Especificações oficiais dos minicontratos B3 (públicas):
#   mini dólar: 1 ponto = R$10,00 · tick (variação mínima) = 0,5 ponto
#   mini índice: 1 ponto = R$0,20  · tick (variação mínima) = 5 pontos
# Cripto (perp) não tem "ponto": risco = stake × stop%, sizing é pela stake.
CONTRATOS = {
    "mini dólar": {"ponto": 10.0, "tick_pts": 0.5},
    "mini índice": {"ponto": 0.20, "tick_pts": 5.0},
}


def _arg(flag, default=None, cast=str):
    if flag in sys.argv:
        return cast(sys.argv[sys.argv.index(flag) + 1])
    return default


def carregar_trades_zip(caminho: Path | None = None) -> tuple[pd.DataFrame, str]:
    """Extrai o DataFrame de trades de um zip de backtest do freqtrade."""
    if caminho is None:
        zips = sorted(BT_DIR.glob("backtest-result-*.zip"))
        if not zips:
            sys.exit("✗ nenhum backtest em user_data/backtest_results")
        caminho = zips[-1]
    with zipfile.ZipFile(caminho) as z:
        alvo = next(n for n in z.namelist()
                    if n.endswith(".json") and not n.endswith("_config.json")
                    and "market_change" not in n)
        dados = json.loads(z.read(alvo))
    estrategias = dados.get("strategy", {})
    nome, corpo = next(iter(estrategias.items()))
    df = pd.DataFrame(corpo["trades"])
    df["open_date"] = pd.to_datetime(df["open_date"], utc=True)
    df["close_date"] = pd.to_datetime(df["close_date"], utc=True)
    return df, f"{nome} · {caminho.name}"


def carregar_trades_dryrun() -> tuple[pd.DataFrame, str]:
    import sqlite3
    db = RAIZ / "user_data" / "tradesv3.futures-dryrun.sqlite"
    con = sqlite3.connect(db)
    df = pd.read_sql(
        "select pair, enter_tag, exit_reason, is_short, open_date, close_date, "
        "close_profit as profit_ratio, close_profit_abs as profit_abs "
        "from trades where is_open=0", con)
    if df.empty:
        sys.exit("✗ dry-run ainda sem trades fechados")
    df["open_date"] = pd.to_datetime(df["open_date"], utc=True)
    df["close_date"] = pd.to_datetime(df["close_date"], utc=True)
    return df, f"dry-run futuros · {db.name}"


def metricas(df: pd.DataFrame) -> dict:
    ganhos = df.loc[df["profit_abs"] > 0, "profit_abs"]
    perdas = df.loc[df["profit_abs"] <= 0, "profit_abs"]
    n = len(df)
    win = len(ganhos) / n if n else 0
    ganho_medio = ganhos.mean() if len(ganhos) else 0.0
    perda_media = abs(perdas.mean()) if len(perdas) else 0.0
    payoff = ganho_medio / perda_media if perda_media else float("inf")
    pf = ganhos.sum() / abs(perdas.sum()) if len(perdas) and perdas.sum() != 0 else float("inf")
    # R realizado = perda média (proxy do risco por trade efetivamente pago)
    r_unit = perda_media
    exp_abs = df["profit_abs"].mean() if n else 0.0
    exp_r = exp_abs / r_unit if r_unit else float("nan")
    exp_pct = df["profit_ratio"].mean() * 100 if n else 0.0
    # drawdown da curva realizada (ordem cronológica de fechamento)
    curva = df.sort_values("close_date")["profit_abs"].cumsum()
    dd = (curva - curva.cummax()).min() if n else 0.0
    return dict(n=n, win=win * 100, payoff=payoff, pf=pf, exp_abs=exp_abs,
                exp_r=exp_r, exp_pct=exp_pct, r_unit=r_unit, pnl=df["profit_abs"].sum(),
                dd=dd)


def linha(nome: str, m: dict) -> str:
    payoff = f"{m['payoff']:.2f}" if m["payoff"] != float("inf") else "∞"
    pf = f"{m['pf']:.2f}" if m["pf"] != float("inf") else "∞"
    return (f"   {nome:<28} n={m['n']:<5} win={m['win']:5.1f}%  payoff={payoff:<5} "
            f"PF={pf:<5} exp={m['exp_abs']:+7.2f}/trade ({m['exp_r']:+.2f}R)")


def kelly(win_pct: float, payoff: float) -> float:
    p, b = win_pct / 100, payoff
    if b <= 0 or b == float("inf"):
        return 0.0
    return max(0.0, p - (1 - p) / b)


def tabela_sizing(capital: float, risco_pct: float, stop_pts: float, stop_pct: float):
    risco_rs = capital * risco_pct / 100
    print(f"\n SIZING POR RISCO — capital R${capital:,.0f} · risco {risco_pct}%/trade"
          f" = R${risco_rs:,.2f}")
    print(f"   B3 (stop pedido: {stop_pts:g} pts — ajustado ao tick de cada contrato):")
    for ativo, spec in CONTRATOS.items():
        tick = spec["tick_pts"]
        # stop tradável = arredonda PRA CIMA no múltiplo do tick (conservador)
        stop_real = max(tick, math.ceil(stop_pts / tick) * tick)
        custo_stop = stop_real * spec["ponto"]
        contratos = int(risco_rs // custo_stop) if custo_stop else 0
        print(f"     {ativo}: ponto R${spec['ponto']:.2f} · tick {tick:g} pts (R${tick * spec['ponto']:.2f})"
              f" · stop tradável {stop_real:g} pts = R${custo_stop:,.2f}/contrato"
              f" → máx {contratos} contrato(s)")
    stake = risco_rs / (stop_pct / 100) if stop_pct else 0
    print(f"   Cripto (perp — sem ponto; risco = stake × stop%):")
    print(f"     stop {stop_pct:g}% → stake máxima R${stake:,.2f} p/ arriscar R${risco_rs:,.2f}")


def main():
    if "--dryrun" in sys.argv:
        df, origem = carregar_trades_dryrun()
    else:
        arqs = [a for a in sys.argv[1:] if a.endswith(".zip")]
        df, origem = carregar_trades_zip(Path(arqs[0]) if arqs else None)

    sem = _arg("--sem")  # ex.: --sem BTC → exclui pares que contenham "BTC"
    if sem:
        df = df[~df["pair"].str.contains(sem, case=False)].reset_index(drop=True)
        origem += f" · SEM {sem}"

    m = metricas(df)
    print("═" * 78)
    print(f" MÓDULO DE RISCO — {origem}")
    print("═" * 78)
    print(linha("GERAL", m))
    print(f"   PnL total {m['pnl']:+.2f} · DD máx {m['dd']:.2f} · "
          f"1R (perda média) = {m['r_unit']:.2f}")

    k = kelly(m["win"], m["payoff"])
    print(f"\n KELLY: fração ótima {k * 100:.1f}% do capital por trade"
          f" → recomendado meio-Kelly {k * 50:.1f}% · quarto-Kelly {k * 25:.1f}%")
    if k == 0:
        print("   (Kelly zero = sem edge líquido nesses trades — sizing não conserta expectância negativa)")

    for coluna, titulo in [("enter_tag", "POR SETUP (enter_tag)"), ("pair", "POR PAR"),
                           ("exit_reason", "POR SAÍDA")]:
        if coluna in df.columns and df[coluna].notna().any():
            print(f"\n {titulo}")
            for valor, grupo in df.groupby(df[coluna].fillna("—")):
                print(linha(str(valor)[:28], metricas(grupo)))

    print("\n POR ANO")
    for ano, grupo in df.groupby(df["close_date"].dt.year):
        print(linha(str(ano), metricas(grupo)))

    capital = _arg("--capital", 10_000.0, float)
    risco_pct = _arg("--risco-pct", 1.0, float)
    stop_pts = _arg("--stop-pts", 6.0, float)
    stop_pct = _arg("--stop-pct", 1.5, float)
    tabela_sizing(capital, risco_pct, stop_pts, stop_pct)
    print("═" * 78)


if __name__ == "__main__":
    main()
