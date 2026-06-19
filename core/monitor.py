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

    # APIs de preço BTC (tenta em ordem até funcionar)
    BTC_APIS = [
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true",
        "https://api.coinbase.com/v2/prices/BTC-USD/spot",
        "https://min-api.cryptocompare.com/data/price?fsym=BTC&tsyms=USD",
    ]

    async def _btc_loop(self):
        while self.running:
            try:
                await self._fetch_btc_price()
            except Exception as e:
                print(f"[Monitor] Erro BTC: {e}")
            await asyncio.sleep(10)

    async def _fetch_btc_price(self):
        """Tenta múltiplas APIs públicas para pegar preço do BTC"""
        for api_url in self.BTC_APIS:
            try:
                async with self._session.get(
                    api_url, timeout=aiohttp.ClientTimeout(total=8)
                ) as r:
                    if r.status != 200:
                        continue
                    data = await r.json()

                    # CoinGecko
                    if "bitcoin" in data:
                        price = float(data["bitcoin"]["usd"])
                        change_24h = float(data["bitcoin"].get("usd_24h_change", 0))
                        self._update_btc(price, change_24h)
                        return

                    # Coinbase
                    if "data" in data and "amount" in data.get("data", {}):
                        price = float(data["data"]["amount"])
                        self._update_btc(price, 0)
                        return

                    # CryptoCompare
                    if "USD" in data:
                        price = float(data["USD"])
                        self._update_btc(price, 0)
                        return

            except Exception as e:
                continue

        print("[Monitor] Todas as APIs de BTC falharam")

    def _update_btc(self, price: float, change_24h: float):
        """Atualiza preço e calcula movimento"""
        prev = self.btc_current
        self.btc_current = price
        self.btc_24h_move = round(change_24h, 3)

        # Histórico de preços
        self.btc_prices.append(price)
        if len(self.btc_prices) > 60:
            self.btc_prices = self.btc_prices[-60:]

        # Movimento 1h
        if len(self.btc_prices) >= 6:
            self.btc_1h_move = round(
                (self.btc_prices[-1] - self.btc_prices[0]) / self.btc_prices[0] * 100, 3
            )

        # Alerta de movimento brusco
        if abs(self.btc_1h_move) >= BTC_MOVE_TRIGGER:
            self._add_alert("BTC_MOVE", {
                "move_pct": self.btc_1h_move,
                "price": price,
                "direction": "UP" if self.btc_1h_move > 0 else "DOWN"
            })

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
