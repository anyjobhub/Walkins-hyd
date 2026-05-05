"""
routes/scraper_routes.py — Admin-only scraper management endpoints.

All routes require the X-API-Key header matching ADMIN_API_KEY in .env.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, jsonify, request, Response

from config import Config
from services.database_service import ScrapLogRepository

logger = logging.getLogger(__name__)
scraper_bp = Blueprint("scraper", __name__)
log_repo = ScrapLogRepository()

_scraper_status = {
    "running": False,
    "last_run": None,
    "last_source": None,
    "next_run": None,
}


# ─────────────────────────────────────────────────────────────────────────────
# Auth middleware
# ─────────────────────────────────────────────────────────────────────────────
def require_admin_key(f):
    """Decorator: reject requests without a valid X-API-Key header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get("X-API-Key", "")
        if not Config.flask.ADMIN_API_KEY or api_key != Config.flask.ADMIN_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/scraper/trigger — Manually trigger scraping
# ─────────────────────────────────────────────────────────────────────────────
@scraper_bp.route("/scraper/trigger", methods=["POST"])
@require_admin_key
def trigger_scraper():
    """
    Trigger scraping for one or more sources.

    Body (JSON):
      sources (list) — e.g. ["naukri", "linkedin", "indeed"]
      location (str) — default "India"
    """
    if _scraper_status["running"]:
        return jsonify({
            "status": "already_running",
            "message": "A scrape is already in progress",
        }), 409

    data = request.get_json(silent=True) or {}
    sources = data.get("sources", ["naukri", "linkedin", "indeed"])
    location = data.get("location", "India")

    valid_sources = {"naukri", "linkedin", "indeed"}
    sources = [s for s in sources if s in valid_sources]

    if not sources:
        return jsonify({"error": "No valid sources specified"}), 400

    # Run scraping in background thread so request returns immediately
    def run_scrape():
        from tasks.scraper_tasks import run_scraper_pipeline
        _scraper_status["running"] = True
        _scraper_status["last_run"] = datetime.now(timezone.utc).isoformat()
        try:
            result = run_scraper_pipeline(sources=sources, location=location)
            _scraper_status["last_result"] = result
        finally:
            _scraper_status["running"] = False

    thread = threading.Thread(target=run_scrape, daemon=True)
    thread.start()

    return jsonify({
        "status": "started",
        "sources": sources,
        "location": location,
        "message": "Scraping started in background. Check /api/scraper/status for updates.",
    }), 202


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/scraper/status — Current scraper status
# ─────────────────────────────────────────────────────────────────────────────
@scraper_bp.route("/scraper/status", methods=["GET"])
@require_admin_key
def scraper_status():
    """Return the current scraper status."""
    return jsonify(_scraper_status), 200


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/scraper/logs — Recent scrape logs
# ─────────────────────────────────────────────────────────────────────────────
@scraper_bp.route("/scraper/logs", methods=["GET"])
@require_admin_key
def scraper_logs():
    """Get recent scraping audit logs."""
    try:
        limit = min(100, max(1, int(request.args.get("limit", 20))))
        logs = log_repo.get_recent_logs(limit=limit)
        return jsonify({"logs": logs, "total": len(logs)}), 200
    except Exception as e:
        logger.error("Error fetching scraper logs: %s", e)
        return jsonify({"error": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/scraper/post-to-telegram — Trigger Telegram posting
# ─────────────────────────────────────────────────────────────────────────────
@scraper_bp.route("/scraper/post-to-telegram", methods=["POST"])
@require_admin_key
def post_to_telegram():
    """Manually trigger posting of unposted jobs to Telegram."""
    try:
        from tasks.scraper_tasks import post_unposted_jobs
        result = post_unposted_jobs()
        return jsonify(result), 200
    except Exception as e:
        logger.error("Error posting to Telegram: %s", e)
        return jsonify({"error": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/admin/dashboard — Unified admin dashboard data
# ─────────────────────────────────────────────────────────────────────────────
@scraper_bp.route("/admin/dashboard", methods=["GET"])
@require_admin_key
def admin_dashboard():
    """Return all stats for the admin dashboard."""
    try:
        from services.database_service import JobRepository, TelegramUserRepository
        from utils.monitoring_service import MonitoringService

        stats = JobRepository().get_stats()
        stats["subscriber_count"] = TelegramUserRepository().get_subscriber_count()
        stats["scraper_status"] = _scraper_status
        stats["recent_logs"] = log_repo.get_recent_logs(limit=5)
        stats["health"] = MonitoringService().get_health_status()

        return jsonify(stats), 200
    except Exception as e:
        logger.error("Error fetching dashboard: %s", e)
        return jsonify({{"error": "Internal server error"}}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /scrape-now  (legacy — kept for backwards compat, redirects to /scrape)
# ─────────────────────────────────────────────────────────────────────────────
@scraper_bp.route("/scrape-now", methods=["GET"])
def scrape_now():
    key = request.args.get("key", "")
    from flask import redirect
    return redirect(f"/api/scrape?key={key}")


# ─────────────────────────────────────────────────────────────────────────────
# GET  /scrape?key=   — Scrape Control Dashboard
# GET  /scrape/start?key= — Start scrape (AJAX)
# GET  /scrape/stop?key=  — Stop scrape  (AJAX)
# GET  /scrape/status?key= — Poll status + recent jobs (AJAX)
# ─────────────────────────────────────────────────────────────────────────────

# Shared state (process-level)
_scrape_state = {
    "running":    False,
    "started_at": None,
    "jobs_added": 0,
    "jobs_found": 0,
    "log":        [],      # list of log strings shown live
    "stop_flag":  False,
}
_scrape_lock = threading.Lock()


def _auth(key: str) -> bool:
    return bool(Config.flask.ADMIN_API_KEY) and key == Config.flask.ADMIN_API_KEY


@scraper_bp.route("/scrape", methods=["GET"])
def scrape_dashboard():
    """Serves the Scrape Control Panel HTML page."""
    key = request.args.get("key", "")
    if not _auth(key):
        return Response(
            "<html><body style='font:sans-serif;text-align:center;padding:4rem;"
            "background:#0f172a;color:#fff'><h1 style='color:#ef4444'>❌ Unauthorized</h1>"
            "<p>Add ?key=YOUR_ADMIN_KEY to the URL.</p></body></html>",
            status=401, mimetype="text/html"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scrape Control Panel</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Inter',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;padding:2rem 1rem}}
  .container{{max-width:900px;margin:0 auto}}
  h1{{font-size:1.75rem;font-weight:700;color:#f8fafc;margin-bottom:.25rem}}
  .subtitle{{color:#64748b;font-size:.9rem;margin-bottom:2rem}}
  .card{{background:#1e293b;border:1px solid #334155;border-radius:16px;padding:1.5rem;margin-bottom:1.5rem}}
  .controls{{display:flex;gap:1rem;align-items:center;flex-wrap:wrap}}
  .btn{{padding:.75rem 2rem;border:none;border-radius:10px;font-size:1rem;font-weight:600;cursor:pointer;transition:all .2s;font-family:inherit}}
  .btn-start{{background:linear-gradient(135deg,#22c55e,#16a34a);color:#fff}}
  .btn-start:hover{{transform:translateY(-1px);box-shadow:0 4px 20px rgba(34,197,94,.4)}}
  .btn-start:disabled{{background:#334155;color:#64748b;cursor:not-allowed;transform:none;box-shadow:none}}
  .btn-stop{{background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff}}
  .btn-stop:hover{{transform:translateY(-1px);box-shadow:0 4px 20px rgba(239,68,68,.4)}}
  .btn-stop:disabled{{background:#334155;color:#64748b;cursor:not-allowed;transform:none;box-shadow:none}}
  .status-pill{{padding:.4rem 1rem;border-radius:99px;font-size:.85rem;font-weight:600}}
  .pill-idle{{background:#1e293b;border:1px solid #475569;color:#94a3b8}}
  .pill-running{{background:#064e3b;border:1px solid #10b981;color:#6ee7b7;animation:pulse 2s infinite}}
  @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.7}}}}
  .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem;margin-top:1rem}}
  .stat{{background:#0f172a;border-radius:12px;padding:1rem;text-align:center}}
  .stat-num{{font-size:2rem;font-weight:700;color:#38bdf8}}
  .stat-label{{font-size:.75rem;color:#64748b;margin-top:.25rem;text-transform:uppercase;letter-spacing:.05em}}
  .log-box{{background:#0f172a;border-radius:10px;padding:1rem;height:160px;overflow-y:auto;font-family:'Courier New',monospace;font-size:.8rem;color:#94a3b8;border:1px solid #1e293b}}
  .log-line{{padding:.15rem 0;border-bottom:1px solid #1e293b20}}
  .log-line.info{{color:#7dd3fc}}
  .log-line.ok{{color:#86efac}}
  .log-line.err{{color:#fca5a5}}
  .jobs-grid{{display:grid;gap:1rem;margin-top:1rem}}
  .job-card{{background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:1.25rem;transition:border-color .2s}}
  .job-card:hover{{border-color:#38bdf8}}
  .job-title{{font-size:1rem;font-weight:600;color:#f1f5f9;margin-bottom:.4rem}}
  .job-company{{color:#7dd3fc;font-size:.875rem;margin-bottom:.25rem}}
  .job-meta{{display:flex;gap:.75rem;flex-wrap:wrap;margin-top:.5rem}}
  .tag{{background:#1e293b;border-radius:6px;padding:.2rem .6rem;font-size:.75rem;color:#94a3b8}}
  .tag.walkin{{background:#052e16;color:#86efac;border:1px solid #166534}}
  .empty{{text-align:center;padding:3rem;color:#475569}}
  .empty-icon{{font-size:3rem;margin-bottom:1rem}}
  #jobs-count{{color:#38bdf8;font-weight:700}}
</style>
</head>
<body>
<div class="container">
  <h1>🔍 Scrape Control Panel</h1>
  <p class="subtitle">Walk-in Jobs Aggregator — Manual Scrape Override</p>

  <!-- Controls -->
  <div class="card">
    <div class="controls">
      <button class="btn btn-start" id="btn-start" onclick="startScrape()">▶ Start Scrape</button>
      <button class="btn btn-stop"  id="btn-stop"  onclick="stopScrape()" disabled>⬛ Stop</button>
      <span class="status-pill pill-idle" id="status-pill">Idle</span>
      <span style="color:#64748b;font-size:.85rem" id="started-at"></span>
    </div>
    <div class="stats">
      <div class="stat"><div class="stat-num" id="stat-found">0</div><div class="stat-label">Jobs Found</div></div>
      <div class="stat"><div class="stat-num" id="stat-added">0</div><div class="stat-label">Jobs Added</div></div>
      <div class="stat"><div class="stat-num" id="stat-jobs">0</div><div class="stat-label">Total in DB</div></div>
    </div>
  </div>

  <!-- Live log -->
  <div class="card">
    <div style="font-weight:600;margin-bottom:.75rem;color:#94a3b8;font-size:.85rem;text-transform:uppercase;letter-spacing:.05em">📋 Live Log</div>
    <div class="log-box" id="log-box"><div class="log-line">Ready. Click Start Scrape to begin.</div></div>
  </div>

  <!-- Jobs -->
  <div class="card">
    <div style="font-weight:600;margin-bottom:.75rem;color:#94a3b8;font-size:.85rem;text-transform:uppercase;letter-spacing:.05em">
      💼 Extracted Jobs &nbsp;<span id="jobs-count">0</span>
    </div>
    <div id="jobs-container">
      <div class="empty"><div class="empty-icon">🕵️</div><p>No jobs yet. Start a scrape to see results here.</p></div>
    </div>
  </div>
</div>

<script>
const KEY = '{key}';
const API = '/api/scrape';
let pollTimer = null;

async function api(path, method='GET') {{
  const r = await fetch(`${{API}}${{path}}?key=${{KEY}}`, {{method}});
  return r.json();
}}

async function startScrape() {{
  document.getElementById('btn-start').disabled = true;
  document.getElementById('btn-stop').disabled  = false;
  appendLog('info', '▶ Starting scrape — Naukri + LinkedIn + Indeed...');
  await api('/start');
  startPolling();
}}

async function stopScrape() {{
  appendLog('err', '⬛ Stop requested...');
  await api('/stop');
}}

function startPolling() {{
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(poll, 3000);
  poll();
}}

async function poll() {{
  try {{
    const d = await api('/status');
    updateUI(d);
  }} catch(e) {{ appendLog('err', 'Poll error: ' + e); }}
}}

function updateUI(d) {{
  const running = d.running;

  // Status pill
  const pill = document.getElementById('status-pill');
  pill.textContent = running ? '⚡ Running...' : (d.jobs_found > 0 ? '✅ Complete' : 'Idle');
  pill.className = 'status-pill ' + (running ? 'pill-running' : 'pill-idle');

  // Buttons
  document.getElementById('btn-start').disabled = running;
  document.getElementById('btn-stop').disabled  = !running;

  // Started at
  if (d.started_at) {{
    document.getElementById('started-at').textContent = 'Started: ' + new Date(d.started_at).toLocaleTimeString();
  }}

  // Stats
  document.getElementById('stat-found').textContent = d.jobs_found  || 0;
  document.getElementById('stat-added').textContent = d.jobs_added  || 0;
  document.getElementById('stat-jobs').textContent  = d.total_in_db || 0;

  // Log lines
  if (d.log && d.log.length) {{
    const box = document.getElementById('log-box');
    box.innerHTML = '';
    d.log.slice(-30).forEach(line => {{
      const cls = line.startsWith('✅') || line.startsWith('▶') ? 'ok' : line.startsWith('❌') ? 'err' : 'info';
      box.innerHTML += `<div class="log-line ${{cls}}">${{line}}</div>`;
    }});
    box.scrollTop = box.scrollHeight;
  }}

  // Jobs
  if (d.jobs && d.jobs.length) {{
    renderJobs(d.jobs);
  }}

  // Stop polling when done
  if (!running && pollTimer) {{
    clearInterval(pollTimer);
    pollTimer = null;
    if (d.jobs_found > 0) appendLog('ok', `✅ Done! ${{d.jobs_added}} new jobs added to database.`);
  }}
}}

function renderJobs(jobs) {{
  document.getElementById('jobs-count').textContent = jobs.length;
  const c = document.getElementById('jobs-container');
  c.innerHTML = jobs.map(j => `
    <div class="job-card">
      <div class="job-title">${{j.title || '—'}}</div>
      <div class="job-company">🏢 ${{j.company || '—'}}</div>
      <div class="job-meta">
        <span class="tag">📍 ${{j.location || '—'}}</span>
        <span class="tag">💰 ${{j.salary || '—'}}</span>
        <span class="tag">📊 ${{j.experience || '—'}}</span>
        ${{j.is_walkin ? '<span class="tag walkin">✅ Walk-In</span>' : ''}}
        <span class="tag" style="color:#64748b;font-size:.7rem">${{j.source || ''}}</span>
      </div>
      ${{j.job_url ? `<a href="${{j.job_url}}" target="_blank" style="display:inline-block;margin-top:.75rem;font-size:.8rem;color:#38bdf8;text-decoration:none">View Job →</a>` : ''}}
    </div>`).join('');
}}

function appendLog(cls, msg) {{
  const box = document.getElementById('log-box');
  box.innerHTML += `<div class="log-line ${{cls}}">${{msg}}</div>`;
  box.scrollTop = box.scrollHeight;
}}

// Auto-start polling to sync state on page load
startPolling();
</script>
</body></html>"""
    return Response(html, status=200, mimetype="text/html")


@scraper_bp.route("/scrape/start", methods=["GET"])
def scrape_start():
    """AJAX: Start scraping in background thread."""
    key = request.args.get("key", "")
    if not _auth(key):
        return jsonify({"error": "Unauthorized"}), 401

    with _scrape_lock:
        if _scrape_state["running"]:
            return jsonify({"status": "already_running"})

        _scrape_state.update({
            "running":    True,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "jobs_added": 0,
            "jobs_found": 0,
            "log":        ["▶ Scrape started — Naukri + LinkedIn + Indeed"],
            "stop_flag":  False,
            "jobs":       [],
        })

    # ✅ Capture app object HERE (inside request context), BEFORE spawning thread
    from flask import current_app
    app = current_app._get_current_object()

    def _log(msg: str):
        _scrape_state["log"].append(msg)
        logger.info(msg)

    def run():
        from tasks.scraper_tasks import _run_scraper_task, run_deduplication
        # Use captured app — not current_app (which has no context in a thread)
        with app.app_context():
            try:
                for source in ["naukri", "linkedin", "indeed"]:
                    if _scrape_state["stop_flag"]:
                        _log(f"⬛ Stopped before {source}")
                        break
                    _log(f"🔍 Scraping {source.capitalize()}...")
                    result = _run_scraper_task(source, "Hyderabad")
                    found = result.get("jobs_found", 0)
                    added = result.get("jobs_added", 0)
                    _scrape_state["jobs_found"] += found
                    _scrape_state["jobs_added"] += added
                    _log(f"✅ {source.capitalize()}: {found} found, {added} new added")

                if not _scrape_state["stop_flag"]:
                    _log("🔄 Running deduplication...")
                    run_deduplication()
                    _log("✅ Deduplication complete")

                # Load recent jobs for display
                from services.database_service import JobRepository
                recent = JobRepository().get_recent_jobs(days=1, limit=50)
                _scrape_state["jobs"] = recent

            except Exception as exc:
                _log(f"❌ Error: {exc}")
                logger.error("Scrape dashboard error: %s", exc, exc_info=True)
            finally:
                _scrape_state["running"] = False
                _log(f"✅ Scrape complete — {_scrape_state['jobs_added']} new jobs")

    thread = threading.Thread(target=run, daemon=True, name="dashboard-scraper")
    thread.start()

    return jsonify({"status": "started"})


@scraper_bp.route("/scrape/stop", methods=["GET"])
def scrape_stop():
    """AJAX: Signal the running scrape to stop after current source."""
    key = request.args.get("key", "")
    if not _auth(key):
        return jsonify({"error": "Unauthorized"}), 401
    _scrape_state["stop_flag"] = True
    _scrape_state["log"].append("⬛ Stop requested — will stop after current source")
    return jsonify({"status": "stop_requested"})


@scraper_bp.route("/scrape/status", methods=["GET"])
def scrape_status():
    """AJAX: Return current scrape state + recent jobs for live dashboard."""
    key = request.args.get("key", "")
    if not _auth(key):
        return jsonify({"error": "Unauthorized"}), 401

    # Total jobs in DB
    total_in_db = 0
    try:
        from services.database_service import JobRepository
        stats = JobRepository().get_stats()
        total_in_db = stats.get("total_jobs", 0)
    except Exception:
        pass

    jobs = _scrape_state.get("jobs", [])
    # Convert ORM objects to dicts if needed
    safe_jobs = []
    for j in jobs[:50]:
        if isinstance(j, dict):
            safe_jobs.append(j)
        else:
            try:
                safe_jobs.append(j.to_dict())
            except Exception:
                pass

    return jsonify({
        "running":    _scrape_state["running"],
        "started_at": _scrape_state.get("started_at"),
        "jobs_found": _scrape_state.get("jobs_found", 0),
        "jobs_added": _scrape_state.get("jobs_added", 0),
        "total_in_db": total_in_db,
        "log":        _scrape_state.get("log", []),
        "jobs":       safe_jobs,
    })




