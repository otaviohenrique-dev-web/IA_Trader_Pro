#!/usr/bin/env python3
"""
Main entry point for Render deployment.
Inicializa o servidor FastAPI com MÁXIMA rapidez.
"""

import os
import sys

# Definir PATH antes de tudo
os.chdir(os.path.dirname(os.path.abspath(__file__)))

print(">>> [1/5] Verificando ambiente...")
port = os.environ.get("PORT", "10000")
host = "0.0.0.0"

print(f">>> [2/5] Será iniciado em {host}:{port}")

# Importa Uvicorn PRIMEIRO (leve)
print(">>> [3/5] Importando Uvicorn...")
import uvicorn

# AGORA importa a app (pesado, mas uvicorn já está pronto)
print(">>> [4/5] Importando aplicação...")
from server import app

print(">>> [5/5] Iniciando servidor...")
print(f">>> ✅ Servidor iniciando em {host}:{port}")
print(f">>> 📍 Acesso: http://localhost:{port}")
print(f">>> 🔗 Health: http://localhost:{port}/health")

# Inicia Uvicorn
uvicorn.run(
    app,
    host=host,
    port=int(port),
    log_level="info",
    timeout_keep_alive=75,
    access_log=True,
    loop="auto",
)
