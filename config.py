"""
Configuração do Polymarket Macro Bot
"""
import os
from dotenv import load_dotenv
load_dotenv()

# ─── APIs ──────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GAMMA_API  = "https://gamma-api.polymarket.com"
CLOB_API   = "https://clob.polymarket.com"
BINANCE_API = "https://fapi.binance.com"

# ─── Wallet Polymarket (para modo real) ────────────────────
POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY", "")
POLY_FUNDER      = os.getenv("POLY_FUNDER", "")

# ─── Estratégia ────────────────────────────────────────────
BET_SIZE_USD      = 3.0     # $3 por trade
MAX_POSITIONS     = 20      # 20 simultâneos
MIN_EDGE          = 0.02    # edge mínimo 2%
BTC_MOVE_TRIGGER  = 2.0     # % de movimento do BTC para disparar
MIN_CONFIDENCE    = 0.60    # confiança mínima do Claude

# ─── Monitoramento ─────────────────────────────────────────
SCAN_INTERVAL     = 30      # segundos entre scans
NEWS_INTERVAL     = 120     # segundos entre busca de notícias
BTC_INTERVAL      = 10      # segundos entre atualização BTC

# ─── Modo ──────────────────────────────────────────────────
PAPER_TRADING  = True
PAPER_BALANCE  = 500.0

# ─── API ───────────────────────────────────────────────────
API_PORT = 8001
