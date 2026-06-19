"""
Buscador de mercados Polymarket
Filtra mercados relevantes baseado nos alertas do monitor
"""
import asyncio
import aiohttp
import json
import time
from typing import Optional, List
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import GAMMA_API, CLOB_API


# Keywords por categoria de alerta
KEYWORDS = {
    "BTC_MOVE": [
        "bitcoin", "btc", "crypto", "price", "above", "below",
        "higher", "lower", "reach", "hit", "$"
    ],
    "MACRO_EVENT": [
        "fed", "rate", "interest", "cpi", "inflation", "nfp", "jobs",
        "gdp", "recession", "economy", "fomc", "powell", "treasury",
        "yield", "dollar", "usd", "market", "stock", "sp500"
    ],
    "GENERAL": [
        "btc", "eth", "crypto", "bitcoin", "ethereum", "price",
        "above", "below", "reach", "hit", "end"
    ]
}


class MarketFinder:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self.active_markets: List[dict] = []
        self.last_update: float = 0

    async def start(self):
        self._session = aiohttp.ClientSession()
        await self._load_markets()
        asyncio.create_task(self._refresh_loop())

    async def stop(self):
        if self._session:
            await self._session.close()

    async def _load_markets(self):
        """Carrega mercados ativos do Polymarket"""
        try:
            params = {"active": "true", "closed": "false", "limit": 500}
            async with self._session.get(
                f"{GAMMA_API}/markets", params=params,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status != 200:
                    print(f"[MarketFinder] Erro API: {r.status}")
                    return
                data = await r.json()

            markets = data if isinstance(data, list) else data.get("markets", [])
            valid = []

            for m in markets:
                token_ids = m.get("clobTokenIds")
                if not token_ids:
                    continue
                if isinstance(token_ids, str):
                    try:
                        token_ids = json.loads(token_ids)
                    except:
                        continue
                if len(token_ids) < 2:
                    continue

                vol = float(m.get("volume") or 0)
                if vol < 1000:  # mínimo $1000 de volume
                    continue

                valid.append({
                    "id":        m.get("id"),
                    "question":  m.get("question", ""),
                    "yes_token": token_ids[0],
                    "no_token":  token_ids[1],
                    "volume":    vol,
                    "end_date":  m.get("endDate"),
                    "prices":    m.get("outcomePrices"),
                })

            self.active_markets = valid
            self.last_update = time.time()
            print(f"[MarketFinder] {len(valid)} mercados carregados")

        except Exception as e:
            print(f"[MarketFinder] Erro: {e}")

    async def find_relevant(self, alert_type: str, alert_data: dict) -> List[dict]:
        """Encontra mercados relevantes para um alerta específico"""
        keywords = KEYWORDS.get(alert_type, KEYWORDS["GENERAL"])
        relevant = []

        for m in self.active_markets:
            q = m["question"].lower()
            if any(k in q for k in keywords):
                # Busca odds atuais
                odds = await self._get_odds(m["yes_token"])
                if odds and 0.05 < odds < 0.95:
                    m["yes_odds"] = odds
                    m["no_odds"] = round(1 - odds, 4)
                    relevant.append(m)

        # Ordena por volume
        relevant.sort(key=lambda x: x["volume"], reverse=True)
        return relevant[:10]  # top 10

    async def _get_odds(self, token_id: str) -> Optional[float]:
        """Busca odds atuais de um token"""
        try:
            async with self._session.get(
                f"{CLOB_API}/book",
                params={"token_id": token_id},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status != 200:
                    return None
                book = await r.json()

            bids = book.get("bids", [])
            asks = book.get("asks", [])
            if not bids and not asks:
                return None

            best_bid = float(bids[0]["price"]) if bids else 0
            best_ask = float(asks[0]["price"]) if asks else 1
            return round((best_bid + best_ask) / 2, 4)
        except:
            return None

    async def _refresh_loop(self):
        """Atualiza mercados a cada 5 minutos"""
        while True:
            await asyncio.sleep(300)
            await self._load_markets()
