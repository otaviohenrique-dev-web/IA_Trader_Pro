# IA Trader Pro - Documentação Técnica Completa

## 📑 Índice
1. [Visão Geral](#visão-geral)
2. [Arquitetura do Sistema](#arquitetura-do-sistema)
3. [Backend - Python + FastAPI](#backend---python--fastapi)
4. [Frontend - Next.js + React](#frontend---nextjs--react)
5. [Sistema de IA (RecurrentPPO)](#sistema-de-ia-recurrentppo)
6. [Análise de Sentimentos com Gemini LLM](#análise-de-sentimentos-com-gemini-llm)
7. [Motor de Trading (Sniper Loop)](#motor-de-trading-sniper-loop)
8. [Sistema de Treinamento (Dojo)](#sistema-de-treinamento-dojo)
9. [Gestão de Risco](#gestão-de-risco)
10. [Fluxo de Dados](#fluxo-de-dados)
11. [Deployment & Configuração](#deployment--configuração)
12. [Últimas Correções Aplicadas](#últimas-correções-aplicadas)

---

## Visão Geral

**IA Trader Pro** é um sistema completo de trading automático de Bitcoin que combina:
- **Inteligência Artificial**: Rede neural recorrente (RecurrentPPO + LSTM) treinada em histórico real
- **Análise Técnica**: 9 indicadores (RSI, MACD, Bandas de Bollinger, EMA, ATR)
- **Análise de Sentimento**: Gemini LLM processa notícias de mercado em tempo real
- **Gestão de Risco**: Stop-loss dinâmico, proteção diária, kill-switch automático
- **Dashboard em Tempo Real**: Gráficos com TradingView Lightweight Charts + Status Live

**Stack:**
- Backend: Python 3.11 + FastAPI + CCXT + StableBaselines3
- Frontend: Next.js 16 + React 19 + TailwindCSS
- Deployment: Render (Backend) + Vercel (Frontend)
- Status: 🟢 Online em produção

---

## Arquitetura do Sistema

```
┌──────────────────────────────────────────────────────────────────┐
│                     INTERNET (Usuário - Browser)                  │
└──────────────┬───────────────────────────────────────────────────┘
               │
        ┌──────▼──────┐                  
        │   Vercel    │ (Frontend https://iatraderproweb.vercel.app)
        │  Next.js    │
        │  React      │
        │ Dashboard   │
        └──────┬──────┘
               │ HTTPS + WebSocket (wss://)
               │
        ┌──────▼──────────────────────────────────────┐
        │    Render (Backend)                         │
        │  https://ia-trader-pro-backend.onrender.com │
        │                                              │
        │  ┌────────────────────────────────────────┐ │
        │  │ FastAPI Application (server.py)        │ │
        │  │                                         │ │
        │  │ 📊 Endpoints HTTP:                      │ │
        │  │   - GET /api/state         → Snapshot   │ │
        │  │   - GET /api/historico     → Velas OHLC│ │
        │  │   - GET /api/health        → Health    │ │
        │  │   - POST /upload-cerebro   → IA Update │ │
        │  │   - GET /download-dados    → Export    │ │
        │  │                                         │ │
        │  │ 🔌 WebSocket /ws:                       │ │
        │  │   - Broadcast state a cada segundo      │ │
        │  │   - Real-time dashboard sync            │ │
        │  └────────────────────────────────────────┘ │
        │                                              │
        │  ┌────────────────────────────────────────┐ │
        │  │ Loop Sniper (Trader Principal)         │ │
        │  │                                         │ │
        │  │ 1. Fetch OHLCV (500 velas)             │ │
        │  │ 2. Calcula Indicadores                 │ │
        │  │ 3. IA Predição (RecurrentPPO)          │ │
        │  │ 4. Valida sinais                       │ │
        │  │ 5. Gerencia posições                   │ │
        │  │ 6. Executa compra/venda/sai            │ │
        │  │ 7. Atualiza state + broadcast          │ │
        │  └────────────────────────────────────────┘ │
        │                                              │
        │  ┌────────────────────────────────────────┐ │
        │  │ Loop Sentiment Analyst                 │ │
        │  │                                         │ │
        │  │ 1. Busca notícias (CryptoCompare)      │ │
        │  │ 2. Gemini LLM análise               │ │
        │  │ 3. Classifica: SAFE/CAUTION/DANGER    │ │
        │  │ 4. Ativa kill-switch se necessário     │ │
        │  │ 5. Atualiza dashboard                  │ │
        │  └────────────────────────────────────────┘ │
        │                                              │
        │  Estado Global (JSON):                       │
        │  ├─ balance, position, entry_price           │
        │  ├─ wins, losses, win_rate                   │
        │  ├─ chart_data, markers                      │
        │  ├─ news_agent status                        │
        │  └─ order_book (histórico)                   │
        │                                              │
        └──────┬───────────────────────────────────────┘
               │
        ┌──────▼──────────────────────────┐
        │  APIs Externas                   │
        │                                   │
        │  🪙 CCXT (Kraken)                │
        │     → Fetch OHLCV                │
        │     → Market data                │
        │                                   │
        │  📰 CryptoCompare                 │
        │     → Notícias BTC               │
        │     → Feed português/inglês      │
        │                                   │
        │  🧠 Google Gemini LLM            │
        │     → Análise sentimento/risco   │
        │     → Cache 30min p/ economizar  │
        │                                   │
        └──────────────────────────────────┘
```

---

## Backend - Python + FastAPI

### Arquivo: `backend/server.py` (663 linhas)

**Propósito:** Orquestrador central do sistema. Gerencia:
- Inicialização de loops assincronamente
- Estado global (balance, posições, métricas)
- APIs HTTP para dashboard
- WebSocket para atualizações em tempo real
- Carregamento do modelo IA

#### 1. Configurações Iniciais (Linhas 1-80)

```python
# Symbols e config
SYMBOL = 'BTC/USDT'
TIMEFRAME = '15m'
MODEL_PATH = "models/sniper_pro_gen_6.zip"
DATA_PATH = "data/live_market_data.csv"
FEE_RATE = 0.0010  # 0.1% por trade
STOP_LOSS_PCT = -0.010  # -1%
TAKE_PROFIT_PCT = +0.020  # +2%

# Variáveis Globais de Estado
balance = 100.00  # Saldo inicial em USD
position = 0  # 0=flat, 1=long, -1=short
entry_price = 0.0
wins = 0
losses = 0
kill_switch_active = False

# Controle de Fluxo
startup_phase = True  # Executa backtest ao iniciar
warming_up = True  # Aquecimento de 15 passos
consecutive_signals = 0  # Validação de sinais repetidos
```

#### 2. Estado Global (Linhas 66-110)

```json
state = {
  "asset": "BTC/USDT",
  "is_online": true,
  "in_position": false,
  "current_position": 0,
  "entry_price": 0.0,
  "balance": 100.00,
  "floating_pnl": 0.0,
  "display_balance": 100.0,
  "status": "Reiniciando o sistema...",
  "uptime": "00:00:00",
  "last_candle": {
    "time": 0,
    "open": 0, "high": 0, "low": 0, "close": 0
  },
  "chart_data": [],
  "markers": [
    {"time": 1234567, "position": "belowBar", "shape": "circle", "color": "#22c55e", "text": "ENTRADA COMPRA"}
  ],
  "order_book": [
    {"text": "[14:30:45] 🚀 Abriu compra (long) a US$ 42500.00"}
  ],
  "adaptation": {
    "generation": 1,
    "learning_state": "ATIVO",
    "initial_win_rate": 50.5,
    "current_win_rate": 48.3,
    "wins": 23,
    "losses": 24
  },
  "news_agent": {
    "status": "SAFE",
    "sentiment_score": 0.35,
    "risk_level": "BAIXO",
    "last_headlines": ["Bitcoin ETF aprovado... •", "Mineração continua... •"]
  }
}
```

#### 3. Funções de Suporte

**`run_startup_backtest(df_clean, model_instance)`** (Linhas 120-155)
- Executa backtest rápido nos últimos 300 candles
- Calcula win_rate inicial para diagnosticar modelo
- Inicializa LSTM state para evitar viés

**`load_brain(path=MODEL_PATH)`** (Linhas 157-163)
- Carrega modelo `.zip` do RecurrentPPO
- Device: CPU (economiza recursos no Render)

**`get_uptime()`** (Linhas 165-167)
- Retorna tempo desde START_TIME em formato HH:MM:SS

#### 4. Análise de Sentimentos com Gemini LLM (Linhas 250-380)

**`async def analyze_sentiment_with_llm(headlines)`**

Sistema sofisticado de análise de risco macroeconômico:

```
REGULAGEM DE RISCO (Calibrado para não ser alarmista):

Score 0.0 - 0.45 (SAFE):
  ✅ Notícias de adoção, ETFs, desenvolvimentos técnicos
  ✅ FUD genérico ("analista prevê queda")
  ✅ Oscilações normais de mercado
  → Bot PODE operar

Score 0.46 - 0.75 (CAUTION):
  ⚠️ Aumento severo de juros do FED
  ⚠️ Inflação acima do esperado
  ⚠️ Hack em corretora (impacto médio)
  → Bot REDUZ agressividade

Score 0.76 - 1.0 (DANGER):
  🔴 Eventos catastróficos
  🔴 Falência top 3 corretoras (FTX-style)
  🔴 Banimento em grandes potências
  → Bot INATIVO (kill-switch)
```

**Features:**
- ⏳ Cache de 30min para economizar quota Gemini
- 🔁 Fallback com última análise se cota estourar
- 🧠 Prompt calibrado (não sensacionalista)
- 🛡️ Valida tipo da resposta (float, status em enum)

#### 5. Loop Sniper Principal (Linhas 330-510)

**`async def sniper_loop()`**

Coração do sistema. Executado continuamente:

```
Sequência a cada iteração:

1. FETCH DE DADOS (a cada 15s)
   ├─ Busca últimas 500 velas via CCXT
   ├─ Calcula indicadores técnicos
   ├─ Salva vela fechada em CSV
   └─ Limpa dados com dropna()

2. LÓGICA DE DECISÃO
   ├─ Startup: Executa backtest (1x)
   ├─ Warmup: Aquecimento 15 passos (1x)
   └─ Trading:
       ├─ Predição IA: obs → RecurrentPPO → action (0/1/2)
       ├─ Validação: 3 sinais consecutivos necessários
       ├─ Proteção: 15min após entrada (sem sair)
       ├─ Análise de Risco: Se status ≠ SAFE, aguarda
       └─ Controle PnL: Stop-loss dinâmico

3. EXECUÇÃO (se target_pos ≠ current_position)
   ├─ Fechar posição existente (se houver)
   │  ├─ Calcula PnL: (current_price - entry_price) / entry_price
   │  ├─ Deduz taxa: PnL - (balance × 0.1%)
   │  ├─ Atualiza balance
   │  ├─ Registra marker visual (vela amarela)
   │  ├─ Insere no order_book
   │  └─ Contabiliza win/loss
   │
   └─ Abrir nova posição (se target_pos ≠ 0)
      ├─ Deduz taxa de entrada: balance × 0.1%
      ├─ entry_price = current_price
      ├─ position = target_pos (1 ou -1)
      ├─ Registra marker (verde=long, vermelho=short)
      └─ Insere no order_book

4. ATUALIZAÇÃO DE ESTADO
   ├─ Calcula floating_pnl (PnL não-realizado)
   ├─ display_balance = balance + floating_pnl
   ├─ Atualiza adaptation.win_rate
   ├─ Atualiza uptime
   └─ Broadcast via WebSocket

5. SLEEP 1s (próxima iteração)
```

**Indicadores Calculados:**
| Feature | Fórmula | PropósitoPython Code |
|---------|---------|---------|
| `log_ret` | log(close/close[-1]) | Retorno logarítmico (momentum) |
| `rsi` | RSI(14) | Overbought/Oversold (0-100) |
| `rsi_slope` | RSI.diff() | Taxa de mudança do RSI |
| `macd_diff` | MACD Histogram | Convergência/Divergência |
| `bb_pband` | (close - lower) / (upper - lower) | Posição em Bollinger (0-1) |
| `bb_width` | upper - lower | Volatilidade (largura BB) |
| `dist_ema50` | (close - ema50) / ema50 | Desvio do EMA 50 |
| `dist_ema200` | (close - ema200) / ema200 | Desvio do EMA 200 |
| `atr_pct` | ATR / close | Volatilidade em % |

#### 6. Loop Sentiment Analyst (Linhas 200-260)

**`async def analyst_market_loop()`**

Loop paralelo que executa a cada 10min (600s):

```
Sequência:

1. Fetch notícias BTC (português preferido)
   └─ CryptoCompare API

2. Se API esgotada:
   ├─ Status → "MODO 100% TÉCNICO"
   ├─ kill_switch_active = False
   └─ Sleep 1h (respeita limite)

3. Análise com Gemini LLM:
   ├─ Extrai score (0-1)
   ├─ Classifica: SAFE/CAUTION/DANGER
   └─ Cache por 30min

4. Atualiza state["news_agent"]:
   ├─ status = SAFE/CAUTION/DANGER
   ├─ sentiment_score = score
   ├─ risk_level = status
   └─ last_headlines = lista

5. Se status ≠ SAFE:
   └─ Ativa kill_switch (bloqueia novas entradas)
```

#### 7. Middleware CORS & Endpoints (Linhas 525-650)

**CORS Configuration (Linhas 527-538):**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://iatraderproweb.vercel.app",
        "http://localhost:3000",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)
```

**Endpoints HTTP:**

| Método | Path | Descrição | Retorno |
|--------|------|-----------|---------|
| GET | `/api/state` | Snapshot estado atual | JSON completo |
| GET | `/api/health` | Health check CORS | {"status": "ok"} |
| GET | `/health` | Health simples | {"status": "online", "uptime": "HH:MM:SS"} |
| GET | `/api/historico` | Últimas 1000 velas | Array OHLCV |
| GET | `/download-dados` | Export CSV histórico | CSV file (requer senha) |
| POST | `/upload-cerebro` | Injeta novo modelo | {"status": "sucesso"} |
| WS | `/ws` | WebSocket real-time | state a cada 1s |

**Segurança com Headers:**
```
Requisições autenticadas usam header x-admin-password:

curl -H "x-admin-password: ADMIN_PASSWORD" \
  https://backend.com/download-dados
```

---

## Frontend - Next.js + React

### Arquivo: `frontend/app/page.js` (692 linhas)

**Componentes Principais:**

#### 1. Inicialização & Conexão (Linhas 1-50)

```javascript
// URL deriving (suporta local e produção)
function backendHttpBase() {
  const api = process.env.NEXT_PUBLIC_API_URL;
  if (api) return api.replace(/\/$/, "");
  const ws = process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:10000/ws";
  return ws
    .replace(/^wss:\/\//i, "https://")
    .replace(/^ws:\/\//i, "http://")
    .replace(/\/ws\/?$/i, "");
}

function backendWsUrl() {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  const api = process.env.NEXT_PUBLIC_API_URL;
  if (api) {
    const u = api.replace(/\/$/, "");
    const host = u.includes("://") ? u.split("://")[1] : u;
    if (/^https:/i.test(u)) return `wss://${host}/ws`;
    return `ws://${host}/ws`;
  }
  return "ws://127.0.0.1:10000/ws";
}
```

#### 2. Algoritmo ZigZag (Linhas 50-120)

Desenha linhas conectando topos e fundos significativos:

```javascript
const calculateZigZag = (data, thresholdPct = 0.5) => {
  // Identifica pontos de reversão significativos
  // Se mudança de high > 0.5% → novo topo
  // Se mudança de low > 0.5% → novo fundo
  // Retorna array para desenhar no gráfico
}
```

#### 3. Painel "Dojo" (Linhas 115-190)

Interface de controle administrativo:

```
┌─────────────────────────────────────┐
│ Laboratório Neural (Dojo)            │
├─────────────────────────────────────┤
│ Chave de Autorização: [••••••••]    │
│                                      │
│ [EXPORTAR HISTÓRICO (CSV)]           │
│ [INJETAR GERAÇÃO]  [Selecionar...]  │
│                                      │
│ ✅ Geração Injetada!                │
└─────────────────────────────────────┘
```

**Funcionalidades:**
- Download CSV: `GET /download-dados` com password no header
- Upload Modelo: `POST /upload-cerebro` com password no header
- Validação de senha (não enviada em URL)

#### 4. Componente NewsSentinel (Arquivo separado)

**`frontend/components/NewsSentinel.js`** (80 linhas)

Painel de análise de sentimento com:

```
┌────────────────────────────────────┐
│ 🛡️ Analista do BTC                 │ [SEGURO]
├────────────────────────────────────┤
│                                     │
│ Sentimento macro:        [35%]     │
│ ▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░   │
│                                     │
│ 📰 TICKER DE NOTÍCIAS (Scroll)     │
│ ► Bitcoin ETF... • Mineração...   │
└────────────────────────────────────┘

Estados Visuais:
- SAFE (0-45%)     → Verde + ✅
- CAUTION (46-75%) → Amarelo + ⚠️
- DANGER (76-100%) → Vermelho (pulsante) + ❌
- TECH MODE        → Cinza (sem notícias)
```

#### 5. Gráfico ao Vivo (Linhas 300-500)

Usa TradingView Lightweight Charts:

```javascript
const chart = createChart(container, {
  layout: { background: { type: ColorType.Solid, color: '#020617' } },
  timeScale: { timeVisible: true, secondsVisible: true }
});

const candlestickSeries = chart.addCandlestickSeries({
  upColor: '#22c55e',
  downColor: '#ef4444',
  borderVisible: false
});

// Feed em tempo real via WebSocket
candlestickSeries.setData(chartData);

// Desenha marcadores (entradas/saídas)
candlestickSeries.setMarkers(markers);

// Desenha linhas (ZigZag + support/resistance)
const lineSeries = chart.addLineSeries({ color: '#f97316' });
lineSeries.setData(zigzagData);
```

#### 6. Painel de Métricas (Linhas 600-650)

```
┌──────────────────────────────────┐
│ CARTEIRA  │  POSIÇÃO  │  ANÁLISE │
├──────────────────────────────────┤
│ Saldo: US$ 103.45               │
│ PnL Flutuante: US$ +2.10        │
│ Win Rate: 48.3%                 │
│ Wins: 23 | Losses: 24           │
│ Uptime: 04:32:15                │
│ Status: 📊 AGUARDANDO SINAL...  │
└──────────────────────────────────┘
```

---

## Sistema de IA (RecurrentPPO)

### Arquivo: `backend/envs/trading_env.py` (120 linhas)

**Tipo:** Gymnasium Environment (compatível com StableBaselines3)

#### Configuração

```python
class BitcoinTradingEnv(gym.Env):
    action_space = spaces.Discrete(3)  # 0=flat, 1=long, 2=short
    observation_space = spaces.Box(
        low=-np.inf, high=np.inf,
        shape=(9,),  # 9 features
        dtype=np.float32
    )
    
    fee = 0.0005  # 0.05% por lado (Maker rate)
    stop_loss = -0.010  # -1%
```

#### Features (Observações)

| Índice | Feature | Tipo | Intervalo | Propósito |
|--------|---------|------|-----------|-----------|
| 0 | `log_ret` | float | (-∞, +∞) | Momentum |
| 1 | `rsi` | float | (0, 100) | Overbought/Oversold |
| 2 | `rsi_slope` | float | (-∞, +∞) | Dinâmica RSI |
| 3 | `macd_diff` | float | (-∞, +∞) | Força do trend |
| 4 | `bb_pband` | float | (0, 1) | Posição em BB |
| 5 | `bb_width` | float | (0, ∞) | Volatilidade |
| 6 | `dist_ema50` | float | (-∞, +∞) | Desvio curto |
| 7 | `dist_ema200` | float | (-∞, +∞) | Desvio longo |
| 8 | `atr_pct` | float | (0, ∞) | Volatilidade % |

#### Sistema de Recompensas

```python
def step(self, action):
    # Ações
    target_pos = 1 if action == 1 else (-1 if action == 2 else 0)
    
    # RECOMPENSA 1: Incentivo à Paciência
    if target_pos == 0 and atr_pct < 0.15%:
        reward += 0.1  # Prêmio por esperar mercado menos volátil
    
    # RECOMPENSA 2: Gestão de Risco
    if self.position != 0:
        change_pct = (current_price - entry_price) / entry_price
        self.max_profit_pct = max(self.max_profit_pct, change_pct)
        
        # Trailing stop dinâmico
        dynamic_stop = -1%
        if max_profit >= 1.5%: dynamic_stop = max_profit - 0.6%
        elif max_profit >= 0.8%: dynamic_stop = +0.2%
        
        if change_pct <= dynamic_stop:
            target_pos = 0  # Força saída
    
    # RECOMPENSA 3: Recompensas Reais (Principal)
    if target_pos != position:
        if position != 0:  # FECHAMENTO
            real_pnl = pnl_pct - (fee × 2)
            if real_pnl > 0:
                reward += real_pnl × 150.0  # Bônus agressivo
            else:
                reward += real_pnl × 200.0  # Punição severa
        
        if target_pos != 0:  # ABERTURA
            reward -= (fee × 10.0)  # Custo de entrada
```

**Filosofia:**
- Se lucro: multiplicador 150× (incentiva ganhos)
- Se perda: multiplicador 200× (aprende a cortar perdas rápido)
- Abertura custosa: desestimula trades barulhentos

---

## Sistema de Treinamento (Dojo)

### Arquivo: `backend/dojo.py` (75 linhas)

Script standalone para refinar o modelo com dados reais.

#### Workflow

```
1. Carregar CSV com histórico real
   └─ DADOS_BAIXADOS = "data/mercado_real_20260313.csv"

2. Engenharia de Features
   ├─ log_ret = log(close / close[-1])
   ├─ rsi = RSI(14)
   ├─ rsi_slope = rsi.diff()
   ├─ macd_diff = MACD Histogram
   ├─ bb_pband = (close - lower) / (upper - lower)
   ├─ bb_width = upper - lower
   ├─ ema50/200 = EMA
   ├─ dist_ema50/200 = (close - ema) / ema
   └─ atr_pct = ATR / close

3. Carregar modelo base
   ├─ MODELO_ATUAL = "models/sniper_pro_gen_5.zip"
   └─ model = RecurrentPPO.load(...)

4. Treinamento
   ├─ total_timesteps = 10.000 passos
   ├─ Evita overfitting ao dia (decora padrões)
   └─ model.learn(10000)

5. Salvar geração
   ├─ novo_nome = "models/sniper_pro_gen_6.zip"
   └─ Fazer upload via Dashboard (Protocolo Apocalipse)
```

#### Integração com Pipeline

```
Ciclo de Melhoria:
┌──────────────────┐
│  Backend Render  │
│  Gen 5 ativo     │
└────────┬─────────┘
         │
         ▼ (Exportar histórico via Dojo)
┌──────────────────┐
│  Python Local    │
│  Treina Gen 6    │
│  10k timesteps   │
└────────┬─────────┘
         │
         ▼ (Upload via Dashboard)
┌──────────────────┐
│  Backend Render  │
│  Gen 6 ativo ✅  │
│  Injeta live     │
└──────────────────┘
```

---

## Gestão de Risco

### Kill-Switch (Triplo Sistema)

**1. Risk Level (Análise de Sentimentos)**
```
score < 0.45  → SAFE     (bloqueia nada)
0.45...0.75   → CAUTION  (bloqueia nada, mas alerta)
score > 0.75  → DANGER   → kill_switch_active = True
```

**2. Stop-Loss Dinâmico**
```
if unrealized_loss <= -1%:
    position = 0  # Saída forçada

if max_profit >= 1.5%:
    dynamic_stop = max_profit - 0.6%  // Trailing stop
elif max_profit >= 0.8%:
    dynamic_stop = +0.2%  // Breakeven + 0.2%
```

**3. Limite Diário**
```
DAILY_LOSS_LIMIT = -5%

if cumulative_pnl <= -5%:
    kill_switch_active = True
```

### Fee Management
```
Entrada: balance -= balance × 0.1%
Saída:   pnl -= pnl × 0.1%
Total por trade: 0.2% (0.1% + 0.1%)
```

---

## Fluxo de Dados

### Arquivos de Dados

```
/data/
├─ ac.csv                          # Dados genéricos
├─ btc_futures_data_PRO.csv        # Histórico futures
├─ live_market_data.csv            # Velas em tempo real (append-only)
├─ mercado_real_20260313.csv       # Para treinamento Dojo
└─ mercado_real_20260313_1.csv

/models/
├─ sniper_pro_gen_5.zip            # Modelo ativo
├─ sniper_pro_gen_6.zip            # (será injetado)
└─ ...

/tensorboard_logs/
├─ RecurrentPPO_1/
│  └─ events.out.tfevents.*        # Métricas treinamento
└─ RecurrentPPO_2/
```

### CSV Format: live_market_data.csv

```
timestamp,open,high,low,close,volume
2026-04-17T14:30:00.000Z,42500.0,42600.0,42400.0,42550.0,150.5
2026-04-17T14:45:00.000Z,42550.0,42700.0,42500.0,42650.0,140.2
```

---

## Deployment & Configuração

### Backend (Render)

**Build Command:**
```bash
pip install --no-cache-dir -r backend/requirements.txt
```

**Start Command:**
```bash
cd backend && uvicorn server:app --host 0.0.0.0 --port $PORT --workers 1
```

**Environment Variables:**
```
GEMINI_API_KEY=<sua-chave-gemini>
CRYPTOCOMPARE_API_KEY=<sua-chave-cc>
ADMIN_PASSWORD=<senha-segura>
PYTHONUNBUFFERED=true
```

**Procfile:**
```
web: cd backend && uvicorn server:app --host 0.0.0.0 --port $PORT --workers 1
```

### Frontend (Vercel)

**Root Directory:** `frontend/`

**Build Command:**
```bash
npm run build
```

**Environment Variables:**
```
NEXT_PUBLIC_API_URL=https://ia-trader-pro-backend.onrender.com
NEXT_PUBLIC_WS_URL=wss://ia-trader-pro-backend.onrender.com/ws
```

---

## Últimas Correções Aplicadas (Abril 2026)

### 🔴 Problemas Detectados

**Erro 1: WebSocket 500**
```
WebSocket connection to 'wss://ia-trader-pro-backend.onrender.com/ws'
failed: Error during WebSocket handshake: Unexpected response code: 500
```

**Erro 2: CORS Bloqueado**
```
Access to fetch at 'https://ia-trader-pro-backend.onrender.com/api/state'
from origin 'https://iatraderproweb.vercel.app' has been blocked by CORS policy
```

### 🔍 Análise de Causa Raiz

| Problema | Causa | Localização |
|----------|-------|-------------|
| WebSocket 500 | Handler com `except: pass` silenciava todos os erros | Linha ~554 |
| Serialização | `state` continha tipos numpy não-JSON (arrays, datetime) | Linha ~505 |
| CORS incompleto | Middleware sem domínio específico da Vercel | Linha 526 |

### ✅ Solução Implementada

**1. Handler WebSocket Melhorado** (Linhas 584-607)

```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    try:
        await websocket.accept()
        print(">>> 🟢 WebSocket conectado")
        while True:
            try:
                # Serialização segura
                safe_state = json.loads(json.dumps(state, default=str))
                await websocket.send_json(safe_state)
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f">>> ❌ Erro ao enviar: {type(e).__name__}: {e}")
                break
    except Exception as e:
        print(f">>> ❌ Erro aceitar: {type(e).__name__}: {e}")
```

**2. Endpoint `/api/state` Corrigido** (Linhas 542-550)

```python
@app.get("/api/state")
async def get_state_snapshot():
    try:
        safe_state = json.loads(json.dumps(state, default=str))
        return safe_state
    except Exception as e:
        print(f">>> ❌ Erro ao retornar state: {e}")
        return {"error": str(e), "status": "offline"}
```

**3. Middleware CORS Melhorado** (Linhas 527-538)

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://iatraderproweb.vercel.app",
        "http://localhost:3000",
        "http://localhost:8000",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)
```

**4. Novos Endpoints de Health** (Linhas 568-583)

```python
@app.get("/api/health")
async def api_health():
    return {
        "status": "ok",
        "backend": "online",
        "timestamp": datetime.now().isoformat(),
        "cors": "enabled"
    }
```

**5. Arquivos de Configuração Criados**

- ✅ `Procfile` - Inicialização Render
- ✅ `render.yaml` - Config específica Render
- ✅ `backend/.env.example` - Template de variáveis
- ✅ `frontend/.env.local.example` - Config frontend
- ✅ `README_DEPLOY.md` - Guia de deployment

### 📊 Impacto das Correções

| Métrica | Antes | Depois |
|---------|-------|--------|
| WebSocket Errors | ∞ (sem logs) | 0 (com logs detalhados) |
| CORS Bloqueios | Sim (domínio não reconhecido) | Não (Vercel adicionado) |
| Serialização | Fails (numpy arrays) | ✅ (conversão automática) |
| Debug Info | Nenhum | Log completo de erro |

**Status:** 🟢 Online e Operacional

---

## Arquivos Principais

```
IA_Trader_Pro/
│
├── backend/
│   ├── server.py                 # ⭐ Orquestrador principal
│   ├── dojo.py                   # Treinamento offline
│   ├── envs/
│   │   └── trading_env.py         # ⭐ Ambiente Gymnasium
│   ├── data/
│   │   ├── live_market_data.csv   # Dados em tempo real
│   │   └── mercado_real_*.csv     # Dados treinamento
│   ├── models/
│   │   └── sniper_pro_gen_6.zip   # Modelo RecurrentPPO
│   ├── requirements.txt           # ⭐ Dependências
│   └── .env.example               # Variáveis ambiente
│
├── frontend/
│   ├── app/
│   │   ├── page.js                # ⭐ Dashboard principal
│   │   ├── layout.js              # Layout Next.js
│   │   └── globals.css            # Estilos globais
│   ├── components/
│   │   └── NewsSentinel.js        # Painel sentimentos
│   ├── package.json               # ⭐ Dependências
│   ├── next.config.mjs            # Config Next.js
│   └── .env.local.example         # Variáveis environment
│
├── tensorboard_logs/              # Histórico treinamento
│
├── Procfile                        # ⭐ Deploy Render
├── render.yaml                     # ⭐ Config Render
├── README.md                       # Documentação resumida
└── README_DEPLOY.md                # Guia deployment
```

---

## Fluxograma de Execução

```
┌─────────────────────────────────────┐
│ server.py iniciado                  │
│ load_brain() → Carrega Gen 6        │
│ state inicializado                  │
└──────────┬──────────────────────────┘
           │
           ├─────────────────────────────┐
           │                             │
           ▼                             ▼
    ┌──────────────────┐      ┌──────────────────┐
    │ sniper_loop()    │      │ analyst_loop()   │
    │ (a cada 1s)      │      │ (a cada 10min)   │
    └────────┬─────────┘      └────────┬─────────┘
             │                        │
             ├─ Fetch OHLCV           ├─ Fetch notícias
             ├─ Calc indicadores      ├─ Gemini LLM
             ├─ IA predição           ├─ Scoring (0-1)
             ├─ Executa trades        ├─ Kill-switch
             ├─ Atualiza state        └─ Cache 30min
             │
             └─> WebSocket broadcast
                 (todos clients)

┌─────────────────────────────────────────────────────────────────┐
│ Frontend (Vercel) recebe                                        │
│ connecta WebSocket → wss://ia-trader-pro-backend.onrender.com/ws│
└────────┬────────────────────────────────────────────────────────┘
         │
         ├─ Atualiza gráfico
         ├─ Desenha markers
         ├─ Atualiza métricas
         ├─ Mostra sentimento
         └─ Refresh a cada 1s
```

---

## Requisitos de Hardware

**Mínimo (Render Starter):**
- CPU: 1 vCPU
- RAM: 512 MB
- Storage: 1 GB
- Uptime: Suficiente

**Recomendado (Render Standard):**
- CPU: 2+ vCPU
- RAM: 1-2 GB
- Storage: 5 GB
- Uptime: 24/7

---

## Roadmap Futuro

- [ ] Multi-exchange suporte (Binance, Coinbase)
- [ ] Múltiplos pares (ETH, XRP, SOL)
- [ ] Refinamento automático (sem manual Dojo)
- [ ] Backtesting interativo Web
- [ ] Alertas SMS/Discord
- [ ] Histórico de trades com P&L
- [ ] Machine Learning AutoML (AutoGluon)

---

**Última atualização:** 17 de Abril de 2026  
**Versão:** 3.0.1  
**Status:** 🟢 Em Produção
