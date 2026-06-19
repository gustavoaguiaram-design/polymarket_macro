"""
Executor Polymarket — paper trading e real
"""
import asyncio
import aiohttp
import time
from typing import Optional, Dict
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    BET_SIZE_USD, MAX_POSITIONS, PAPER_TRADING,
    PAPER_BALANCE, CLOB_API, POLY_PRIVATE_KEY, POLY_FUNDER
)


class PolyExecutor:
    def __init__(self):
        self.paper         = PAPER_TRADING
        self.balance       = PAPER_BALANCE
        self.positions: Dict[str, dict] = {}
        self.closed: list  = []
        self.daily_pnl     = 0.0
        self._session: Optional[aiohttp.ClientSession] = None
        self.stats = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}

    async def start(self):
        self._session = aiohttp.ClientSession()
        mode = "PAPER" if self.paper else "REAL"
        print(f"[Executor] {mode} | Saldo: ${self.balance:.2f} | Max: {MAX_POSITIONS} posições")

    async def stop(self):
        if self._session:
            await self._session.close()

    async def open(self, decision: dict) -> Optional[dict]:
        key = f"{decision['market_id']}_{decision['direction']}"
        if key in self.positions:
            return None
        if len(self.positions) >= MAX_POSITIONS:
            print(f"[Executor] Limite de {MAX_POSITIONS} posições atingido")
            return None
        if self.balance < BET_SIZE_USD:
            print(f"[Executor] Saldo insuficiente: ${self.balance:.2f}")
            return None

        # Tamanho da aposta proporcional ao edge
        edge   = decision.get("edge", 0.05)
        conf   = decision.get("confidence", 0.6)
        bet    = min(BET_SIZE_USD * (1 + edge), self.balance * 0.12)
        bet    = max(BET_SIZE_USD * 0.5, bet)

        trade = {
            "id":          key,
            "market_id":   decision["market_id"],
            "question":    decision["question"],
            "direction":   decision["direction"],
            "token_id":    decision["token_id"],
            "entry_price": decision["entry_price"],
            "tp_price":    decision["tp_price"],
            "sl_price":    decision["sl_price"],
            "payout":      decision["payout"],
            "edge":        decision["edge"],
            "confidence":  decision["confidence"],
            "reasoning":   decision["reasoning"],
            "bet":         round(bet, 2),
            "alert_type":  decision["alert_type"],
            "opened_at":   time.time(),
            "pnl":         0.0,
            "current_price": decision["entry_price"],
        }

        if self.paper:
            self.balance -= bet
            self.positions[key] = trade
            print(f"[Paper] ✓ {decision['direction']} '{decision['question'][:35]}' "
                  f"@ {decision['entry_price']:.3f} | Bet: ${bet:.2f} | "
                  f"Edge: {edge:.1%}")
            return trade

        return await self._execute_real(trade)

    async def _execute_real(self, trade: dict) -> Optional[dict]:
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY

            client = ClobClient(
                CLOB_API, key=POLY_PRIVATE_KEY,
                chain_id=137, signature_type=1, funder=POLY_FUNDER
            )
            client.set_api_creds(client.create_or_derive_api_creds())

            order = MarketOrderArgs(
                token_id=trade["token_id"],
                amount=trade["bet"],
                side=BUY,
                order_type=OrderType.FOK
            )
            resp = client.post_order(client.create_market_order(order), OrderType.FOK)
            if resp.get("success"):
                self.positions[trade["id"]] = trade
                print(f"[REAL] ✓ Ordem executada")
                return trade
        except ImportError:
            print("[Executor] py-clob-client não instalado — usando paper")
            self.paper = True
            return await self.open(trade)
        except Exception as e:
            print(f"[Executor] Erro real: {e}")
        return None

    async def update(self, finder) -> list:
        """Monitora posições e fecha quando TP/SL ou timeout"""
        closed = []
        for key, pos in list(self.positions.items()):
            odds = await finder._get_odds(pos["token_id"])
            if odds is None:
                continue

            pos["current_price"] = round(odds, 4)
            pnl = pos["bet"] * (odds - pos["entry_price"]) / pos["entry_price"]
            pos["pnl"] = round(pnl, 4)

            elapsed = time.time() - pos["opened_at"]
            hit_tp  = odds >= pos["tp_price"]
            hit_sl  = odds <= pos["sl_price"]
            timeout = elapsed > 3600 * 4  # 4 horas máximo

            if hit_tp or hit_sl or timeout:
                final_pnl = pos["bet"] * pos["payout"] if hit_tp else (
                    -pos["bet"] if hit_sl else pnl
                )
                won = final_pnl > 0

                if self.paper:
                    self.balance += pos["bet"] + final_pnl

                self.daily_pnl        += final_pnl
                self.stats["pnl"]     += final_pnl
                self.stats["trades"]  += 1
                if won: self.stats["wins"] += 1
                else:   self.stats["losses"] += 1

                reason = "TP" if hit_tp else "SL" if hit_sl else "TIMEOUT"
                emoji  = "✓" if won else "✗"
                print(f"[Paper] {emoji} {reason} '{pos['question'][:30]}' "
                      f"PnL: ${final_pnl:+.3f}")

                pos.update({
                    "exit_price": odds, "final_pnl": round(final_pnl, 4),
                    "won": won, "reason": reason
                })
                self.closed.insert(0, pos.copy())
                self.closed = self.closed[:200]
                closed.append(pos.copy())
                del self.positions[key]

        return closed

    def get_portfolio(self) -> dict:
        t = self.stats["trades"]
        return {
            "balance":    round(self.balance, 2),
            "positions":  len(self.positions),
            "daily_pnl":  round(self.daily_pnl, 2),
            "total_pnl":  round(self.stats["pnl"], 2),
            "trades":     t,
            "wins":       self.stats["wins"],
            "win_rate":   round(self.stats["wins"]/t*100, 1) if t > 0 else 0,
            "paper":      self.paper,
        }
