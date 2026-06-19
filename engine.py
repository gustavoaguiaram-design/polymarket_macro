"""
Motor principal do Polymarket Macro Bot
Combina 4 estratégias validadas para máximo lucro
"""
import asyncio
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from core.monitor import MarketMonitor
from core.finder import MarketFinder
from core.analyzer import ClaudeAnalyzer
from core.executor import PolyExecutor
from strategies.combined import CombinedStrategy

state = {
    "running": False,
    "started_at": None,
    "alerts_processed": 0,
    "opportunities_found": 0,
    "trades_opened": 0,
    "strategies_stats": {
        "INFO_ARB": 0,
        "COMB_ARB": 0,
        "REBALANCING": 0,
        "CRYPTO_SPEC": 0,
        "MACRO": 0,
    },
    "log": [],
}


class MacroEngine:
    def __init__(self):
        self.monitor   = MarketMonitor()
        self.finder    = MarketFinder()
        self.analyzer  = ClaudeAnalyzer()
        self.executor  = PolyExecutor()
        self.combined  = CombinedStrategy()
        self._processed = set()

    async def start(self):
        await self.monitor.start()
        await self.finder.start()
        await self.analyzer.start()
        await self.executor.start()
        await self.combined.start()

        state["running"]    = True
        state["started_at"] = datetime.utcnow().isoformat()
        print(f"[MacroEngine] Bot iniciado com 4 estratégias | Paper: {self.executor.paper}")

        asyncio.create_task(self._alert_loop())
        asyncio.create_task(self._scan_loop())
        asyncio.create_task(self._monitor_loop())

    async def stop(self):
        state["running"] = False
        await self.monitor.stop()
        await self.finder.stop()
        await self.analyzer.stop()
        await self.executor.stop()
        await self.combined.stop()

    # ── Loop 1: Alertas de BTC/Macro ─────────────────────────────────────────

    async def _alert_loop(self):
        """Processa alertas de movimento do BTC e eventos macro"""
        while state["running"]:
            try:
                alerts = self.monitor.get_active_alerts()
                for alert in alerts:
                    aid = f"{alert['type']}_{int(alert['time'])}"
                    if aid in self._processed:
                        continue
                    self._processed.add(aid)
                    state["alerts_processed"] += 1

                    markets = await self.finder.find_relevant(alert["type"], alert["data"])
                    btc     = self.monitor.get_btc_summary()
                    news    = self.monitor.recent_news[:3]

                    for market in markets[:5]:
                        # Tenta Info Arbitrage
                        decision = await self.combined.analyze_info_arbitrage(market, btc, news)
                        if not decision:
                            # Tenta análise macro padrão
                            decision = await self.analyzer.analyze(market, alert, btc)

                        if decision:
                            await self._execute_trade(decision)

            except Exception as e:
                print(f"[Engine] Erro alert_loop: {e}")
            await asyncio.sleep(30)

    # ── Loop 2: Scan proativo de todas as estratégias ─────────────────────────

    async def _scan_loop(self):
        """A cada 5 minutos varre todos os mercados com 4 estratégias"""
        while state["running"]:
            try:
                markets = self.finder.active_markets
                btc     = self.monitor.get_btc_summary()
                news    = self.monitor.recent_news[:5]

                if not markets:
                    await asyncio.sleep(60)
                    continue

                # ── Estratégia 1: Rebalancing (mais rápido) ───────────────────
                rebalancing = await self.combined.find_rebalancing(markets)
                for opp in rebalancing:
                    await self._execute_trade(opp)

                # ── Estratégia 2: Arbitragem Combinatória ─────────────────────
                comb_arbs = await self.combined.find_combinatorial_arb(markets)
                for opp in comb_arbs:
                    await self._execute_trade(opp)

                # ── Estratégia 3: Especialização Crypto (top 10 mercados) ─────
                top_markets = sorted(markets, key=lambda x: x.get("volume", 0), reverse=True)[:10]
                for market in top_markets:
                    decision = await self.combined.analyze_crypto_specialist(market, btc)
                    if decision:
                        await self._execute_trade(decision)

                # ── Estratégia 4: Info Arbitrage (mercados com notícia) ───────
                if news:
                    for market in top_markets[:5]:
                        decision = await self.combined.analyze_info_arbitrage(market, btc, news)
                        if decision:
                            await self._execute_trade(decision)

                print(f"[Engine] Scan completo | Posições: {len(self.executor.positions)} | "
                      f"Trades: {state['trades_opened']}")

            except Exception as e:
                print(f"[Engine] Erro scan_loop: {e}")

            await asyncio.sleep(300)  # scan a cada 5 minutos

    # ── Loop 3: Monitor de posições ───────────────────────────────────────────

    async def _monitor_loop(self):
        while state["running"]:
            try:
                closed = await self.executor.update(self.finder)
                for pos in closed:
                    strat = pos.get("strategy", "UNKNOWN")
                    state["log"].insert(0, {
                        "time":      datetime.utcnow().isoformat(),
                        "type":      "CLOSE",
                        "strategy":  strat,
                        "market":    pos["question"],
                        "direction": pos["direction"],
                        "pnl":       pos.get("final_pnl", 0),
                        "reason":    pos.get("reason", ""),
                        "won":       pos.get("won", False),
                    })
                    state["log"] = state["log"][:50]
            except Exception as e:
                print(f"[Engine] Erro monitor: {e}")
            await asyncio.sleep(30)

    # ── Helper execução ───────────────────────────────────────────────────────

    async def _execute_trade(self, decision: dict):
        """Executa trade e atualiza estatísticas"""
        trade = await self.executor.open(decision)
        if trade:
            state["trades_opened"] += 1
            strat = decision.get("strategy", "UNKNOWN")
            state["strategies_stats"][strat] = state["strategies_stats"].get(strat, 0) + 1
            state["opportunities_found"] += 1

            state["log"].insert(0, {
                "time":      datetime.utcnow().isoformat(),
                "type":      "TRADE",
                "strategy":  strat,
                "market":    decision["question"],
                "direction": decision["direction"],
                "edge":      decision["edge"],
                "reasoning": decision["reasoning"],
            })
            state["log"] = state["log"][:50]


engine = MacroEngine()
