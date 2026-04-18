# Guia de Deployment - IA Trader Pro

## Render (Backend)

### 1. Pré-requisitos
- Repositório no GitHub
- Conta no Render (render.com)

### 2. Variáveis de Ambiente no Render
No dashboard do Render, configure as seguintes variáveis de ambiente:

```
GEMINI_API_KEY=your_gemini_api_key
CRYPTOCOMPARE_API_KEY=your_cryptocompare_api_key
ADMIN_PASSWORD=your_secure_password
PYTHONUNBUFFERED=true
```

### 3. Deploy no Render
1. Conectar repositório GitHub ao Render
2. Selecionar "Web Service"
3. Apontar raiz do repositório
4. Runtime: Python 3.11
5. Build Command: `pip install --no-cache-dir -r backend/requirements.txt`
6. Start Command: `cd backend && uvicorn server:app --host 0.0.0.0 --port $PORT --workers 1`

### 4. Erros Comuns

#### ❌ WebSocket erro 500
**Causa:** Dados não-serializáveis em `state` ou exceçõesnão tratadas
**Solução:** Verifique se há erros no backend. Os logs do Render mostram claramente.

#### ❌ CORS bloqueado
**Causa:** Frontend em domínio diferente do backend
**Solução:** Variáveis de ambiente do backend devem ter:
- `GEMINI_API_KEY` e `CRYPTOCOMPARE_API_KEY` configuradas
- Middleware CORS está ativado em `server.py`

---

## Vercel (Frontend)

### 1. Pré-requisitos
- Repositório no GitHub
- Conta no Vercel (vercel.com)

### 2. Variáveis de Ambiente no Vercel
Configure estas variáveis no dashboard do Vercel:

```
NEXT_PUBLIC_API_URL=https://ia-trader-pro-backend.onrender.com
NEXT_PUBLIC_WS_URL=wss://ia-trader-pro-backend.onrender.com/ws
```

**Importante:** Substituir URLs pelos seus endereços reais do Render

### 3. Deploy no Vercel
1. Conectar repositório GitHub ao Vercel
2. Selecionar "Next.js"
3. Apontar pasta: `frontend`
4. Variáveis de Ambiente: As listadas acima
5. Deploy

### 4. next.config.mjs
Verifique se o arquivo permite requisições ao backend:
```javascript
// Não há proxy necessário se usando CORS correto
```

---

## Testes Locais

### Backend
```bash
cd backend
python -m uvicorn server:app --reload --host 0.0.0.0 --port 10000
```

Teste CORS:
```bash
curl -i -X OPTIONS http://localhost:10000/api/state \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET"
```

Teste Health:
```bash
curl http://localhost:10000/health
curl http://localhost:10000/api/health
```

### Frontend
```bash
cd frontend
npm install
npm run dev
# Acesso em http://localhost:3000
```

---

## Troubleshooting

### 1. Verificar Logs do Render
```
Dashboard > Services > [Seu Service] > Logs
```

### 2. Verificar Variáveis de Ambiente
```
Dashboard > Services > [Seu Service] > Environment
```

### 3. Testar Endpoint do Backend
```bash
curl https://ia-trader-pro-backend.onrender.com/api/health
```

### 4. Verificar Console do Navegador
- F12 → Console
- Procure por erros CORS
- Procure por erros WebSocket

---

## Estrutura de Pasta para Deploy

```
.
├── backend/
│   ├── requirements.txt
│   ├── server.py
│   ├── .env.example  (Configure as variáveis)
│   ├── data/
│   ├── envs/
│   ├── models/
│   └── __pycache__/
├── frontend/
│   ├── package.json
│   ├── next.config.mjs
│   ├── app/
│   └── components/
├── Procfile
├── render.yaml
└── README_DEPLOY.md
```
