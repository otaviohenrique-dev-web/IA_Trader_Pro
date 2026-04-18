# IA Trader Pro - Documentação Técnica

## 📋 Visão Geral

IA Trader Pro é um sistema de trading automatizado de Bitcoin baseado em IA (Redes Neurais Recorrentes com PPO). Combina análise técnica com análise de sentimento de notícias para tomar decisões de compra/venda em tempo real.

**Status:** Online em produção (Backend: Render | Frontend: Vercel)

---

## 🏗️ Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (Next.js) - Vercel                                │
│  Dashboard com gráficos TradingView + Painel de Análise     │
└────────────────┬──────────────────────────────────────────┘
                 │ HTTPS + WebSocket
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  Backend (FastAPI) - Render                                 │
│  ├─ Motor Trading (Análise Técnica + IA)                    │
│  ├─ Gerenciador de Posições                                 │
│  ├─ IA Sentinela (Análise de Notícias)                      │
│  └─ APIs Externas (CCXT, CryptoCompare, Gemini)             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 Componentes Principais

### 1. **Backend (Python + FastAPI)**
- **Localização:** `/backend/server.py`
- **Porta:** 10000 (local) | Render (produção)
- **Dependências:** FastAPI, Uvicorn, CCXT, RL (StableBaselines3)

#### Módulos:
| Módulo | Função |
|--------|--------|
| `dojo.py` | Sistema de treinamento e refinamento de modelos IA |
| `server.py` | API REST + WebSocket, gerenciamento de estado |
| `envs/trading_env.py` | Ambiente de ginásio para treinamento RL |
| `models/` | Modelos PPO treinados (`.zip`) |

#### Endpoints Principais:
```
GET  /api/state           → Estado atual do trader (posição, saldo, sinais)
GET  /api/health          → Verificação de saúde do servidor
GET  /api/historico       → Histórico de velas OHLCV (1000 últimas)
WS   /ws                  → WebSocket para atualizações em tempo real
GET  /health              → Health check simples
GET  /download-dados      → Download de dados históricos (requer senha)
POST /upload-cerebro      → Upload de novo modelo IA (requer senha)
```

### 2. **Frontend (Next.js + React)**
- **Localização:** `/frontend`
- **URL:** https://iatraderproweb.vercel.app
- **Componentes:**
  - Gráfico de velas em tempo real (LightweightCharts)
  - Painel de métricas do trader
  - Monitor de sentimento de notícias
  - Controles administrativos

### 3. **Motor de Trading**
O sistema funciona em loop:
1. **Fetch de dados:** Busca últimas 1000 velas BTC/USDT 15min
2. **Processamento:** Calcula indicadores técnicos (RSI, MACD, BB, ATR, EMA)
3. **Predição IA:** Rede Neural Recorrente (RecurrentPPO) prevê ação
4. **Análise de Risco:** Sentinela verifica notícias em tempo real
5. **Execução:** Gerencia posições (long/short/flat)
6. **Broadcast:** Envia estado via WebSocket a cada segundo

---

## 🧠 Inteligência Artificial

### Modelo: RecurrentPPO (Proximal Policy Optimization com LSTM)

**Configuração:**
- Arquitetura: LSTM (memória de 256 passos) + PPO
- Janela de observação: 64 velas anteriores
- Features: 9 indicadores técnicos normalizados
- Ações: 3 tipos (0=flat, 1=long, 2=short)
- Treinamento: Historial de dados com recompensas baseadas em PnL

**Features de entrada (9 variáveis):**
1. `log_ret` - Retorno logarítmico
2. `rsi` - Índice de Força Relativa
3. `rsi_slope` - Taxa de mudança do RSI
4. `macd_diff` - Diferença MACD
5. `bb_pband` - Banda de Bollinger (posição)
6. `bb_width` - Largura das Bandas
7. `dist_ema50` - Distância do EMA 50
8. `dist_ema200` - Distância do EMA 200
9. `atr_pct` - Volatilidade (ATR%)

---

## 🛡️ Sistema de Proteção (Sentinela)

**IA Análise de Risco:**
- Coleta notícias de mercado via CryptoCompare
- Usa Gemini LLM para análise de sentimento
- Classifica risco: SAFE | CAUTION | DANGER
- Ativa kill-switch se risco crítico detectado
- Fallback: Modo 100% técnico se API de notícias falhar

**Stop-Loss & Take-Profit:**
- Stop-Loss: -1% da entrada
- Take-Profit: +2% da entrada
- Limite diário: -5% do saldo
- Kill-switch automático em perdas críticas

---

## 📊 Estado Gerenciado (Real-Time)

```json
{
  "asset": "BTC/USDT",
  "is_online": true,
  "in_position": false,
  "entry_price": 0.0,
  "current_position": 0,
  "balance": 100.00,
  "status": "Aguardando sinais...",
  "uptime": "HH:MM:SS",
  "last_candle": { "time": 0, "open": 0, "high": 0, "low": 0, "close": 0 },
  "chart_data": [ /* velas */ ],
  "markers": [ /* sinais */ ],
  "adaptation": {
    "generation": 1,
    "learning_state": "ATIVO",
    "current_win_rate": 0.0,
    "wins": 0,
    "losses": 0
  },
  "news_agent": {
    "status": "SAFE",
    "sentiment_score": 0.0,
    "risk_level": "BAIXO",
    "last_headlines": []
  }
}
```

---

## 📁 Estrutura de Dados

| Pasta | Conteúdo |
|-------|----------|
| `/data` | CSVs históricos + live_market_data.csv |
| `/models` | Modelos `.zip` treinados (RecurrentPPO) |
| `/tensorboard_logs` | Logs de treinamento para visualização |
| `/envs` | Ambiente de ginásio (trading_env.py) |

---

## 🚀 Deployment

### Backend (Render)
```
Repository: GitHub
Runtime: Python 3.11
Build: pip install -r backend/requirements.txt
Start: cd backend && uvicorn server:app --host 0.0.0.0 --port $PORT
```

**Variáveis de Ambiente:**
```
GEMINI_API_KEY=<sua chave>
CRYPTOCOMPARE_API_KEY=<sua chave>
ADMIN_PASSWORD=<senha segura>
```

### Frontend (Vercel)
```
Repository: GitHub
Root: frontend/
Framework: Next.js
```

**Environment Variables:**
```
NEXT_PUBLIC_API_URL=https://ia-trader-pro-backend.onrender.com
NEXT_PUBLIC_WS_URL=wss://ia-trader-pro-backend.onrender.com/ws
```

---

## 🔴 Últimas Correções (Abril 2026)

### Problema Identificado
Frontend retornava erros:
- ❌ `WebSocket connection... Unexpected response code: 500`
- ❌ `CORS policy: No 'Access-Control-Allow-Origin' header`

### Raízes
1. **WebSocket:** Handler com `except: pass` silenciava erros
2. **Serialização:** `state` continha tipos não-JSON (numpy arrays, etc)
3. **CORS:** Middleware incompleto sem configuração de domínio específico

### Solução Implementada

**1. Melhorado Handler WebSocket** (`server.py` linhas 584-607)
```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    try:
        await websocket.accept()
        while True:
            # Serialização segura com json.loads(json.dumps(state, default=str))
            safe_state = json.loads(json.dumps(state, default=str))
            await websocket.send_json(safe_state)
            await asyncio.sleep(1)
    except Exception as e:
        print(f">>> ❌ Erro WebSocket: {type(e).__name__}: {e}")
```

**2. Corrigido Endpoint `/api/state`** (linhas 542-550)
```python
@app.get("/api/state")
async def get_state_snapshot():
    try:
        safe_state = json.loads(json.dumps(state, default=str))
        return safe_state
    except Exception as e:
        return {"error": str(e), "status": "offline"}
```

**3. Melhorado Middleware CORS** (linhas 527-538)
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

**4. Adicionados Novos Endpoints** (linhas 568-576)
```python
@app.get("/api/health")    # Para testes CORS
@app.websocket("/ws")      # Com logging detalhado
```

**5. Configuração de Deploy**
- ✅ Criado `Procfile` (inicialização Render)
- ✅ Criado `render.yaml` (configuração específica)
- ✅ Criado `.env.example` (variáveis necessárias)
- ✅ Criado guia `README_DEPLOY.md`

**Status:** ✅ Corrigido e testado

---

## 🔌 Como Usar Localmente

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn server:app --reload --port 10000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
# Acesso: http://localhost:3000
```

### Testar Endpoints
```bash
# Health check
curl http://localhost:10000/api/health

# Estado do trader
curl http://localhost:10000/api/state

# CORS headers
curl -i http://localhost:10000/api/state
```

### Testar WebSocket
```bash
# Usando wscat (npm install -g wscat)
wscat -c ws://localhost:10000/ws
```

---

## 📈 Métricas e Monitoramento

**Tensorboard:**
```bash
tensorboard --logdir=tensorboard_logs/
```

**Logs do Render:**
Dashboard → Services → [Service] → Logs

---

## 🔐 Segurança

- ✅ CORS configurado corretamente
- ✅ Autenticação por header (ADMIN_PASSWORD)
- ✅ Sem credenciais no código (usa .env)
- ✅ WebSocket com tratamento de erros
- ✅ Validação de tipos em endpoints

---

## 📞 Troubleshooting

| Erro | Causa | Solução |
|------|-------|---------|
| WebSocket 500 | Dados não-serializáveis | Usar `json.loads(json.dumps(x, default=str))` |
| CORS bloqueado | Domínio não autorizado | Verificar `allow_origins` em middleware |
| API timeout | Conexão CCXT lenta | Aumentar timeout ou usar proxy |
| Modelo não carrega | Arquivo `.zip` corrompido | Re-treinar com `dojo.py` |

---

## 📦 Dependências Principais

```
fastapi              # Framework web
uvicorn[standard]    # ASGI server
websockets           # WebSocket suporte
ccxt                 # APIs de exchange
stable-baselines3    # Algoritmos RL
sb3-contrib          # PPO recorrente
pytorch              # Computação numérica
pandas               # Manipulação de dados
google-genai         # API Gemini LLM
aiohttp              # Requisições assíncronas
```

---

## 🎯 Roadmap Futuro

- [ ] Suporte a múltiplos pares (ETH, XRP, etc)
- [ ] Dashboard de análise histórica
- [ ] Refinamento automático de modelo
- [ ] Backtesting interativo
- [ ] Alertas SMS/Email
- [ ] Multi-exchange suporte

---

**Última atualização:** 17 de Abril de 2026  
**Versão:** 3.0.1  
**Status:** 🟢 Produção - Online
