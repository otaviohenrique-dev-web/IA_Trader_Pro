import pandas as pd
import numpy as np
import pandas_ta_classic as ta
import os
from sb3_contrib import RecurrentPPO
from envs.trading_env import BitcoinTradingEnv

# --- CONFIGURAÇÕES DO DOJO ---
# Lembre-se de baixar o CSV do Dashboard e salvar na pasta data com este nome:
DADOS_BAIXADOS = "data/mercado_real_20260313.csv"

# 👇 O treino agora parte da Gen 3 (a que está no ar)!
MODELO_ATUAL = "models/sniper_pro_gen_3.zip" 

# 🎯 Ajuste Fino: 10.000 passos. 
# Ideal para não "decorar" o dia (Overfitting) e aprender a nova tendência.
PASSOS_DE_TREINO = 10000 

def preparar_dados(caminho_csv):
    print("🧹 Engenharia de Features nos dados reais...")
    df = pd.read_csv(caminho_csv)
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
    df['rsi'] = ta.rsi(df['close'], length=14)
    df['rsi_slope'] = df['rsi'].diff()
    
    macd = ta.macd(df['close'])
    macd_col = [c for c in macd.columns if c.startswith('MACDh') or c.startswith('MACDH')][0]
    df['macd_diff'] = macd[macd_col]
    
    bb = ta.bbands(df['close'], length=20, std=2)
    upper_col, lower_col, width_col = [c for c in bb.columns if c.startswith('BBU')][0], [c for c in bb.columns if c.startswith('BBL')][0], [c for c in bb.columns if c.startswith('BBB')][0]
    df['bb_pband'] = (df['close'] - bb[lower_col]) / (bb[upper_col] - bb[lower_col])
    df['bb_width'] = bb[width_col]
    
    df['ema50'] = ta.ema(df['close'], length=50)
    df['ema200'] = ta.ema(df['close'], length=200)
    df['dist_ema50'] = (df['close'] - df['ema50']) / df['ema50']
    df['dist_ema200'] = (df['close'] - df['ema200']) / df['ema200']
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['atr_pct'] = df['atr'] / df['close']
    
    return df.dropna().copy()

if __name__ == "__main__":
    print("🥋 BEM-VINDO AO DOJO DE TREINAMENTO INSTITUCIONAL 🥋")
    
    if not os.path.exists(DADOS_BAIXADOS):
        print(f"❌ Arquivo {DADOS_BAIXADOS} não encontrado. Exporte da Vercel primeiro!")
        exit()

    df_treino = preparar_dados(DADOS_BAIXADOS)
    env = BitcoinTradingEnv(df_treino)
    
    print(f"🧠 Carregando Cérebro Base: {MODELO_ATUAL}")
    model = RecurrentPPO.load(MODELO_ATUAL, env=env, device="cpu")
    
    print(f"🔥 Iniciando Treinamento com Gestão de Risco Ativada ({PASSOS_DE_TREINO} steps)...")
    model.learn(total_timesteps=PASSOS_DE_TREINO)
    
    novo_nome = "models/sniper_pro_gen_5.zip"
    model.save(novo_nome)
    print(f"🏆 Treinamento Concluído! Novo modelo salvo como: {novo_nome}")
    print(">>> Suba este arquivo no Dashboard da Vercel para injetar a Gen 5!")