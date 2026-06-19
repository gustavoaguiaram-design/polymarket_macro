"""
Motor principal do Polymarket Macro Bot
"""
import asyncio
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from core.monitor import MarketMonitor
from core.finder import MarketFinder
from core.analyzer import ClaudeAnalyzer
from core.executor import PolyExecutor

state = {
    "running": False,
    "started_at": None,
    "alerts_processed": 0,
    "opportunities_found": 0,
    "trades_opened": 0,
    "log": [],
}


class MacroEngine:
    def __init__(self):
        self.monitor  = MarketMonitor()
        self.finder   = MarketFinder()
        self.analyzer = ClaudeAnalyzer()
        self.executor = PolyExecutor()
        self._processed_alerts = set()

    async def start(self):
        await self.monitor.start()
        await self.finder.start()
        await self.analyzer.start()
        await self.executor.start()

        state["running"]    = True
        state["started_at"] = datetime.utcnow().isoformat()

        print(f"[MacroEngine] Bot iniciado | Paper: {self.executor.paper}")
        asyncio.create_task(self._main_loop())
        asyncio.create_task(self._monitor_loop())

    async def stop(self):
        state["running"] = False
        await self.monitor.stop()
        await self.finder.stop()
        await self.analyzer.stop()
        await self.executor.stop()

    async def _main_loop(self):
        """Loop principal — processa alertas e busca oportunidades"""
        while state["running"]:
            try:
                alerts = self.monitor.get_active_alerts()

                for alert in alerts:
                    alert_id = f"{alert['type']}_{int(alert['time'])}"
                    if alert_id in self._processed_alerts:
                        continue

                    self._processed_alerts.add(alert_id)
                    state["alerts_processed"] += 1

                    print(f"[Engine] Processando alerta: {alert['type']}")

                    # Busca mercados relevantes
                    markets = await self.finder.find_relevant(
                        alert["type"], alert["data"]
                    )

                    btc = self.monitor.get_btc_summary()

                    for market in markets[:5]:  # analisa top 5
                        decision = await self.analyzer.analyze(market, alert, btc)

                        if decision:
                            state["opportunities_found"] += 1
                            trade = await self.executor.open(decision)

                            if trade:
                                state["trades_opened"] += 1
                                state["log"].insert(0, {
                                    "time":      datetime.utcnow().isoformat(),
                                    "type":      "TRADE",
                                    "market":    decision["question"],
                                    "direction": decision["direction"],
                                    "edge":      decision["edge"],
                                    "reasoning": decision["reasoning"],
                                })
                                state["log"] = state["log"][:50]

            except Exception as e:
                print(f"[Engine] Erro loop: {e}")

            await asyncio.sleep(30)

    async def _monitor_loop(self):
        """Monitora posições abertas a cada 30 segundos"""
        while state["running"]:
            try:
                closed = await self.executor.update(self.finder)
                for pos in closed:
                    state["log"].insert(0, {
                        "time":      datetime.utcnow().isoformat(),
                        "type":      "CLOSE",
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


engine = MacroEngine()
