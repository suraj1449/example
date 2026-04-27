import os
from flask import Flask, Response
import datetime
import logging
import threading
import time

from kiteconnect import KiteTicker

import HEATMAP as heatmap
import FUTURE_BIAS as future
import OI_BIAS as oi


app = Flask(__name__)

# Prefer environment variables for deployment:
# KITE_API_KEY / KITE_ACCESS_TOKEN
# Local fallback is still available by replacing the placeholders below.
API_KEY = (os.getenv("KITE_API_KEY") or os.getenv("API_KEY") or "PASTE_YOUR_API_KEY_HERE").strip()
ACCESS_TOKEN = (os.getenv("KITE_ACCESS_TOKEN") or os.getenv("ACCESS_TOKEN") or "PASTE_YOUR_ACCESS_TOKEN_HERE").strip()

_future_init_lock = threading.Lock()
_future_started = False
_clients_configured = False
_client_lock = threading.Lock()
_live_lock = threading.Lock()
_live_start_lock = threading.Lock()
_live_started = False
_live_ws_connected = False
_live_ws = None
_live_oi_maintainer_started = False
_live_oi_bootstrapped = False
_live_error = None
_live_heatmap_token_to_symbol = {}
_live_nifty_token = None
_live_heatmap_cache = {}
_live_nifty_cache = {}
_live_oi_state = {
    "expiry": None,
    "step": 50,
    "underlying_symbol": None,
    "underlying_token": None,
    "spot": None,
    "all_options": [],
    "token_to_meta": {},
    "subscribed_tokens": set(),
    "quotes": {},
    "current_atm": None,
    "last_subscription_refresh": 0.0,
}


MAIN_HTML = """<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Merged Market Dashboard</title>
<style>
:root,
[data-theme="light"]{
  --bg:#f4f6fb;
  --surface:#ffffff;
  --surface-soft:#edf1f6;
  --border:#d6dee8;
  --text:#1d2430;
  --muted:#647084;
  --accent:#0f766e;
  --accent-soft:#d7f3ef;
  --shadow:0 14px 34px rgba(15, 23, 42, 0.08);
}
[data-theme="dark"]{
  --bg:#0f1722;
  --surface:#141d2b;
  --surface-soft:#1a2536;
  --border:#293548;
  --text:#e7edf7;
  --muted:#9ba9bc;
  --accent:#5eead4;
  --accent-soft:#123c3a;
  --shadow:0 16px 38px rgba(0, 0, 0, 0.32);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0;
  background:var(--bg);
  color:var(--text);
  font-family:"Segoe UI",Arial,Helvetica,sans-serif;
  transition:background .25s ease,color .25s ease;
}
.topbar{
  position:sticky;
  top:0;
  z-index:20;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:16px;
  padding:14px 22px;
  background:rgba(255,255,255,.92);
  border-bottom:1px solid var(--border);
  backdrop-filter:blur(10px);
}
[data-theme="dark"] .topbar{
  background:rgba(20,29,43,.92);
}
.brand{
  font-size:18px;
  font-weight:700;
  letter-spacing:.04em;
}
.topbar-right{
  display:flex;
  align-items:center;
  gap:14px;
  flex-wrap:wrap;
}
.nav{
  display:flex;
  align-items:center;
  gap:10px;
  flex-wrap:wrap;
}
.nav a{
  text-decoration:none;
  color:var(--text);
  background:var(--surface);
  border:1px solid var(--border);
  padding:8px 12px;
  border-radius:8px;
  font-size:13px;
  font-weight:600;
  transition:background .2s ease,border-color .2s ease,color .2s ease,transform .2s ease;
}
.nav a:hover{
  border-color:var(--accent);
  color:var(--accent);
  transform:translateY(-1px);
}
.theme-toggle{
  border:1px solid var(--border);
  background:var(--surface);
  color:var(--text);
  padding:8px 14px;
  border-radius:8px;
  font-size:13px;
  font-weight:600;
  cursor:pointer;
  transition:background .2s ease,border-color .2s ease,color .2s ease;
}
.theme-toggle:hover{
  border-color:var(--accent);
  color:var(--accent);
}
.page{
  padding:20px;
}
.dashboard-section{
  scroll-margin-top:88px;
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:12px;
  box-shadow:var(--shadow);
  margin-bottom:18px;
  overflow:hidden;
}
.section-head{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding:14px 18px;
  background:var(--surface-soft);
  border-bottom:1px solid var(--border);
  flex-wrap:wrap;
}
.section-head h2{
  margin:0;
  font-size:18px;
  font-weight:700;
}
.section-head span{
  color:var(--muted);
  font-size:13px;
}
.frame-wrap{
  padding:14px;
  background:var(--surface);
}
iframe{
  width:100%;
  height:calc(100vh - 165px);
  min-height:760px;
  border:1px solid var(--border);
  border-radius:10px;
  background:#ffffff;
  display:block;
}
#oi-frame{height:900px;min-height:900px}
[data-theme="dark"] iframe{
  background:#0f1722;
}
@media (max-width: 900px){
  .topbar{
    padding:12px 14px;
  }
  .page{
    padding:14px;
  }
  .section-head h2{
    font-size:16px;
  }
  iframe{
    height:calc(100vh - 185px);
    min-height:620px;
  }
  #oi-frame{height:760px;min-height:760px}
}
</style>
</head>
<body>
  <header class="topbar">
    <div class="brand">Merged Market Dashboard</div>
    <div class="topbar-right">
      <nav class="nav">
        <a href="#heatmap-section">HEATMAP</a>
        <a href="#future-section">FUTURE_BIAS</a>
        <a href="#oi-section">OI_BIAS</a>
      </nav>
      <button class="theme-toggle" id="theme-toggle" type="button">Night Theme</button>
    </div>
  </header>

  <main class="page">
    <section id="heatmap-section" class="dashboard-section">
      <div class="section-head">
        <h2>HEATMAP.py</h2>
        <span>Section 1 of 3</span>
      </div>
      <div class="frame-wrap">
        <iframe id="heatmap-frame" src="heatmap" loading="eager"></iframe>
      </div>
    </section>

    <section id="future-section" class="dashboard-section">
      <div class="section-head">
        <h2>FUTURE_BIAS.py</h2>
        <span>Section 2 of 3</span>
      </div>
      <div class="frame-wrap">
        <iframe id="future-frame" src="future" loading="lazy"></iframe>
      </div>
    </section>

    <section id="oi-section" class="dashboard-section">
      <div class="section-head">
        <h2>OI_BIAS.py</h2>
        <span>Section 3 of 3</span>
      </div>
      <div class="frame-wrap">
        <iframe id="oi-frame" src="oi" loading="lazy"></iframe>
      </div>
    </section>
  </main>

<script>
const frameIds = ["heatmap-frame", "future-frame", "oi-frame"];
const autoSizeFrameIds = new Set(["oi-frame"]);
let activeTheme = "light";

function labelForTheme(theme) {
  return theme === "light" ? "Night Theme" : "Day Theme";
}

function mapTheme(frameId, theme) {
  if (frameId === "oi-frame") {
    return theme === "light" ? "day" : "night";
  }
  return theme;
}

function syncFrameTheme(frame) {
  try {
    const targetTheme = mapTheme(frame.id, activeTheme);
    const frameWindow = frame.contentWindow;
    const frameDoc = frame.contentDocument;
    if (frameWindow && frameWindow.__MERGED_DASHBOARD && typeof frameWindow.__MERGED_DASHBOARD.setTheme === "function") {
      frameWindow.__MERGED_DASHBOARD.setTheme(targetTheme);
    } else if (frameDoc && frameDoc.documentElement) {
      frameDoc.documentElement.setAttribute("data-theme", targetTheme);
    }
  } catch (err) {
    console.warn("Theme sync failed for", frame.id, err);
  }
}

function resizeFrame(frame) {
  if (!frame || !autoSizeFrameIds.has(frame.id)) {
    return;
  }
  try {
    const doc = frame.contentDocument;
    if (!doc || !doc.documentElement || !doc.body) {
      return;
    }
    const html = doc.documentElement;
    const body = doc.body;
    const nextHeight = Math.max(
      body.scrollHeight,
      body.offsetHeight,
      html.scrollHeight,
      html.offsetHeight,
      html.clientHeight
    );
    if (nextHeight && Math.abs(frame.offsetHeight - nextHeight) > 1) {
      frame.style.height = nextHeight + "px";
    }
  } catch (err) {
    console.warn("Frame resize failed for", frame.id, err);
  }
}

function installFrameResize(frame) {
  if (!frame || !autoSizeFrameIds.has(frame.id)) {
    return;
  }
  resizeFrame(frame);
  frame.setAttribute("scrolling", "no");
  try {
    const win = frame.contentWindow;
    const doc = frame.contentDocument;
    if (!win || !doc || !doc.documentElement) {
      return;
    }
    if (frame.__mergedMutationObserver) {
      frame.__mergedMutationObserver.disconnect();
    }
    if (frame.__mergedResizeObserver) {
      frame.__mergedResizeObserver.disconnect();
    }
    frame.__mergedMutationObserver = new win.MutationObserver(function () {
      win.requestAnimationFrame(function () {
        resizeFrame(frame);
      });
    });
    frame.__mergedMutationObserver.observe(doc.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
    });
    frame.__mergedResizeObserver = new win.ResizeObserver(function () {
      resizeFrame(frame);
    });
    frame.__mergedResizeObserver.observe(doc.documentElement);
    if (doc.body) {
      frame.__mergedResizeObserver.observe(doc.body);
    }
    win.setTimeout(function () { resizeFrame(frame); }, 0);
    win.setTimeout(function () { resizeFrame(frame); }, 250);
    win.setTimeout(function () { resizeFrame(frame); }, 1000);
  } catch (err) {
    console.warn("Frame resize observer failed for", frame.id, err);
  }
}

window.__resizeMergedFrame = function (frameId) {
  const frame = typeof frameId === "string" ? document.getElementById(frameId) : frameId;
  resizeFrame(frame);
};

function syncAllFrames() {
  frameIds.forEach((id) => {
    const frame = document.getElementById(id);
    if (frame) {
      syncFrameTheme(frame);
      resizeFrame(frame);
    }
  });
}

function applyTheme(theme) {
  activeTheme = theme;
  document.documentElement.setAttribute("data-theme", theme);
  document.getElementById("theme-toggle").textContent = labelForTheme(theme);
  syncAllFrames();
}

document.getElementById("theme-toggle").addEventListener("click", function () {
  applyTheme(activeTheme === "light" ? "dark" : "light");
});

frameIds.forEach((id) => {
  const frame = document.getElementById(id);
  frame.addEventListener("load", function () {
    syncFrameTheme(frame);
    installFrameResize(frame);
  });
});

window.addEventListener("resize", function () {
  frameIds.forEach(function (id) {
    resizeFrame(document.getElementById(id));
  });
});

applyTheme("light");
</script>
</body>
</html>
"""


CHILD_FONT_STYLE = """
<style id="merged-dashboard-overrides">
html, body {
  overflow-x: hidden !important;
}
html, body, button, input, select, textarea, table, th, td, div, span, label {
  font-family: "Segoe UI", Arial, Helvetica, sans-serif !important;
}
.theme-btn,
.theme-toggle{
  display:none !important;
}
</style>
"""


def credentials_ready():
    return (
        API_KEY.strip()
        and ACCESS_TOKEN.strip()
        and API_KEY != "PASTE_YOUR_API_KEY_HERE"
        and ACCESS_TOKEN != "PASTE_YOUR_ACCESS_TOKEN_HERE"
    )


def apply_credentials(module):
    if hasattr(module, "set_kite_credentials"):
        module.set_kite_credentials(API_KEY, ACCESS_TOKEN)
    else:
        module.API_KEY = API_KEY
        module.ACCESS_TOKEN = ACCESS_TOKEN


def ensure_clients_configured():
    global _clients_configured
    with _client_lock:
        if _clients_configured:
            return
        if not credentials_ready():
            raise RuntimeError(
                "Update API_KEY and ACCESS_TOKEN at the top of MERGED_DASHBOARD.py before running the merged app."
            )
        apply_credentials(heatmap)
        apply_credentials(future)
        apply_credentials(oi)
        _clients_configured = True


def _quote_snapshot_from_map(q):
    ohlc = q.get("ohlc") or {}
    last_price = q.get("last_price", 0) or 0
    return {
        "instrument_token": q.get("instrument_token"),
        "last_price": last_price,
        "ohlc": {
            "open": ohlc.get("open", 0) or 0,
            "high": ohlc.get("high", 0) or 0,
            "low": ohlc.get("low", 0) or 0,
            "close": ohlc.get("close", last_price) or last_price,
        },
        "volume": q.get("volume", 0) or 0,
        "oi": q.get("oi", 0) or 0,
    }


def _quote_snapshot_from_tick(tick):
    ohlc = tick.get("ohlc") or {}
    last_price = tick.get("last_price", 0) or 0
    return {
        "instrument_token": tick.get("instrument_token"),
        "last_price": last_price,
        "ohlc": {
            "open": ohlc.get("open", 0) or 0,
            "high": ohlc.get("high", 0) or 0,
            "low": ohlc.get("low", 0) or 0,
            "close": ohlc.get("close", last_price) or last_price,
        },
        "volume": tick.get("volume", 0) or 0,
        "oi": tick.get("oi", 0) or 0,
    }


def _apply_heatmap_quote_locked(symbol, q):
    ltp = q.get("last_price", 0) or 0
    ohlc = q.get("ohlc") or {}
    close_price = ohlc.get("close", ltp) or ltp
    change = round(((ltp - close_price) / close_price * 100) if close_price else 0, 2)
    _live_heatmap_cache[symbol] = {
        "ltp": round(ltp, 2),
        "change": change,
        "open": ohlc.get("open", 0) or 0,
        "high": ohlc.get("high", 0) or 0,
        "low": ohlc.get("low", 0) or 0,
        "close": round(close_price, 2),
        "volume": q.get("volume", 0) or 0,
    }


def _apply_nifty_quote_locked(q):
    ltp = q.get("last_price", 0) or 0
    ohlc = q.get("ohlc") or {}
    close_price = ohlc.get("close", ltp) or ltp
    points = round(ltp - close_price, 2)
    pct = round((points / close_price * 100) if close_price else 0, 2)
    _live_nifty_cache.update({
        "ltp": round(ltp, 2),
        "points": points,
        "pct": pct,
    })


def _prime_heatmap_live(client):
    global _live_nifty_token
    quotes = client.quote(heatmap.INSTRUMENTS + [heatmap.NIFTY_SYM])
    with _live_lock:
        _live_heatmap_token_to_symbol.clear()
        for key, q in quotes.items():
            token = q.get("instrument_token")
            if key == heatmap.NIFTY_SYM:
                _live_nifty_token = token
                _apply_nifty_quote_locked(_quote_snapshot_from_map(q))
                continue
            symbol = key.split(":", 1)[1]
            if token is not None:
                _live_heatmap_token_to_symbol[token] = symbol
            _apply_heatmap_quote_locked(symbol, _quote_snapshot_from_map(q))


def _oi_underlying_symbol():
    return {
        "NIFTY": "NSE:NIFTY 50",
        "BANKNIFTY": "NSE:NIFTY BANK",
        "FINNIFTY": "NSE:NIFTY FIN SERVICE",
        "MIDCPNIFTY": "NSE:NIFTY MID SELECT",
    }.get(oi.SYMBOL, f"NSE:{oi.SYMBOL}")


def _desired_oi_meta_for_spot(spot):
    options = list(_live_oi_state["all_options"])
    step = _live_oi_state["step"] or 50
    atm = oi.round_to_strike(spot, step)
    wanted = set(atm + step * i for i in range(-oi.OTM_COUNT, oi.OTM_COUNT + 1))
    selected = [meta for meta in options if meta["strike"] in wanted]
    return atm, selected


def _prime_oi_live(client):
    instruments = client.instruments(oi.EXCHANGE)
    options = [
        item for item in instruments
        if item["name"] == oi.SYMBOL and item["instrument_type"] in ("CE", "PE")
    ]
    expiry = oi.get_nearest_expiry(options)
    if not expiry:
        raise RuntimeError(f"No upcoming expiry found for {oi.SYMBOL}")
    options = [item for item in options if item["expiry"] == expiry]

    underlying_symbol = _oi_underlying_symbol()
    spot_data = client.ltp([underlying_symbol])
    spot_payload = spot_data[underlying_symbol]
    spot = spot_payload["last_price"]
    underlying_token = spot_payload["instrument_token"]

    strikes = sorted(set(item["strike"] for item in options))
    step = 50
    if len(strikes) >= 2:
        diffs = [strikes[i + 1] - strikes[i] for i in range(min(10, len(strikes) - 1))]
        positive = [diff for diff in diffs if diff > 0]
        if positive:
            step = min(positive)

    option_meta = [{
        "token": item["instrument_token"],
        "strike": item["strike"],
        "type": item["instrument_type"],
        "tradingsymbol": item["tradingsymbol"],
        "key": f"{oi.EXCHANGE}:{item['tradingsymbol']}",
    } for item in options]

    with _live_lock:
        _live_oi_state["expiry"] = expiry
        _live_oi_state["step"] = step
        _live_oi_state["underlying_symbol"] = underlying_symbol
        _live_oi_state["underlying_token"] = underlying_token
        _live_oi_state["spot"] = spot
        _live_oi_state["all_options"] = option_meta

    _refresh_oi_subscription(client=client, spot=spot)


def _refresh_oi_subscription(client=None, spot=None):
    client = oi.ensure_kite() if client is None else client
    with _live_lock:
        underlying_symbol = _live_oi_state["underlying_symbol"]
        underlying_token = _live_oi_state["underlying_token"]
        current_spot = _live_oi_state["spot"]

    if not underlying_symbol:
        return
    if spot is None:
        spot = current_spot
    if spot is None:
        spot_payload = client.ltp([underlying_symbol]).get(underlying_symbol) or {}
        spot = spot_payload.get("last_price")
        if spot is None:
            return
        with _live_lock:
            _live_oi_state["spot"] = spot

    atm, selected = _desired_oi_meta_for_spot(spot)
    desired_tokens = {meta["token"] for meta in selected}
    desired_quotes = [meta["key"] for meta in selected]
    if underlying_token is not None:
        desired_tokens.add(underlying_token)

    quote_map = {}
    if desired_quotes:
        quote_map = client.quote(desired_quotes)
    if underlying_symbol:
        try:
            spot_quote = client.ltp([underlying_symbol]).get(underlying_symbol)
            if spot_quote:
                spot = spot_quote.get("last_price", spot)
        except Exception:
            pass

    with _live_lock:
        old_tokens = set(_live_oi_state["subscribed_tokens"])
        _live_oi_state["current_atm"] = atm
        _live_oi_state["spot"] = spot
        _live_oi_state["token_to_meta"] = {meta["token"]: meta for meta in selected}
        _live_oi_state["subscribed_tokens"] = desired_tokens
        _live_oi_state["last_subscription_refresh"] = time.time()
        for key, q in quote_map.items():
            _live_oi_state["quotes"][key] = _quote_snapshot_from_map(q)
        ws = _live_ws
        ws_connected = _live_ws_connected

    if ws and ws_connected:
        add_tokens = sorted(desired_tokens - old_tokens)
        remove_tokens = sorted(old_tokens - desired_tokens)
        if add_tokens:
            ws.subscribe(add_tokens)
            ws.set_mode(ws.MODE_FULL, add_tokens)
        if remove_tokens:
            ws.unsubscribe(remove_tokens)


def _oi_live_maintainer():
    while True:
        time.sleep(20)
        try:
            if not _live_started:
                continue
            _refresh_oi_subscription()
        except Exception as exc:
            logging.warning("[merged:oi-live] refresh failed: %s", exc)


def _all_live_tokens():
    with _live_lock:
        tokens = set(_live_heatmap_token_to_symbol.keys())
        if _live_nifty_token is not None:
            tokens.add(_live_nifty_token)
        tokens.update(_live_oi_state["subscribed_tokens"])
    return sorted(token for token in tokens if token is not None)


def _live_on_connect(ws, response):
    global _live_ws_connected
    _live_ws_connected = True
    tokens = _all_live_tokens()
    if tokens:
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_FULL, tokens)


def _live_on_close(ws, code, reason):
    global _live_ws_connected
    _live_ws_connected = False
    logging.warning("[merged:live] websocket closed: %s %s", code, reason)


def _live_on_error(ws, code, reason):
    global _live_error
    _live_error = f"{code}: {reason}"
    logging.warning("[merged:live] websocket error: %s", _live_error)


def _live_on_ticks(ws, ticks):
    with _live_lock:
        for tick in ticks:
            token = tick.get("instrument_token")
            snapshot = _quote_snapshot_from_tick(tick)
            symbol = _live_heatmap_token_to_symbol.get(token)
            if symbol:
                _apply_heatmap_quote_locked(symbol, snapshot)
            if token == _live_nifty_token:
                _apply_nifty_quote_locked(snapshot)
            if token == _live_oi_state["underlying_token"]:
                _live_oi_state["spot"] = snapshot.get("last_price")
            meta = _live_oi_state["token_to_meta"].get(token)
            if meta:
                _live_oi_state["quotes"][meta["key"]] = snapshot


def ensure_live_feed_started():
    global _live_started, _live_ws, _live_error
    with _live_start_lock:
        if _live_started:
            return
        ensure_clients_configured()
        try:
            client = heatmap.ensure_kite()
            _prime_heatmap_live(client)
            kws = KiteTicker(API_KEY, ACCESS_TOKEN, reconnect=True, reconnect_max_tries=300, reconnect_max_delay=60)
            kws.on_connect = _live_on_connect
            kws.on_close = _live_on_close
            kws.on_error = _live_on_error
            kws.on_ticks = _live_on_ticks
            kws.connect(threaded=True)
            _live_ws = kws
            _live_started = True
        except Exception as exc:
            _live_error = str(exc)
            logging.warning("[merged:live] startup failed: %s", exc)


def ensure_oi_live_started():
    global _live_oi_bootstrapped, _live_oi_maintainer_started, _live_error
    ensure_live_feed_started()
    with _live_start_lock:
        if _live_oi_bootstrapped:
            return
        try:
            _prime_oi_live(oi.ensure_kite())
            if not _live_oi_maintainer_started:
                threading.Thread(target=_oi_live_maintainer, daemon=True, name="merged-oi-live-maintainer").start()
                _live_oi_maintainer_started = True
            _live_oi_bootstrapped = True
        except Exception as exc:
            _live_error = str(exc)
            logging.warning("[merged:oi-live] startup failed: %s", exc)


def build_heatmap_live_payload():
    with _live_lock:
        stocks = []
        advances = declines = unchanged = 0
        nifty_data = dict(_live_nifty_cache)
        nifty_level = nifty_data.get("ltp") or 24000
        for stock in heatmap.NIFTY50:
            live = _live_heatmap_cache.get(stock["symbol"], {})
            change = live.get("change", 0)
            contrib = round((change / 100) * (stock["weight"] / 100) * nifty_level, 2) if nifty_level else 0
            if change > 0:
                advances += 1
            elif change < 0:
                declines += 1
            else:
                unchanged += 1
            stocks.append({**stock, **live, "change": change, "contrib": contrib})
        nifty_contrib = round(sum(item["contrib"] for item in stocks), 2)
    return {
        "stocks": stocks,
        "advances": advances,
        "declines": declines,
        "unchanged": unchanged,
        "nifty_contrib": nifty_contrib,
        "nifty": nifty_data,
    }


def build_oi_live_payload():
    with _live_lock:
        if not _live_oi_state["all_options"] or _live_oi_state["spot"] is None:
            raise RuntimeError("OI live feed is not ready yet")
        expiry = _live_oi_state["expiry"]
        step = _live_oi_state["step"] or 50
        spot = _live_oi_state["spot"]
        underlying_symbol = _live_oi_state["underlying_symbol"]
        quotes = dict(_live_oi_state["quotes"])
        all_options = list(_live_oi_state["all_options"])

    atm = oi.round_to_strike(spot, step)
    strike_range = set(atm + step * i for i in range(-oi.OTM_COUNT, oi.OTM_COUNT + 1))
    selected = [meta for meta in all_options if meta["strike"] in strike_range]
    if not selected:
        raise RuntimeError("No live OI instruments in the current strike range")

    ltp_rows = {}
    volume_snapshot = {}
    grouped = {}
    for meta in selected:
        q = quotes.get(meta["key"], {})
        strike = meta["strike"]
        grouped.setdefault(strike, {})
        oi_val = q.get("oi", 0) or 0
        open_oi = (q.get("ohlc") or {}).get("open", oi_val) or oi_val
        volume = q.get("volume", 0) or 0
        prev_vol = oi.PREVIOUS_VOLUME.get(meta["key"])
        volume_change = 0 if prev_vol is None else volume - prev_vol
        volume_snapshot[meta["key"]] = volume
        grouped[strike][meta["type"]] = {
            "oi": oi_val,
            "oi_change": oi_val - open_oi,
            "ltp": q.get("last_price", 0) or 0,
            "volume": volume,
            "volume_change": volume_change,
            "key": meta["key"],
        }
    oi.PREVIOUS_VOLUME.update(volume_snapshot)

    rows = []
    for strike in sorted(strike_range):
        ce = grouped.get(strike, {}).get("CE", {
            "oi": 0, "oi_change": 0, "ltp": 0, "volume": 0, "volume_change": 0, "key": None,
        })
        pe = grouped.get(strike, {}).get("PE", {
            "oi": 0, "oi_change": 0, "ltp": 0, "volume": 0, "volume_change": 0, "key": None,
        })
        if strike == atm:
            call_tag = put_tag = "ATM"
        elif strike > atm:
            call_tag, put_tag = "OTM", "ITM"
        else:
            call_tag, put_tag = "ITM", "OTM"
        rows.append({
            "strike": strike,
            "call_tag": call_tag,
            "put_tag": put_tag,
            "call_oi": ce["oi"],
            "call_coi": ce["oi_change"],
            "call_ltp": ce["ltp"],
            "call_volume": ce["volume"],
            "call_volume_change": ce["volume_change"],
            "put_oi": pe["oi"],
            "put_coi": pe["oi_change"],
            "put_ltp": pe["ltp"],
            "put_volume": pe["volume"],
            "put_volume_change": pe["volume_change"],
        })
        ltp_rows[strike] = {"CE": ce["key"], "PE": pe["key"]}

    oi.CURRENT_LTP_KEYS = {"underlying": underlying_symbol, "rows": ltp_rows}

    call_otm_rows = [row for row in rows if row["strike"] > atm and row["call_oi"] > 0]
    put_otm_rows = [row for row in rows if row["strike"] < atm and row["put_oi"] > 0]
    resistance_rows = sorted(call_otm_rows, key=lambda row: row["call_oi"], reverse=True)[:2]
    support_rows = sorted(put_otm_rows, key=lambda row: row["put_oi"], reverse=True)[:2]
    resistance_row = resistance_rows[0] if resistance_rows else None
    support_row = support_rows[0] if support_rows else None

    atm_row = next((row for row in rows if row["strike"] == atm), None)
    call_itm = [row for row in rows if row["strike"] < atm]
    put_itm = [row for row in rows if row["strike"] > atm]
    spot_dir = oi.check_spot_direction(spot)
    atm_call_vol = atm_row["call_volume"] if atm_row else 0
    atm_put_vol = atm_row["put_volume"] if atm_row else 0
    vol_spike = oi.check_volume_spike(atm_call_vol, atm_put_vol)

    signal = "NO TRADE"
    reasons = []
    conditions = {}
    if atm_row:
        atm_call_coi = atm_row["call_coi"]
        atm_put_coi = atm_row["put_coi"]
        bull1 = spot_dir == "BULLISH"
        bull2 = atm_put_coi > atm_call_coi
        bull3 = support_row is not None
        bull4 = sum(row["call_coi"] for row in call_itm) > 0
        bull5 = vol_spike
        bear1 = spot_dir == "BEARISH"
        bear2 = atm_call_coi > atm_put_coi
        bear3 = resistance_row is not None
        bear4 = sum(row["put_coi"] for row in put_itm) > 0
        bear5 = vol_spike
        conditions = {
            "spot_dir": spot_dir,
            "vol_spike": vol_spike,
            "atm_call_coi": atm_call_coi,
            "atm_put_coi": atm_put_coi,
            "bull": [bull1, bull2, bull3, bull4, bull5],
            "bear": [bear1, bear2, bear3, bear4, bear5],
        }
        if bull1 and bull2 and bull3 and bull4 and bull5:
            signal = "BUY CALL"
            reasons = [
                f"Spot Breakout / Higher High (dir: {spot_dir})",
                f"ATM Put COI ({atm_put_coi:+,}) > Call COI ({atm_call_coi:+,}) - Bullish bias",
                f"OTM Put support at {support_row['strike']} (Put OI: {support_row['put_oi']:,})",
                "ITM Call OI building - conviction confirmed",
                "Volume spike at ATM - participation confirmed",
            ]
        elif bear1 and bear2 and bear3 and bear4 and bear5:
            signal = "BUY PUT"
            reasons = [
                f"Spot Breakdown / Lower Low (dir: {spot_dir})",
                f"ATM Call COI ({atm_call_coi:+,}) > Put COI ({atm_put_coi:+,}) - Bearish bias",
                f"OTM Call resistance at {resistance_row['strike']} (Call OI: {resistance_row['call_oi']:,})",
                "ITM Put OI building - conviction confirmed",
                "Volume spike at ATM - participation confirmed",
            ]
        else:
            failed = []
            if not (bull1 or bear1):
                failed.append("Spot sideways - no clear HH/LL")
            if not vol_spike:
                failed.append("Volume below spike threshold")
            if not (bull2 or bear2):
                failed.append("ATM COI mixed - no directional bias")
            if not (bull4 or bear4):
                failed.append("ITM OI not confirming direction")
            reasons = ["Mixed signals - not all 5 conditions align. Stay flat."] + [f"{item}" for item in failed]

    spot_history = list(oi.SPOT_HISTORY)
    return {
        "symbol": oi.SYMBOL,
        "expiry": str(expiry),
        "spot": spot,
        "atm": atm,
        "signal": signal,
        "reasons": reasons,
        "resistance": resistance_row["strike"] if resistance_row else None,
        "support": support_row["strike"] if support_row else None,
        "resistance_levels": [
            {"strike": row["strike"], "oi": row["call_oi"], "rank": idx + 1}
            for idx, row in enumerate(resistance_rows)
        ],
        "support_levels": [
            {"strike": row["strike"], "oi": row["put_oi"], "rank": idx + 1}
            for idx, row in enumerate(support_rows)
        ],
        "rows": rows,
        "conditions": conditions,
        "spot_dir": spot_dir,
        "vol_spike": vol_spike,
        "recent_high": max(spot_history) if spot_history else None,
        "recent_low": min(spot_history) if spot_history else None,
    }


def build_oi_live_ltp_payload():
    cached = oi.CURRENT_LTP_KEYS
    underlying = cached.get("underlying")
    ltp_rows = cached.get("rows") or {}
    with _live_lock:
        quotes = dict(_live_oi_state["quotes"])
        spot = _live_oi_state["spot"]
    rows = []
    for strike in sorted(ltp_rows):
        legs = ltp_rows[strike]
        call_key = legs.get("CE")
        put_key = legs.get("PE")
        rows.append({
            "strike": strike,
            "call_ltp": (quotes.get(call_key) or {}).get("last_price") if call_key else None,
            "put_ltp": (quotes.get(put_key) or {}).get("last_price") if put_key else None,
        })
    return {
        "spot": spot if underlying else None,
        "rows": rows,
    }


def inject_child_overrides(html, light_theme):
    helper = """
<script>
window.__MERGED_DASHBOARD = {
  setTheme: function(themeValue) {
    document.documentElement.setAttribute("data-theme", themeValue);
    if (typeof theme !== "undefined") {
      theme = themeValue;
    }
    if (typeof _isDark !== "undefined") {
      _isDark = themeValue === "dark";
    }
    var themeBtn = document.getElementById("themeBtn");
    if (themeBtn) {
      themeBtn.textContent = themeValue === "day" ? "Day" : "Night";
    }
    var themeIcon = document.getElementById("theme-icon");
    var themeLabel = document.getElementById("theme-lbl");
    if (themeIcon) {
      themeIcon.textContent = themeValue === "dark" ? "DAY" : "NIGHT";
    }
    if (themeLabel) {
      themeLabel.textContent = themeValue === "dark" ? "Day" : "Night";
    }
    window.dispatchEvent(new Event("resize"));
    if (typeof window.__MERGED_DASHBOARD.notifyParentSize === "function") {
      window.__MERGED_DASHBOARD.notifyParentSize();
    }
  },
  notifyParentSize: function() {
    try {
      if (window.frameElement && window.parent && typeof window.parent.__resizeMergedFrame === "function") {
        window.parent.__resizeMergedFrame(window.frameElement.id);
      }
    } catch (err) {}
  }
};
window.__MERGED_DASHBOARD.setTheme("%s");
</script>
""" % light_theme
    html = html.replace("</head>", CHILD_FONT_STYLE + "\n</head>", 1)
    html = html.replace("</body>", helper + "\n</body>", 1)
    return html


def build_heatmap_html():
    html = heatmap.HTML
    html = html.replace('data-theme="dark"', 'data-theme="light"', 1)
    html = html.replace("/api/data", "/heatmap/api/data")
    return inject_child_overrides(html, "light")


def build_future_html():
    html = future.HTML
    html = html.replace('<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Barlow+Condensed:wght@400;600;700&display=swap" rel="stylesheet">', "")
    html = html.replace("/api/data/", "/future/api/data/")
    html = html.replace("/api/stream/", "/future/api/stream/")
    return inject_child_overrides(html, "light")


def build_oi_html():
    html = oi.HTML_TEMPLATE
    html = html.replace("/api/oi", "/oi/api/oi")
    html = html.replace("/api/ltp", "/oi/api/ltp")
    return inject_child_overrides(html, "day")


def ensure_future_started():
    global _future_started
    with _future_init_lock:
        if _future_started:
            return
        ensure_clients_configured()

        logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
        for key in future.INTERVALS:
            thread = threading.Thread(
                target=future._refresh_loop,
                args=(key,),
                daemon=True,
                name="merged-refresh-" + key,
            )
            thread.start()

        _future_started = True


@app.route("/healthz")
def healthz():
    return {
        "ok": True,
        "credentials_ready": credentials_ready(),
        "future_started": _future_started,
        "live_started": _live_started,
        "oi_live_started": _live_oi_bootstrapped,
        "live_ws_connected": _live_ws_connected,
        "live_error": _live_error,
    }


@app.route("/")
def merged_home():
    ensure_clients_configured()
    ensure_future_started()
    return Response(MAIN_HTML, mimetype="text/html")


@app.route("/heatmap")
def heatmap_page():
    ensure_clients_configured()
    ensure_live_feed_started()
    return Response(build_heatmap_html(), mimetype="text/html")


@app.route("/heatmap/api/data")
def heatmap_api_data():
    ensure_clients_configured()
    ensure_live_feed_started()
    if _live_started:
        try:
            return build_heatmap_live_payload()
        except Exception as exc:
            logging.warning("[merged:heatmap-live] falling back to REST: %s", exc)
    return heatmap.api_data()


@app.route("/future")
def future_page():
    ensure_clients_configured()
    ensure_future_started()
    return Response(build_future_html(), mimetype="text/html")


@app.route("/future/api/data/<iv>")
def future_api_data(iv):
    ensure_clients_configured()
    ensure_future_started()
    return future.api_data(iv)


@app.route("/future/api/stream/<iv>")
def future_api_stream(iv):
    ensure_clients_configured()
    ensure_future_started()
    return future.api_stream(iv)


@app.route("/oi")
def oi_page():
    ensure_clients_configured()
    ensure_oi_live_started()
    return Response(build_oi_html(), mimetype="text/html")


@app.route("/oi/api/oi")
def oi_api_data():
    ensure_clients_configured()
    ensure_oi_live_started()
    if _live_started:
        try:
            return {"ok": True, "data": build_oi_live_payload()}
        except Exception as exc:
            logging.warning("[merged:oi-live] falling back to REST: %s", exc)
    return oi.api_oi()


@app.route("/oi/api/ltp")
def oi_api_ltp():
    ensure_clients_configured()
    ensure_oi_live_started()
    if _live_started:
        try:
            return {"ok": True, "data": build_oi_live_ltp_payload()}
        except Exception as exc:
            logging.warning("[merged:oi-live-ltp] falling back to REST: %s", exc)
    return oi.api_ltp()


if __name__ == "__main__":
    ensure_clients_configured()
    ensure_future_started()
    ensure_live_feed_started()
    port = int(os.getenv("PORT", "5002"))
    print("=" * 64)
    print("  Merged Market Dashboard")
    print("  http://localhost:" + str(port))
    print("  Sections: HEATMAP -> FUTURE_BIAS -> OI_BIAS")
    print("  Credentials source: env KITE_API_KEY / KITE_ACCESS_TOKEN")
    print("=" * 64)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
