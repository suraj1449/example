import os
from flask import Flask, Response

app = Flask(__name__)

HEATMAP_URL = os.getenv("HEATMAP_URL", "http://localhost:5000")
FUTURE_URL  = os.getenv("FUTURE_URL",  "http://localhost:5001")
OI_URL      = os.getenv("OI_URL",      "http://localhost:5002")

def build_html():
    return """<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Merged Market Dashboard</title>
<style>
:root {
  --bg:#f4f6fb; --surface:#ffffff; --surface-soft:#edf1f6;
  --border:#d6dee8; --text:#1d2430; --muted:#647084;
  --accent:#0f766e; --shadow:0 14px 34px rgba(15,23,42,0.08);
}
[data-theme="dark"] {
  --bg:#0f1722; --surface:#141d2b; --surface-soft:#1a2536;
  --border:#293548; --text:#e7edf7; --muted:#9ba9bc;
  --accent:#5eead4; --shadow:0 16px 38px rgba(0,0,0,0.32);
}
* { box-sizing:border-box; margin:0; padding:0; }
body {
  background:var(--bg); color:var(--text);
  font-family:"Segoe UI",Arial,sans-serif;
  transition:background .25s,color .25s;
}
.topbar {
  position:sticky; top:0; z-index:20;
  display:flex; align-items:center; justify-content:space-between;
  gap:16px; padding:14px 22px;
  background:rgba(255,255,255,.92);
  border-bottom:1px solid var(--border);
  backdrop-filter:blur(10px);
}
[data-theme="dark"] .topbar { background:rgba(20,29,43,.92); }
.brand { font-size:18px; font-weight:700; letter-spacing:.04em; }
.nav { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.nav a {
  text-decoration:none; color:var(--text); background:var(--surface);
  border:1px solid var(--border); padding:8px 12px; border-radius:8px;
  font-size:13px; font-weight:600;
  transition:background .2s,border-color .2s,color .2s,transform .2s;
}
.nav a:hover { border-color:var(--accent); color:var(--accent); transform:translateY(-1px); }
.theme-toggle {
  border:1px solid var(--border); background:var(--surface); color:var(--text);
  padding:8px 14px; border-radius:8px; font-size:13px; font-weight:600;
  cursor:pointer;
}
.theme-toggle:hover { border-color:var(--accent); color:var(--accent); }
.page { padding:20px; }
.dashboard-section {
  background:var(--surface); border:1px solid var(--border);
  border-radius:12px; box-shadow:var(--shadow);
  margin-bottom:18px; overflow:hidden; scroll-margin-top:88px;
}
.section-head {
  display:flex; align-items:center; justify-content:space-between;
  gap:12px; padding:14px 18px;
  background:var(--surface-soft); border-bottom:1px solid var(--border);
}
.section-head h2 { margin:0; font-size:18px; font-weight:700; }
.status {
  font-size:12px; color:var(--muted);
  display:flex; align-items:center; gap:6px;
}
.status-dot {
  width:8px; height:8px; border-radius:50%;
  background:#94a3b8; display:inline-block;
  transition:background .3s; flex-shrink:0;
}
.status-dot.live { background:#22c55e; animation:blink 1.4s infinite; }
.status-dot.error { background:#ef4444; animation:none; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.2} }
.frame-wrap { padding:14px; }
iframe {
  width:100%; height:calc(100vh - 165px); min-height:760px;
  border:1px solid var(--border); border-radius:10px;
  background:#ffffff; display:block;
}
#oi-frame { height:900px; min-height:900px; }
@media(max-width:900px) {
  .topbar { padding:12px 14px; }
  .page { padding:14px; }
  iframe { height:calc(100vh - 185px); min-height:620px; }
  #oi-frame { height:760px; min-height:760px; }
}
</style>
</head>
<body>

<header class="topbar">
  <div class="brand">Market Dashboard</div>
  <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
    <nav class="nav">
      <a href="#heatmap-section">HEATMAP</a>
      <a href="#future-section">FUTURE BIAS</a>
      <a href="#oi-section">OI BIAS</a>
    </nav>
    <button class="theme-toggle" id="theme-toggle">Night Theme</button>
  </div>
</header>

<main class="page">

  <section id="heatmap-section" class="dashboard-section">
    <div class="section-head">
      <h2>HEATMAP</h2>
      <div class="status">
        <span class="status-dot" id="dot-heatmap"></span>
        <span id="lbl-heatmap">Connecting…</span>
      </div>
    </div>
    <div class="frame-wrap">
      <iframe id="heatmap-frame" src=" """ + HEATMAP_URL + """ " loading="eager"></iframe>
    </div>
  </section>

  <section id="future-section" class="dashboard-section">
    <div class="section-head">
      <h2>FUTURE BIAS</h2>
      <div class="status">
        <span class="status-dot" id="dot-future"></span>
        <span id="lbl-future">Connecting…</span>
      </div>
    </div>
    <div class="frame-wrap">
      <iframe id="future-frame" src=" """ + FUTURE_URL + """ " loading="lazy"></iframe>
    </div>
  </section>

  <section id="oi-section" class="dashboard-section">
    <div class="section-head">
      <h2>OI BIAS</h2>
      <div class="status">
        <span class="status-dot" id="dot-oi"></span>
        <span id="lbl-oi">Connecting…</span>
      </div>
    </div>
    <div class="frame-wrap">
      <iframe id="oi-frame" src=" """ + OI_URL + """ " loading="lazy"></iframe>
    </div>
  </section>

</main>

<script>
let theme = "light";
document.getElementById("theme-toggle").addEventListener("click", function() {
  theme = theme === "light" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", theme);
  document.getElementById("theme-toggle").textContent =
    theme === "light" ? "Night Theme" : "Day Theme";
});

[
  { frame: "heatmap-frame", dot: "dot-heatmap", lbl: "lbl-heatmap" },
  { frame: "future-frame",  dot: "dot-future",  lbl: "lbl-future"  },
  { frame: "oi-frame",      dot: "dot-oi",      lbl: "lbl-oi"      }
].forEach(function(f) {
  var iframe = document.getElementById(f.frame);
  var dot    = document.getElementById(f.dot);
  var lbl    = document.getElementById(f.lbl);

  iframe.addEventListener("load", function() {
    dot.className = "status-dot live";
    lbl.textContent = "Live";
  });

  setTimeout(function() {
    if (!dot.classList.contains("live")) {
      dot.className = "status-dot error";
      lbl.textContent = "Waking up… please wait";
    }
  }, 15000);

  setInterval(function() {
    if (!dot.classList.contains("live")) {
      iframe.src = iframe.src;
      lbl.textContent = "Retrying…";
    }
  }, 30000);
});
</script>

</body>
</html>"""

@app.route("/")
def home():
    return Response(build_html(), mimetype="text/html")

@app.route("/healthz")
def healthz():
    return {"ok": True}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5003"))
    print("=" * 50)
    print("  Market Dashboard")
    print("  http://localhost:" + str(port))
    print("  HEATMAP_URL = " + HEATMAP_URL)
    print("  FUTURE_URL  = " + FUTURE_URL)
    print("  OI_URL      = " + OI_URL)
    print("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=False)
