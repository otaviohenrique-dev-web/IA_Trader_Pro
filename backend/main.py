#!/usr/bin/env python3
"""Ponto de entrada do Render: sobe o FastAPI em UM único processo (o robô guarda estado em memória)."""
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import uvicorn

from server import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f">>> Servidor em 0.0.0.0:{port} | health: /health | estado: /api/state")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info", timeout_keep_alive=75,
                access_log=False, proxy_headers=True, forwarded_allow_ips="*")
