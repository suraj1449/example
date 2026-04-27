"""
OI Signal Dashboard — Flask + Kite Connect API
Single-file app: backend + embedded HTML/CSS/JS frontend

Usage:
  1. pip install flask kiteconnect
  2. Set your API_KEY and ACCESS_TOKEN below
  3. python oi_signal_dashboard.py
  4. Open http://localhost:5000

Signal conditions (ALL 5 must align):
  BULLISH → BUY CE:
    1. Spot Breakout / Higher High (spot > recent high)
    2. ATM: Put COI > Call COI
    3. OTM: Strong Put OI support below ATM
    4. ITM: Call OI building
    5. Volume: Above average spike

  BEARISH → BUY PE:
    1. Spot Breakdown / Lower Low (spot < recent low)
    2. ATM: Call COI > Put COI
    3. OTM: Strong Call OI resistance above ATM
    4. ITM: Put OI building
    5. Volume: Above average spike

  Else → NO TRADE (trap zone)

OTM/ITM logic:
  CALL: strike > ATM → OTM  |  strike < ATM → ITM
  PUT : strike < ATM → OTM  |  strike > ATM → ITM

Resistance = OTM Call strike with highest Call OI (above ATM)
Support    = OTM Put  strike with highest Put  OI (below ATM)
"""

from flask import Flask, jsonify, render_template_string
from kiteconnect import KiteConnect
import traceback
from collections import deque

# ─── CONFIG ────────────────────────────────────────────────────────────────────
API_KEY      = ""
ACCESS_TOKEN = ""

SYMBOL    = "NIFTY"   # BANKNIFTY / FINNIFTY / MIDCPNIFTY etc.
EXCHANGE  = "NFO"
OTM_COUNT = 5         # strikes to show above and below ATM

# Spot price history for HH/LL detection
SPOT_HISTORY_SIZE = 10          # keep last N spot readings (each ~3-min interval)
VOLUME_SPIKE_RATIO = 1.25       # volume must be >= 1.25x rolling average to qualify
VOLUME_HISTORY_SIZE = 5         # rolling average over last N refreshes
# ───────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
kite = None

PREVIOUS_VOLUME = {}
CURRENT_LTP_KEYS = {"underlying": None, "rows": {}}

# Spot price ring buffer for HH/LL
SPOT_HISTORY = deque(maxlen=SPOT_HISTORY_SIZE)

# Total ATM volume (call+put) ring buffer for spike detection
VOLUME_HISTORY = deque(maxlen=VOLUME_HISTORY_SIZE)


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
        raise RuntimeError("Set API_KEY and ACCESS_TOKEN before running OI_BIAS.py")
    return kite


def get_nearest_expiry(instruments):
    from datetime import date
    today = date.today()
    expiries = sorted(set(
        i["expiry"] for i in instruments
        if i["expiry"] and i["expiry"] >= today
    ))
    return expiries[0] if expiries else None


def round_to_strike(price, step=50):
    return round(price / step) * step


def check_spot_direction(spot):
    """
    Returns:
      'BULLISH' if spot > max of recent history (breakout / Higher High)
      'BEARISH' if spot < min of recent history (breakdown / Lower Low)
      'NEUTRAL' otherwise (sideways)
    Also records current spot into history AFTER the check.
    """
    if len(SPOT_HISTORY) < 2:
        result = "NEUTRAL"
    else:
        recent_high = max(SPOT_HISTORY)
        recent_low  = min(SPOT_HISTORY)
        if spot > recent_high:
            result = "BULLISH"
        elif spot < recent_low:
            result = "BEARISH"
        else:
            result = "NEUTRAL"
    SPOT_HISTORY.append(spot)
    return result


def check_volume_spike(atm_call_vol, atm_put_vol):
    """
    Returns True if combined ATM volume is >= VOLUME_SPIKE_RATIO × rolling average.
    Records current combined volume into history AFTER the check.
    """
    combined = (atm_call_vol or 0) + (atm_put_vol or 0)
    if len(VOLUME_HISTORY) < 2:
        result = False   # not enough history yet; be conservative
    else:
        avg = sum(VOLUME_HISTORY) / len(VOLUME_HISTORY)
        result = (avg > 0) and (combined >= VOLUME_SPIKE_RATIO * avg)
    VOLUME_HISTORY.append(combined)
    return result


def fetch_oi_data(symbol=SYMBOL, otm_count=OTM_COUNT):
    global CURRENT_LTP_KEYS
    client = ensure_kite()

    # 1. Pull NFO instruments
    instruments = client.instruments(EXCHANGE)
    options = [
        i for i in instruments
        if i["name"] == symbol and i["instrument_type"] in ("CE", "PE")
    ]

    expiry = get_nearest_expiry(options)
    if not expiry:
        raise ValueError(f"No upcoming expiry found for {symbol}")
    options = [i for i in options if i["expiry"] == expiry]

    # 2. Spot price to find ATM
    underlying_map = {
        "NIFTY":      "NSE:NIFTY 50",
        "BANKNIFTY":  "NSE:NIFTY BANK",
        "FINNIFTY":   "NSE:NIFTY FIN SERVICE",
        "MIDCPNIFTY": "NSE:NIFTY MID SELECT",
    }
    ul_sym   = underlying_map.get(symbol, f"NSE:{symbol}")
    ltp_data = client.ltp([ul_sym])
    spot     = ltp_data[ul_sym]["last_price"]

    strikes = sorted(set(i["strike"] for i in options))
    step = 50
    if len(strikes) >= 2:
        diffs = [strikes[j+1] - strikes[j] for j in range(min(10, len(strikes)-1))]
        step  = min(d for d in diffs if d > 0)

    atm = round_to_strike(spot, step)

    # 3. Strike window: ATM ± otm_count
    strike_range = set(atm + step * i for i in range(-otm_count, otm_count + 1))

    # 4. Build symbol → meta map
    sym_map = {}
    for i in options:
        if i["strike"] in strike_range:
            sym_map[i["tradingsymbol"]] = {
                "strike": i["strike"],
                "type":   i["instrument_type"],
                "key":    f"{EXCHANGE}:{i['tradingsymbol']}",
            }
    if not sym_map:
        raise ValueError("No option instruments found in strike range")

    # 5. Fetch live quotes
    trading_syms = [f"{EXCHANGE}:{s}" for s in sym_map]
    quotes       = client.quote(trading_syms)

    # 6. Collate per strike
    data = {}
    volume_snapshot = {}
    for full_sym, q in quotes.items():
        ts   = full_sym.split(":")[1]
        meta = sym_map.get(ts)
        if not meta:
            continue
        strike    = meta["strike"]
        otype     = meta["type"]
        oi        = q.get("oi", 0) or 0
        open_oi   = (q.get("ohlc") or {}).get("open", oi) or oi
        oi_change = oi - open_oi   # COI proxy
        volume    = q.get("volume", 0) or 0
        prev_vol  = PREVIOUS_VOLUME.get(full_sym)
        vol_change = 0 if prev_vol is None else volume - prev_vol
        volume_snapshot[full_sym] = volume

        data.setdefault(strike, {})
        data[strike][otype] = {
            "oi":            oi,
            "oi_change":     oi_change,
            "ltp":           q.get("last_price", 0),
            "volume":        volume,
            "volume_change": vol_change,
            "key":           meta["key"],
        }

    PREVIOUS_VOLUME.update(volume_snapshot)

    # 7. Build rows sorted ascending by strike
    rows = []
    ltp_rows = {}
    for strike in sorted(strike_range):
        ce = data.get(strike, {}).get("CE", {
            "oi": 0, "oi_change": 0, "ltp": 0, "volume": 0,
            "volume_change": 0, "key": None,
        })
        pe = data.get(strike, {}).get("PE", {
            "oi": 0, "oi_change": 0, "ltp": 0, "volume": 0,
            "volume_change": 0, "key": None,
        })

        if strike == atm:
            call_tag = "ATM"
            put_tag  = "ATM"
        elif strike > atm:
            call_tag = "OTM"
            put_tag  = "ITM"
        else:
            call_tag = "ITM"
            put_tag  = "OTM"

        rows.append({
            "strike":              strike,
            "call_tag":            call_tag,
            "put_tag":             put_tag,
            "call_oi":             ce["oi"],
            "call_coi":            ce["oi_change"],
            "call_ltp":            ce["ltp"],
            "call_volume":         ce["volume"],
            "call_volume_change":  ce["volume_change"],
            "put_oi":              pe["oi"],
            "put_coi":             pe["oi_change"],
            "put_ltp":             pe["ltp"],
            "put_volume":          pe["volume"],
            "put_volume_change":   pe["volume_change"],
        })
        ltp_rows[strike] = {"CE": ce["key"], "PE": pe["key"]}

    CURRENT_LTP_KEYS = {"underlying": ul_sym, "rows": ltp_rows}

    # 8. Resistance / Support
    call_otm_rows = [r for r in rows if r["strike"] > atm and r["call_oi"] > 0]
    put_otm_rows  = [r for r in rows if r["strike"] < atm and r["put_oi"] > 0]

    resistance_rows = sorted(call_otm_rows, key=lambda r: r["call_oi"], reverse=True)[:2]
    support_rows    = sorted(put_otm_rows,  key=lambda r: r["put_oi"],  reverse=True)[:2]
    resistance_row  = resistance_rows[0] if resistance_rows else None
    support_row     = support_rows[0] if support_rows else None

    # 9. ATM row helpers
    atm_row  = next((r for r in rows if r["strike"] == atm), None)
    call_itm = [r for r in rows if r["strike"] < atm]   # ITM for calls
    put_itm  = [r for r in rows if r["strike"] > atm]   # ITM for puts

    # ── Condition checks ──────────────────────────────────────────────────────

    # Condition 1: Spot direction (HH / LL)
    spot_dir = check_spot_direction(spot)  # also records spot into history

    # Condition 5: Volume spike at ATM
    atm_call_vol = atm_row["call_volume"] if atm_row else 0
    atm_put_vol  = atm_row["put_volume"]  if atm_row else 0
    vol_spike    = check_volume_spike(atm_call_vol, atm_put_vol)

    signal  = "NO TRADE"
    reasons = []

    conditions = {}   # for frontend condition checklist

    if atm_row:
        atm_call_coi = atm_row["call_coi"]
        atm_put_coi  = atm_row["put_coi"]

        # ── BULLISH conditions ────────────────────────────────────────────────
        bull1 = spot_dir == "BULLISH"                              # Breakout / HH
        bull2 = atm_put_coi > atm_call_coi                        # ATM bias
        bull3 = support_row is not None                            # OTM support
        bull4 = sum(r["call_coi"] for r in call_itm) > 0          # ITM call OI
        bull5 = vol_spike                                          # Volume spike

        # ── BEARISH conditions ────────────────────────────────────────────────
        bear1 = spot_dir == "BEARISH"                              # Breakdown / LL
        bear2 = atm_call_coi > atm_put_coi                        # ATM bias
        bear3 = resistance_row is not None                         # OTM resistance
        bear4 = sum(r["put_coi"] for r in put_itm) > 0            # ITM put OI
        bear5 = vol_spike                                          # Volume spike

        conditions = {
            "spot_dir":   spot_dir,
            "vol_spike":  vol_spike,
            "atm_call_coi": atm_call_coi,
            "atm_put_coi":  atm_put_coi,
            "bull": [bull1, bull2, bull3, bull4, bull5],
            "bear": [bear1, bear2, bear3, bear4, bear5],
        }

        if bull1 and bull2 and bull3 and bull4 and bull5:
            signal  = "BUY CALL"
            reasons = [
                f"✔ Spot Breakout / Higher High (dir: {spot_dir})",
                f"✔ ATM Put COI ({atm_put_coi:+,}) > Call COI ({atm_call_coi:+,}) — Bullish bias",
                f"✔ OTM Put support at {support_row['strike']} (Put OI: {support_row['put_oi']:,})",
                "✔ ITM Call OI building — conviction confirmed",
                "✔ Volume spike at ATM — participation confirmed",
            ]
        elif bear1 and bear2 and bear3 and bear4 and bear5:
            signal  = "BUY PUT"
            reasons = [
                f"✔ Spot Breakdown / Lower Low (dir: {spot_dir})",
                f"✔ ATM Call COI ({atm_call_coi:+,}) > Put COI ({atm_put_coi:+,}) — Bearish bias",
                f"✔ OTM Call resistance at {resistance_row['strike']} (Call OI: {resistance_row['call_oi']:,})",
                "✔ ITM Put OI building — conviction confirmed",
                "✔ Volume spike at ATM — participation confirmed",
            ]
        else:
            # Build partial-match explanation
            failed = []
            if not (bull1 or bear1): failed.append("Spot sideways — no clear HH/LL")
            if not vol_spike:        failed.append("Volume below spike threshold")
            if not (bull2 or bear2): failed.append("ATM COI mixed — no directional bias")
            if not (bull4 or bear4): failed.append("ITM OI not confirming direction")
            reasons = ["Mixed signals — not all 5 conditions align. Stay flat."] + \
                      [f"✘ {f}" for f in failed]

    # Spot history snapshot for frontend info
    spot_history_list = list(SPOT_HISTORY)
    recent_high = max(spot_history_list) if spot_history_list else None
    recent_low  = min(spot_history_list) if spot_history_list else None

    return {
        "symbol":     symbol,
        "expiry":     str(expiry),
        "spot":       spot,
        "atm":        atm,
        "signal":     signal,
        "reasons":    reasons,
        "resistance": resistance_row["strike"] if resistance_row else None,
        "support":    support_row["strike"]    if support_row    else None,
        "resistance_levels": [
            {"strike": r["strike"], "oi": r["call_oi"], "rank": idx + 1}
            for idx, r in enumerate(resistance_rows)
        ],
        "support_levels": [
            {"strike": r["strike"], "oi": r["put_oi"], "rank": idx + 1}
            for idx, r in enumerate(support_rows)
        ],
        "rows":       rows,
        "conditions": conditions,
        "spot_dir":   spot_dir,
        "vol_spike":  vol_spike,
        "recent_high": recent_high,
        "recent_low":  recent_low,
    }


def fetch_ltp_data():
    client = ensure_kite()
    cached = CURRENT_LTP_KEYS
    underlying = cached.get("underlying")
    ltp_rows = cached.get("rows") or {}

    if not underlying or not ltp_rows:
        return {"spot": None, "rows": []}

    keys = [underlying]
    for legs in ltp_rows.values():
        keys.extend(k for k in legs.values() if k)
    keys = list(dict.fromkeys(keys))

    prices = client.ltp(keys)

    def last_price(key):
        if not key:
            return None
        return (prices.get(key) or {}).get("last_price")

    rows = []
    for strike in sorted(ltp_rows):
        legs = ltp_rows[strike]
        rows.append({
            "strike":   strike,
            "call_ltp": last_price(legs.get("CE")),
            "put_ltp":  last_price(legs.get("PE")),
        })

    return {
        "spot": last_price(underlying),
        "rows": rows,
    }


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/oi")
def api_oi():
    try:
        data = fetch_oi_data()
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/ltp")
def api_ltp():
    try:
        data = fetch_ltp_data()
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500


# ══════════════════════════════════════════════════════════════════════════════
#  EMBEDDED FRONTEND
# ══════════════════════════════════════════════════════════════════════════════
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en" data-theme="day">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>OI Signal Dashboard</title>
<style>
/* ── THEMES ── */
[data-theme="day"] {
  --bg:         #f2f4f7;
  --surface:    #ffffff;
  --surface2:   #f8f9fb;
  --border:     #d4d9e2;
  --border2:    #e8ebf0;
  --text:       #1a1e2b;
  --text2:      #4a5568;
  --muted:      #8a97b0;
  --accent:     #1a56db;
  --green:      #166534;
  --green-bg:   #dcfce7;
  --green-bd:   #86efac;
  --red:        #991b1b;
  --red-bg:     #fee2e2;
  --red-bd:     #fca5a5;
  --yellow:     #854d0e;
  --yellow-bg:  #fef3c7;
  --yellow-bd:  #fcd34d;
  --atm-bg:     #fffbeb;
  --atm-bd:     #f59e0b;
  --call-bar:   #dc2626;
  --put-bar:    #16a34a;
  --th-bg:      #111827;
  --th-text:    #f8fafc;
  --res-row-1:  #b91c1c;
  --res-row-2:  #fee2e2;
  --sup-row-1:  #15803d;
  --sup-row-2:  #dcfce7;
  --level-row-text: #ffffff;
  --shadow:     0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.04);
  --log-bull:   #dcfce7;
  --log-bull-bd:#86efac;
  --log-bull-tx:#166534;
  --log-bear:   #fee2e2;
  --log-bear-bd:#fca5a5;
  --log-bear-tx:#991b1b;
  --log-none:   #fef3c7;
  --log-none-bd:#fcd34d;
  --log-none-tx:#854d0e;
  --cond-ok:    #166534;
  --cond-fail:  #991b1b;
}
[data-theme="night"] {
  --bg:         #0d1117;
  --surface:    #161b22;
  --surface2:   #0d1117;
  --border:     #2a3340;
  --border2:    #1e2a38;
  --text:       #e0e6f0;
  --text2:      #8b9ab8;
  --muted:      #4a5a74;
  --accent:     #58a6ff;
  --green:      #3fb868;
  --green-bg:   #0a2010;
  --green-bd:   #1a6030;
  --red:        #f07070;
  --red-bg:     #200a0a;
  --red-bd:     #602020;
  --yellow:     #e0b040;
  --yellow-bg:  #1a1200;
  --yellow-bd:  #604000;
  --atm-bg:     #1a1800;
  --atm-bd:     #b08000;
  --call-bar:   #f07070;
  --put-bar:    #3fb868;
  --th-bg:      #020617;
  --th-text:    #f8fafc;
  --res-row-1:  #7f1d1d;
  --res-row-2:  #3f1212;
  --sup-row-1:  #14532d;
  --sup-row-2:  #0f2f1d;
  --level-row-text: #ffffff;
  --shadow:     0 1px 3px rgba(0,0,0,.4);
  --log-bull:   #0a2010;
  --log-bull-bd:#1a6030;
  --log-bull-tx:#3fb868;
  --log-bear:   #200a0a;
  --log-bear-bd:#602020;
  --log-bear-tx:#f07070;
  --log-none:   #1a1200;
  --log-none-bd:#604000;
  --log-none-tx:#e0b040;
  --cond-ok:    #3fb868;
  --cond-fail:  #f07070;
}

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}

body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 13px;
  line-height: 1.5;
  min-height: 100vh;
  transition: background .2s, color .2s;
}

.wrap { max-width: 1700px; margin: 0 auto; padding: 18px 14px; }

/* ── HEADER ── */
.header {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 10px; margin-bottom: 16px;
}
.header h1 { font-size: 18px; font-weight: 700; }
.header .sub { font-size: 11px; color: var(--muted); margin-top: 2px; }
.hright { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
#clock { font-size: 12px; color: var(--text2); font-variant-numeric: tabular-nums; }

.theme-btn {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 5px; padding: 5px 11px; font-size: 12px;
  font-family: inherit; color: var(--text); cursor: pointer;
  transition: background .15s;
}
.theme-btn:hover { background: var(--surface2); }

/* ── SIGNAL BAR ── */
.signal-bar {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px 18px; margin-bottom: 14px;
  box-shadow: var(--shadow);
  display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-start;
}
.sig-pill {
  font-size: 15px; font-weight: 700; padding: 7px 18px;
  border-radius: 5px; letter-spacing: .02em; white-space: nowrap; align-self: center;
}
.sig-bull { background: var(--green-bg); color: var(--green); border: 1px solid var(--green-bd); }
.sig-bear { background: var(--red-bg);   color: var(--red);   border: 1px solid var(--red-bd);   }
.sig-none { background: var(--yellow-bg);color: var(--yellow);border: 1px solid var(--yellow-bd); }

.sig-meta { display: flex; flex-wrap: wrap; gap: 8px; flex: 1; }
.meta-item {
  background: var(--surface2); border: 1px solid var(--border2);
  border-radius: 5px; padding: 7px 12px; min-width: 100px;
}
.meta-item label {
  font-size: 10px; color: var(--muted); text-transform: uppercase;
  letter-spacing: .06em; display: block; margin-bottom: 2px;
}
.meta-item .val { font-size: 13px; font-weight: 600; }
.meta-item .val.g { color: var(--green); }
.meta-item .val.r { color: var(--red);   }
.meta-item .val.bull { color: var(--green); }
.meta-item .val.bear { color: var(--red); }
.meta-item .val.neut { color: var(--yellow); }

.reasons { flex: 0 0 100%; display: flex; flex-direction: column; gap: 3px; padding-top: 2px; }
.reason {
  font-size: 12px; color: var(--text2); padding: 4px 9px;
  border-left: 3px solid var(--accent); background: var(--surface2);
  border-radius: 0 3px 3px 0;
}

/* ── CONDITION CHECKLIST ── */
.cond-grid {
  display: flex; flex-wrap: wrap; gap: 6px; flex: 0 0 100%; padding-top: 4px;
}
.cond-item {
  display: flex; align-items: center; gap: 5px;
  background: var(--surface2); border: 1px solid var(--border2);
  border-radius: 4px; padding: 4px 9px; font-size: 11px;
}
.cond-item .cicon { font-size: 12px; }
.cond-ok   .cicon { color: var(--cond-ok); }
.cond-fail .cicon { color: var(--cond-fail); }
.cond-na   .cicon { color: var(--muted); }

/* ── MAIN LAYOUT: table + log panel ── */
.main-layout {
  display: flex; gap: 12px; align-items: flex-start;
}
.tbl-col { flex: 1 1 0; min-width: 0; }

/* ── STEP CARDS ── */
.steps {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px; margin-bottom: 14px;
}
.step-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 7px; padding: 11px 13px; box-shadow: var(--shadow);
}
.step-num   { font-size: 10px; font-weight: 700; color: var(--accent); margin-bottom: 3px; letter-spacing:.05em; }
.step-title { font-size: 12px; font-weight: 600; margin-bottom: 3px; }
.step-body  { font-size: 11px; color: var(--text2); line-height: 1.6; }

/* ── TABLE CARD ── */
.tbl-wrap {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; overflow: hidden; box-shadow: var(--shadow);
}
.tbl-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 11px 14px; border-bottom: 1px solid var(--border);
  flex-wrap: wrap; gap: 8px;
}
.tbl-title { font-size: 12px; font-weight: 700; letter-spacing: .03em; }

.refresh-btn {
  background: var(--accent); color: #fff; border: none; border-radius: 4px;
  padding: 5px 13px; font-family: inherit; font-size: 12px; font-weight: 600;
  cursor: pointer; transition: opacity .15s;
}
.refresh-btn:hover    { opacity: .87; }
.refresh-btn:disabled { opacity: .5; cursor: not-allowed; }

.tbl-scroll { overflow-x: auto; }

table { width: 100%; border-collapse: collapse; font-size: 12px; }

thead tr { background: var(--th-bg); }
thead th {
  padding: 8px 10px; font-size: 10px; font-weight: 800; color: var(--th-text);
  text-transform: uppercase; letter-spacing: .06em; white-space: nowrap;
  border-bottom: 2px solid var(--border);
}
.th-call { text-align: right; }
.th-str  { text-align: center; background: var(--th-bg); min-width: 90px; }
.th-put  { text-align: left; }

tbody tr { border-bottom: 1px solid var(--border2); transition: background .1s; }
tbody tr:last-child { border-bottom: none; }
tbody tr:hover { background: var(--surface2); }
tbody tr.atm-row { background: var(--atm-bg); border-top: 2px solid var(--atm-bd); border-bottom: 2px solid var(--atm-bd); }
tbody tr.atm-row:hover { background: var(--atm-bg); }
tbody tr.level-res-1 td,
tbody tr.level-res-1 .td-str { background: var(--res-row-1); color: var(--level-row-text); }
tbody tr.level-res-2 td,
tbody tr.level-res-2 .td-str { background: var(--res-row-2); }
tbody tr.level-sup-1 td,
tbody tr.level-sup-1 .td-str { background: var(--sup-row-1); color: var(--level-row-text); }
tbody tr.level-sup-2 td,
tbody tr.level-sup-2 .td-str { background: var(--sup-row-2); }
tbody tr.level-res-1:hover td,
tbody tr.level-res-1:hover .td-str { background: var(--res-row-1); }
tbody tr.level-res-2:hover td,
tbody tr.level-res-2:hover .td-str { background: var(--res-row-2); }
tbody tr.level-sup-1:hover td,
tbody tr.level-sup-1:hover .td-str { background: var(--sup-row-1); }
tbody tr.level-sup-2:hover td,
tbody tr.level-sup-2:hover .td-str { background: var(--sup-row-2); }
tbody tr.level-res-1 .coi-p,
tbody tr.level-res-1 .coi-n,
tbody tr.level-res-1 .coi-z,
tbody tr.level-sup-1 .coi-p,
tbody tr.level-sup-1 .coi-n,
tbody tr.level-sup-1 .coi-z { color: var(--level-row-text); }

td { padding: 7px 10px; vertical-align: middle; white-space: nowrap; }

.td-str {
  text-align: center; font-weight: 700; font-size: 13px;
  background: var(--surface2);
  border-left: 1px solid var(--border); border-right: 1px solid var(--border);
}
.atm-row .td-str { color: var(--accent); }
.atm-label {
  display: inline-block; font-size: 9px; font-weight: 600;
  color: var(--atm-bd); margin-left: 4px; vertical-align: middle;
}

.td-call { text-align: right; }
.td-put  { text-align: left;  }

.bar-call { display: flex; align-items: center; justify-content: flex-end; gap: 5px; }
.bar-put  { display: flex; align-items: center; justify-content: flex-start;  gap: 5px; }
.oi-bar   { height: 5px; border-radius: 2px; min-width: 2px; max-width: 80px; flex-shrink: 0; }
.call-bar { background: var(--call-bar); }
.put-bar  { background: var(--put-bar);  }

.coi-p  { color: var(--green); font-weight: 600; }
.coi-n  { color: var(--red);   font-weight: 600; }
.coi-z  { color: var(--muted); }

.tag {
  display: inline-block; font-size: 9px; font-weight: 700;
  padding: 1px 5px; border-radius: 3px; letter-spacing: .04em;
}
.tag-atm { background: var(--yellow-bg); color: var(--yellow); border: 1px solid var(--yellow-bd); }
.tag-otm { background: var(--red-bg);    color: var(--red);    border: 1px solid var(--red-bd);    }
.tag-itm { background: var(--green-bg);  color: var(--green);  border: 1px solid var(--green-bd);  }

#status { font-size: 12px; color: var(--muted); padding: 10px 14px; }
.s-load { color: var(--accent); }
.s-ok   { color: var(--text2); }
.s-err  { color: var(--red);    }

/* ── SIGNAL LOG PANEL ── */
.log-panel {
  flex: 0 0 260px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; box-shadow: var(--shadow);
  display: flex; flex-direction: column;
  max-height: 700px;
  position: sticky; top: 14px;
}
.log-header {
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
  flex-shrink: 0;
}
.log-title { font-size: 12px; font-weight: 700; letter-spacing: .03em; }
.log-clear {
  background: none; border: 1px solid var(--border); border-radius: 3px;
  padding: 2px 7px; font-size: 10px; color: var(--muted); cursor: pointer;
  font-family: inherit;
}
.log-clear:hover { color: var(--red); border-color: var(--red); }

/* sticky column headers inside the scrollable log */
.log-tbl-wrap {
  flex: 1; overflow-y: auto;
}
.log-tbl-wrap table {
  width: 100%; border-collapse: collapse; font-size: 12px;
}
.log-tbl-wrap thead th {
  position: sticky; top: 0; z-index: 1;
  background: var(--th-bg); color: var(--th-text);
  padding: 7px 10px; font-size: 10px; font-weight: 800;
  text-transform: uppercase; letter-spacing: .06em;
  border-bottom: 2px solid var(--border);
}
.log-tbl-wrap thead th:first-child { text-align: center; width: 64px; }
.log-tbl-wrap thead th:last-child  { text-align: center; }

.log-tbl-wrap tbody tr {
  border-bottom: 1px solid var(--border2);
  animation: fadeIn .25s ease;
}
.log-tbl-wrap tbody tr:last-child { border-bottom: none; }
@keyframes fadeIn { from { opacity:0; } to { opacity:1; } }

.log-tbl-wrap tbody td {
  padding: 6px 10px; vertical-align: middle; white-space: nowrap;
}
.log-tbl-wrap tbody td:first-child {
  text-align: center; font-size: 11px;
  font-variant-numeric: tabular-nums; color: var(--muted);
}
.log-tbl-wrap tbody td:last-child { text-align: center; }

/* signal cell pill */
.log-sig-pill {
  display: inline-block; font-size: 11px; font-weight: 700;
  padding: 2px 8px; border-radius: 3px; letter-spacing: .02em;
}
.log-sig-pill.bull { background: var(--log-bull); color: var(--log-bull-tx); border: 1px solid var(--log-bull-bd); }
.log-sig-pill.bear { background: var(--log-bear); color: var(--log-bear-tx); border: 1px solid var(--log-bear-bd); }
.log-sig-pill.none { background: var(--log-none); color: var(--log-none-tx); border: 1px solid var(--log-none-bd); }

/* empty state row */
.log-empty td {
  text-align: center; color: var(--muted); font-size: 11px;
  padding: 22px 10px !important;
}

.log-count {
  font-size: 10px; color: var(--muted); text-align: center;
  padding: 6px 0; border-top: 1px solid var(--border);
  flex-shrink: 0;
}

footer { text-align: center; font-size: 10px; color: var(--muted); padding: 14px 0 6px; }

@media (max-width: 900px) {
  .main-layout { flex-direction: column; }
  .log-panel { flex: none; width: 100%; max-height: 260px; position: static; }
}
</style>
</head>
<body>
<div class="wrap">

  <!-- HEADER -->
  <div class="header">
    <div>
      <h1>OI Signal Dashboard</h1>
      <div class="sub">Kite Connect · NFO · Open Interest Analysis · All 5 conditions must align</div>
    </div>
    <div class="hright">
      <span id="clock"></span>
      <button class="theme-btn" id="themeBtn" onclick="toggleTheme()">☀ Day</button>
    </div>
  </div>

  <!-- SIGNAL BAR -->
  <div class="signal-bar">
    <div class="sig-pill sig-none" id="sigPill">Loading…</div>
    <div class="sig-meta">
      <div class="meta-item"><label>Symbol</label>   <div class="val"    id="mSymbol">—</div></div>
      <div class="meta-item"><label>Expiry</label>    <div class="val"    id="mExpiry">—</div></div>
      <div class="meta-item"><label>Spot</label>      <div class="val"    id="mSpot">—</div></div>
      <div class="meta-item"><label>ATM Strike</label><div class="val"    id="mAtm">—</div></div>
      <div class="meta-item"><label>Spot Dir</label>  <div class="val"    id="mSpotDir">—</div></div>
      <div class="meta-item"><label>Rec High</label>  <div class="val r"  id="mRecHigh">—</div></div>
      <div class="meta-item"><label>Rec Low</label>   <div class="val g"  id="mRecLow">—</div></div>
      <div class="meta-item"><label>Resistance</label><div class="val r"  id="mRes">—</div></div>
      <div class="meta-item"><label>Support</label>   <div class="val g"  id="mSup">—</div></div>
      <div class="meta-item"><label>Volume</label>    <div class="val"    id="mVol">—</div></div>
    </div>

    <!-- Condition checklist -->
    <div class="cond-grid" id="condGrid"></div>

    <div class="reasons" id="reasons"></div>
  </div>

  <!-- STEP CARDS -->
  <div class="steps">
    <div class="step-card">
      <div class="step-num">STEP 1 — Spot</div>
      <div class="step-title">Breakout / Breakdown</div>
      <div class="step-body">Spot &gt; recent high → Bullish (HH)<br>Spot &lt; recent low → Bearish (LL)<br>Sideways → NO TRADE</div>
    </div>
    <div class="step-card">
      <div class="step-num">STEP 2 — ATM Direction</div>
      <div class="step-title">Call COI vs Put COI</div>
      <div class="step-body">Put COI &gt; Call COI → Bullish<br>Call COI &gt; Put COI → Bearish</div>
    </div>
    <div class="step-card">
      <div class="step-num">STEP 3 — OTM Levels</div>
      <div class="step-title">Resistance &amp; Support</div>
      <div class="step-body">OTM Call max OI = Resistance<br>OTM Put max OI = Support</div>
    </div>
    <div class="step-card">
      <div class="step-num">STEP 4 — ITM Confirm</div>
      <div class="step-title">OI Building in Direction?</div>
      <div class="step-body">YES → Conviction trade<br>NO  → Wait, weak move</div>
    </div>
    <div class="step-card">
      <div class="step-num">STEP 5 — Volume</div>
      <div class="step-title">ATM Volume Spike</div>
      <div class="step-body">ATM vol ≥ 1.25× avg → Spike<br>Low volume → Trap zone</div>
    </div>
  </div>

  <!-- MAIN LAYOUT -->
  <div class="main-layout">

    <!-- OI TABLE -->
    <div class="tbl-col">
      <div class="tbl-wrap">
        <div class="tbl-head">
          <div class="tbl-title">Strike-wise OI Table — Ascending (lowest → highest)</div>
          <button class="refresh-btn" id="refreshBtn" onclick="loadData()">Refresh</button>
        </div>
        <div id="status" class="s-load">Fetching data from Kite Connect…</div>
        <div class="tbl-scroll">
          <table id="oiTable" style="display:none">
            <thead>
              <tr>
                <th class="th-call">Call Tag</th>
                <th class="th-call">Call LTP</th>
                <th class="th-call">Call Volume</th>
                <th class="th-call">Call Vol Δ</th>
                <th class="th-call">Call OI</th>
                <th class="th-call">Call COI</th>
                <th class="th-str">Strike</th>
                <th class="th-put">Put COI</th>
                <th class="th-put">Put OI</th>
                <th class="th-put">Put Vol Δ</th>
                <th class="th-put">Put Volume</th>
                <th class="th-put">Put LTP</th>
                <th class="th-put">Put Tag</th>
              </tr>
            </thead>
            <tbody id="oiBody"></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- SIGNAL LOG -->
    <div class="log-panel">
      <div class="log-header">
        <div class="log-title">📋 Signal Log</div>
        <button class="log-clear" onclick="clearLog()">Clear</button>
      </div>
      <div class="log-tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Signal</th>
            </tr>
          </thead>
          <tbody id="logBody">
            <tr class="log-empty"><td colspan="2">Waiting for first refresh…</td></tr>
          </tbody>
        </table>
      </div>
      <div class="log-count" id="logCount">0 entries</div>
    </div>

  </div>

  <footer>OI Signal Dashboard · Kite Connect API · OI: 3-min candle +10s · LTP: every second · All 5 conditions required</footer>
</div>

<script>
/* ── THEME ── */
let theme = 'day';
function toggleTheme(){
  theme = theme === 'day' ? 'night' : 'day';
  document.documentElement.setAttribute('data-theme', theme);
  document.getElementById('themeBtn').textContent = theme === 'day' ? '☀ Day' : '☾ Night';
}

/* ── CLOCK ── */
(function(){
  const el = document.getElementById('clock');
  function tick(){ el.textContent = new Date().toLocaleTimeString('en-IN',{hour12:false}); }
  tick(); setInterval(tick, 1000);
})();

/* ── UTILS ── */
function fmt(n)  { return n == null ? '—' : Number(n).toLocaleString('en-IN'); }
function fmtP(n) { return n == null ? '—' : Number(n).toFixed(2); }
function fmtC(n) {
  if (n == null) return '—';
  return (n >= 0 ? '+' : '') + Number(n).toLocaleString('en-IN');
}
function coiCls(v){ return v > 0 ? 'coi-p' : v < 0 ? 'coi-n' : 'coi-z'; }
function maxOf(rows, key){ return Math.max(...rows.map(r => r[key]||0), 1); }
function strikeKey(v){ return String(v).replace(/[^0-9A-Za-z_-]/g, '_'); }

function nowStr(){
  return new Date().toLocaleTimeString('en-IN', {hour:'2-digit', minute:'2-digit', hour12:false});
}

/* ── SIGNAL LOG ── */
let signalLog = [];   // [{time, signal}]

function addLogEntry(signal, spot){
  const entry = { time: nowStr(), signal };
  signalLog.unshift(entry);  // newest first
  renderLog();
}

function renderLog(){
  const body = document.getElementById('logBody');
  if (signalLog.length === 0) {
    body.innerHTML = '<tr class="log-empty"><td colspan="2">No signals yet…</td></tr>';
    document.getElementById('logCount').textContent = '0 entries';
    return;
  }
  body.innerHTML = '';
  for (const e of signalLog){
    const cls = e.signal.includes('CALL') ? 'bull' :
                e.signal.includes('PUT')  ? 'bear' : 'none';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${e.time}</td>
      <td><span class="log-sig-pill ${cls}">${e.signal}</span></td>
    `;
    body.appendChild(tr);
  }
  document.getElementById('logCount').textContent =
    signalLog.length + ' entr' + (signalLog.length === 1 ? 'y' : 'ies');
}

function clearLog(){
  signalLog = [];
  renderLog();
}

/* ── CONDITION CHECKLIST ── */
const COND_LABELS_BULL = [
  'Spot Breakout / HH',
  'ATM Put COI > Call COI',
  'OTM Put Support exists',
  'ITM Call OI building',
  'Volume Spike at ATM',
];
const COND_LABELS_BEAR = [
  'Spot Breakdown / LL',
  'ATM Call COI > Put COI',
  'OTM Call Resistance exists',
  'ITM Put OI building',
  'Volume Spike at ATM',
];

function renderConditions(cond){
  const grid = document.getElementById('condGrid');
  if (!cond || !cond.bull) { grid.innerHTML = ''; return; }

  const isBull = cond.bull.every(Boolean);
  const isBear = cond.bear.every(Boolean);
  const labels = (cond.bear && cond.bear[0]) ? COND_LABELS_BEAR : COND_LABELS_BULL;
  const flags  = (cond.bear && cond.bear[0]) ? cond.bear : cond.bull;

  grid.innerHTML = flags.map((ok, i) => `
    <div class="cond-item ${ok ? 'cond-ok' : 'cond-fail'}">
      <span class="cicon">${ok ? '✔' : '✘'}</span>
      <span>${labels[i]}</span>
    </div>
  `).join('');
}

/* ── NETWORK ── */
const MARKET_OPEN_HOUR = 9;
const MARKET_OPEN_MINUTE = 15;
const OI_REFRESH_MS = 3 * 60 * 1000;
const OI_REFRESH_DELAY_MS = 10 * 1000;
let hasOiData = false;
let oiLoading = false;
let ltpLoading = false;
let oiTimer = null;

function notifyParentSize(){
  try {
    if (window.__MERGED_DASHBOARD && typeof window.__MERGED_DASHBOARD.notifyParentSize === 'function') {
      window.__MERGED_DASHBOARD.notifyParentSize();
    }
  } catch (e) {}
}

function setStatus(message, cls){
  const status = document.getElementById('status');
  status.className = cls;
  status.style.display = 'block';
  status.textContent = message;
  notifyParentSize();
}

function setRefreshButtonLoading(isLoading){
  const btn = document.getElementById('refreshBtn');
  btn.disabled = isLoading;
  btn.textContent = isLoading ? (hasOiData ? 'Updating...' : 'Loading...') : 'Refresh';
}

async function loadData(){
  if (oiLoading) return;
  oiLoading = true;
  const table  = document.getElementById('oiTable');
  const firstLoad = !hasOiData;
  setRefreshButtonLoading(true);
  if (firstLoad) {
    setStatus('Fetching data from Kite Connect...', 's-load');
    table.style.display = 'none';
  } else {
    setStatus('Updating live OI values...', 's-load');
  }
  try {
    const res  = await fetch('/api/oi', { cache: 'no-store' });
    const json = await res.json();
    if (!json.ok) throw new Error(json.error || 'Unknown error');
    render(json.data);
    addLogEntry(json.data.signal, json.data.spot);
    hasOiData = true;
    table.style.display  = '';
    setStatus('Last full OI update: ' + nowStr(), 's-ok');
  } catch(e){
    if (!hasOiData) {
      table.style.display = 'none';
    }
    setStatus((hasOiData ? 'Update failed: ' : 'Error: ') + e.message, 's-err');
  } finally {
    setRefreshButtonLoading(false);
    oiLoading = false;
    notifyParentSize();
  }
}

async function refreshLtp(){
  if (!hasOiData || oiLoading || ltpLoading) return;
  ltpLoading = true;
  try {
    const res = await fetch('/api/ltp');
    const json = await res.json();
    if (json.ok) updateLtp(json.data);
  } finally {
    ltpLoading = false;
  }
}

function updateLtp(d){
  if (d.spot != null) document.getElementById('mSpot').textContent = fmtP(d.spot);
  for (const r of d.rows || []){
    const key = strikeKey(r.strike);
    const callEl = document.getElementById(`callLtp-${key}`);
    const putEl  = document.getElementById(`putLtp-${key}`);
    if (callEl && r.call_ltp != null) callEl.textContent = fmtP(r.call_ltp);
    if (putEl && r.put_ltp != null) putEl.textContent = fmtP(r.put_ltp);
  }
}

function msUntilNextOiRefresh(now = new Date()){
  const start = new Date(now);
  start.setHours(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE, 0, 0);
  if (now < start) {
    return start.getTime() + OI_REFRESH_MS + OI_REFRESH_DELAY_MS - now.getTime();
  }
  const elapsed = now.getTime() - start.getTime();
  const completedSlots = Math.floor(elapsed / OI_REFRESH_MS) + 1;
  let target = new Date(start.getTime() + completedSlots * OI_REFRESH_MS + OI_REFRESH_DELAY_MS);
  if (target <= now) target = new Date(target.getTime() + OI_REFRESH_MS);
  return target.getTime() - now.getTime();
}

function scheduleOiRefresh(){
  window.clearTimeout(oiTimer);
  oiTimer = window.setTimeout(async () => {
    await loadData();
    scheduleOiRefresh();
  }, msUntilNextOiRefresh());
}

/* ── RENDER ── */
function render(d){
  /* Signal pill */
  const pill = document.getElementById('sigPill');
  pill.textContent = d.signal;
  pill.className   = 'sig-pill ' + (
    d.signal.includes('CALL') ? 'sig-bull' :
    d.signal.includes('PUT')  ? 'sig-bear' : 'sig-none'
  );

  /* Meta */
  document.getElementById('mSymbol').textContent = d.symbol;
  document.getElementById('mExpiry').textContent = d.expiry;
  document.getElementById('mSpot').textContent   = fmtP(d.spot);
  document.getElementById('mAtm').textContent    = fmt(d.atm);
  document.getElementById('mRes').textContent    = d.resistance != null ? fmt(d.resistance) : '—';
  document.getElementById('mSup').textContent    = d.support    != null ? fmt(d.support)    : '—';

  /* Spot direction */
  const sdEl = document.getElementById('mSpotDir');
  sdEl.textContent = d.spot_dir || '—';
  sdEl.className   = 'val ' + (
    d.spot_dir === 'BULLISH' ? 'bull' :
    d.spot_dir === 'BEARISH' ? 'bear' : 'neut'
  );

  /* Recent high / low */
  document.getElementById('mRecHigh').textContent = d.recent_high != null ? fmtP(d.recent_high) : '—';
  document.getElementById('mRecLow').textContent  = d.recent_low  != null ? fmtP(d.recent_low)  : '—';

  /* Volume spike */
  const volEl = document.getElementById('mVol');
  volEl.textContent = d.vol_spike ? '🔥 SPIKE' : 'Low';
  volEl.className   = 'val ' + (d.vol_spike ? 'bull' : 'neut');

  /* Conditions checklist */
  renderConditions(d.conditions);

  /* Reasons */
  document.getElementById('reasons').innerHTML =
    (d.reasons||[]).map(r=>`<div class="reason">${r}</div>`).join('');

  /* Table */
  const maxCI = maxOf(d.rows, 'call_oi');
  const maxPI = maxOf(d.rows, 'put_oi');
  const atm   = d.atm;
  const resRanks = new Map((d.resistance_levels || []).map(l => [Number(l.strike), l.rank]));
  const supRanks = new Map((d.support_levels || []).map(l => [Number(l.strike), l.rank]));

  const body = document.getElementById('oiBody');
  const scroller = document.querySelector('.tbl-scroll');
  const prevLeft = scroller ? scroller.scrollLeft : 0;
  body.innerHTML = '';

  for (const r of d.rows){
    const isAtm = r.strike === atm;
    const tr    = document.createElement('tr');
    if (isAtm) tr.classList.add('atm-row');
    if (resRanks.has(Number(r.strike))) tr.classList.add(`level-res-${resRanks.get(Number(r.strike))}`);
    if (supRanks.has(Number(r.strike))) tr.classList.add(`level-sup-${supRanks.get(Number(r.strike))}`);

    const cW = Math.round((r.call_oi / maxCI) * 80);
    const pW = Math.round((r.put_oi  / maxPI) * 80);

    const ctCls = r.call_tag==='ATM'?'tag-atm':r.call_tag==='OTM'?'tag-otm':'tag-itm';
    const ptCls = r.put_tag ==='ATM'?'tag-atm':r.put_tag ==='OTM'?'tag-otm':'tag-itm';

    const atmLabel = isAtm ? '<span class="atm-label">ATM</span>' : '';
    const sKey = strikeKey(r.strike);

    tr.innerHTML = `
      <td class="td-call"><span class="tag ${ctCls}">${r.call_tag}</span></td>
      <td class="td-call" id="callLtp-${sKey}">${fmtP(r.call_ltp)}</td>
      <td class="td-call">${fmt(r.call_volume)}</td>
      <td class="td-call ${coiCls(r.call_volume_change)}">${fmtC(r.call_volume_change)}</td>
      <td class="td-call">
        <div class="bar-call">
          ${fmt(r.call_oi)}<div class="oi-bar call-bar" style="width:${cW}px"></div>
        </div>
      </td>
      <td class="td-call ${coiCls(r.call_coi)}">${fmtC(r.call_coi)}</td>

      <td class="td-str">${fmt(r.strike)}${atmLabel}</td>

      <td class="td-put ${coiCls(r.put_coi)}">${fmtC(r.put_coi)}</td>
      <td class="td-put">
        <div class="bar-put">
          <div class="oi-bar put-bar" style="width:${pW}px"></div>${fmt(r.put_oi)}
        </div>
      </td>
      <td class="td-put ${coiCls(r.put_volume_change)}">${fmtC(r.put_volume_change)}</td>
      <td class="td-put">${fmt(r.put_volume)}</td>
      <td class="td-put" id="putLtp-${sKey}">${fmtP(r.put_ltp)}</td>
      <td class="td-put"><span class="tag ${ptCls}">${r.put_tag}</span></td>
    `;
    body.appendChild(tr);
  }
  if (scroller) scroller.scrollLeft = prevLeft;
  notifyParentSize();
}

loadData().finally(scheduleOiRefresh);
window.setInterval(refreshLtp, 1000);
</script>
</body>
</html>
"""

# ── ENTRY ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  OI Signal Dashboard")
    print("  http://localhost:5000")
    print("  Edit API_KEY and ACCESS_TOKEN at the top before running!")
    print("=" * 60)
    app.run(debug=True, host="0.0.0.0", port=5000)
