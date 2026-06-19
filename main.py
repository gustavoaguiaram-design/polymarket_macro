#!/usr/bin/env python3
import uvicorn
if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════╗
║         POLYMARKET MACRO BOT v1.0                    ║
║   Claude AI + BTC Monitor + Notícias Macro           ║
╚══════════════════════════════════════════════════════╝
→ Dashboard: http://localhost:8001
""")
    uvicorn.run("api:app", host="0.0.0.0", port=8001, reload=False, log_level="warning")
