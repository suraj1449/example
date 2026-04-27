"""
Nifty 50 Live Treemap Heatmap — Flask + Kite Connect
=====================================================
pip install flask kiteconnect
python nifty50_heatmap.py
Open: http://localhost:5000

Fill your credentials below before running.
"""

from flask import Flask, jsonify, render_template_string
from kiteconnect import KiteConnect
import threading, time

# ── CREDENTIALS ──────────────────────────────────────
API_KEY      = ""
ACCESS_TOKEN = ""
# ─────────────────────────────────────────────────────

app  = Flask(__name__)
kite = None
_bg_started = False

NIFTY50 = [
    {"symbol":"HDFCBANK",   "sector":"Financial Services",           "weight":10.92},
    {"symbol":"ICICIBANK",  "sector":"Financial Services",           "weight":8.73},
    {"symbol":"SBIN",       "sector":"Financial Services",           "weight":4.08},
    {"symbol":"KOTAKBANK",  "sector":"Financial Services",           "weight":2.47},
    {"symbol":"AXISBANK",   "sector":"Financial Services",           "weight":3.53},
    {"symbol":"BAJFINANCE", "sector":"Financial Services",           "weight":2.22},
    {"symbol":"BAJAJFINSV", "sector":"Financial Services",           "weight":0.92},
    {"symbol":"HDFCLIFE",   "sector":"Financial Services",           "weight":0.58},
    {"symbol":"SBILIFE",    "sector":"Financial Services",           "weight":0.75},
    {"symbol":"SHRIRAMFIN", "sector":"Financial Services",           "weight":1.63},
    {"symbol":"JIOFIN",     "sector":"Financial Services",           "weight":0.7},
    {"symbol":"TCS",        "sector":"Information Technology",       "weight":2.31},
    {"symbol":"INFY",       "sector":"Information Technology",       "weight":3.97},
    {"symbol":"HCLTECH",    "sector":"Information Technology",       "weight":1.21},
    {"symbol":"WIPRO",      "sector":"Information Technology",       "weight":0.52},
    {"symbol":"TECHM",      "sector":"Information Technology",       "weight":0.83},
    {"symbol":"RELIANCE",   "sector":"Oil, Gas & Consumable Fuels", "weight":8.2},
    {"symbol":"ONGC",       "sector":"Oil, Gas & Consumable Fuels", "weight":0.98},
    {"symbol":"COALINDIA",  "sector":"Oil, Gas & Consumable Fuels", "weight":0.9},
    {"symbol":"MARUTI",     "sector":"Automobiles",                  "weight":1.56},
    {"symbol":"M&M",        "sector":"Automobiles",                  "weight":2.51},
    {"symbol":"TMPV",       "sector":"Automobiles",                  "weight":0.68},
    {"symbol":"BAJAJ-AUTO", "sector":"Automobiles",                  "weight":0.92},
    {"symbol":"EICHERMOT",  "sector":"Automobiles",                  "weight":0.89},
    {"symbol":"ITC",        "sector":"Fast Moving Consumer Goods",   "weight":2.62},
    {"symbol":"HINDUNILVR", "sector":"Fast Moving Consumer Goods",   "weight":1.87},
    {"symbol":"NESTLEIND",  "sector":"Fast Moving Consumer Goods",   "weight":0.89},
    {"symbol":"TATACONSUM", "sector":"Fast Moving Consumer Goods",   "weight":0.68},
    {"symbol":"LT",         "sector":"Construction",                  "weight":4.21},
    {"symbol":"ADANIPORTS", "sector":"Services",                     "weight":1.05},
    {"symbol":"INDIGO",     "sector":"Services",                     "weight":1.05},
    {"symbol":"TATASTEEL",  "sector":"Metals & Mining",              "weight":1.56},
    {"symbol":"JSWSTEEL",   "sector":"Metals & Mining",              "weight":1.06},
    {"symbol":"HINDALCO",   "sector":"Metals & Mining",              "weight":1.34},
    {"symbol":"ADANIENT",   "sector":"Metals & Mining",              "weight":0.59},
    {"symbol":"BHARTIARTL", "sector":"Telecommunication",            "weight":5.01},
    {"symbol":"SUNPHARMA",  "sector":"Healthcare",                   "weight":1.61},
    {"symbol":"DRREDDY",    "sector":"Healthcare",                   "weight":0.66},
    {"symbol":"CIPLA",      "sector":"Healthcare",                   "weight":0.63},
    {"symbol":"APOLLOHOSP", "sector":"Healthcare",                   "weight":0.7},
    {"symbol":"MAXHEALTH",  "sector":"Healthcare",                   "weight":0.66},
    {"symbol":"NTPC",       "sector":"Power",                        "weight":1.71},
    {"symbol":"POWERGRID",  "sector":"Power",                        "weight":1.29},
    {"symbol":"ETERNAL",    "sector":"Consumer Services",            "weight":1.69},
    {"symbol":"TRENT",      "sector":"Consumer Services",            "weight":0.88},
    {"symbol":"TITAN",      "sector":"Consumer Durables",            "weight":1.64},
    {"symbol":"ASIANPAINT", "sector":"Consumer Durables",            "weight":1.03},
    {"symbol":"ULTRACEMCO", "sector":"Construction Materials",       "weight":1.29},
    {"symbol":"GRASIM",     "sector":"Construction Materials",       "weight":0.94},
    {"symbol":"BEL",        "sector":"Capital Goods",                "weight":1.43},
]

NIFTY_SYM    = "NSE:NIFTY 50"
INSTRUMENTS  = ["NSE:" + s["symbol"] for s in NIFTY50]

_cache       = {}
_nifty_cache = {}
_lock        = threading.Lock()


def _has_credentials(api_key, access_token):
    return bool((api_key or "").strip()) and bool((access_token or "").strip())


def _build_kite_client(api_key=None, access_token=None):
    api_key = API_KEY if api_key is None else api_key
    access_token = ACCESS_TOKEN if access_token is None else access_token
    if not _has_credentials(api_key, access_token):
        return None
    client = KiteConnect(api_key=api_key)
    client.set_access_token(access_token)
    return client


def set_kite_credentials(api_key, access_token):
    global API_KEY, ACCESS_TOKEN, kite
    API_KEY = api_key
    ACCESS_TOKEN = access_token
    kite = _build_kite_client(api_key, access_token)


def ensure_kite():
    global kite
    if kite is None:
        kite = _build_kite_client()
    if kite is None:
        raise RuntimeError("Set API_KEY and ACCESS_TOKEN before running HEATMAP.py")
    return kite


def fetch_all():
    try:
        client = ensure_kite()
        quotes = client.quote(INSTRUMENTS)
        idx    = client.quote([NIFTY_SYM])

        with _lock:
            for s in NIFTY50:
                key = "NSE:" + s["symbol"]
                if key in quotes:
                    q   = quotes[key]
                    ltp = q.get("last_price", 0) or 0
                    cl  = (q.get("ohlc") or {}).get("close", ltp) or ltp
                    chg = round(((ltp - cl) / cl * 100) if cl else 0, 2)
                    _cache[s["symbol"]] = {
                        "ltp":    round(ltp, 2),
                        "change": chg,
                        "open":   (q.get("ohlc") or {}).get("open", 0),
                        "high":   (q.get("ohlc") or {}).get("high", 0),
                        "low":    (q.get("ohlc") or {}).get("low", 0),
                        "close":  round(cl, 2),
                        "volume": q.get("volume", 0),
                    }

            if NIFTY_SYM in idx:
                ni  = idx[NIFTY_SYM]
                ltp = ni.get("last_price", 0) or 0
                cl  = (ni.get("ohlc") or {}).get("close", ltp) or ltp
                pts = round(ltp - cl, 2)
                pct = round((pts / cl * 100) if cl else 0, 2)
                _nifty_cache.update({"ltp": round(ltp, 2), "points": pts, "pct": pct})

    except Exception as e:
        print(f"[Kite Error] {e}")


def bg():
    while True:
        fetch_all()
        time.sleep(5)


def start_background_thread():
    global _bg_started
    if _bg_started:
        return
    ensure_kite()
    threading.Thread(target=bg, daemon=True).start()
    _bg_started = True


@app.route("/api/data")
def api_data():
    start_background_thread()
    with _lock:
        stocks, adv, dec, unc = [], 0, 0, 0
        nc = 0.0
        nifty_level = _nifty_cache.get("ltp") or 24000
        for s in NIFTY50:
            d    = _cache.get(s["symbol"], {})
            chg  = d.get("change", 0)
            cont = round((chg / 100) * (s["weight"] / 100) * nifty_level, 2) if nifty_level else 0
            if chg > 0:   adv += 1
            elif chg < 0: dec += 1
            else:         unc += 1
            nc += cont
            stocks.append({**s, **d, "change": chg, "contrib": cont})
        return jsonify({
            "stocks": stocks, "advances": adv, "declines": dec,
            "unchanged": unc, "nifty_contrib": round(nc, 2),
            "nifty": dict(_nifty_cache),
        })


HTML = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Nifty 50 Live Heatmap</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;overflow:hidden}

/* ── CSS Variables: Dark theme (default) ── */
:root,[data-theme="dark"]{
  --bg:        #0d0d0d;
  --hdr-bg:    #111111;
  --hdr-bdr:   #1e1e1e;
  --sbar-bg:   #0d0d0d;
  --sbar-bdr:  #1a1a1a;
  --lbl-color: #999;
  --lbl-bg:    rgba(0,0,0,.60);
  --sep-color: #222;
  --stat-lbl:  #555;
  --ts-color:  #444;
  --title-color:#fff;
  --ltp-color: #fff;
  --tip-bg:    #1a1a1a;
  --tip-bdr:   #2a2a2a;
  --tip-row-bdr:#1e1e1e;
  --tip-lbl:   #555;
  --tip-val:   #bbb;
  --sec-wrap-bdr:#1a1a1a;
  --adbar-u:   #333;
  --tbl-bg:    #111;
  --tbl-bdr:   #1e1e1e;
  --tbl-row-hover: #181818;
  --tbl-hdr:   #0a0a0a;
  --tbl-hdr-txt:#555;
  --tbl-txt:   #bbb;
  /* tile colours – dark: vivid greens/reds */
  --t-g4:#1a5c1f; --t-g2:#1e7a24; --t-g1:#1b6b21; --t-g0:#164f1a;
  --t-flat:#1e1e1e;
  --t-r1:#5a1111; --t-r2:#7a1515; --t-r4:#9e1a1a; --t-rmax:#c62828;
  --t-gbdr:#2e7d32; --t-rbdr:#b71c1c; --t-fbdr:#2a2a2a;
  --tile-sym:#ffffff;
}

/* ── Light theme ── */
[data-theme="light"]{
  --bg:        #f0f2f5;
  --hdr-bg:    #ffffff;
  --hdr-bdr:   #e0e0e0;
  --sbar-bg:   #f8f9fa;
  --sbar-bdr:  #e4e4e4;
  --lbl-color: #333;
  --lbl-bg:    rgba(255,255,255,.75);
  --sep-color: #ddd;
  --stat-lbl:  #888;
  --ts-color:  #aaa;
  --title-color:#111;
  --ltp-color: #111;
  --tip-bg:    #ffffff;
  --tip-bdr:   #ddd;
  --tip-row-bdr:#f0f0f0;
  --tip-lbl:   #999;
  --tip-val:   #222;
  --sec-wrap-bdr:#ddd;
  --adbar-u:   #ccc;
  --tbl-bg:    #fff;
  --tbl-bdr:   #e0e0e0;
  --tbl-row-hover: #f5f5f5;
  --tbl-hdr:   #f8f9fa;
  --tbl-hdr-txt:#888;
  --tbl-txt:   #333;
  /* tile colours – light */
  --t-g4:#2d7a34; --t-g2:#3a9e43; --t-g1:#338a3b; --t-g0:#276e2e;
  --t-flat:#d8d8d8;
  --t-r1:#c94040; --t-r2:#c03030; --t-r4:#b02020; --t-rmax:#981818;
  --t-gbdr:#388e3c; --t-rbdr:#c62828; --t-fbdr:#bbb;
}

body{
  background:var(--bg);color:var(--lbl-color);
  font-family:'Segoe UI',Arial,Helvetica,sans-serif;
  display:flex;flex-direction:column;height:100vh;
  transition:background .25s,color .25s;
}

/* HEADER */
.hdr{
  background:var(--hdr-bg);border-bottom:1px solid var(--hdr-bdr);
  padding:6px 14px;display:flex;align-items:center;justify-content:space-between;
  flex-shrink:0;transition:background .25s,border-color .25s;
}
.hdr-left{display:flex;align-items:center;gap:12px}
.title{font-size:13px;font-weight:700;color:var(--title-color);letter-spacing:.08em;text-transform:uppercase}
.dot{width:7px;height:7px;border-radius:50%;background:#00c853;animation:blink 1.4s ease-in-out infinite;flex-shrink:0}
.dot.offline{background:#f44336;animation:none}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.15}}
.ts{font-size:11px;color:var(--ts-color)}

.mkt-badge{
  font-size:10px;font-weight:700;padding:2px 7px;border-radius:10px;
  letter-spacing:.05em;white-space:nowrap;
}
.mkt-badge.open{background:#0a3318;color:#00c853;border:1px solid #0d4720}
.mkt-badge.closed{background:#1e1e1e;color:#888;border:1px solid #2a2a2a}
.mkt-badge.pre{background:#1a2a10;color:#aeea00;border:1px solid #2a3d10}
[data-theme="light"] .mkt-badge.open{background:#e8f5e9;color:#2e7d32;border-color:#a5d6a7}
[data-theme="light"] .mkt-badge.closed{background:#eee;color:#888;border-color:#ccc}
[data-theme="light"] .mkt-badge.pre{background:#f0f4e3;color:#558b2f;border-color:#c5e1a5}

.nifty-blk{display:flex;align-items:center;gap:10px}
.nifty-ltp{font-size:21px;font-weight:700;color:var(--ltp-color)}
.nchg{font-size:12px;font-weight:700;padding:3px 10px;border-radius:3px;white-space:nowrap}
.nchg.up{background:#1b3a1e;color:#4caf50}
.nchg.dn{background:#3a1212;color:#ef5350}
.nchg.fl{background:#2a2a1a;color:#ffd600}
[data-theme="light"] .nchg.up{background:#e8f5e9;color:#2e7d32}
[data-theme="light"] .nchg.dn{background:#ffebee;color:#c62828}
[data-theme="light"] .nchg.fl{background:#fffde7;color:#f57f17}

.theme-btn{
  display:flex;align-items:center;gap:6px;
  background:none;border:1px solid var(--sep-color);
  color:var(--stat-lbl);border-radius:20px;
  padding:4px 10px;cursor:pointer;font-size:11px;font-weight:600;
  transition:all .2s;white-space:nowrap;
}
.theme-btn:hover{border-color:#888;color:var(--title-color)}
.theme-btn .icon{font-size:13px;line-height:1}

/* ── STATS BAR (slightly larger) ── */
.sbar{
  background:var(--sbar-bg);border-bottom:1px solid var(--sbar-bdr);
  padding:7px 16px;display:flex;align-items:center;gap:20px;
  flex-shrink:0;font-size:12.5px;transition:background .25s;
}
.si{display:flex;align-items:center;gap:6px}
.si .lbl{color:var(--stat-lbl);font-size:11.5px}
.si .v{font-weight:700;font-size:13px}
.green{color:#4caf50}.red{color:#ef5350}.yellow{color:#ffd600}.white{color:var(--ltp-color)}
[data-theme="light"] .green{color:#2e7d32}
[data-theme="light"] .red{color:#c62828}
[data-theme="light"] .yellow{color:#e65100}
.adbar{display:flex;height:5px;border-radius:3px;overflow:hidden;width:110px;gap:1px;align-self:center}
.adbar .a{background:#4caf50;transition:width .6s ease}
.adbar .d{background:#ef5350;transition:width .6s ease}
.adbar .u{background:var(--adbar-u)}
.sep{width:1px;height:16px;background:var(--sep-color)}

/* ── TOP 10 TABLE PANEL ── */
.contrib-panel{
  background:var(--tbl-bg);
  border-bottom:1px solid var(--tbl-bdr);
  flex-shrink:0;
  overflow:hidden;
  transition:background .25s,border-color .25s;
}
.contrib-header{
  display:flex;align-items:center;justify-content:space-between;
  padding:5px 14px 3px;
}
.contrib-title{
  font-size:10.5px;font-weight:700;
  color:var(--stat-lbl);letter-spacing:.08em;text-transform:uppercase;
}
.sentiment-badge{
  font-size:10px;font-weight:700;padding:2px 9px;border-radius:10px;
  letter-spacing:.04em;white-space:nowrap;
  transition:all .3s;
}
.sentiment-badge.bull{background:#0d3318;color:#00c853;border:1px solid #1a5c30}
.sentiment-badge.bear{background:#3a1212;color:#ef5350;border:1px solid #6b2020}
.sentiment-badge.neut{background:#2a2a1a;color:#ffd600;border:1px solid #4a4a20}
[data-theme="light"] .sentiment-badge.bull{background:#e8f5e9;color:#2e7d32;border-color:#a5d6a7}
[data-theme="light"] .sentiment-badge.bear{background:#ffebee;color:#c62828;border-color:#ef9a9a}
[data-theme="light"] .sentiment-badge.neut{background:#fffde7;color:#e65100;border-color:#ffe082}

.contrib-table{
  width:100%;border-collapse:collapse;
  font-size:11px;
}
.contrib-table th{
  background:var(--tbl-hdr);
  color:var(--tbl-hdr-txt);
  font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  padding:3px 10px;text-align:left;white-space:nowrap;
  border-bottom:1px solid var(--tbl-bdr);
}
.contrib-table th:nth-child(n+4){text-align:right}
.contrib-table td{
  padding:3px 10px;
  border-bottom:1px solid var(--tbl-bdr);
  color:var(--tbl-txt);
  white-space:nowrap;
  vertical-align:middle;
  transition:background .15s;
}
.contrib-table tr:last-child td{border-bottom:none}
.contrib-table tbody tr:hover td{background:var(--tbl-row-hover)}
.contrib-table td:nth-child(n+4){text-align:right}

.rank-num{
  font-size:10px;font-weight:700;color:var(--stat-lbl);
  width:16px;display:inline-block;text-align:center;
}
.sym-cell{font-weight:700;font-size:11.5px;color:var(--title-color)}
.sec-cell{font-size:10px;color:var(--stat-lbl);max-width:110px;overflow:hidden;text-overflow:ellipsis}
.chg-cell{font-weight:700;font-size:11px}
.wt-cell{font-size:10.5px;color:var(--stat-lbl)}
.contrib-cell{font-weight:700;font-size:11px}

/* Mini bar for contribution magnitude */
.mini-bar-wrap{display:flex;align-items:center;gap:4px;justify-content:flex-end}
.mini-bar{height:4px;border-radius:2px;min-width:2px;max-width:60px;transition:width .5s ease}
.mini-bar.pos{background:#4caf50}
.mini-bar.neg{background:#ef5350}
[data-theme="light"] .mini-bar.pos{background:#2e7d32}
[data-theme="light"] .mini-bar.neg{background:#c62828}

/* HEATMAP */
.hm-wrap{flex:1;overflow:hidden;position:relative;min-height:80px}
#heatmap{width:100%;height:100%;position:absolute;top:0;left:0}

.sec-label{
  position:absolute;
  font-size:10px;font-weight:600;
  color:var(--lbl-color);letter-spacing:.04em;
  background:var(--lbl-bg);
  padding:1px 5px;
  pointer-events:none;z-index:10;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}

#tip{
  position:fixed;pointer-events:none;z-index:9999;
  background:var(--tip-bg);border:1px solid var(--tip-bdr);border-radius:5px;
  padding:10px 13px;font-size:11px;width:200px;
  box-shadow:0 6px 24px rgba(0,0,0,.35);
  opacity:0;transition:opacity .12s,background .25s;
}
#tip.show{opacity:1}
#tip .tn{font-size:15px;font-weight:700;color:var(--ltp-color);margin-bottom:4px}
#tip .tc{font-size:13px;font-weight:700;margin-bottom:6px}
#tip .tr{display:flex;justify-content:space-between;color:var(--tip-lbl);padding:2px 0;border-bottom:1px solid var(--tip-row-bdr);font-size:10.5px}
#tip .tr:last-child{border:none}
#tip .tr span:last-child{color:var(--tip-val)}

#refresh-flash{
  position:fixed;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,#00c853,#69f0ae);
  transform:scaleX(0);transform-origin:left;
  transition:transform .4s ease;z-index:99999;pointer-events:none;
}
#refresh-flash.active{transform:scaleX(1)}
</style>
</head>
<body>
<div id="refresh-flash"></div>

<div class="hdr">
  <div class="hdr-left">
    <div class="dot" id="dot"></div>
    <span class="title">Nifty 50 Live Heatmap</span>
    <span class="mkt-badge closed" id="mkt-badge">MARKET CLOSED</span>
    <span class="ts" id="ts">--:--:--</span>
  </div>
  <div style="display:flex;align-items:center;gap:14px">
    <div class="nifty-blk">
      <span class="nifty-ltp" id="nltp">—</span>
      <span class="nchg fl" id="nchg">— (—%)</span>
    </div>
    <button class="theme-btn" id="theme-btn" onclick="toggleTheme()">
      <span class="icon" id="theme-icon">☀️</span>
      <span id="theme-lbl">Day</span>
    </button>
  </div>
</div>

<!-- STATS BAR (slightly larger) -->
<div class="sbar">
  <div class="si"><span class="lbl">Advances</span><span class="v green" id="adv">—</span></div>
  <div class="sep"></div>
  <div class="si"><span class="lbl">Declines</span><span class="v red" id="dec">—</span></div>
  <div class="sep"></div>
  <div class="si"><span class="lbl">Unchanged</span><span class="v yellow" id="unc">—</span></div>
  <div class="sep"></div>
  <div class="si"><span class="lbl">A/D Ratio</span><span class="v white" id="adr">—</span></div>
  <div class="adbar"><div class="a" id="ab" style="width:50%"></div><div class="d" id="db" style="width:40%"></div><div class="u" id="ub" style="width:10%"></div></div>
  <div class="sep"></div>
  <div class="si"><span class="lbl">Est. Nifty Move</span><span class="v" id="nc" style="color:var(--ltp-color)">—</span></div>
  <div class="sep"></div>
  <div class="si"><span class="lbl">Updates every</span><span class="v white">5s</span></div>
</div>

<!-- TOP 10 CONTRIBUTORS TABLE -->
<div class="contrib-panel">
  <div class="contrib-header">
    <span class="contrib-title">⚡ Top 10 Contributors to Nifty Move</span>
    <span class="sentiment-badge neut" id="sent-badge">NEUTRAL MARKET</span>
  </div>
  <table class="contrib-table">
    <thead>
      <tr>
        <th style="width:22px">#</th>
        <th>Symbol</th>
        <th>Sector</th>
        <th>Weight %</th>
        <th>Change %</th>
        <th>Contribution (pts)</th>
        <th style="width:80px">Impact</th>
      </tr>
    </thead>
    <tbody id="contrib-body">
      <tr><td colspan="7" style="text-align:center;color:var(--stat-lbl);padding:8px">Loading…</td></tr>
    </tbody>
  </table>
</div>

<div class="hm-wrap">
  <div id="heatmap"></div>
</div>
<div id="tip"></div>

<script>
// ── Squarified Treemap ────────────────────────────────
function squarify(items, x, y, w, h) {
  if (!items.length || w <= 0 || h <= 0) return [];
  const total = items.reduce((s, i) => s + i._w, 0);
  if (total <= 0) return [];
  const area = w * h;
  const norm = items.map(i => ({ ...i, _nw: i._w / total * area }));
  const result = [];
  layoutSquarify(norm, x, y, w, h, result);
  return result;
}

function layoutSquarify(items, x, y, w, h, out) {
  if (!items.length) return;
  if (items.length === 1) { out.push({ ...items[0], x, y, w, h }); return; }
  let row = [], remaining = [...items], rx = x, ry = y, rw = w, rh = h;
  while (remaining.length) {
    const shortSide = Math.min(rw, rh);
    const next = remaining[0];
    if (!row.length) { row.push(next); remaining.shift(); continue; }
    const withNext = [...row, next];
    if (worstRatio(withNext, shortSide) <= worstRatio(row, shortSide)) {
      row.push(next); remaining.shift();
    } else {
      const laid = layoutRow(row, rx, ry, rw, rh);
      for (const r of laid) out.push(r);
      const rowSum = row.reduce((s, i) => s + i._nw, 0);
      const frac = rowSum / (rw * rh);
      if (rw >= rh) { rx += rw * frac; rw -= rw * frac; }
      else          { ry += rh * frac; rh -= rh * frac; }
      row = [];
    }
  }
  if (row.length) { const laid = layoutRow(row, rx, ry, rw, rh); for (const r of laid) out.push(r); }
}

function worstRatio(row, side) {
  const s = row.reduce((a, i) => a + i._nw, 0);
  const max = Math.max(...row.map(i => i._nw));
  const min = Math.min(...row.map(i => i._nw));
  return Math.max((side * side * max) / (s * s), (s * s) / (side * side * min));
}

function layoutRow(row, x, y, w, h) {
  const s = row.reduce((a, i) => a + i._nw, 0);
  const horiz = w >= h, strip = horiz ? s / h : s / w;
  let cur = horiz ? y : x;
  return row.map(item => {
    const frac = item._nw / s;
    const iw = horiz ? strip : w * frac, ih = horiz ? h * frac : strip;
    const ix = horiz ? x : cur, iy = horiz ? cur : y;
    cur += horiz ? ih : iw;
    return { ...item, x: ix, y: iy, w: iw, h: ih };
  });
}

// ── Theme toggle ──────────────────────────────────────
let _isDark = true;
function toggleTheme() {
  _isDark = !_isDark;
  document.documentElement.setAttribute("data-theme", _isDark ? "dark" : "light");
  document.getElementById("theme-icon").textContent = _isDark ? "☀️" : "🌙";
  document.getElementById("theme-lbl").textContent  = _isDark ? "Day" : "Night";
  if (_allStocks.length) render(_allStocks);
}

function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function tileColor(c) {
  if (c >=  4) return cssVar("--t-g4");
  if (c >=  2) return cssVar("--t-g2");
  if (c >=  1) return cssVar("--t-g1");
  if (c >   0) return cssVar("--t-g0");
  if (c === 0) return cssVar("--t-flat");
  if (c >= -1) return cssVar("--t-r1");
  if (c >= -2) return cssVar("--t-r2");
  if (c >= -4) return cssVar("--t-r4");
  return cssVar("--t-rmax");
}
function borderColor(c) {
  if (c > 0) return cssVar("--t-gbdr");
  if (c < 0) return cssVar("--t-rbdr");
  return cssVar("--t-fbdr");
}
function textColor(c) {
  if (_isDark) return c > 0 ? "#81c784" : c < 0 ? "#ef9a9a" : "#888";
  return c > 0 ? "#ffffff" : c < 0 ? "#ffffff" : "#555";
}

// ── Market status ─────────────────────────────────────
function updateMarketStatus() {
  const now = new Date();
  const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const day = ist.getDay(), h = ist.getHours(), m = ist.getMinutes();
  const mins = h * 60 + m;
  const badge = document.getElementById("mkt-badge"), dot = document.getElementById("dot");
  const isWeekday = day >= 1 && day <= 5;
  const PRE_START = 9*60, MKT_START = 9*60+15, MKT_END = 15*60+30;
  if (!isWeekday || mins < PRE_START || mins >= MKT_END + 30) {
    badge.textContent = "MARKET CLOSED"; badge.className = "mkt-badge closed"; dot.className = "dot offline";
  } else if (mins < MKT_START) {
    badge.textContent = "PRE-OPEN"; badge.className = "mkt-badge pre"; dot.className = "dot";
  } else if (mins < MKT_END) {
    badge.textContent = "LIVE"; badge.className = "mkt-badge open"; dot.className = "dot";
  } else {
    badge.textContent = "POST-CLOSE"; badge.className = "mkt-badge closed"; dot.className = "dot offline";
  }
}

function fmt(n, d=2) { return Number(n||0).toFixed(d); }
function fmtVol(v) {
  v = Number(v||0);
  if (v >= 1e7) return (v/1e7).toFixed(2)+'Cr';
  if (v >= 1e5) return (v/1e5).toFixed(2)+'L';
  return v.toLocaleString('en-IN');
}

// ── Top 10 Contributors table ─────────────────────────
function updateContribTable(stocks, adv, dec) {
  // Sort by absolute contribution descending, take top 10
  const sorted = [...stocks].sort((a, b) => Math.abs(b.contrib) - Math.abs(a.contrib)).slice(0, 10);
  const maxAbs = Math.max(...sorted.map(s => Math.abs(s.contrib)), 0.01);

  const tbody = document.getElementById("contrib-body");
  tbody.innerHTML = "";

  sorted.forEach((s, i) => {
    const chg  = s.change || 0;
    const cont = s.contrib || 0;
    const sign = chg >= 0 ? "+" : "";
    const csign = cont >= 0 ? "+" : "";
    const chgCol  = chg  > 0 ? "#4caf50" : chg  < 0 ? "#ef5350" : "#ffd600";
    const contCol = cont > 0 ? "#4caf50" : cont < 0 ? "#ef5350" : "#ffd600";
    const barW = Math.round((Math.abs(cont) / maxAbs) * 58);

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="rank-num">${i+1}</span></td>
      <td><span class="sym-cell">${s.symbol}</span></td>
      <td><span class="sec-cell">${s.sector}</span></td>
      <td><span class="wt-cell">${s.weight}%</span></td>
      <td><span class="chg-cell" style="color:${chgCol}">${sign}${fmt(chg)}%</span></td>
      <td><span class="contrib-cell" style="color:${contCol}">${csign}${fmt(cont,2)} pts</span></td>
      <td>
        <div class="mini-bar-wrap">
          <div class="mini-bar ${cont>=0?'pos':'neg'}" style="width:${barW}px"></div>
        </div>
      </td>`;
    tbody.appendChild(tr);
  });

  // Sentiment badge
  const total = adv + dec;
  const badge = document.getElementById("sent-badge");
  if (total === 0) { badge.textContent = "NEUTRAL MARKET"; badge.className = "sentiment-badge neut"; return; }
  const bullPct = adv / (adv + dec);
  if (bullPct >= 0.65) {
    badge.textContent = `🐂 BULLISH  ${adv}↑ / ${dec}↓`;
    badge.className = "sentiment-badge bull";
  } else if (bullPct <= 0.35) {
    badge.textContent = `🐻 BEARISH  ${adv}↑ / ${dec}↓`;
    badge.className = "sentiment-badge bear";
  } else {
    badge.textContent = `⚖️ MIXED  ${adv}↑ / ${dec}↓`;
    badge.className = "sentiment-badge neut";
  }
}

// ── Treemap sector order ──────────────────────────────
const SEC_ORDER = [
  "Financial Services","Oil, Gas & Consumable Fuels","Information Technology",
  "Fast Moving Consumer Goods","Automobiles","Construction","Telecommunication",
  "Metals & Mining","Healthcare","Power","Consumer Services","Consumer Durables","Capital Goods"
];
const GAP = 2, IGAP = 1;
let _allStocks = [];

function render(stocks) {
  _allStocks = stocks;
  const hmEl = document.getElementById("heatmap");
  const W = hmEl.clientWidth, H = hmEl.clientHeight;
  if (!W || !H) return;

  const secMap = {};
  for (const s of stocks) { if (!secMap[s.sector]) secMap[s.sector] = []; secMap[s.sector].push(s); }

  const orderedSecs = SEC_ORDER.filter(s => secMap[s]).concat(Object.keys(secMap).filter(s => !SEC_ORDER.includes(s)));
  const secItems = orderedSecs.map(sec => ({ sector: sec, stocks: secMap[sec], _w: secMap[sec].reduce((a,s) => a + s.weight, 0) }));
  const secRects = squarify(secItems, 0, 0, W, H);

  hmEl.innerHTML = "";
  const LBL_H = 16;

  for (const sr of secRects) {
    const sx = sr.x + GAP, sy = sr.y + GAP;
    const sw = Math.max(0, sr.w - GAP * 2), sh = Math.max(0, sr.h - GAP * 2);
    if (sw < 8 || sh < 8) continue;

    const wrap = document.createElement("div");
    wrap.style.cssText = `position:absolute;left:${sx}px;top:${sy}px;width:${sw}px;height:${sh}px;overflow:hidden;border:1px solid #1a1a1a;`;

    const lbl = document.createElement("div");
    lbl.className = "sec-label";
    lbl.style.cssText = `top:0;left:0;right:0;max-width:${sw}px;`;
    lbl.textContent = sr.sector;
    wrap.appendChild(lbl);

    const IW = sw, IH = sh - LBL_H;
    if (IW < 4 || IH < 4) { hmEl.appendChild(wrap); continue; }

    const stkItems = [...sr.stocks].sort((a,b) => b.weight - a.weight).map(s => ({...s, _w: s.weight}));
    const tileRects = squarify(stkItems, 0, 0, IW, IH);

    for (const tr of tileRects) {
      const tx = tr.x + IGAP, ty = tr.y + IGAP + LBL_H;
      const tw = Math.max(0, tr.w - IGAP * 2), th = Math.max(0, tr.h - IGAP * 2);
      if (tw < 4 || th < 4) continue;

      const chg = tr.change || 0, area = tw * th;
      const tile = document.createElement("div");
      tile.style.cssText = `position:absolute;left:${tx}px;top:${ty}px;width:${tw}px;height:${th}px;`
        + `background:${tileColor(chg)};border:1px solid ${borderColor(chg)};`
        + `display:flex;flex-direction:column;justify-content:center;align-items:center;`
        + `text-align:center;overflow:hidden;padding:2px;cursor:pointer;transition:filter .12s;`;

      tile.addEventListener("mouseenter", e => { tile.style.filter="brightness(1.3)"; showTip(e,tr); });
      tile.addEventListener("mousemove", moveTip);
      tile.addEventListener("mouseleave", () => { tile.style.filter=""; hideTip(); });

      const fs1 = area>12000?16:area>5000?13:area>2000?11:area>700?9:7;
      const fs2 = area>12000?13:area>5000?11:area>2000?10:area>700?8:0;
      const fs3 = area>12000?10:area>5000?9:0;
      const sign = chg>=0?"+":"", tc = textColor(chg);
      let html = "";
      if (fs1>=7) html += `<div style="font-weight:700;color:#fff;font-size:${fs1}px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;width:100%;text-align:center;line-height:1.2;">${tr.symbol}</div>`;
      if (fs2>=7) html += `<div style="font-weight:600;color:${tc};font-size:${fs2}px;white-space:nowrap;line-height:1.2;">${sign}${fmt(chg)}%</div>`;
      if (fs3>=9) html += `<div style="color:rgba(255,255,255,.45);font-size:${fs3}px;white-space:nowrap;line-height:1.2;">₹${fmt(tr.ltp||0)}</div>`;
      tile.innerHTML = html;
      wrap.appendChild(tile);
    }
    hmEl.appendChild(wrap);
  }
}

// ── Tooltip ───────────────────────────────────────────
const tip = document.getElementById("tip");
function showTip(e, s) {
  const chg = s.change||0, col = chg>0?"#4caf50":chg<0?"#ef5350":"#ffd600";
  const sign = chg>=0?"+":"", cs=(s.contrib||0)>=0?"+":"";
  tip.innerHTML = `
    <div class="tn">${s.symbol}</div>
    <div class="tc" style="color:${col}">${sign}${fmt(chg)}%</div>
    <div class="tr"><span>LTP</span><span>₹${fmt(s.ltp)}</span></div>
    <div class="tr"><span>Open</span><span>₹${fmt(s.open)}</span></div>
    <div class="tr"><span>High</span><span style="color:#4caf50">₹${fmt(s.high)}</span></div>
    <div class="tr"><span>Low</span><span style="color:#ef5350">₹${fmt(s.low)}</span></div>
    <div class="tr"><span>Prev Close</span><span>₹${fmt(s.close)}</span></div>
    <div class="tr"><span>Volume</span><span>${fmtVol(s.volume)}</span></div>
    <div class="tr"><span>Weight</span><span>${s.weight}%</span></div>
    <div class="tr"><span>Nifty Contrib</span><span style="color:${col}">${cs}${fmt(s.contrib,2)} pts</span></div>
    <div class="tr"><span>Sector</span><span>${s.sector}</span></div>`;
  tip.classList.add("show");
  moveTip(e);
}
function moveTip(e) {
  const x=e.clientX+14, y=e.clientY-12, tw=205, th=310;
  tip.style.left=(x+tw>innerWidth?x-tw-20:x)+"px";
  tip.style.top=(y+th>innerHeight?y-th:y)+"px";
}
function hideTip() { tip.classList.remove("show"); }

// ── Refresh flash ─────────────────────────────────────
function flashRefresh() {
  const el = document.getElementById("refresh-flash");
  el.classList.remove("active"); void el.offsetWidth; el.classList.add("active");
  setTimeout(() => el.classList.remove("active"), 500);
}

// ── Main update ───────────────────────────────────────
async function update() {
  updateMarketStatus();
  try {
    const j = await fetch("/api/data").then(r => r.json());
    const { advances:a, declines:d, unchanged:u, nifty_contrib:nc, stocks, nifty:ni } = j;
    const tot = a+d+u||1;

    document.getElementById("adv").textContent = a;
    document.getElementById("dec").textContent = d;
    document.getElementById("unc").textContent = u;
    document.getElementById("adr").textContent = d===0?"∞":(a/d).toFixed(2);
    document.getElementById("ab").style.width=(a/tot*100)+"%";
    document.getElementById("db").style.width=(d/tot*100)+"%";
    document.getElementById("ub").style.width=(u/tot*100)+"%";

    const ncEl = document.getElementById("nc");
    ncEl.textContent = (nc>=0?"+":"")+nc+" pts";
    ncEl.style.color = nc>0?"#4caf50":nc<0?"#ef5350":"#ffd600";

    if (ni && ni.ltp) {
      document.getElementById("nltp").textContent =
        "₹" + Number(ni.ltp).toLocaleString("en-IN",{minimumFractionDigits:2});
      const pts=ni.points||0, pct=ni.pct||0, sign=pts>=0?"+":"";
      const cel = document.getElementById("nchg");
      cel.textContent = `${sign}${pts.toFixed(2)} (${sign}${pct.toFixed(2)}%)`;
      cel.className = "nchg "+(pts>0?"up":pts<0?"dn":"fl");
    }

    document.getElementById("ts").textContent =
      new Date().toLocaleTimeString("en-IN",{hour12:false});

    // Update top-10 table
    updateContribTable(stocks, a, d);

    render(stocks);
    flashRefresh();
  } catch(e) {
    console.error("Update error:", e);
  }
}

let _rt;
window.addEventListener("resize", () => {
  clearTimeout(_rt);
  _rt = setTimeout(() => { if (_allStocks.length) render(_allStocks); }, 150);
});

update();
setInterval(update, 5000);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

if __name__ == "__main__":
    ensure_kite()
    start_background_thread()
    print("\n🚀  Nifty 50 Live Heatmap")
    print("📌  Set API_KEY and ACCESS_TOKEN at the top of this file")
    print("🌐  Open http://localhost:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
