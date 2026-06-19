"""
Monitor de BTC e notícias macro em tempo real
"""
import asyncio
import aiohttp
import time
import json
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import BINANCE_API, BTC_MOVE_TRIGGER, ANTHROPIC_API_KEY


class MarketMonitor:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self.btc_prices: list = []          # últimos 30 preços 1min
        self.btc_current: float = 0.0
        self.btc_1h_move: float = 0.0       # movimento da última hora
        self.btc_24h_move: float = 0.0
        self.recent_news: list = []          # notícias recentes analisadas
        self.alerts: list = []              # alertas ativos
        self.running = False

    async def start(self):
        self._session = aiohttp.ClientSession()
        self.running = True
        asyncio.create_task(self._btc_loop())
        asyncio.create_task(self._news_loop())
        print("[Monitor] Iniciado — monitorando BTC e notícias")

    async def stop(self):
        self.running = False
        if self._session:
            await self._session.close()

    # ── BTC em tempo real ─────────────────────────────────────────────────────

    async def _btc_loop(self):
        while self.running:
            try:
                # Preço atual
                async with self._session.get(
                    f"{BINANCE_API}/fapi/v1/ticker/price",
                    params={"symbol": "BTCUSDT"},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        self.btc_current = float(data["price"])

                # Candles 1h para calcular movimento
                async with self._session.get(
                    f"{BINANCE_API}/fapi/v1/klines",
                    params={"symbol": "BTCUSDT", "interval": "1m", "limit": 60},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as r:
                    if r.status == 200:
                        candles = await r.json()
                        closes = [float(c[4]) for c in candles]
                        self.btc_prices = closes

                        if len(closes) >= 60:
                            self.btc_1h_move = (closes[-1] - closes[0]) / closes[0] * 100

                        # 24h move
                        async with self._session.get(
                            f"{BINANCE_API}/fapi/v1/ticker/24hr",
                            params={"symbol": "BTCUSDT"},
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as r24:
                            if r24.status == 200:
                                d24 = await r24.json()
                                self.btc_24h_move = float(d24.get("priceChangePercent", 0))

                        # Detecta movimento brusco
                        if abs(self.btc_1h_move) >= BTC_MOVE_TRIGGER:
                            self._add_alert("BTC_MOVE", {
                                "move_pct": round(self.btc_1h_move, 3),
                                "price": self.btc_current,
                                "direction": "UP" if self.btc_1h_move > 0 else "DOWN"
                            })

            except Exception as e:
                print(f"[Monitor] Erro BTC: {e}")

            await asyncio.sleep(10)

    # ── Notícias via Claude ───────────────────────────────────────────────────

    async def _news_loop(self):
        """A cada 2 minutos busca e analisa notícias relevantes"""
        while self.running:
            try:
                await self._analyze_macro_context()
            except Exception as e:
                print(f"[Monitor] Erro notícias: {e}")
            await asyncio.sleep(120)

    async def _analyze_macro_context(self):
        """Usa Claude para analisar contexto macro atual"""
        try:
            prompt = f"""Você é um analista de mercado financeiro. Analise o contexto atual:

BTC atual: ${self.btc_current:,.0f}
Movimento 1h: {self.btc_1h_move:+.2f}%
Movimento 24h: {self.btc_24h_move:+.2f}%

Com base no seu conhecimento atualizado, identifique:
1. Existe algum evento macro importante HOJE ou AMANHÃ? (Fed, CPI, NFP, etc)
2. Existe alguma notícia de crypto relevante nas últimas horas?
3. O movimento do BTC tem explicação fundamentalista?

Responda APENAS com JSON:
{{
  "has_macro_event": true/false,
  "event_name": "nome do evento ou null",
  "event_impact": "HIGH/MEDIUM/LOW",
  "btc_explanation": "explicação em 1 frase",
  "recommended_direction": "UP/DOWN/NEUTRAL",
  "confidence": 0.0-1.0,
  "reasoning": "motivo em 1 frase"
}}"""

            async with self._session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01"
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    text = data["content"][0]["text"]
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    if start >= 0:
                        analysis = json.loads(text[start:end])
                        analysis["timestamp"] = time.time()
                        analysis["btc_price"] = self.btc_current
                        analysis["btc_1h"] = self.btc_1h_move

                        self.recent_news.insert(0, analysis)
                        self.recent_news = self.recent_news[:20]

                        if analysis.get("has_macro_event") and analysis.get("confidence", 0) > 0.6:
                            self._add_alert("MACRO_EVENT", analysis)
                            print(f"[Monitor] 📰 Evento macro: {analysis.get('event_name')} | Conf: {analysis.get('confidence'):.0%}")

        except Exception as e:
            print(f"[Monitor] Erro análise Claude: {e}")

    def _add_alert(self, alert_type: str, data: dict):
        """Adiciona alerta sem duplicar"""
        # Evita duplicar alertas do mesmo tipo em 30 minutos
        now = time.time()
        recent = [a for a in self.alerts if a["type"] == alert_type and now - a["time"] < 1800]
        if recent:
            return

        alert = {"type": alert_type, "data": data, "time": now}
        self.alerts.insert(0, alert)
        self.alerts = self.alerts[:50]
        print(f"[Monitor] 🚨 Alerta: {alert_type} | {data}")

    def get_active_alerts(self) -> list:
        """Retorna alertas dos últimos 30 minutos"""
        now = time.time()
        return [a for a in self.alerts if now - a["time"] < 1800]

    def get_btc_summary(self) -> dict:
        return {
            "price": self.btc_current,
            "move_1h": round(self.btc_1h_move, 3),
            "move_24h": round(self.btc_24h_move, 3),
            "trend": "UP" if self.btc_1h_move > 0.5 else "DOWN" if self.btc_1h_move < -0.5 else "NEUTRAL"
        }
