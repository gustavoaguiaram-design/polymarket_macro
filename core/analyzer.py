"""
Analisador Claude — cérebro do bot
Analisa cada mercado e decide se vale entrar
"""
import aiohttp
import json
import time
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import ANTHROPIC_API_KEY, MIN_EDGE, MIN_CONFIDENCE


class ClaudeAnalyzer:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self.decisions: list = []

    async def start(self):
        self._session = aiohttp.ClientSession()

    async def stop(self):
        if self._session:
            await self._session.close()

    async def analyze(self, market: dict, alert: dict, btc_summary: dict) -> Optional[dict]:
        """
        Analisa um mercado específico e decide se entra.
        Retorna dict com decisão ou None se não entrar.
        """
        question = market["question"]
        yes_odds = market.get("yes_odds", 0.5)
        no_odds  = market.get("no_odds", 0.5)
        volume   = market.get("volume", 0)
        alert_type = alert["type"]
        alert_data = alert["data"]

        prompt = f"""Você é um trader especialista em mercados de predição (Polymarket).
Analise este mercado e decida se vale entrar agora.

MERCADO: "{question}"
Odds YES: {yes_odds:.3f} (paga {1/yes_odds:.2f}x se ganhar)
Odds NO:  {no_odds:.3f} (paga {1/no_odds:.2f}x se ganhar)
Volume:   ${volume:,.0f}

CONTEXTO DO ALERTA:
Tipo: {alert_type}
Dados: {json.dumps(alert_data, ensure_ascii=False)}

BITCOIN AGORA:
Preço: ${btc_summary['price']:,.0f}
Movimento 1h: {btc_summary['move_1h']:+.2f}%
Tendência: {btc_summary['trend']}

INSTRUÇÕES:
1. Analise se as odds estão CORRETAS ou DEFASADAS dado o contexto atual
2. Se as odds estiverem erradas (edge > 0), identifique a direção (YES ou NO)
3. Calcule sua estimativa de probabilidade real
4. Só recomende entrada se edge > 5% após considerar o rake de 2%

Responda APENAS com JSON:
{{
  "enter": true/false,
  "direction": "YES" ou "NO",
  "our_probability": 0.0-1.0,
  "market_odds": {yes_odds:.3f},
  "edge": 0.0-1.0,
  "confidence": 0.0-1.0,
  "reasoning": "explicação em 1-2 frases",
  "risk": "LOW/MEDIUM/HIGH"
}}"""

        try:
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
                if r.status != 200:
                    return None
                data = await r.json()

            text = data["content"][0]["text"]
            start = text.find("{")
            end = text.rfind("}") + 1
            if start < 0:
                return None

            result = json.loads(text[start:end])

            # Validações
            if not result.get("enter"):
                return None
            if result.get("confidence", 0) < MIN_CONFIDENCE:
                return None
            if result.get("edge", 0) < MIN_EDGE:
                return None

            # Calcula preço de entrada e saída
            direction = result.get("direction", "YES")
            if direction == "YES":
                entry_price = yes_odds
                payout = 1.0 / yes_odds - 1
            else:
                entry_price = no_odds
                payout = 1.0 / no_odds - 1

            decision = {
                "market_id":   market["id"],
                "question":    question[:60],
                "direction":   direction,
                "entry_price": round(entry_price, 4),
                "tp_price":    round(min(entry_price + 0.08, 0.95), 4),
                "sl_price":    round(max(entry_price - 0.05, 0.05), 4),
                "payout":      round(payout, 4),
                "our_prob":    result.get("our_probability", 0),
                "edge":        result.get("edge", 0),
                "confidence":  result.get("confidence", 0),
                "reasoning":   result.get("reasoning", ""),
                "risk":        result.get("risk", "MEDIUM"),
                "token_id":    market["yes_token"] if direction == "YES" else market["no_token"],
                "volume":      volume,
                "alert_type":  alert_type,
                "timestamp":   time.time(),
            }

            self.decisions.insert(0, decision)
            self.decisions = self.decisions[:100]

            print(f"[Claude] ✓ {direction} '{question[:40]}...' "
                  f"@ {entry_price:.3f} | Edge: {result.get('edge',0):.1%} | "
                  f"Conf: {result.get('confidence',0):.0%}")

            return decision

        except Exception as e:
            print(f"[Claude] Erro análise: {e}")
            return None
