# ═══════════════════════════════════════════════════════════════════
#  ESTRATÉGIA DE EXEMPLO — cruzamento de médias (EMA rápida × EMA lenta)
#
#  Isto NÃO é uma estratégia real do projeto. É um cruzamento de médias
#  de manual, aqui só pra deixar o pipeline concreto e rodável: gerar um
#  backtest do freqtrade que o analysis/harness.py e o analysis/risco.py
#  possam ler e julgar. As estratégias reais ficam fora deste repositório.
#
#  Rodar:
#    freqtrade backtesting --strategy CruzamentoEMA \
#        --timerange 20230101- --timeframe 4h
#  Depois:
#    python analysis/harness.py    → régua de validação no zip gerado
#    python analysis/risco.py      → analytics de risco no mesmo zip
# ═══════════════════════════════════════════════════════════════════
import talib.abstract as ta
from pandas import DataFrame

import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.strategy import IStrategy


class CruzamentoEMA(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False

    # saída é pela regra de cruzamento; ROI/stop são redes de segurança
    minimal_roi = {"0": 100}
    stoploss = -0.10
    trailing_stop = False
    startup_candle_count = 200

    EMA_RAPIDA = 20
    EMA_LENTA = 50

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_rapida"] = ta.EMA(dataframe, timeperiod=self.EMA_RAPIDA)
        dataframe["ema_lenta"] = ta.EMA(dataframe, timeperiod=self.EMA_LENTA)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cond = (
            qtpylib.crossed_above(dataframe["ema_rapida"], dataframe["ema_lenta"])
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[cond, ["enter_long", "enter_tag"]] = (1, "ema_cross")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cond = qtpylib.crossed_below(dataframe["ema_rapida"], dataframe["ema_lenta"])
        dataframe.loc[cond, ["exit_long", "exit_tag"]] = (1, "ema_cross_down")
        return dataframe
