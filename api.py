"""
API + Dashboard do Polymarket Macro Bot
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import asyncio
import json
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from engine import engine, state

app = FastAPI(title="Polymarket Macro Bot")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
ws_clients = []


@app.on_event("startup")
async def startup():
    asyncio.create_task(engine.start())
    asyncio.create_task(_broadcaster())


@app.on_event("shutdown")
async def shutdown():
    await engine.stop()


@app.get("/api/status")
async def status():
    return {
        **state,
        "portfolio":  engine.executor.get_portfolio(),
        "btc":        engine.monitor.get_btc_summary(),
        "alerts":     engine.monitor.get_active_alerts(),
        "news":       engine.monitor.recent_news[:5],
        "decisions":  engine.analyzer.decisions[:10],
    }

@app.get("/api/positions")
async def positions():
    return list(engine.executor.positions.values())

@app.get("/api/trades")
async def trades():
    return engine.executor.closed[:50]

@app.get("/api/markets")
async def markets():
    return engine.finder.active_markets[:20]

@app.get("/api/log")
async def log():
    return state["log"]


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in ws_clients:
            ws_clients.remove(ws)


async def _broadcaster():
    while True:
        if ws_clients:
            data = {
                "type":      "update",
                "portfolio": engine.executor.get_portfolio(),
                "btc":       engine.monitor.get_btc_summary(),
                "alerts":    len(engine.monitor.get_active_alerts()),
                "positions": list(engine.executor.positions.values()),
                "log":       state["log"][:5],
            }
            dead = []
            for ws in ws_clients:
                try:
                    await ws.send_text(json.dumps(data))
                except:
                    dead.append(ws)
            for ws in dead:
                if ws in ws_clients:
                    ws_clients.remove(ws)
        await asyncio.sleep(2)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Macro Bot</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
  :root{--bg:#06090f;--bg2:#0c1219;--bg3:#111a24;--border:#1a2535;
    --text:#e2e8f0;--text2:#7a8fa6;--text3:#4a6080;
    --green:#00d68f;--red:#ff4757;--blue:#3d9fff;--yellow:#ffd32a;--purple:#a855f7;
    --mono:'JetBrains Mono',monospace;--sans:'Inter',sans-serif;}
  *{margin:0;padding:0;box-sizing:border-box;}
  body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh;}
  header{display:flex;align-items:center;justify-content:space-between;
    padding:14px 24px;background:var(--bg2);border-bottom:1px solid var(--border);
    position:sticky;top:0;z-index:100;gap:16px;flex-wrap:wrap;}
  .logo{font-size:16px;font-weight:700;display:flex;align-items:center;gap:8px;}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--green);
    box-shadow:0 0 8px var(--green);animation:pulse 2s infinite;}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
  .hstats{display:flex;gap:20px;flex-wrap:wrap;}
  .hs{text-align:right;}
  .hs-l{font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:1px;}
  .hs-v{font-size:14px;font-weight:600;font-family:var(--mono);}
  .badge{padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;text-transform:uppercase;}
  .badge-paper{background:rgba(255,211,42,.15);color:var(--yellow);}
  .layout{display:grid;grid-template-columns:1fr 340px;min-height:calc(100vh - 53px);}
  .main{padding:20px;display:flex;flex-direction:column;gap:16px;overflow-y:auto;}
  .sidebar{background:var(--bg2);border-left:1px solid var(--border);overflow-y:auto;}
  .stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
  .stat{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:16px;position:relative;overflow:hidden;}
  .stat::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;}
  .stat.g::before{background:var(--green);}
  .stat.b::before{background:var(--blue);}
  .stat.p::before{background:var(--purple);}
  .stat.y::before{background:var(--yellow);}
  .stat-l{font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:.8px;margin-bottom:8px;}
  .stat-v{font-size:22px;font-weight:700;font-family:var(--mono);line-height:1;}
  .stat-s{font-size:11px;color:var(--text2);margin-top:4px;}
  .card{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:16px;}
  .card-t{font-size:12px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:.8px;margin-bottom:14px;}
  .btc-card{background:linear-gradient(135deg,rgba(61,159,255,.08),rgba(168,85,247,.08));
    border:1px solid rgba(61,159,255,.2);border-radius:10px;padding:20px;
    display:flex;align-items:center;justify-content:space-between;}
  .btc-price{font-size:28px;font-weight:700;font-family:var(--mono);}
  .btc-move{font-size:16px;font-weight:600;font-family:var(--mono);}
  .log-item{padding:12px 16px;border-bottom:1px solid var(--border);}
  .log-header{display:flex;justify-content:space-between;margin-bottom:5px;}
  .log-market{font-size:12px;color:var(--text2);}
  .log-time{font-size:10px;color:var(--text3);}
  .log-body{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
  .tag{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;font-family:var(--mono);}
  .tag-yes{background:rgba(0,214,143,.15);color:var(--green);}
  .tag-no{background:rgba(255,71,87,.15);color:var(--red);}
  .tag-trade{background:rgba(61,159,255,.12);color:var(--blue);}
  .tag-close{background:rgba(168,85,247,.12);color:var(--purple);}
  .log-reason{font-size:11px;color:var(--text3);margin-top:4px;line-height:1.4;}
  .pos-item{display:grid;grid-template-columns:1fr auto auto;gap:10px;
    align-items:center;padding:10px 0;border-bottom:1px solid var(--border);}
  .news-item{padding:10px 16px;border-bottom:1px solid var(--border);}
  .news-event{font-size:12px;font-weight:600;margin-bottom:4px;}
  .news-body{font-size:11px;color:var(--text3);}
  .alert-item{padding:8px 16px;border-bottom:1px solid var(--border);
    background:rgba(255,211,42,.04);}
  .empty{padding:30px;text-align:center;color:var(--text3);font-size:12px;}
  .scanning{animation:sc 2s ease-in-out infinite;}
  @keyframes sc{0%,100%{opacity:1}50%{opacity:.4}}
  .positive{color:var(--green);}
  .negative{color:var(--red);}
  ::-webkit-scrollbar{width:4px;}
  ::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px;}
  @media(max-width:768px){.stats-grid{grid-template-columns:repeat(2,1fr);}
    .layout{grid-template-columns:1fr;}}
</style>
</head>
<body>
<header>
  <div class="logo"><div class="dot"></div>MACRO BOT</div>
  <div class="hstats">
    <div class="hs"><div class="hs-l">Saldo</div><div class="hs-v positive" id="hBal">$—</div></div>
    <div class="hs"><div class="hs-l">PnL Hoje</div><div class="hs-v" id="hPnl">$—</div></div>
    <div class="hs"><div class="hs-l">BTC</div><div class="hs-v" id="hBtc">—</div></div>
    <div class="hs"><div class="hs-l">Trades</div><div class="hs-v" id="hTrades">—</div></div>
  </div>
  <span class="badge badge-paper" id="modeBadge">PAPER</span>
</header>

<div class="layout">
  <div class="main">
    <div class="stats-grid">
      <div class="stat g">
        <div class="stat-l">Saldo</div>
        <div class="stat-v positive" id="balance">$500</div>
        <div class="stat-s" id="openPos">0 posições</div>
      </div>
      <div class="stat b">
        <div class="stat-l">PnL Total</div>
        <div class="stat-v" id="totalPnl">$0.00</div>
        <div class="stat-s" id="winRate">Win Rate: —</div>
      </div>
      <div class="stat p">
        <div class="stat-l">Alertas Ativos</div>
        <div class="stat-v" id="alertsCount">0</div>
        <div class="stat-s" id="oppsFound">Oportunidades: 0</div>
      </div>
      <div class="stat y">
        <div class="stat-l">Mercados</div>
        <div class="stat-v" id="marketsCount">0</div>
        <div class="stat-s">Polymarket ativos</div>
      </div>
    </div>

    <!-- BTC Card -->
    <div class="btc-card">
      <div>
        <div style="font-size:11px;color:var(--text3);margin-bottom:4px">BITCOIN</div>
        <div class="btc-price" id="btcPrice">$—</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:11px;color:var(--text3);margin-bottom:4px">1H / 24H</div>
        <div class="btc-move" id="btcMove">— / —</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:11px;color:var(--text3);margin-bottom:4px">Tendência</div>
        <div style="font-size:16px;font-weight:700" id="btcTrend">—</div>
      </div>
    </div>

    <!-- Posições -->
    <div class="card">
      <div class="card-t">Posições Abertas</div>
      <div id="positions"><div class="empty">Nenhuma posição aberta</div></div>
    </div>

    <!-- Últimas decisões Claude -->
    <div class="card">
      <div class="card-t">Últimas Decisões do Claude</div>
      <div id="decisions"><div class="empty scanning">Aguardando análise...</div></div>
    </div>

    <!-- Trades fechados -->
    <div class="card">
      <div class="card-t">Últimos Trades</div>
      <div id="tradesList"><div class="empty scanning">Aguardando primeiro trade...</div></div>
    </div>
  </div>

  <!-- Sidebar -->
  <div class="sidebar">
    <div style="padding:14px 16px 10px;font-size:11px;font-weight:600;color:var(--text3);
      text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid var(--border);">
      Log de Atividade
    </div>
    <div id="activityLog"><div class="empty scanning">Monitorando mercados...</div></div>

    <div style="padding:14px 16px 10px;font-size:11px;font-weight:600;color:var(--text3);
      text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid var(--border);
      border-top:1px solid var(--border);margin-top:8px;">
      Análise Macro (Claude)
    </div>
    <div id="newsLog"><div class="empty scanning">Analisando contexto...</div></div>
  </div>
</div>

<script>
const API = window.location.origin;

function connectWS(){
  const proto = location.protocol==='https:'?'wss:':'ws:';
  const ws = new WebSocket(proto+'//'+location.host+'/ws');
  ws.onmessage = e => {
    const d = JSON.parse(e.data);
    if(d.type==='update'){
      updatePortfolio(d.portfolio);
      updateBtc(d.btc);
      updatePositions(d.positions);
      if(d.log) updateLog(d.log);
      document.getElementById('alertsCount').textContent = d.alerts||0;
    }
  };
  ws.onclose = () => setTimeout(connectWS, 2000);
}

function updatePortfolio(p){
  if(!p) return;
  document.getElementById('hBal').textContent = '$'+p.balance.toFixed(2);
  document.getElementById('balance').textContent = '$'+p.balance.toFixed(2);
  document.getElementById('openPos').textContent = p.positions+' posições abertas';
  document.getElementById('totalPnl').textContent = '$'+p.total_pnl.toFixed(2);
  document.getElementById('totalPnl').className = 'stat-v '+(p.total_pnl>=0?'positive':'negative');
  document.getElementById('winRate').textContent = 'Win Rate: '+p.win_rate+'%';
  document.getElementById('hTrades').textContent = p.trades;
  const pnl = p.daily_pnl||0;
  const pnlEl = document.getElementById('hPnl');
  pnlEl.textContent = (pnl>=0?'+':'')+'$'+pnl.toFixed(2);
  pnlEl.className = 'hs-v '+(pnl>=0?'positive':'negative');
}

function updateBtc(b){
  if(!b) return;
  document.getElementById('btcPrice').textContent = '$'+b.price.toLocaleString();
  document.getElementById('hBtc').textContent = '$'+b.price.toLocaleString();
  const m1 = b.move_1h||0, m24 = b.move_24h||0;
  const m1El = document.getElementById('btcMove');
  m1El.innerHTML = `<span class="${m1>=0?'positive':'negative'}">${m1>=0?'+':''}${m1.toFixed(2)}%</span> / <span class="${m24>=0?'positive':'negative'}">${m24>=0?'+':''}${m24.toFixed(2)}%</span>`;
  const tEl = document.getElementById('btcTrend');
  tEl.textContent = b.trend==='UP'?'↑ Alta':b.trend==='DOWN'?'↓ Baixa':'→ Lateral';
  tEl.className = b.trend==='UP'?'positive':b.trend==='DOWN'?'negative':'';
  tEl.style.fontSize='16px'; tEl.style.fontWeight='700';
}

function updatePositions(positions){
  const el = document.getElementById('positions');
  if(!positions||positions.length===0){
    el.innerHTML='<div class="empty">Nenhuma posição aberta</div>'; return;
  }
  el.innerHTML = positions.map(p=>{
    const pnl = p.pnl||0;
    const dc = p.direction==='YES'?'tag-yes':'tag-no';
    return `<div class="pos-item">
      <div>
        <div style="font-size:12px;font-weight:600;font-family:var(--mono)">${p.direction}</div>
        <div class="log-market">${p.question}</div>
        <div class="log-reason">${p.reasoning||''}</div>
      </div>
      <span class="tag ${dc}">${p.direction}</span>
      <div class="${pnl>=0?'positive':'negative'}" style="font-family:var(--mono);font-size:13px;font-weight:600">
        ${pnl>=0?'+':''}$${pnl.toFixed(4)}
      </div>
    </div>`;
  }).join('');
}

function updateLog(log){
  const el = document.getElementById('activityLog');
  if(!log||log.length===0){
    el.innerHTML='<div class="empty scanning">Monitorando mercados...</div>'; return;
  }
  el.innerHTML = log.map(l=>{
    const t = new Date(l.time).toLocaleTimeString('pt-BR');
    const tc = l.type==='TRADE'?'tag-trade':'tag-close';
    const dc = l.direction==='YES'?'tag-yes':'tag-no';
    return `<div class="log-item">
      <div class="log-header">
        <div class="log-market">${l.market}</div>
        <div class="log-time">${t}</div>
      </div>
      <div class="log-body">
        <span class="tag ${tc}">${l.type}</span>
        <span class="tag ${dc}">${l.direction}</span>
        ${l.edge ? `<span style="font-size:11px;color:var(--text3)">Edge ${(l.edge*100).toFixed(1)}%</span>` : ''}
        ${l.pnl !== undefined ? `<span class="${l.won?'positive':'negative'}" style="font-family:var(--mono);font-size:11px">${l.pnl>=0?'+':''}$${l.pnl.toFixed(3)}</span>` : ''}
      </div>
      ${l.reasoning ? `<div class="log-reason">${l.reasoning}</div>` : ''}
    </div>`;
  }).join('');
}

async function loadStatus(){
  try{
    const r = await fetch(API+'/api/status');
    const d = await r.json();
    updatePortfolio(d.portfolio);
    updateBtc(d.btc);
    document.getElementById('alertsCount').textContent = (d.alerts||[]).length;
    document.getElementById('oppsFound').textContent = 'Oportunidades: '+(d.opportunities_found||0);

    // Mercados
    const mr = await fetch(API+'/api/markets');
    const ms = await mr.json();
    document.getElementById('marketsCount').textContent = ms.length||0;

    // Decisions Claude
    if(d.decisions && d.decisions.length > 0){
      const del = document.getElementById('decisions');
      del.innerHTML = d.decisions.slice(0,5).map(dec=>{
        const dc = dec.direction==='YES'?'tag-yes':'tag-no';
        return `<div style="padding:10px 0;border-bottom:1px solid var(--border)">
          <div style="display:flex;gap:8px;align-items:center;margin-bottom:4px">
            <span class="tag ${dc}">${dec.direction}</span>
            <span style="font-size:12px;font-weight:600">${dec.question}</span>
          </div>
          <div style="display:flex;gap:12px;font-size:11px;color:var(--text3)">
            <span>Edge: ${(dec.edge*100).toFixed(1)}%</span>
            <span>Conf: ${(dec.confidence*100).toFixed(0)}%</span>
            <span>Risco: ${dec.risk}</span>
          </div>
          <div class="log-reason">${dec.reasoning}</div>
        </div>`;
      }).join('');
    }

    // News
    if(d.news && d.news.length > 0){
      const nel = document.getElementById('newsLog');
      nel.innerHTML = d.news.map(n=>{
        return `<div class="news-item">
          <div class="news-event">${n.event_name||'Análise Macro'}</div>
          <div class="news-body">${n.btc_explanation||''}</div>
          <div style="margin-top:4px;display:flex;gap:8px">
            <span class="tag ${n.recommended_direction==='UP'?'tag-yes':'tag-no'}">${n.recommended_direction||'NEUTRAL'}</span>
            <span style="font-size:10px;color:var(--text3)">Conf: ${((n.confidence||0)*100).toFixed(0)}%</span>
          </div>
        </div>`;
      }).join('');
    }

    // Trades
    const tr = await fetch(API+'/api/trades');
    const ts = await tr.json();
    const tel = document.getElementById('tradesList');
    if(ts && ts.length > 0){
      tel.innerHTML = ts.slice(0,8).map(t=>{
        const pnl = t.final_pnl||0;
        return `<div class="pos-item">
          <div>
            <div style="font-size:11px;color:var(--text2)">${t.question}</div>
            <div class="log-reason">${t.reason||''}</div>
          </div>
          <span class="tag ${t.won?'tag-yes':'tag-no'}">${t.won?'WIN':'LOSS'}</span>
          <div class="${pnl>=0?'positive':'negative'}" style="font-family:var(--mono);font-size:12px">
            ${pnl>=0?'+':''}$${pnl.toFixed(3)}
          </div>
        </div>`;
      }).join('');
    }

  }catch(e){ console.error(e); }
}

connectWS();
loadStatus();
setInterval(loadStatus, 10000);
</script>
</body>
</html>"""
