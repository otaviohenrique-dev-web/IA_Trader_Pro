"""
Lógica do modelo em PRODUÇÃO (perfil 4H, long-only, sem volume). Cópia fiel do laboratório (mf4h.py + mfeatures.py),
mantida aqui porque o laboratório não vai para o repositório. Qualquer alteração precisa ser espelhada lá e
revalidada com o teste de paridade (ver README).
"""
import numpy as np
import pandas as pd
import pandas_ta_classic as ta
from numpy.lib.stride_tricks import sliding_window_view

H4 = 4 * 3_600_000
DAY = 24 * 3_600_000

ASSETS = ["BTC", "ETH", "BNB", "XRP"]
FEATURES = [
    "ret1", "ret6", "ret18", "ret42", "atr_pct", "rsi", "bb_pband", "bb_width", "adx",
    "dist_ema50", "dist_ema200", "dist_d50", "dist_d200", "dd30",
    "hour_sin", "hour_cos", "btc_ret6", "btc_dist200", "rel_str6",
]
LAGS = 6
K_SL, RR = 1.5, 2.0
S_MIN, S_MAX = 0.012, 0.08
HOLD = 18                       # velas de 4h (3 dias)
COST = 0.0005 + 0.0001          # taxa + slippage por lado
MIN_BARS = 3000                 # histórico de 4h por ativo (~500 dias): desvio de dist_d200 vs treino cai a 0,018 desvio-padrão
# regras do portfólio (idênticas ao simulador do laboratório)
CFG = dict(max_pos=3, max_same_dir=2, max_lev_pos=1.0, max_lev_total=2.0, cooldown=1, max_trades_day=4,
           daily_loss=-0.03, breaker_1=0.06, breaker_n=0.09, breaker_lb=3, breaker_bars=2)


def stop_pct(atr_pct):
    return np.clip(K_SL * np.asarray(atr_pct, dtype=np.float64), S_MIN, S_MAX)


def expected_value(p_win, p_loss, stop):
    """Ganho esperado em múltiplos de risco (R), já com o custo de entrada e saída."""
    return RR * p_win - p_loss - 2 * COST / stop


def asset_features(df: pd.DataFrame, btc: pd.DataFrame | None = None) -> pd.DataFrame:
    """df: velas de 4h FECHADAS (timestamp = abertura, ms)."""
    df = df.sort_values("timestamp").reset_index(drop=True).copy()
    c, h, l = df["close"], df["high"], df["low"]
    out = pd.DataFrame({"timestamp": df["timestamp"].astype("int64")})
    out["ret1"] = np.log(c / c.shift(1)) * 100
    out["ret6"] = np.log(c / c.shift(6)) * 100
    out["ret18"] = np.log(c / c.shift(18)) * 100
    out["ret42"] = np.log(c / c.shift(42)) * 100
    out["atr_pct"] = ta.atr(h, l, c, length=14) / c
    out["rsi"] = ta.rsi(c, length=14) / 100.0
    bb = ta.bbands(c, length=20, std=2)
    up = [x for x in bb.columns if x.startswith("BBU")][0]
    lo = [x for x in bb.columns if x.startswith("BBL")][0]
    wd = [x for x in bb.columns if x.startswith("BBB")][0]
    out["bb_pband"] = (c - bb[lo]) / (bb[up] - bb[lo])
    out["bb_width"] = bb[wd]
    out["adx"] = ta.adx(h, l, c, length=14)["ADX_14"] / 100.0
    e50, e200 = ta.ema(c, length=50), ta.ema(c, length=200)
    out["dist_ema50"] = (c - e50) / e50 * 100
    out["dist_ema200"] = (c - e200) / e200 * 100
    out["dd30"] = (c / c.rolling(180).max() - 1) * 100

    # macro diário: só velas diárias FECHADAS (6 velas de 4h completas)
    gd = df["timestamp"] // DAY
    ag = df.groupby(gd).agg(close=("close", "last"), n=("close", "size"))
    ag = ag[ag["n"] == 6].copy()
    ag["e50"], ag["e200"] = ta.ema(ag["close"], length=50), ta.ema(ag["close"], length=200)
    ag["avail"] = (ag.index.to_numpy() + 1) * DAY
    macro = ag.dropna(subset=["e50", "e200"])[["avail", "e50", "e200"]]
    left = pd.DataFrame({"t_close": df["timestamp"] + H4, "i": np.arange(len(df))})
    mm = pd.merge_asof(left, macro, left_on="t_close", right_on="avail", direction="backward").sort_values("i")
    out["dist_d50"] = (c.to_numpy() - mm["e50"].to_numpy()) / mm["e50"].to_numpy() * 100
    out["dist_d200"] = (c.to_numpy() - mm["e200"].to_numpy()) / mm["e200"].to_numpy() * 100

    hr = ((df["timestamp"] + H4) // H4) % 6
    out["hour_sin"], out["hour_cos"] = np.sin(2 * np.pi * hr / 6), np.cos(2 * np.pi * hr / 6)

    if btc is None:
        out["btc_ret6"], out["btc_dist200"] = out["ret6"], out["dist_ema200"]
    else:
        ctx = btc[["timestamp", "ret6", "dist_ema200"]].rename(columns={"ret6": "btc_ret6", "dist_ema200": "btc_dist200"})
        out = out.merge(ctx, on="timestamp", how="left")
    out["rel_str6"] = out["ret6"] - out["btc_ret6"]
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = df[col].to_numpy()
    return out


def features_for_all(bars: dict) -> dict:
    """bars: {ativo: DataFrame de velas 4h fechadas}. O BTC é calculado primeiro (contexto das demais)."""
    btc_f = asset_features(bars["BTC"])
    return {a: (btc_f if a == "BTC" else asset_features(bars[a], btc_f)) for a in bars}


def normalize(df, stats):
    cols = [(df[c].to_numpy(np.float64) - stats[c][0]) / (stats[c][1] + 1e-8) for c in FEATURES]
    return np.clip(np.stack(cols, 1), -5, 5).astype(np.float32)


def stack_lags(Xn, lags=LAGS):
    """(N,F) -> (N, lags*F); as primeiras lags-1 linhas ficam NaN (sem histórico)."""
    n, f = Xn.shape
    win = sliding_window_view(Xn, (lags, f)).reshape(n - lags + 1, lags * f)
    return np.vstack([np.full((lags - 1, lags * f), np.nan, np.float32), win])
