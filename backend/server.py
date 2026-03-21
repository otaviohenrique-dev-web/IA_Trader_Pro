from fastapi.responses import FileResponse
import shutil
import asyncio
import json
import time
from datetime import datetime
import pandas as pd
import numpy as np
import pandas_ta_classic as ta
import ccxt.async_support as ccxt
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import gc
from sb3_contrib import RecurrentPPO
import warnings
import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, HTTPException, UploadFile, File, Header
warnings.filterwarnings("ignore")

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

# 2. Puxa as variáveis
CRYPTOPANIC_KEY = os.environ.get("CRYPTOPANIC_API_KEY")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD")

# 3. Trava de Segurança: Avisa no terminal se as chaves falharam
if not GEMINI_KEY or not CRYPTOPANIC_KEY:
    print(">>> ⚠️ ALERTA CRÍTICO: Chaves de API não encontradas no ambiente ou no .env!")
    print(">>> O sistema pode falhar ao acessar o Sentinela.")


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

state = {
    "asset": SYMBOL,
    "is_online": True,
    "in_position": False,
    "entry_price": 0.0,
    "current_position": 0,
    "balance": balance, 
    "status": "REBOOT DO SISTEMA...",
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
    }
}

model = None
exchange = None
lstm_states = None 
episode_starts = np.ones((1,), dtype=bool)
feature_cols = ['log_ret', 'rsi', 'rsi_slope', 'macd_diff', 'bb_pband', 'bb_width', 'dist_ema50', 'dist_ema200', 'atr_pct']
last_analysis_time = 0
cached_analysis = {"score": 50, "status": "SAFE", "reason": "Sincronizando com a rede neural..."}

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
    global model
    try:
        if os.path.exists(path):
            model = RecurrentPPO.load(path, device="cpu")
            print(f">>> 🧠 CÉREBRO CARREGADO: {path}")
    except Exception as e: print(f"❌ Erro neural: {e}")

def get_uptime():
    seconds = int(time.time() - START_TIME)
    return time.strftime('%H:%M:%S', time.gmtime(seconds))


# --- INICIALIZAÇÃO DO CLIENTE (SDK ATUALIZADO) ---
from google import genai
# O cliente puxa a chave direto ou podemos passar explicitamente
client = genai.Client(api_key=GEMINI_KEY)

# --- AGENTE DE NOTÍCIAS (IA SENTINELA) ---
async def fetch_btc_news():
    # Usando EXATAMENTE a rota v2 developer fornecida na documentação
    api_url = f"https://cryptopanic.com/api/developer/v2/posts/?auth_token={CRYPTOPANIC_KEY}&currencies=BTC"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get('results', [])
                    
                    if results:
                        # Extraímos os títulos para o letreiro
                        news_list = [f" {p['title']} •" for p in results[:10]]
                        return news_list
                    
                    return []
                else:
                    print(f">>> ❌ Erro na API CryptoPanic (Status {resp.status}).")
                    return []
    except Exception as e:
        print(f">>> ❌ Falha na conexão de notícias: {e}")
        return []

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
    
    # 🧠 PROMPT CALIBRADO: Ensinando a IA a ser um trader frio, não um jornalista assustado
    prompt = f"""
    Você é um Gestor de Risco Quantitativo sênior de Bitcoin. Avalie o risco macroeconômico atual baseado nestas manchetes:
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

async def analyst_market_loop():
    print(">>> 🕵️ IA_Analista_BTC_Market: Escudo ativado!")
    while True:
        try:
            headlines = await fetch_btc_news()
            
            # Se a busca por BTC vier vazia, tentamos buscar notícias GERAIS para não deixar o letreiro parado
            if not headlines:
                general_url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_KEY}&regions=en,pt"
                async with aiohttp.ClientSession() as session:
                    async with session.get(general_url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            headlines = [f" {p['title']} •" for p in data.get('results', [])[:10]]

            analysis = await analyze_sentiment_with_llm(headlines)
            
            state["news_agent"].update({
                "status": analysis["status"],
                "sentiment_score": analysis["score"],
                "risk_level": analysis["status"],
                "last_headlines": headlines if headlines else ["SISTEMA EM MONITORAMENTO: AGUARDANDO NOVOS EVENTOS •"]
            })
            
            global kill_switch_active
            if analysis["status"] == "SAFE":
                kill_switch_active = False
            
            print(f">>> ✅ Analista: {analysis['status']} | Letreiro atualizado com {len(headlines)} notícias.")
            await asyncio.sleep(600) # Atualiza a cada 10 min para não ser banido
        except Exception as e:
            print(f"❌ Erro no Analista: {e}")
            await asyncio.sleep(60)


# --- LOOP PRINCIPAL DO TRADER (SNIPER) ---
async def sniper_loop():
    global state, exchange, lstm_states, episode_starts, balance, position, entry_price, wins, losses
    global kill_switch_active, last_entry_ts, startup_phase, startup_timer, warming_up, warmup_counter, consecutive_signals, last_signal

    # Configuração de Guerra para o Render (Evita Erro 451 de Localização Restrita)
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'timeout': 30000,
        'urls': {
            'api': {
                'public': 'https://api.binance.me/api/v3',
                'private': 'https://api.binance.me/api/v3',
            }
        },
        'options': {
            'adjustForTimeDifference': True,
            'recvWindow': 10000,
        }
    })

    last_saved_candle_ts = 0 
    last_fetch_ts = 0

    # Reset de memórias para evitar viés de reinicialização
    lstm_states = None
    episode_starts = np.ones((1,), dtype=bool)
    consecutive_signals = 0
    last_signal = 0

    while True:
        try:
            now_ts = int(time.time())
            
            # 1. BUSCA DE DADOS (A cada 15s para poupar API)
            if now_ts - last_fetch_ts > 15 or last_fetch_ts == 0:
                ohlcv = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=500)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                
                # Cálculo de Indicadores
                df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
                df['rsi'] = ta.rsi(df['close'], length=14)
                df['rsi_slope'] = df['rsi'].diff()
                df['ema200'] = ta.ema(df['close'], length=200)
                df['dist_ema200'] = (df['close'] - df['ema200']) / df['ema200']
                df['atr_pct'] = ta.atr(df['high'], df['low'], df['close'], length=14) / df['close']
                df['bb_pband'], df['bb_width'], df['macd_diff'], df['dist_ema50'] = 0, 0, 0, 0
                df_clean = df.dropna().copy()
                last_fetch_ts = now_ts
                
                # Log de Velas para CSV
                closed_candle_ts = ohlcv[-2][0] 
                if closed_candle_ts > last_saved_candle_ts:
                    if not os.path.exists("data"): os.makedirs("data")
                    df.iloc[:-1].tail(1).to_csv(DATA_PATH, mode='a', header=not os.path.exists(DATA_PATH), index=False)
                    last_saved_candle_ts = closed_candle_ts

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
                    state["status"] = "REBOOT: EXECUTANDO BACKTEST..."
                    startup_timer += 1
                    if startup_timer == 1:
                        res = run_startup_backtest(df_clean, model)
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
                    # IA PREDIÇÃO
                    obs = last_row[feature_cols].values.astype(np.float32)
                    action, lstm_states = model.predict(obs, state=lstm_states, episode_start=episode_starts, deterministic=True)
                    episode_starts = np.zeros((1,), dtype=bool)
                    act_idx = action.item()

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
                            state["status"] = f"⏳ AGUARDANDO ANALISTA ({state['news_agent']['status']})"
                        elif consecutive_signals >= 3:
                            target_pos = 1 if act_idx == 1 else (-1 if act_idx == 2 else 0)
                        else:
                            state["status"] = "🔍 BUSCANDO OPORTUNIDADE..."

                # --- 3. EXECUÇÃO ÚNICA (FINANCEIRO + VISUAL) ---
                if target_pos != position:
                    # ABRIR POSIÇÃO
                    if position == 0 and target_pos != 0 and not warming_up:
                        balance -= (balance * FEE_RATE)
                        entry_price = current_price
                        last_entry_ts = int(time.time()) 
                        position = target_pos
                        
                        # [MARKER] Registro de Entrada no Gráfico (TradingView)
                        state["markers"].append({
                            "time": int(last_row['timestamp'].timestamp()),
                            "position": "belowBar" if position == 1 else "aboveBar",
                            "color": "#22c55e" if position == 1 else "#ef4444",
                            "shape": "circle",
                            "text": f"ENTRY {'LONG' if position==1 else 'SHORT'}"
                        })
                        state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 ABRIU {'LONG' if position==1 else 'SHORT'} em ${current_price:.2f}"})

                    # FECHAR POSIÇÃO
                    elif position != 0 and target_pos == 0:
                        pnl = (balance * ((current_price - entry_price)/entry_price)) if position == 1 else (balance * -((current_price - entry_price)/entry_price))
                        balance += (pnl - (balance * FEE_RATE))
                        
                        # [MARKER] Registro de Saída no Gráfico
                        state["markers"].append({
                            "time": int(last_row['timestamp'].timestamp()),
                            "position": "aboveBar",
                            "color": "#facc15", # Amarelo para Saída
                            "shape": "square",
                            "text": f"EXIT: {'WIN' if pnl > 0 else 'LOSS'}"
                        })
                        
                        # 🟢 [NOVO] REGISTRO DE FECHAMENTO NO LIVRO DE AÇÕES
                        resultado_texto = "WIN ✅" if pnl > 0 else "LOSS ❌"
                        state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] 🏁 FECHOU {'LONG' if position==1 else 'SHORT'} | PnL: ${pnl:.2f} ({resultado_texto})"})
                        
                        # Limite de segurança: Mantém apenas os 50 registros mais recentes no livro para não travar a memória
                        if len(state["order_book"]) > 50:
                            state["order_book"].pop()
                        
                        state["balance"] = balance
                        state["floating_pnl"] = 0.0
                        if pnl > 0: wins += 1
                        else: losses += 1
                        position = 0

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
            await asyncio.sleep(1) 

        except Exception as e:
            print(f"❌ Erro no Loop Sniper: {e}")
            await asyncio.sleep(5)

# --- FASTAPI E ROTAS (Pylance Fix: Fora de funções) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_brain(MODEL_PATH)
    t1 = asyncio.create_task(sniper_loop())
    t2 = asyncio.create_task(analyst_market_loop())
    yield
    t1.cancel(); t2.cancel()
    if exchange: await exchange.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/historico")
async def get_historico():
    try:
        if exchange is None:
            temp_ex = ccxt.binanceus({'enableRateLimit': True})
            ohlcv = await temp_ex.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=1000)
            await temp_ex.close()
            return [{"time": int(r[0]/1000), "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in ohlcv]
        ohlcv = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=1000)
        return [{"time": int(r[0]/1000), "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in ohlcv]
    except: raise HTTPException(status_code=500, detail="Erro no histórico")

@app.get("/health")
async def health(): return {"status": "online"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(state)
            await asyncio.sleep(1)
    except: pass

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
    if x_admin_password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="Acesso Negado. Senha incorreta.")
    
    try:
        if not os.path.exists("models"):
            os.makedirs("models")
            
        with open(MODEL_PATH, "wb") as buffer:
            import shutil
            shutil.copyfileobj(file.file, buffer)
        
        load_brain(MODEL_PATH)
        
        state["adaptation"]["generation"] += 1
        state["adaptation"]["learning_state"] = "NOVA GERAÇÃO INJETADA"
        
        return {"status": "sucesso", "mensagem": "Cérebro atualizado e carregado."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar: {str(e)}")
    
# ==========================================
# INICIALIZAÇÃO DO SERVIDOR
# ==========================================
if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 10000))
    # Importante: usar o formato de string "server:app" para o Render
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")