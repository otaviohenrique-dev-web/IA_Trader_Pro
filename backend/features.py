"""
Fonte ÚNICA da verdade para treino (dojo), backtest e produção (server).

Tudo que precisa ser idêntico nos três lugares mora aqui:
  - cálculo dos indicadores (sem look-ahead: só velas FECHADAS)
  - normalização (estatísticas ajustadas só no treino e salvas junto do modelo)
  - custos, stop/take, cooldown e limites diários
  - regra que converte a saída da rede em posição-alvo
"""
import json
import os

import numpy as np
import pandas as pd
import pandas_ta_classic as ta

FEATURE_VERSION = 2
FEATURE_COLS = [
    'log_ret', 'atr_pct', 'rsi', 'bb_pband', 'bb_width_pct',
    'dist_ema50_4h', 'dist_ema200_4h', 'dist_vwap', 'obv_slope_pct', 'adx',
]
# + posição atual (-1/0/1) + PnL não realizado normalizado pelo stop
OBS_DIM = len(FEATURE_COLS) + 2

M15_MS = 15 * 60 * 1000
H4_MS = 4 * 60 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000

# --- Custos e regras de risco (iguais no treino, no backtest e na produção) ---
# 0.05% por lado = taxa taker de perpétuos; a taxa de spot varejo (0.10%+) é pior.
FEE_RATE = float(os.environ.get("TRADING_FEE", 0.0005))
SLIPPAGE = float(os.environ.get("TRADING_SLIPPAGE", 0.0001))
COST_PER_SIDE = FEE_RATE + SLIPPAGE
STOP_LOSS_PCT = 0.010
TAKE_PROFIT_PCT = 0.020
COOLDOWN_BARS = 4            # 1h sem reabrir depois de fechar
MAX_TRADES_PER_DAY = 6       # teto de aberturas por dia UTC
ACTION_TO_POS = {0: 0, 1: 1, 2: -1}


# ---------------------------------------------------------------- features
def compute_features(df15: pd.DataFrame, df4h: pd.DataFrame) -> pd.DataFrame:
    """
    df15/df4h: colunas timestamp(ms, abertura da vela), open, high, low, close, volume.
    Devem conter apenas velas FECHADAS. A EMA 4h só passa a valer quando a vela 4h fecha
    (evita o vazamento do futuro que existia ao casar pelo horário de abertura).
    """
    d4 = df4h[['timestamp', 'close']].sort_values('timestamp').reset_index(drop=True)
    d4['timestamp'] = d4['timestamp'].astype('int64')
    d4['ema50_4h'] = ta.ema(d4['close'], length=50)
    d4['ema200_4h'] = ta.ema(d4['close'], length=200)
    d4 = d4.dropna(subset=['ema50_4h', 'ema200_4h'])
    d4['avail_ts'] = d4['timestamp'] + H4_MS

    df = df15.sort_values('timestamp').reset_index(drop=True).copy()
    df['timestamp'] = df['timestamp'].astype('int64')
    df['avail_ts'] = df['timestamp'] + M15_MS   # decisão tomada no fechamento da vela
    df = pd.merge_asof(df, d4[['avail_ts', 'ema50_4h', 'ema200_4h']], on='avail_ts', direction='backward')
    df = df.drop(columns=['avail_ts'])

    close, high, low, vol = df['close'], df['high'], df['low'], df['volume']
    df['dist_ema50_4h'] = (close - df['ema50_4h']) / df['ema50_4h'] * 100.0
    df['dist_ema200_4h'] = (close - df['ema200_4h']) / df['ema200_4h'] * 100.0
    df['log_ret'] = np.log(close / close.shift(1)) * 100.0
    df['rsi'] = ta.rsi(close, length=14) / 100.0

    bb = ta.bbands(close, length=20, std=2)
    up = [c for c in bb.columns if c.startswith('BBU')][0]
    lo = [c for c in bb.columns if c.startswith('BBL')][0]
    wd = [c for c in bb.columns if c.startswith('BBB')][0]
    df['bb_pband'] = (close - bb[lo]) / (bb[up] - bb[lo])
    df['bb_width'] = bb[wd]
    df['bb_width_pct'] = bb[wd] / close

    df['atr_pct'] = ta.atr(high, low, close, length=14) / close

    # VWAP diário (reinicia 00:00 UTC)
    day = df['timestamp'] // DAY_MS
    tp_vol = ((high + low + close) / 3.0) * vol
    df['vwap'] = tp_vol.groupby(day).cumsum() / vol.groupby(day).cumsum()
    df['dist_vwap'] = (close - df['vwap']) / df['vwap'] * 100.0

    # OBV relativo ao volume recente. O OBV cru depende de onde a série começa
    # (24 meses no treino x 250 velas ao vivo), então não era comparável.
    obv = ta.obv(close, vol)
    obv_ema = ta.ema(obv, length=10)
    df['obv_slope_pct'] = np.clip((obv - obv_ema) / (vol.rolling(20).sum() + 1e-8), -2.0, 2.0)

    df['adx'] = ta.adx(high, low, close, length=14)['ADX_14'] / 100.0

    return df.dropna(subset=FEATURE_COLS + ['ema50_4h', 'ema200_4h']).reset_index(drop=True)


def fit_stats(df: pd.DataFrame) -> dict:
    return {c: [float(df[c].mean()), float(df[c].std())] for c in FEATURE_COLS}


def normalize(df: pd.DataFrame, stats: dict) -> np.ndarray:
    cols = [(df[c].to_numpy(dtype=np.float64) - stats[c][0]) / (stats[c][1] + 1e-8) for c in FEATURE_COLS]
    return np.clip(np.stack(cols, axis=1), -5, 5).astype(np.float32)


def save_stats(stats: dict, path: str) -> None:
    with open(path, 'w') as f:
        json.dump({"version": FEATURE_VERSION, "features": stats}, f, indent=1)


def load_stats(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    if data.get("version") != FEATURE_VERSION:
        raise ValueError(f"stats v{data.get('version')} incompatível com features v{FEATURE_VERSION}")
    return data["features"]


def stats_path_for(model_path: str) -> str:
    return os.path.splitext(model_path)[0] + ".stats.json"


def build_dataset(path15: str, path4h: str) -> pd.DataFrame:
    return compute_features(pd.read_csv(path15), pd.read_csv(path4h))


def split_train_test(df: pd.DataFrame, test_frac: float = 0.2):
    """Corte temporal (nunca embaralhar série financeira)."""
    cut = int(len(df) * (1.0 - test_frac))
    return df.iloc[:cut].reset_index(drop=True), df.iloc[cut:].reset_index(drop=True)


# ------------------------------------------------------------------ regras
def softmax(x) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    e = np.exp(x - x.max())
    return e / e.sum()


def pick_action(logits, position: int, conf_threshold: float = 0.0):
    """
    Escolhe a ação mais provável. Abrir posição nova exige confiança >= limiar;
    com confiança baixa a rede apenas mantém o que já está (fechar nunca é bloqueado).
    """
    p = softmax(logits)
    a = int(p.argmax())
    cur = {0: 0, 1: 1, -1: 2}[position]
    if a != 0 and a != cur and p[a] < conf_threshold:
        a = cur
    return a, float(p[a])


def resolve_target(position: int, action: int, cooldown: int, trades_today: int) -> int:
    """Posição-alvo após aplicar cooldown e teto diário. Sem inversão direta (long->short)."""
    want = ACTION_TO_POS[action]
    if want == position:
        return position
    if position != 0:
        return 0
    if cooldown > 0 or trades_today >= MAX_TRADES_PER_DAY:
        return 0
    return want
