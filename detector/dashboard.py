import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import psutil
from flask import Flask, jsonify


class RuntimeState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = datetime.now(timezone.utc)
        self._global_rps = 0.0
        self._top_ips: List[List[Any]] = []
        self._banned_ips: List[Dict[str, Any]] = []
        self._baseline_mean = 0.0
        self._baseline_stddev = 0.0
        self._baseline_source = "floor"

    def set_metrics(self, global_rps: float, top_ips: List[tuple[str, int]]) -> None:
        with self._lock:
            self._global_rps = global_rps
            self._top_ips = [[ip, count] for ip, count in top_ips[:10]]

    def set_baseline(self, mean_value: float, stddev_value: float, source: str) -> None:
        with self._lock:
            self._baseline_mean = mean_value
            self._baseline_stddev = stddev_value
            self._baseline_source = source

    def set_banned_ips(self, active_bans: Dict[str, Dict[str, Any]]) -> None:
        formatted: List[Dict[str, Any]] = []
        for ip, meta in active_bans.items():
            expires_at = meta.get("expires_at")
            formatted.append(
                {
                    "ip": ip,
                    "condition": str(meta.get("condition", "")),
                    "duration_seconds": meta.get("duration_seconds"),
                    "expires_at": expires_at.isoformat() if hasattr(expires_at, "isoformat") else None,
                }
            )
        with self._lock:
            self._banned_ips = formatted

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            uptime_seconds = int((datetime.now(timezone.utc) - self._started_at).total_seconds())
            return {
                "uptime_seconds": uptime_seconds,
                "global_rps": self._global_rps,
                "top_ips": self._top_ips,
                "banned_ips": self._banned_ips,
                "effective_mean": self._baseline_mean,
                "effective_stddev": self._baseline_stddev,
                "baseline_source": self._baseline_source,
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_percent": psutil.virtual_memory().percent,
            }


def create_dashboard_app(state: RuntimeState) -> Flask:
    app = Flask(__name__)

    @app.get("/api/metrics")
    def api_metrics() -> Any:
        return jsonify(state.snapshot())

    @app.get("/")
    def index() -> str:
        return """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>HNG Stage 3 Anomaly Detection Dashboard</title>
    <style>
      :root {
        --bg: #070b1a;
        --bg-soft: #0a1130;
        --panel: #0f1630;
        --panel-2: #121b3a;
        --text: #e8ecff;
        --muted: #9aa4c7;
        --ok: #22c55e;
        --warn: #f59e0b;
        --danger: #ef4444;
        --accent: #60a5fa;
        --border: rgba(255, 255, 255, 0.08);
        --radius: 16px;
      }

      * { box-sizing: border-box; }
      body {
        margin: 0;
        min-height: 100vh;
        font-family: Inter, "Segoe UI", Arial, sans-serif;
        color: var(--text);
        background:
          radial-gradient(circle at top left, #101b45 0%, transparent 35%),
          radial-gradient(circle at bottom right, #1c1240 0%, transparent 30%),
          var(--bg);
      }

      .container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 24px;
      }

      .header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 16px;
        margin-bottom: 20px;
      }

      .title-wrap h1 {
        margin: 0;
        font-size: 34px;
        font-weight: 700;
        letter-spacing: 0.2px;
      }

      .subtitle {
        margin-top: 6px;
        color: var(--muted);
        font-size: 15px;
      }

      .status-wrap {
        text-align: right;
        color: var(--muted);
        font-size: 13px;
      }

      .live-chip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        margin-bottom: 8px;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: rgba(34, 197, 94, 0.12);
        color: #b9f6ca;
        font-weight: 600;
      }

      .live-dot {
        width: 9px;
        height: 9px;
        border-radius: 999px;
        background: var(--ok);
        box-shadow: 0 0 12px rgba(34, 197, 94, 0.9);
        animation: pulse 1.8s infinite;
      }

      @keyframes pulse {
        0% { transform: scale(0.9); opacity: 0.75; }
        50% { transform: scale(1.25); opacity: 1; }
        100% { transform: scale(0.9); opacity: 0.75; }
      }

      .cards {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 14px;
        margin-bottom: 20px;
      }

      .card {
        background: linear-gradient(180deg, var(--panel), var(--panel-2));
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 16px;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.25);
        transition: transform 120ms ease;
      }

      .card:hover { transform: translateY(-2px); }
      .card-label {
        color: var(--muted);
        font-size: 13px;
        margin-bottom: 8px;
      }
      .card-value {
        font-size: 36px;
        font-weight: 700;
        line-height: 1;
        margin-bottom: 8px;
      }
      .card-sub {
        color: var(--muted);
        font-size: 12px;
      }

      .ok { color: var(--ok); }
      .warn { color: var(--warn); }
      .danger { color: var(--danger); }
      .accent { color: var(--accent); }

      .sparkline {
        width: 100%;
        height: 40px;
      }

      .panel {
        background: linear-gradient(180deg, rgba(16, 24, 52, 0.95), rgba(10, 16, 38, 0.98));
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 18px;
        margin-bottom: 14px;
      }

      .panel h2 {
        margin: 0 0 12px;
        font-size: 22px;
      }

      .baseline-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 16px;
      }

      .kv {
        display: grid;
        gap: 10px;
      }

      .kv-item {
        display: flex;
        justify-content: space-between;
        border-bottom: 1px dashed rgba(255, 255, 255, 0.09);
        padding-bottom: 8px;
        font-size: 14px;
      }

      .table {
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
      }
      .table th, .table td {
        text-align: left;
        padding: 10px 8px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      }
      .table th { color: var(--muted); font-weight: 600; font-size: 12px; }

      .bar-wrap {
        width: 100%;
        background: rgba(255, 255, 255, 0.06);
        border-radius: 999px;
        height: 8px;
        overflow: hidden;
      }
      .bar {
        height: 8px;
        background: linear-gradient(90deg, #3b82f6, #06b6d4);
      }

      .ban-tag {
        display: inline-block;
        padding: 4px 9px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        background: rgba(239, 68, 68, 0.15);
        color: #ffc3c3;
        border: 1px solid rgba(239, 68, 68, 0.4);
      }

      .muted { color: var(--muted); }
      .empty {
        color: var(--muted);
        font-style: italic;
      }

      @media (max-width: 860px) {
        .baseline-grid { grid-template-columns: 1fr; }
        .header { flex-direction: column; align-items: flex-start; }
        .status-wrap { text-align: left; }
      }
    </style>
  </head>
  <body>
    <div class="container">
      <div class="header">
        <div class="title-wrap">
          <h1>HNG Stage 3 Anomaly Detection Dashboard</h1>
          <div class="subtitle">Live metrics refresh every 3 seconds | Detector + Nginx + Nextcloud</div>
        </div>
        <div class="status-wrap">
          <div class="live-chip"><span class="live-dot"></span> Live</div>
          <div id="updatedAt">Last updated: --</div>
        </div>
      </div>

      <section class="cards">
        <article class="card">
          <div class="card-label">Global Requests/Sec</div>
          <div class="card-value accent" id="globalRps">0.000</div>
          <svg class="sparkline" viewBox="0 0 100 28" preserveAspectRatio="none">
            <polyline id="rpsLine" points="" fill="none" stroke="#60a5fa" stroke-width="2.2"></polyline>
          </svg>
        </article>

        <article class="card">
          <div class="card-label">Logs Processed</div>
          <div class="card-value" id="logsProcessed">0</div>
          <div class="card-sub">Since detector start</div>
        </article>

        <article class="card" id="bannedCard">
          <div class="card-label">Banned IPs</div>
          <div class="card-value" id="bannedCount">0</div>
          <div class="card-sub">Currently active bans</div>
        </article>

        <article class="card">
          <div class="card-label">Uptime</div>
          <div class="card-value" id="uptime">0s</div>
          <div class="card-sub">Detector runtime</div>
        </article>

        <article class="card">
          <div class="card-label">CPU Usage</div>
          <div class="card-value" id="cpuValue">0%</div>
          <div class="bar-wrap"><div class="bar" id="cpuBar" style="width:0%"></div></div>
        </article>

        <article class="card">
          <div class="card-label">Memory Usage</div>
          <div class="card-value" id="memValue">0%</div>
          <div class="bar-wrap"><div class="bar" id="memBar" style="width:0%"></div></div>
        </article>
      </section>

      <section class="panel">
        <h2>Effective Baseline</h2>
        <div class="baseline-grid">
          <div class="kv">
            <div class="kv-item"><span>Mean</span><strong id="baseMean">0.0000</strong></div>
            <div class="kv-item"><span>Stddev</span><strong id="baseStd">0.0000</strong></div>
            <div class="kv-item"><span>Source</span><strong id="baseSource">floor</strong></div>
            <div class="kv-item"><span>Current Global Req/Sec</span><strong id="baseCurrent">0.000</strong></div>
          </div>
          <div>
            <svg class="sparkline" style="height:120px" viewBox="0 0 100 60" preserveAspectRatio="none">
              <polyline id="baselineLine" points="" fill="none" stroke="#22d3ee" stroke-width="2.1"></polyline>
            </svg>
            <div class="muted" style="font-size:12px;">Trend: recent effective mean values</div>
          </div>
        </div>
      </section>

      <section class="panel">
        <h2>Top 10 Source IPs</h2>
        <table class="table">
          <thead>
            <tr><th>IP</th><th>Requests (60s)</th><th>Share</th></tr>
          </thead>
          <tbody id="topIpsBody"></tbody>
        </table>
      </section>

      <section class="panel">
        <h2>Banned IP Details</h2>
        <table class="table">
          <thead>
            <tr><th>IP</th><th>Condition</th><th>Duration</th><th>Expires</th></tr>
          </thead>
          <tbody id="bansBody"></tbody>
        </table>
      </section>
    </div>

    <script>
      const rpsHistory = [];
      const baselineHistory = [];
      let logsProcessedCounter = 0;

      function formatUptime(totalSeconds) {
        const s = Math.max(0, Number(totalSeconds || 0));
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = s % 60;
        return `${h}h ${m}m ${sec}s`;
      }

      function num(n, digits=2) {
        const v = Number(n || 0);
        return v.toFixed(digits);
      }

      function drawSparkline(values, elementId, maxPoints=36) {
        const el = document.getElementById(elementId);
        if (!el) return;
        const points = values.slice(-maxPoints);
        if (!points.length) {
          el.setAttribute('points', '');
          return;
        }
        const min = Math.min(...points);
        const max = Math.max(...points);
        const span = (max - min) || 1;
        const mapped = points.map((v, i) => {
          const x = (i / Math.max(points.length - 1, 1)) * 100;
          const y = 58 - ((v - min) / span) * 50;
          return `${x.toFixed(2)},${y.toFixed(2)}`;
        }).join(' ');
        el.setAttribute('points', mapped);
      }

      function percentToStatus(value) {
        if (value >= 80) return 'danger';
        if (value >= 55) return 'warn';
        return 'ok';
      }

      function rpsToStatus(value) {
        if (value >= 20) return 'danger';
        if (value >= 6) return 'warn';
        return 'accent';
      }

      function renderTopIps(topIps) {
        const tbody = document.getElementById('topIpsBody');
        tbody.innerHTML = '';
        if (!Array.isArray(topIps) || !topIps.length) {
          tbody.innerHTML = '<tr><td colspan="3" class="empty">No source IP traffic yet.</td></tr>';
          return;
        }
        const maxCount = Math.max(...topIps.map(row => Number(row[1] || 0)), 1);
        for (const row of topIps) {
          const ip = row[0];
          const count = Number(row[1] || 0);
          const share = (count / maxCount) * 100;
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td><code>${ip}</code></td>
            <td>${count.toLocaleString()}</td>
            <td>
              <div class="bar-wrap"><div class="bar" style="width:${share.toFixed(1)}%"></div></div>
            </td>
          `;
          tbody.appendChild(tr);
        }
      }

      function renderBans(bans) {
        const tbody = document.getElementById('bansBody');
        tbody.innerHTML = '';
        if (!Array.isArray(bans) || !bans.length) {
          tbody.innerHTML = '<tr><td colspan="4" class="empty">No active bans.</td></tr>';
          return;
        }
        for (const ban of bans) {
          const duration = ban.duration_seconds ? `${ban.duration_seconds}s` : 'permanent';
          const expires = ban.expires_at || '--';
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td><code>${ban.ip || '--'}</code></td>
            <td><span class="ban-tag">${ban.condition || 'anomaly'}</span></td>
            <td>${duration}</td>
            <td>${expires}</td>
          `;
          tbody.appendChild(tr);
        }
      }

      async function render() {
        const r = await fetch('/api/metrics');
        const d = await r.json();

        const globalRps = Number(d.global_rps || 0);
        const cpu = Number(d.cpu_percent || 0);
        const mem = Number(d.memory_percent || 0);
        const baseMean = Number(d.effective_mean || 0);
        const baseStd = Number(d.effective_stddev || 0);
        const bans = Array.isArray(d.banned_ips) ? d.banned_ips : [];

        logsProcessedCounter += Math.max(0, Math.round(globalRps * 3));
        rpsHistory.push(globalRps);
        baselineHistory.push(baseMean);

        const globalEl = document.getElementById('globalRps');
        globalEl.textContent = num(globalRps, 3);
        globalEl.className = `card-value ${rpsToStatus(globalRps)}`;

        document.getElementById('logsProcessed').textContent = logsProcessedCounter.toLocaleString();
        document.getElementById('bannedCount').textContent = bans.length.toString();
        document.getElementById('uptime').textContent = formatUptime(d.uptime_seconds);

        const cpuEl = document.getElementById('cpuValue');
        const memEl = document.getElementById('memValue');
        cpuEl.textContent = `${num(cpu, 1)}%`;
        memEl.textContent = `${num(mem, 1)}%`;
        cpuEl.className = `card-value ${percentToStatus(cpu)}`;
        memEl.className = `card-value ${percentToStatus(mem)}`;

        document.getElementById('cpuBar').style.width = `${Math.min(100, cpu)}%`;
        document.getElementById('memBar').style.width = `${Math.min(100, mem)}%`;

        document.getElementById('baseMean').textContent = num(baseMean, 4);
        document.getElementById('baseStd').textContent = num(baseStd, 4);
        document.getElementById('baseSource').textContent = d.baseline_source || 'floor';
        document.getElementById('baseCurrent').textContent = num(globalRps, 3);

        const bannedCard = document.getElementById('bannedCard');
        bannedCard.style.borderColor = bans.length ? 'rgba(239, 68, 68, 0.65)' : 'rgba(255,255,255,0.08)';
        bannedCard.style.boxShadow = bans.length ? '0 0 24px rgba(239, 68, 68, 0.2)' : '0 10px 28px rgba(0,0,0,0.25)';

        renderTopIps(d.top_ips || []);
        renderBans(bans);
        drawSparkline(rpsHistory, 'rpsLine', 30);
        drawSparkline(baselineHistory, 'baselineLine', 40);

        document.getElementById('updatedAt').textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
      }

      render().catch(() => {
        document.getElementById('updatedAt').textContent = 'Last updated: fetch failed';
      });
      setInterval(render, 3000);
    </script>
  </body>
</html>
"""

    return app


def start_dashboard(state: RuntimeState, host: str = "0.0.0.0", port: int = 5000) -> threading.Thread:
    app = create_dashboard_app(state)

    def run_server() -> None:
        app.run(host=host, port=port, debug=False, use_reloader=False)

    thread = threading.Thread(target=run_server, daemon=True, name="dashboard-server")
    thread.start()
    time.sleep(0.2)
    return thread