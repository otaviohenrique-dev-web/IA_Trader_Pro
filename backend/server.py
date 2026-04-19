import asyncio
import json
import time
import shutil
from datetime import datetime
import pandas as pd
import numpy as np
import pandas_ta_classic as ta
import ccxt.async_support as ccxt
from contextlib import asynccontextmanager
import os
import gc
import math
import copy
import torch
from sb3_contrib import RecurrentPPO
import warnings
import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Header
from fastapi.responses import FileResponse
from starlette.websockets import WebSocketState
warnings.filterwarnings("ignore")

# Trava o PyTorch para não estrangular a CPU do Render
torch.set_num_threads(1)

# --- CONFIGURAÇÕES DO SISTEMA ---
SYMBOL = 'BTC/USDT'
TIMEFRAME = '15m' 
MODEL_PATH = "models/sniper_pro_gen_6.zip" 
DATA_PATH = "data/live_market_data.csv"
START_TIME = time.time()
FEE_RATE = 0.0010 
STOP_LOSS_PCT = -0.010    
TAKE_PROFIT_PCT = +0.020 

# 1. Tenta carregar o arquivo .env que está na mesma pasta (backend/.env)
load_dotenv()

# 2. Puxa as variáveis (CryptoCompare: notícias BTC; Gemini: Sentinela)
CRYPTOCOMPARE_KEY = os.environ.get("CRYPTOCOMPARE_API_KEY") or os.environ.get("CRYPTOCOMPARE_KEY") or ""
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD")

# 3. Avisos de configuração
if not GEMINI_KEY:
    print(">>> ⚠️ ALERTA CRÍTICO: GEMINI_API_KEY não encontrada no ambiente ou no .env!")
    print(">>> O Sentinela (análise de risco por LLM) pode falhar.")
if not CRYPTOCOMPARE_KEY:
    print(">>> ⚠️ AVISO: CRYPTOCOMPARE_API_KEY não encontrada. Cota de notícias pode ser menor.")


# --- VARIÁVEIS GLOBAIS DE ESTADO ---
balance = 100.00
position = 0 
entry_price = 0.0
wins = 0
losses = 0
DAILY_LOSS_LIMIT = -0.05  
session_start_balance = 100.0  
kill_switch_active = False
max_profit_pct = 0.0  

# Variáveis de Controle de Fluxo
startup_phase = True
startup_timer = 0
warming_up = True 
warmup_counter = 0
consecutive_signals = 0 
last_signal = 0   
last_entry_ts = 0


def rotulo_risco_analista(codigo: str) -> str:
    """Rótulos em português para o painel (códigos internos seguem inglês por compatibilidade com o Gemini)."""
    return {
        "SAFE": "seguro",
        "CAUTION": "atenção",
        "DANGER": "perigo",
        "MODO TÉCNICO": "modo técnico",
    }.get(codigo, codigo)


state = {
    "asset": SYMBOL,
    "is_online": True,
    "in_position": False,
    "entry_price": 0.0,
    "current_position": 0,
    "balance": balance, 
    "status": "Reiniciando o sistema...",
    "uptime": "00:00:00",
    "last_candle": {},
    "chart_data": [],
    "markers": [],
    "order_book": [], 
    "adaptation": {
        "generation": 1,
        "learning_state": "SISTEMA REINICIADO",
        "initial_win_rate": 0.0,
        "current_win_rate": 0.0,
        "wins": 0,      
        "losses": 0     
    },
    "news_agent": {
        "status": "INICIALIZANDO...",
        "sentiment_score": 0.0,
        "risk_level": "BAIXO",
        "last_headlines": []
    },
    "performance": {
        "loop_avg_ms": 0.0,
        "loop_max_ms": 0.0,
        "healthy": True,
        "status": "Inicializando..."
    }
}

model = None
exchange = None
lstm_states = None 
episode_starts = np.ones((1,), dtype=bool)
feature_cols = ['log_ret', 'rsi', 'rsi_slope', 'macd_diff', 'bb_pband', 'bb_width', 'dist_ema50', 'dist_ema200', 'atr_pct']
last_analysis_time = 0
cached_analysis = {"score": 50, "status": "SAFE", "reason": "Sincronizando com a rede neural (cache)..."}

# --- FUNÇÕES DE SUPORTE ---

def run_startup_backtest(df_clean, model_instance):
    print(">>> 🔬 EXECUTANDO BACKTEST DE REBOOT...")
    test_wins, test_losses = 0, 0
    sim_pos, sim_entry = 0, 0.0
    temp_lstm, temp_ep = None, np.ones((1,), dtype=bool)
    
    test_df = df_clean.tail(300)
    for i in range(len(test_df)):
        try:
            obs = test_df[feature_cols].iloc[i].values.astype(np.float32)
            action, temp_lstm = model_instance.predict(obs, state=temp_lstm, episode_start=temp_ep, deterministic=True)
            temp_ep = np.zeros((1,), dtype=bool)
            
            act_idx = action.item()
            target_pos = 1 if act_idx == 1 else (-1 if act_idx == 2 else 0)
            
            if target_pos != sim_pos:
                if sim_pos != 0:
                    chg = (test_df.iloc[i]['close'] - sim_entry) / sim_entry
                    pnl = chg if sim_pos == 1 else -chg
                    if pnl > 0: test_wins += 1
                    else: test_losses += 1
                if target_pos != 0: sim_entry = test_df.iloc[i]['close']
                sim_pos = target_pos
        except: continue
            
    tot = test_wins + test_losses
    return round((test_wins/tot)*100, 1) if tot > 0 else 50.0

def load_brain(path=MODEL_PATH):
    """Carrega modelo de forma síncrona com otimização agressiva de RAM."""
    global model
    try:
        if os.path.exists(path):
            print(f">>> 🧠 Carregando modelo: {path}")
            # Limpa RAM antes de carregar
            gc.collect()

            # Carrega o modelo forçando CPU
            model = RecurrentPPO.load(path, device="cpu")

            # Limpa RAM após carregar (sb3 deixa resíduos)
            gc.collect()
            print(f">>> ✅ Modelo carregado com sucesso")
        else:
            print(f"⚠️ Arquivo não encontrado: {path}")
            model = None
    except Exception as e:
        print(f"❌ Erro ao carregar modelo: {type(e).__name__}: {e}")
        model = None
    finally:
        gc.collect()


def get_uptime():
    seconds = int(time.time() - START_TIME)
    return time.strftime('%H:%M:%S', time.gmtime(seconds))


# --- INICIALIZAÇÃO DO CLIENTE (SDK ATUALIZADO) ---
from google import genai
# O cliente puxa a chave direto ou podemos passar explicitamente
try:
    if GEMINI_KEY:
        client = genai.Client(api_key=GEMINI_KEY)
    else:
        print(">>> ⚠️ GEMINI_KEY vazia - Tentando carregamento automático...")
        client = genai.Client()  # Tenta usar variável de ambiente padrão
except Exception as e:
    print(f">>> ❌ Erro ao inicializar cliente Genai: {e}")
    print(">>> ⚠️ Agente de análise de risco desabilitado")
    client = None


# --- AGENTE DE NOTÍCIAS (IA SENTINELA) ---
_NEWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


async def _cryptocompare_news_titles(session, query: str, headers: dict) -> list:
    """query = parte após '?' (ex.: categories=BTC&lang=PT). Retorna lista de títulos, [] ou ['API_ESGOTADA']."""
    key_q = f"&api_key={CRYPTOCOMPARE_KEY}" if CRYPTOCOMPARE_KEY else ""
    url = f"https://min-api.cryptocompare.com/data/v2/news/?{query}{key_q}"
    async with session.get(url, headers=headers, timeout=15) as resp:
        if resp.status == 200:
            data = await resp.json()
            results = data.get("Data", [])
            if results:
                return [f" {p['title']} •" for p in results[:10]]
            return []
        if resp.status == 429:
            return ["API_ESGOTADA"]
        print(f">>> ❌ Erro na API CryptoCompare (Status {resp.status}).")
        return []


async def fetch_btc_news():
    """Manchetes BTC: prioriza português (lang=PT); se vazio, tenta inglês."""
    headers = {"User-Agent": _NEWS_UA}
    try:
        async with aiohttp.ClientSession() as session:
            titles = await _cryptocompare_news_titles(session, "categories=BTC&lang=PT", headers)
            if titles and titles[0] == "API_ESGOTADA":
                return titles
            if not titles:
                titles = await _cryptocompare_news_titles(session, "categories=BTC&lang=EN", headers)
            return titles
    except Exception as e:
        print(f">>> ❌ Falha na conexão de notícias: {e}")
        return []

# (A função analyze_sentiment_with_llm CONTINUA INTACTA AQUI NO MEIO)

async def analyst_market_loop():
    print(">>> 🕵️ IA_ANALISTA: Iniciando Sentinela de Mercado...")
    
    # DECLARAÇÃO GLOBAL AQUI NO TOPO (Evita o SyntaxError)
    global kill_switch_active
    
    headers = {"User-Agent": _NEWS_UA}
    
    print(">>> ✅ IA_ANALISTA: Pronto para análise de notícias")
    
    while True:
        try:
            headlines = await fetch_btc_news()

            # Fallback: feed geral CryptoCompare (PT, depois EN se vazio)
            if not headlines:
                async with aiohttp.ClientSession() as session:
                    for q in ("lang=PT", "lang=EN"):
                        headlines = await _cryptocompare_news_titles(session, q, headers)
                        if headlines:
                            break

            # --- CIRCUITO DE PROTEÇÃO CONTRA COTA ESGOTADA (após BTC + fallback) ---
            if headlines and headlines[0] == "API_ESGOTADA":
                print(">>> ⚠️ API de Notícias Esgotada. Entrando em MODO 100% TÉCNICO.")
                state["news_agent"].update({
                    "status": "SAFE",
                    "sentiment_score": 0.0,
                    "risk_level": "MODO TÉCNICO",
                    "last_headlines": ["⚠️ ALERTA: API DE NOTÍCIAS ESGOTADA - TRABALHANDO 100% VIA GRÁFICOS (TA) •"]
                })
                kill_switch_active = False
                await asyncio.sleep(3600)
                continue

            analysis = await analyze_sentiment_with_llm(headlines)
            
            state["news_agent"].update({
                "status": analysis["status"],
                "sentiment_score": analysis["score"],
                "risk_level": analysis["status"],
                "last_headlines": headlines if headlines else ["SISTEMA EM MONITORAMENTO: AGUARDANDO NOVOS EVENTOS •"]
            })
            
            if analysis["status"] == "SAFE":
                kill_switch_active = False
            
            print(f">>> ✅ Analista: {analysis['status']} | Letreiro atualizado com {len(headlines)} notícias.")
            await asyncio.sleep(600) 
            
        except Exception as e:
            print(f"❌ Erro no Analista: {e}")
            await asyncio.sleep(60)

async def analyze_sentiment_with_llm(headlines):
    """Usa o modelo Gemini 3 Flash Preview calibrado para ignorar ruído."""
    
    # Puxa as variáveis globais que você já colocou no topo do arquivo
    global last_analysis_time, cached_analysis
    current_time = time.time()
    
    # ⏳ TRAVA DO CACHE: 1800 segundos = 30 minutos
    if current_time - last_analysis_time < 1800:
        print(">>> ⏳ IA em Cooldown. Retornando análise de risco do cache para economizar cota.")
        return cached_analysis

    if not headlines:
        return {"score": 0.1, "status": "SAFE", "reason": "Mercado calmo (Sem notícias)"}
    
    # 🔒 VERIFICA SE O CLIENTE GENAI ESTÁ DISPONÍVEL
    if not client:
        print(">>> ⚠️ Cliente Genai não disponível. Retornando análise segura (SAFE).")
        return {"score": 0.1, "status": "SAFE", "reason": "Cliente IA indisponível - modo técnico"}
    
    # 🧠 PROMPT CALIBRADO: Ensinando a IA a ser um trader frio, não um jornalista assustado
    prompt = f"""
    Você é um Gestor de Risco Quantitativo sênior de Bitcoin. Avalie o risco macroeconômico atual baseado nestas manchetes (em português ou inglês):
    {headlines}

    REGULAGEM DE RISCO ESTREITA (O mercado cripto é naturalmente volátil, ignore o sensacionalismo):
    - Score 0.0 a 0.45 (SAFE): Notícias de adoção, ETFs, desenvolvimentos técnicos, ou FUD genérico (ex: "analista prevê queda", oscilações normais, correções pequenas). O bot PODE operar.
    - Score 0.46 a 0.75 (CAUTION): Notícias macroeconômicas ruins REAIS (ex: aumento severo de juros do FED, inflação muito acima do esperado, hack de corretora média).
    - Score 0.76 a 1.0 (DANGER): Eventos catastróficos globais, falência de top 3 corretoras (estilo FTX), banimento em grandes potências, guerras em grande escala.

    Responda APENAS em JSON puro: {{"score": float, "status": "SAFE" ou "CAUTION" ou "DANGER", "reason": "resumo de 1 linha do sentimento geral"}}
    """
    
    try:
        response = await asyncio.to_thread(
            client.models.generate_content, 
            model="gemini-3-flash-preview", 
            contents=prompt
        )
        
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_text)
        
        # Trava de segurança extra
        score = float(data.get("score", 0.0))
        if score > 1.0: score = score / 10.0 if score <= 10.0 else 1.0
        
        # Força o status correto baseado na nossa própria regra, caso a IA erre a palavra
        if score <= 0.45:
            data["status"] = "SAFE"
        elif score <= 0.75:
            data["status"] = "CAUTION"
        else:
            data["status"] = "DANGER"
            
        data["score"] = score
        
        # 💾 SALVA O RESULTADO NO CACHE E ATUALIZA O RELÓGIO ANTES DE RETORNAR
        cached_analysis = data
        last_analysis_time = current_time
        
        return data
        
    except Exception as e:
        print(f"⚠️ Erro na análise da IA: {e}")
        # Se a cota estourar ou a API cair, ele mantém o bot rodando com o último status seguro salvo
        return cached_analysis
# --- LOOP PRINCIPAL DO TRADER (SNIPER) ---
async def sniper_loop():
    global state, exchange, lstm_states, episode_starts, balance, position, entry_price, wins, losses
    global kill_switch_active, last_entry_ts, startup_phase, startup_timer, warming_up, warmup_counter, consecutive_signals, last_signal

    print(">>> 🐍 SNIPER_LOOP: Iniciando...")
    
    try:
        exchange = ccxt.kraken({
            'enableRateLimit': True,
            'timeout': 30000
        })
        print(">>> ✅ SNIPER_LOOP: Conexão com Kraken OK")
    except Exception as e:
        print(f">>> ❌ SNIPER_LOOP: Erro ao conectar em Kraken: {type(e).__name__}: {e}")
        await asyncio.sleep(5)
        return  # Será retentado na próxima execução do lifespan

    # Marca que state está pronto
    state["status"] = "Sistema iniciando... (conectado à corretora)"
    print(f">>> ✅ SNIPER_LOOP: State inicializado: {list(state.keys())}")

    last_saved_candle_ts = 0 
    last_fetch_ts = 0

    # Reset de memórias para evitar viés de reinicialização
    lstm_states = None
    episode_starts = np.ones((1,), dtype=bool)
    consecutive_signals = 0
    last_signal = 0

   # 🚀 CORREÇÃO: Pausa o loop até que o modelo da IA esteja totalmente carregado
    while model is None:
        state["status"] = "🧠 Inicializando Rede Neural..."
        await asyncio.sleep(1)

    while True:
        try:
            # Obtém o timestamp atual no início de cada iteração
            now_ts = time.time()
            
            # 1. BUSCA DE DADOS (A cada 15s para poupar API)
            if now_ts - last_fetch_ts > 60 or last_fetch_ts == 0:
                try:
                    print(f">>> 📊 Buscando OHLCV (timeout: 15s)...")
                    ohlcv = await asyncio.wait_for(
                        exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=250),
                        timeout=15.0 # Aumentado para 15s
                    )
                    print(f">>> ✅ OHLCV recebido ({len(ohlcv)} velas)")
                    
                    # ✅ OTIMIZAÇÃO MÁXIMA: Isolando o Pandas em uma Thread
                    def process_indicators(ohlcv_data):
                        df = pd.DataFrame(ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                        df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
                        df['rsi'] = ta.rsi(df['close'], length=14)
                        df['rsi_slope'] = df['rsi'].diff()
                        
                        macd = ta.macd(df['close'])
                        if macd is not None and not macd.empty:
                            macd_col = [c for c in macd.columns if c.startswith('MACDh') or c.startswith('MACDH')][0]
                            df['macd_diff'] = macd[macd_col]
                        else:
                            df['macd_diff'] = 0.0
                        
                        bb = ta.bbands(df['close'], length=20, std=2)
                        if bb is not None and not bb.empty:
                            upper_col = [c for c in bb.columns if c.startswith('BBU')][0]
                            lower_col = [c for c in bb.columns if c.startswith('BBL')][0]
                            width_col = [c for c in bb.columns if c.startswith('BBB')][0]
                            df['bb_pband'] = (df['close'] - bb[lower_col]) / (bb[upper_col] - bb[lower_col])
                            df['bb_width'] = bb[width_col]
                        else:
                            df['bb_pband'], df['bb_width'] = 0.0, 0.0
                        
                        df['ema50'] = ta.ema(df['close'], length=50)
                        df['ema200'] = ta.ema(df['close'], length=200)
                        df['dist_ema50'] = (df['close'] - df['ema50']) / df['ema50']
                        df['dist_ema200'] = (df['close'] - df['ema200']) / df['ema200']
                        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
                        df['atr_pct'] = df['atr'] / df['close']
                        
                        return df, df.dropna().copy()
                    
                    # 🚀 A MÁGICA: Executa a matemática pesada sem travar o FastAPI
                    df, df_clean = await asyncio.to_thread(process_indicators, ohlcv)
                    
                    last_fetch_ts = now_ts
                    print(f">>> ✅ Indicadores calculados ({len(df_clean)} velas limpas)")
                    
                except asyncio.TimeoutError:
                    print(f"❌ TIMEOUT: fetch_ohlcv demorou > 10s. Pulando esta iteração.")
                    state["status"] = "⚠️ Lentidão na API - Recuperando..."
                    await asyncio.sleep(1)
                    continue
                except Exception as e:
                    print(f"❌ Erro ao buscar OHLCV ou calcular indicadores: {type(e).__name__}: {e}")
                    state["status"] = "❌ Erro conexão API"
                    await asyncio.sleep(2)
                    continue


            # 2. LÓGICA DE DECISÃO E PnL
            if model and 'df_clean' in locals() and len(df_clean) > 0:
                last_row = df_clean.iloc[-1]
                current_price = float(last_row['close'])
                target_pos = position 

                # --- CÁLCULO DE PnL FLUTUANTE (Dinamismo da Carteira) ---
                floating_pnl = 0.0
                if position != 0:
                    change_pct = (current_price - entry_price) / entry_price if position == 1 else (entry_price - current_price) / entry_price
                    floating_pnl = balance * change_pct
                
                state["floating_pnl"] = floating_pnl
                state["display_balance"] = balance + floating_pnl

                # Estados Iniciais
                if startup_phase:
                    state["status"] = "Reinício: executando backtest..."
                    startup_timer += 1
                    if startup_timer == 1:
                        # OTIMIZAÇÃO: Roda o backtest pesado em uma thread paralela
                        res = await asyncio.to_thread(run_startup_backtest, df_clean, model)
                        state["adaptation"]["initial_win_rate"] = res
                        state["adaptation"]["current_win_rate"] = res
                    if startup_timer > 2: 
                        startup_phase = False
                        lstm_states = None # Limpa memória do backtest

                elif warming_up:
                    warmup_counter += 1
                    state["status"] = f"🛡️ AQUECIMENTO... ({warmup_counter}/15)"
                    if warmup_counter >= 15:
                        warming_up = False
                        state["status"] = "📊 AGUARDANDO SINAL..."

                else:
                    # IA PREDIÇÃO (com timeout protetor)
                    # IA PREDIÇÃO (Execução direta, sem criar threads zumbis)
                    try:
                        obs = last_row[feature_cols].values.astype(np.float32)
                        
                        action, lstm_states = model.predict(
                            obs, 
                            state=lstm_states, 
                            episode_start=episode_starts, 
                            deterministic=True
                        )
                        
                        episode_starts = np.zeros((1,), dtype=bool)
                        act_idx = action.item()
                    except Exception as e:
                        print(f">>> [SNIPER] ❌ Erro na predição IA: {type(e).__name__}")
                        act_idx = 0
                        episode_starts = np.ones((1,), dtype=bool) # Reset LSTM em caso de falha

                    # Validação de Sinais
                    if act_idx != 0 and act_idx == last_signal: consecutive_signals += 1
                    elif act_idx != 0: consecutive_signals = 1; last_signal = act_idx
                    else: consecutive_signals = 0; last_signal = 0

                    # Lógica de Posição
                    if position != 0:
                        remaining = 900 - (int(time.time()) - last_entry_ts)
                        if remaining > 0:
                            target_pos = position
                            state["status"] = f"PROTEÇÃO: {remaining}s"
                        else:
                            state["status"] = "📊 MONITORANDO MERCADO..."
                            if act_idx == 0: target_pos = 0
                    elif position == 0:
                        is_safe = state["news_agent"]["status"] == "SAFE"
                        if not is_safe:
                            state["status"] = f"⏳ AGUARDANDO ANALISTA ({rotulo_risco_analista(state['news_agent']['status'])})"
                        elif consecutive_signals >= 3:
                            target_pos = 1 if act_idx == 1 else (-1 if act_idx == 2 else 0)
                        else:
                            state["status"] = "🔍 BUSCANDO OPORTUNIDADE..."

                # --- 3. EXECUÇÃO ÚNICA (FINANCEIRO + VISUAL) ---
                if target_pos != position:
                    
                    # 1. SE JÁ ESTÁ POSICIONADO, FECHA A POSIÇÃO PRIMEIRO
                    if position != 0:
                        pnl = (balance * ((current_price - entry_price)/entry_price)) if position == 1 else (balance * -((current_price - entry_price)/entry_price))
                        balance += (pnl - (balance * FEE_RATE))
                        
                        # [MARKER] Registro de Saída
                        state["markers"].append({
                            "time": int(last_row['timestamp'].timestamp()),
                            "position": "aboveBar",
                            "color": "#facc15", 
                            "shape": "square",
                            "text": f"SAÍDA: {'GANHO' if pnl > 0 else 'PERDA'}"
                        })
                        if len(state["markers"]) > 100: state["markers"].pop(0)
                        
                        resultado_texto = "ganho ✅" if pnl > 0 else "perda ❌"
                        lado = "compra (long)" if position == 1 else "venda (short)"
                        state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] 🏁 Fechou {lado} | PnL: US$ {pnl:.2f} ({resultado_texto})"})
                        
                        if len(state["order_book"]) > 50: state["order_book"].pop()
                        
                        state["balance"] = balance
                        state["floating_pnl"] = 0.0
                        if pnl > 0: wins += 1
                        else: losses += 1
                        position = 0 # Posição zerada e livre!

                    # 2. SE O ALVO EXIGE UMA NOVA POSIÇÃO, ELE ABRE AGORA
                    if target_pos != 0 and not warming_up:
                        balance -= (balance * FEE_RATE)
                        entry_price = current_price
                        last_entry_ts = int(time.time()) 
                        position = target_pos
                        
                        # [MARKER] Registro de Entrada
                        state["markers"].append({
                            "time": int(last_row['timestamp'].timestamp()),
                            "position": "belowBar" if position == 1 else "aboveBar",
                            "color": "#22c55e" if position == 1 else "#ef4444",
                            "shape": "circle",
                            "text": f"ENTRADA {'COMPRA' if position==1 else 'VENDA'}"
                        })
                        if len(state["markers"]) > 100: state["markers"].pop(0)
                        
                        lado_abertura = "compra (long)" if position == 1 else "venda (short)"
                        state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Abriu {lado_abertura} a US$ {current_price:.2f}"})
                        if len(state["order_book"]) > 50: state["order_book"].pop()

                # Sincronização Final do Estado
                state.update({
                    "in_position": position != 0,
                    "current_position": position,
                    "entry_price": entry_price,
                    "adaptation": {
                        **state["adaptation"], 
                        "wins": wins, 
                        "losses": losses, 
                        "current_win_rate": round((wins/(wins+losses))*100, 1) if (wins+losses)>0 else state["adaptation"]["current_win_rate"]
                    }
                })

            state["uptime"] = get_uptime()
            if 'last_row' in locals():
                state["last_candle"] = {
                    "time": int(last_row['timestamp'].timestamp()), 
                    "open": last_row['open'], "high": last_row['high'], 
                    "low": last_row['low'], "close": last_row['close']
                }
            
            # Limpeza forçada de memória
            gc.collect() 

            # Sleep limpo e previsível (descansa 1 segundo entre as iterações)
            await asyncio.sleep(1.0)
            
        except Exception as e:
            print(f"❌ Erro no Loop Sniper: {e}")
            
            # Auto-recuperação de conexão perdida (SSL / Connection Reset)
            error_str = str(e).lower()
            if "ssl" in error_str or "closed" in error_str or "connectionreset" in error_str:
                print(">>> 🔄 Falha de rede detectada. Reiniciando cliente da corretora...")
                try: 
                    await exchange.close()
                except: 
                    pass
                # Recria a conexão limpa
                exchange = ccxt.kraken({'enableRateLimit': True, 'timeout': 30000})
                
            await asyncio.sleep(5)

# --- FASTAPI E ROTAS (Pylance Fix: Fora de funções) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    ⚡⚡⚡ LIFESPAN MÍNIMO - Startup INSTANTÂNEO
    
    Estratégia:
    1. FastAPI já = pronta para receber conexões
    2. Todos os loops em background (não bloqueador)
    3. Modelo carrega em thread (zero efeito no startup)
    """
    print(">>> 🚀 FastAPI iniciando lifespan...")
    
    # ✅ BACKGROUND TASKS - Não bloqueam
    try:
        # Inicia loops de trading em paralelo (fire-and-forget)
        print(">>> 📍 Iniciando sniper_loop...")
        task_sniper = asyncio.create_task(sniper_loop())
        print(">>> ✅ Sniper task criado")
        
        print(">>> 📍 Iniciando analyst_market_loop...")
        task_analyst = asyncio.create_task(analyst_market_loop())
        print(">>> ✅ Analyst task criado")
        
        # Carrega modelo em thread (não bloqueia)
        if os.path.exists(MODEL_PATH):
            print(f">>> 📍 Carregando modelo de {MODEL_PATH} em thread...")
            asyncio.create_task(asyncio.to_thread(load_brain, MODEL_PATH))
        else:
            print(f">>> ⚠️ Modelo não encontrado em {MODEL_PATH}")
        
        print(">>> ✅ FastAPI PRONTO na porta!")
        
    except Exception as e:
        print(f">>> ❌ Erro no startup: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        # NÃO FALHA - Continua mesmo com erro
    
    # ✅ YIELD IMEDIATAMENTE - Nunca bloqueia!
    print(">>> 🟢 Sistema aguardando conexões...")
    yield
    
    # Cleanup (raramente executado em Render)
    print(">>> 🛑 Encerrando lifespan...")



app = FastAPI(lifespan=lifespan)

# ✅ Middleware CORS Padrão (Sem conflitos com WebSockets)
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

@app.get("/api/state")
async def get_state_snapshot():
    """Snapshot HTTP do estado ao vivo (o dashboard usa WebSocket; isto evita tela eterna de load se o WS falhar)."""
    try:
        # Serialização segura para evitar erros com tipos não-JSON
        safe_state = json.loads(json.dumps(state, default=str))
        return safe_state
    except Exception as e:
        print(f">>> ❌ Erro ao retornar state: {e}")
        return {"error": str(e), "status": "offline"}

@app.get("/api/historico")
async def get_historico():
    try:
        if exchange is None:
            temp_ex = ccxt.kraken({'enableRateLimit': True, 'timeout': 30000})
            ohlcv = await temp_ex.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=1000)
            await temp_ex.close()
            return [{"time": int(r[0]/1000), "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in ohlcv]
            
        ohlcv = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=1000)
        return [{"time": int(r[0]/1000), "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in ohlcv]
    except Exception as e:
        print(f"❌ Erro na API Histórico: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar histórico de velas.")

@app.get("/health")
async def health():
    return {
        "status": "online",
        "uptime": get_uptime()
    }

@app.get("/api/health")
async def api_health():
    return {
        "status": "ok",
        "backend": "online",
        "cors": "enabled"
    }

@app.get("/api/performance")
async def performance_metrics():
    return {
        "status": "online",
        "message": "Monitoramento de performance desativado para otimização de CPU."
    }

def sanitize_state(obj):
    """Limpa resquícios do Numpy, NaN e Infinity que quebram o JSON do WebSocket"""
    if isinstance(obj, dict):
        return {k: sanitize_state(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_state(v) for v in obj]
    elif isinstance(obj, (np.integer, np.floating)):
        val = float(obj)
        if math.isnan(val) or math.isinf(val): return 0.0
        return val
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj): return 0.0
        return obj
    elif isinstance(obj, np.ndarray):
        return sanitize_state(obj.tolist())
    return obj

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # 1. Aceita a conexão imediatamente (evita o erro 500 no handshake HTTP)
    await websocket.accept()
    
    try:
        while True:
            # 2. Copia, sanitiza e serializa o estado
            current_state = copy.deepcopy(state)
            safe_state = sanitize_state(current_state)
            safe_state_json = json.loads(json.dumps(safe_state, default=str))
            
            # 3. Dispara para o cliente
            await websocket.send_json(safe_state_json)
            await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        # Cliente fechou a aba ou Next.js recarregou. Sai silenciosamente.
        pass
    except asyncio.CancelledError:
        # Tarefa cancelada pelo servidor. Sai silenciosamente.
        pass
    except Exception as e:
        # Se der erro grave, loga apenas uma linha e encerra. O front reconecta.
        print(f">>> [WS] Conexão encerrada ({type(e).__name__})")


# ==========================================
# 🧬 ROTAS DO DOJO (PROTOCOLO APOCALIPSE)
# ==========================================
@app.get("/download-dados")
async def download_dados(x_admin_password: str = Header(None)):
    """Exporta o histórico de forma segura via Header."""
    if x_admin_password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="Acesso Negado. Senha incorreta.")
    
    if not os.path.exists(DATA_PATH):
        raise HTTPException(status_code=404, detail="O arquivo CSV de dados ainda não foi gerado.")
        
    return FileResponse(
        path=DATA_PATH, 
        media_type='text/csv', 
        filename=f"live_market_data_{int(time.time())}.csv"
    )

@app.post("/upload-cerebro")
async def upload_cerebro(file: UploadFile = File(...), x_admin_password: str = Header(None)):
    """Injeta uma nova geração lendo a senha de forma invisível no Header."""
    global MODEL_PATH
    if x_admin_password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="Acesso Negado. Senha incorreta.")

    try:
        if not os.path.exists("models"):
            os.makedirs("models")

        # Define o novo caminho baseado no nome do arquivo enviado
        new_model_path = os.path.join("models", file.filename)

        # Escrita robusta do arquivo
        content = await file.read()
        with open(new_model_path, "wb") as buffer:
            buffer.write(content)

        # Atualiza a variável global para que o sistema aponte para o novo modelo
        MODEL_PATH = new_model_path

        # 🚀 CORREÇÃO: Carrega o modelo sem congelar o servidor web
        await asyncio.to_thread(load_brain, MODEL_PATH)

        state["adaptation"]["generation"] += 1
        state["adaptation"]["learning_state"] = f"NOVA GERAÇÃO INJETADA ({file.filename})"

        return {"status": "sucesso", "mensagem": f"Cérebro '{file.filename}' atualizado e carregado."}
    except Exception as e:
        print(f">>> ❌ Erro no upload/load do cérebro: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar cérebro: {str(e)}")
    
@app.get("/")
async def root():
    return {"status": "IA Trader Pro API Online 🟢", "versao": "3.0.1"}

# ==========================================
# INICIALIZAÇÃO DO SERVIDOR
# ==========================================
if __name__ == "__main__":
    """
    ⚠️ SOMENTE PARA TESTES LOCAIS
    
    Em produção (Render), usar:
    uvicorn server:app --host 0.0.0.0 --port $PORT
    """
    import uvicorn
    import os
    
    port = int(os.environ.get("PORT", 10000))
    host = os.environ.get("HOST", "0.0.0.0")
    
    print(f">>> 🚀 Iniciando servidor em {host}:{port}")
    print(f">>> 📍 URL: http://{host}:{port}")
    print(f">>> 🔗 WebSocket: ws://{host}:{port}/ws")
    
    # Modo com reload para desenvolvimento
    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        reload=False,  # Desabilitar reload no Render
        log_level="info",
        access_log=True
    )
