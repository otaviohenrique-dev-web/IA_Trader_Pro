# 🔧 Código Pronto para Copiar-Cola

Exemplos de código para implementar a arquitetura simplificada. Todos os arquivos estão prontos para usar.

---

## 1️⃣ backend/services/data_service.py

```python
import asyncio
import time
import pandas as pd
import numpy as np
import pandas_ta_classic as ta
from datetime import datetime

FEATURE_COLS = ['log_ret', 'rsi', 'rsi_slope', 'macd_diff', 'bb_pband', 'bb_width', 'dist_ema50', 'dist_ema200', 'atr_pct']

class DataService:
    """Serviço responsável por buscar e processar dados de mercado."""
    
    def __init__(self, exchange):
        self.exchange = exchange
        self.last_fetch_ts = 0
        self.cached_df = None
    
    async def fetch_and_process(self, symbol, timeframe, limit=250):
        """
        Busca OHLCV da API e calcula indicadores.
        Retorna None se cache ainda é válido (<60s).
        """
        now = time.time()
        
        # Cache de 60 segundos
        if self.last_fetch_ts > 0 and (now - self.last_fetch_ts) < 60:
            return self.cached_df
        
        try:
            print(f">>> 📊 Buscando OHLCV ({symbol} {timeframe})...")
            ohlcv = await asyncio.wait_for(
                self.exchange.fetch_ohlcv(symbol, timeframe, limit),
                timeout=15.0
            )
            
            self.last_fetch_ts = now
            print(f">>> ✅ Recebido {len(ohlcv)} velas")
            
            # Processa indicadores em thread separada (não bloqueia)
            df = await asyncio.to_thread(self._process_indicators, ohlcv)
            self.cached_df = df
            
            return df
        
        except asyncio.TimeoutError:
            print(f">>> ⚠️ Timeout ao buscar OHLCV")
            return None
        except Exception as e:
            print(f">>> ❌ Erro ao buscar OHLCV: {type(e).__name__}: {e}")
            return None
    
    def _process_indicators(self, ohlcv):
        """Cálculo pesado de indicadores - roda em thread."""
        try:
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # Log returns
            df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
            
            # RSI
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['rsi_slope'] = df['rsi'].diff()
            
            # MACD
            macd = ta.macd(df['close'])
            if macd is not None and not macd.empty:
                macd_col = [c for c in macd.columns if c.startswith('MACDH')][0]
                df['macd_diff'] = macd[macd_col]
            else:
                df['macd_diff'] = 0.0
            
            # Bollinger Bands
            bb = ta.bbands(df['close'], length=20, std=2)
            if bb is not None and not bb.empty:
                upper_col = [c for c in bb.columns if c.startswith('BBU')][0]
                lower_col = [c for c in bb.columns if c.startswith('BBL')][0]
                width_col = [c for c in bb.columns if c.startswith('BBB')][0]
                df['bb_pband'] = (df['close'] - bb[lower_col]) / (bb[upper_col] - bb[lower_col])
                df['bb_width'] = bb[width_col]
            else:
                df['bb_pband'], df['bb_width'] = 0.0, 0.0
            
            # EMAs
            df['ema50'] = ta.ema(df['close'], length=50)
            df['ema200'] = ta.ema(df['close'], length=200)
            df['dist_ema50'] = (df['close'] - df['ema50']) / df['ema50']
            df['dist_ema200'] = (df['close'] - df['ema200']) / df['ema200']
            
            # ATR
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
            df['atr_pct'] = df['atr'] / df['close']
            
            return df.dropna()
        
        except Exception as e:
            print(f">>> ❌ Erro ao processar indicadores: {e}")
            return None
```

---

## 2️⃣ backend/services/trading_engine.py

```python
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np

@dataclass
class Trade:
    """Registro de um trade executado."""
    action: str  # 'open' ou 'close'
    position: str  # 'long' ou 'short'
    price: float
    timestamp: float
    pnl: Optional[float] = None

class TradingEngine:
    """Engine de trading - executa operations de mercado."""
    
    def __init__(self, model=None, balance=100.0):
        self.model = model
        self.balance = balance
        self.position = 0  # 0=hold, 1=long, -1=short
        self.entry_price = 0.0
        self.trades_history: List[Trade] = []
        self.lstm_state = None
        self.episode_start = np.ones((1,), dtype=bool)
    
    async def predict_action(self, df_clean, feature_cols):
        """Prediz próxima ação usando o modelo."""
        if self.model is None:
            return 0  # Hold por padrão
        
        try:
            last_row = df_clean.iloc[-1]
            obs = last_row[feature_cols].values.astype(np.float32)
            
            action, self.lstm_state = self.model.predict(
                obs,
                state=self.lstm_state,
                episode_start=self.episode_start,
                deterministic=True
            )
            
            self.episode_start = np.zeros((1,), dtype=bool)
            return action.item()
        
        except Exception as e:
            print(f">>> ❌ Erro na predição IA: {e}")
            return 0
    
    def execute_trade(self, action, current_price, fee_rate=0.001):
        """Executa trade baseado em ação (0=hold, 1=long, -1=short)."""
        target_pos = 1 if action == 1 else (-1 if action == 2 else 0)
        
        # Sem mudança = sem ação
        if target_pos == self.position:
            return None
        
        # Fecha posição anterior se houver
        if self.position != 0:
            pnl = self._calculate_pnl(current_price, fee_rate)
            self.balance += pnl
            
            self.trades_history.append(Trade(
                action='close',
                position='long' if self.position == 1 else 'short',
                price=current_price,
                timestamp=time.time(),
                pnl=pnl
            ))
        
        # Abre nova posição se alvo != 0
        if target_pos != 0:
            self.balance -= (self.balance * fee_rate)  # Fee
            self.position = target_pos
            self.entry_price = current_price
            
            self.trades_history.append(Trade(
                action='open',
                position='long' if target_pos == 1 else 'short',
                price=current_price,
                timestamp=time.time()
            ))
            
            print(f">>> 🚀 Trade: {self.trades_history[-1].position.upper()} @ {current_price:.2f}")
        
        else:
            # Passou a hold
            self.position = 0
            self.entry_price = 0.0
        
        return target_pos
    
    def _calculate_pnl(self, current_price, fee_rate):
        """Calcula P&L do trade que está fechando."""
        if self.position == 1:  # Long
            change_pct = (current_price - self.entry_price) / self.entry_price
            pnl = self.balance * change_pct
        else:  # Short
            change_pct = (self.entry_price - current_price) / self.entry_price
            pnl = self.balance * change_pct
        
        # Desconta fee
        pnl -= (self.balance * fee_rate)
        
        return pnl
    
    def get_stats(self):
        """Retorna estatísticas de performance."""
        closed_trades = [t for t in self.trades_history if t.pnl is not None]
        if not closed_trades:
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0
            }
        
        wins = sum(1 for t in closed_trades if t.pnl > 0)
        losses = sum(1 for t in closed_trades if t.pnl <= 0)
        total_pnl = sum(t.pnl for t in closed_trades)
        
        return {
            'total_trades': len(closed_trades),
            'wins': wins,
            'losses': losses,
            'win_rate': (wins / len(closed_trades) * 100) if closed_trades else 0.0,
            'total_pnl': total_pnl
        }
```

---

## 3️⃣ backend/services/state_manager.py

```python
import json
from typing import Callable, List
import asyncio

class StateManager:
    """Gerenciador de estado imutável e reativo."""
    
    def __init__(self):
        self._state = {
            'asset': 'BTC/USDT',
            'is_online': True,
            'uptime': '00:00:00',
            'status': 'INICIALIZANDO',
            'balance': 100.0,
            'position': 0,
            'entry_price': 0.0,
            'current_price': 0.0,
            'last_candle': {},
            'markers': [],
            'trades': [],
            'news': [],
        }
        self._subscribers: List[Callable] = []
    
    def get(self):
        """Retorna cópia completa do estado (imutável)."""
        return json.loads(json.dumps(self._state))
    
    def update(self, **kwargs):
        """Atualiza estado e notifica subscribers."""
        changed = False
        for key, value in kwargs.items():
            if key in self._state:
                if self._state[key] != value:
                    self._state[key] = value
                    changed = True
        
        if changed:
            self._notify_subscribers()
    
    def subscribe(self, callback: Callable):
        """Registra callback para ser chamado quando estado mudar."""
        self._subscribers.append(callback)
    
    def _notify_subscribers(self):
        """Notifica todos subscribers sobre mudança de estado."""
        state_copy = self.get()
        for callback in self._subscribers:
            try:
                # Se for async
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(state_copy))
                else:
                    callback(state_copy)
            except Exception as e:
                print(f">>> ❌ Erro ao notificar subscriber: {e}")
```

---

## 4️⃣ backend/services/news_service.py

```python
import aiohttp
import asyncio
from typing import List

class NewsService:
    """Serviço de notícias do mercado."""
    
    def __init__(self, api_key=""):
        self.api_key = api_key
        self.cached_news = []
        self.last_fetch_ts = 0
    
    async def fetch_news(self, query="BTC", lang="PT") -> List[str]:
        """Busca notícias de criptografia."""
        import time
        now = time.time()
        
        # Cache de 5 minutos
        if self.last_fetch_ts > 0 and (now - self.last_fetch_ts) < 300:
            return self.cached_news
        
        try:
            url = f"https://min-api.cryptocompare.com/data/v2/news/"
            params = {
                'categories': query,
                'lang': lang,
                'api_key': self.api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        headlines = [
                            item['title'] 
                            for item in data.get('Data', [])[:10]
                        ]
                        self.cached_news = headlines
                        self.last_fetch_ts = now
                        return headlines
        
        except Exception as e:
            print(f">>> ❌ Erro ao buscar notícias: {e}")
        
        return self.cached_news
```

---

## 5️⃣ backend/loops/trading_loop.py

```python
import asyncio
import time
from typing import Optional

async def trading_loop(
    data_service,
    trading_engine,
    state_manager,
    feature_cols,
    symbol='BTC/USDT',
    timeframe='15m'
):
    """Loop principal de trading - simples e testável."""
    
    print(">>> 🟢 Trading loop iniciado...")
    
    while True:
        try:
            # Verifica status
            current_state = state_manager.get()
            if current_state['status'] not in ['OPERANDO', 'INICIALIZANDO']:
                await asyncio.sleep(1)
                continue
            
            # 1. Busca dados (com cache 60s)
            df = await data_service.fetch_and_process(symbol, timeframe)
            if df is None or len(df) < 2:
                await asyncio.sleep(1)
                continue
            
            # 2. Prediz ação (se modelo pronto)
            action = await trading_engine.predict_action(df, feature_cols)
            
            # 3. Executa trade
            last_candle = df.iloc[-1]
            current_price = float(last_candle['close'])
            result = trading_engine.execute_trade(action, current_price)
            
            # 4. Atualiza estado
            stats = trading_engine.get_stats()
            state_manager.update(
                status='OPERANDO',
                balance=round(trading_engine.balance, 2),
                position=trading_engine.position,
                entry_price=round(trading_engine.entry_price, 2),
                current_price=round(current_price, 2),
                last_candle={
                    'time': int(last_candle['timestamp'].timestamp()),
                    'open': float(last_candle['open']),
                    'high': float(last_candle['high']),
                    'low': float(last_candle['low']),
                    'close': current_price
                },
                adaptation={
                    'wins': stats['wins'],
                    'losses': stats['losses'],
                    'win_rate': round(stats['win_rate'], 1),
                    'total_trades': stats['total_trades']
                }
            )
            
            await asyncio.sleep(1)
        
        except Exception as e:
            print(f">>> ❌ Erro no trading loop: {type(e).__name__}: {e}")
            await asyncio.sleep(5)

async def heartbeat_loop(state_manager, start_time):
    """Atualiza uptime a cada segundo."""
    while True:
        try:
            elapsed = int(time.time() - start_time)
            uptime = f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}"
            state_manager.update(uptime=uptime)
            await asyncio.sleep(1)
        except Exception as e:
            print(f">>> ❌ Erro no heartbeat: {e}")
            await asyncio.sleep(1)

async def news_loop(news_service, state_manager):
    """Busca notícias a cada 5 minutos."""
    while True:
        try:
            headlines = await news_service.fetch_news()
            state_manager.update(news=headlines)
            await asyncio.sleep(300)  # 5 minutos
        except Exception as e:
            print(f">>> ❌ Erro no news loop: {e}")
            await asyncio.sleep(300)
```

---

## 6️⃣ backend/server.py (SIMPLIFICADO)

```python
import asyncio
import time
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import ccxt.async_support as ccxt
from sb3_contrib import RecurrentPPO

from services.data_service import DataService, FEATURE_COLS
from services.trading_engine import TradingEngine
from services.state_manager import StateManager
from services.news_service import NewsService
from loops.trading_loop import trading_loop, heartbeat_loop, news_loop

# Configurações
SYMBOL = 'BTC/USDT'
TIMEFRAME = '15m'
MODEL_PATH = "models/sniper_pro_gen_6.zip"
KRAKEN_TIMEOUT = 30000

# Globais (apenas para inicialização)
state_manager = None
data_service = None
trading_engine = None
news_service = None
startup_time = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup e shutdown do app."""
    global state_manager, data_service, trading_engine, news_service, startup_time
    
    print(">>> 🚀 Iniciando IA Trader Pro v3.0.1...")
    startup_time = time.time()
    
    # Inicializa serviços
    try:
        # Exchange
        exchange = ccxt.kraken({'enableRateLimit': True, 'timeout': KRAKEN_TIMEOUT})
        print(">>> ✅ Kraken conectado")
        
        # State Manager
        state_manager = StateManager()
        state_manager.update(status='INICIALIZANDO')
        
        # Data Service
        data_service = DataService(exchange)
        
        # News Service
        news_service = NewsService(os.environ.get("CRYPTOCOMPARE_API_KEY", ""))
        
        # Carrega modelo em thread (não bloqueia)
        print(f">>> 📍 Carregando modelo de {MODEL_PATH} em thread...")
        model = None
        try:
            model = await asyncio.to_thread(
                RecurrentPPO.load,
                MODEL_PATH,
                device="cpu"
            )
            print(">>> ✅ Modelo carregado com sucesso!")
        except Exception as e:
            print(f">>> ⚠️ Erro ao carregar modelo: {e}")
        
        # Trading Engine
        trading_engine = TradingEngine(model=model, balance=100.0)
        
        # Inicia loops em background (não bloqueiam)
        asyncio.create_task(heartbeat_loop(state_manager, startup_time))
        asyncio.create_task(trading_loop(data_service, trading_engine, state_manager, FEATURE_COLS, SYMBOL, TIMEFRAME))
        asyncio.create_task(news_loop(news_service, state_manager))
        
        state_manager.update(status='OPERANDO', is_online=True)
        print(">>> 🟢 Sistema pronto para operar!")
    
    except Exception as e:
        print(f">>> ❌ Erro ao iniciar: {e}")
        state_manager.update(status=f'ERRO: {str(e)}')
    
    yield
    
    # Cleanup
    print(">>> 🛑 Encerrando...")
    try:
        await exchange.close()
    except:
        pass

# App FastAPI
app = FastAPI(title="IA Trader Pro", version="3.0.1", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ENDPOINTS

@app.get("/")
async def root():
    return {"status": "online", "version": "3.0.1"}

@app.get("/api/state")
async def get_state():
    """Retorna estado completo do sistema."""
    if state_manager is None:
        return {"error": "Sistema não inicializado"}
    
    state = state_manager.get()
    return Response(
        content=json.dumps(state),
        media_type="application/json"
    )

@app.post("/api/control/pause")
async def pause():
    """Pausa trading."""
    state_manager.update(status='PAUSADO')
    return {"status": "pausado"}

@app.post("/api/control/resume")
async def resume():
    """Retoma trading."""
    state_manager.update(status='OPERANDO')
    return {"status": "operando"}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/ready")
async def ready():
    """Readiness probe para Render."""
    if state_manager is None:
        return Response(
            content=json.dumps({"ready": False, "status": "inicializando"}),
            status_code=503
        )
    
    state = state_manager.get()
    is_ready = state.get('is_online', False)
    
    return Response(
        content=json.dumps({
            "ready": is_ready,
            "status": state.get('status', 'desconhecido')
        }),
        status_code=200 if is_ready else 503
    )
```

---

## 7️⃣ frontend/hooks/useWebSocket.js

```javascript
import { useEffect, useRef, useState } from 'react';

export function useWebSocket(url) {
  const [data, setData] = useState(null);
  const [connected, setConnected] = useState(false);
  const ws = useRef(null);
  const reconnectAttempts = useRef(0);

  useEffect(() => {
    const connect = () => {
      try {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${url.replace(/^https?:\/\//, '')}`;
        
        console.log(`🔌 Conectando WebSocket: ${wsUrl}`);
        ws.current = new WebSocket(wsUrl);

        ws.current.onopen = () => {
          console.log("✅ WebSocket conectado");
          setConnected(true);
          reconnectAttempts.current = 0;
        };

        ws.current.onmessage = (event) => {
          try {
            const state = JSON.parse(event.data);
            setData(state);
          } catch (e) {
            console.error("❌ Erro ao parsear WebSocket message:", e);
          }
        };

        ws.current.onclose = () => {
          console.log("⚠️ WebSocket desconectado");
          setConnected(false);
          
          // Reconnect com back-off exponencial
          const timeout = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
          reconnectAttempts.current++;
          
          setTimeout(connect, timeout);
        };

        ws.current.onerror = (error) => {
          console.error("❌ WebSocket error:", error);
        };
      } catch (e) {
        console.error("❌ Erro ao conectar WebSocket:", e);
      }
    };

    connect();

    return () => {
      if (ws.current) {
        ws.current.close();
      }
    };
  }, [url]);

  const send = (message) => {
    if (ws.current && ws.current.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(message));
    }
  };

  return { data, connected, send };
}
```

---

Estes arquivos cobrem 80% do que você precisa. O resto são pequenos ajustes e integrações!
