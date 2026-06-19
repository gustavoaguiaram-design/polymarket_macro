"""
Estratégias combinadas validadas para Polymarket
1. Info Arbitrage (Claude analisa notícias)
2. Arbitragem Combinatória (mercados logicamente inconsistentes)
3. Especialização Crypto (análise técnica profunda)
4. Market Rebalancing (YES + NO < $0.97)
"""
import asyncio
import aiohttp
import json
import time
from typing import Optional, List
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import ANTHROPIC_API_KEY, MIN_CONFIDENCE, CLOB_API


class CombinedStrategy:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        self._session = aiohttp.ClientSession()

    async def stop(self):
        if self._session:
            await self._session.close()

    # ── 1. INFO ARBITRAGE ─────────────────────────────────────────────────────

    async def analyze_info_arbitrage(self, market: dict, btc: dict, news: list) -> Optional[dict]:
        """Claude analisa se notícias criaram edge no mercado"""
        if market.get("volume", 0) < 10000:
            return None

        news_context = "\n".join([
            f"- {n.get('event_name','')}: {n.get('btc_explanation','')}"
            for n in news[:3]
        ]) if news else "Sem notícias recentes"

        yes_odds = market.get("yes_odds", 0.5)
        prompt = f"""Analise este mercado do Polymarket para encontrar edge de informação:

MERCADO: "{market['question']}"
Odds YES: {yes_odds:.3f} | Volume: ${market.get('volume',0):,.0f}
BTC: ${btc.get('price',0):,.0f} | Movimento 1h: {btc.get('move_1h',0):+.2f}%

Notícias recentes:
{news_context}

As odds estão ERRADAS dado o contexto atual?
Responda JSON:
{{"enter": true/false, "direction": "YES"/"NO",
  "true_prob": 0.0-1.0, "edge": 0.0-1.0,
  "confidence": 0.0-1.0, "reason": "1 frase"}}"""

        return await self._claude_decide(prompt, market, "INFO_ARB")

    # ── 2. ARBITRAGEM COMBINATÓRIA ────────────────────────────────────────────

    async def find_combinatorial_arb(self, markets: list) -> List[dict]:
        """Detecta inconsistências lógicas entre mercados relacionados"""
        crypto_markets = [m for m in markets if any(
            k in m.get("question", "").lower()
            for k in ["bitcoin", "btc", "eth", "crypto", "price", "above", "below"]
        )]

        if len(crypto_markets) < 2:
            return []

        btc_markets = sorted([
            m for m in crypto_markets
            if "btc" in m.get("question", "").lower() or "bitcoin" in m.get("question", "").lower()
        ], key=lambda x: x.get("volume", 0), reverse=True)[:6]

        if len(btc_markets) < 2:
            return []

        markets_summary = "\n".join([
            f"- '{m['question'][:60]}' → YES: {m.get('yes_odds', 0.5):.3f}"
            for m in btc_markets
        ])

        prompt = f"""Analise esses mercados do Polymarket e encontre inconsistências lógicas:

{markets_summary}

REGRA: Se P(BTC > $X) e P(BTC > $Y) onde Y < X, então P(Y) >= P(X) sempre.
Existe alguma violação dessa lógica?

Responda JSON:
{{"found": true/false,
  "market_question": "pergunta do mercado errado ou null",
  "direction": "YES"/"NO",
  "edge": 0.0-1.0,
  "confidence": 0.0-1.0,
  "reason": "explicação"}}"""

        try:
            async with self._session.post(
                "https://api.anthropic.com/v1/messages",
                headers={"Content-Type": "application/json",
                         "x-api-key": ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 300,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status != 200:
                    return []
                data = await r.json()

            text = data["content"][0]["text"]
            s = text.find("{"); e = text.rfind("}") + 1
            if s < 0:
                return []
            result = json.loads(text[s:e])

            if not result.get("found") or result.get("confidence", 0) < 0.65:
                return []

            target_q = (result.get("market_question") or "").lower()
            target = next((m for m in btc_markets
                          if target_q[:20] in m.get("question", "").lower()), None)
            if not target:
                return []

            direction = result.get("direction", "YES")
            yes_odds  = target.get("yes_odds", 0.5)
            entry     = yes_odds if direction == "YES" else 1 - yes_odds

            opp = {
                "strategy":    "COMB_ARB",
                "market_id":   target["id"],
                "question":    target["question"][:60],
                "direction":   direction,
                "token_id":    target["yes_token"] if direction == "YES" else target.get("no_token"),
                "entry_price": round(entry, 4),
                "tp_price":    round(min(entry + 0.08, 0.95), 4),
                "sl_price":    round(max(entry - 0.05, 0.05), 4),
                "edge":        result.get("edge", 0),
                "confidence":  result.get("confidence", 0),
                "reasoning":   result.get("reason", ""),
                "volume":      target.get("volume", 0),
                "alert_type":  "COMB_ARB",
                "timestamp":   time.time(),
            }
            print(f"[CombArb] ✓ {opp['question'][:40]} | Edge: {opp['edge']:.1%}")
            return [opp]

        except Exception as e:
            print(f"[CombArb] Erro: {e}")
            return []

    # ── 3. MARKET REBALANCING ─────────────────────────────────────────────────

    async def find_rebalancing(self, markets: list) -> List[dict]:
        """YES + NO < $0.97 = lucro garantido após rake"""
        opportunities = []
        for m in markets:
            yes_odds = m.get("yes_odds", 0)
            no_odds  = m.get("no_odds", 0)
            if not yes_odds or not no_odds:
                continue
            total  = yes_odds + no_odds
            spread = 1.0 - total
            if spread > 0.03 and m.get("volume", 0) > 5000:
                net = spread - 0.02
                opportunities.append({
                    "strategy":    "REBALANCING",
                    "market_id":   m["id"],
                    "question":    m["question"][:60],
                    "direction":   "YES",
                    "token_id":    m["yes_token"],
                    "entry_price": round(yes_odds, 4),
                    "tp_price":    1.0,
                    "sl_price":    0.0,
                    "edge":        round(net, 4),
                    "confidence":  0.92,
                    "reasoning":   f"YES+NO={total:.3f} | Spread={spread:.1%} | Lucro={net:.1%}",
                    "volume":      m.get("volume", 0),
                    "alert_type":  "REBALANCING",
                    "timestamp":   time.time(),
                })
                print(f"[Rebalancing] ✓ {m['question'][:40]} | Spread: {spread:.1%}")
        return sorted(opportunities, key=lambda x: x["edge"], reverse=True)[:3]

    # ── 4. ESPECIALIZAÇÃO CRYPTO ──────────────────────────────────────────────

    async def analyze_crypto_specialist(self, market: dict, btc: dict) -> Optional[dict]:
        """Claude como especialista técnico em crypto"""
        q = market["question"].lower()
        if not any(k in q for k in ["btc", "bitcoin", "eth", "crypto", "price"]):
            return None
        if market.get("volume", 0) < 50000:
            return None

        yes_odds = market.get("yes_odds", 0.5)
        prompt = f"""Você é especialista técnico em Bitcoin e crypto markets.

MERCADO: "{market['question']}"
Odds YES: {yes_odds:.3f} | Volume: ${market.get('volume',0):,.0f}
BTC: ${btc.get('price',0):,.0f} | 1h: {btc.get('move_1h',0):+.2f}% | 24h: {btc.get('move_24h',0):+.2f}%

Com análise técnica profunda, as odds estão corretas?
Responda JSON:
{{"enter": true/false, "direction": "YES"/"NO",
  "true_prob": 0.0-1.0, "edge": 0.0-1.0,
  "confidence": 0.0-1.0, "reason": "análise em 1 frase"}}"""

        return await self._claude_decide(prompt, market, "CRYPTO_SPEC")

    # ── Helper Claude ─────────────────────────────────────────────────────────

    async def _claude_decide(self, prompt: str, market: dict, strategy: str) -> Optional[dict]:
        try:
            async with self._session.post(
                "https://api.anthropic.com/v1/messages",
                headers={"Content-Type": "application/json",
                         "x-api-key": ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 250,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()

            text = data["content"][0]["text"]
            s = text.find("{"); e = text.rfind("}") + 1
            if s < 0:
                return None
            result = json.loads(text[s:e])

            if not result.get("enter"):
                return None
            if result.get("confidence", 0) < MIN_CONFIDENCE:
                return None
            if result.get("edge", 0) < 0.05:
                return None

            direction = result.get("direction", "YES")
            yes_odds  = market.get("yes_odds", 0.5)
            entry     = yes_odds if direction == "YES" else 1 - yes_odds
            if entry < 0.05 or entry > 0.95:
                return None

            return {
                "strategy":    strategy,
                "market_id":   market["id"],
                "question":    market["question"][:60],
                "direction":   direction,
                "token_id":    market["yes_token"] if direction == "YES" else market.get("no_token"),
                "entry_price": round(entry, 4),
                "tp_price":    round(min(entry + 0.08, 0.95), 4),
                "sl_price":    round(max(entry - 0.05, 0.05), 4),
                "edge":        round(result.get("edge", 0), 4),
                "confidence":  round(result.get("confidence", 0), 4),
                "reasoning":   result.get("reason", ""),
                "volume":      market.get("volume", 0),
                "alert_type":  strategy,
                "timestamp":   time.time(),
            }

        except Exception as e:
            print(f"[Claude] Erro {strategy}: {e}")
            return None
