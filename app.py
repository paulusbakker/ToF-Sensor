import csv
import io
import json
import logging
import queue
import threading
import time
import traceback

import requests
from flask import Flask, Response, jsonify, render_template, request

import analyzer
import config
import db
import oven

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)


@app.errorhandler(Exception)
def _handle_uncaught(e):
    from werkzeug.exceptions import HTTPException
    if request.path.startswith("/api/"):
        if isinstance(e, HTTPException):
            return jsonify({"ok": False, "error": e.description}), e.code
        log.exception(f"[api] onverwachte fout op {request.path}")
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
    if isinstance(e, HTTPException):
        return e
    raise e

_lock = threading.Lock()
_active_session = None
_oven_timer = None
_oven_on = False
_auto_oven_enabled = config.AUTO_OVEN_ENABLED
_sse_clients = []
_latest_distance_mm = None
_latest_distance_ts = 0.0
_sensor_enabled = True
_signal_fired = False
_last_signal_reminder_ts = 0.0
_sensor_offline = False
_last_successful_measurement_ts = 0.0


def _enrich_measurements(measurements: list) -> list:
    smoothed = analyzer.smooth_rise_series(measurements)
    return [{**m, "rise_mm_smoothed": round(smoothed[i], 2)}
            for i, m in enumerate(measurements)]


def _broadcast(payload: dict):
    msg = f"data: {json.dumps(payload)}\n\n"
    with _lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)


def _send_notification(title: str, message: str, tags: str = "bread",
                       priority: str = "default"):
    """Stuur ntfy-notificatie. `priority` is een ntfy-prio: min, low,
    default, high, urgent. Urgent breekt door DND op de meeste clients heen.
    """
    if not config.NTFY_ENABLED:
        return
    try:
        requests.post(
            f"{config.NTFY_URL}/{config.NTFY_TOPIC}",
            json={"title": title, "message": message, "tags": [tags],
                  "priority": priority},
            timeout=5,
        )
    except Exception as e:
        log.warning(f"[ntfy] Fout: {e}")


def _sensor_loop():
    global _oven_timer, _oven_on, _latest_distance_mm, _latest_distance_ts, _sensor_enabled, _signal_fired, _last_signal_reminder_ts, _sensor_offline, _last_successful_measurement_ts
    print("[sensor_loop] thread gestart", flush=True)
    try:
        from sensor import VL53L1X
        sensor = VL53L1X()
        while True:
            try:
                sensor.connect()
                while True:
                    if not _sensor_enabled:
                        time.sleep(5)
                        continue
                    dist = sensor.read_distance_mm()
                    print(f"[debug] dist={dist}", flush=True)
                    if dist < 0:
                        time.sleep(config.MEASURE_INTERVAL)
                        continue
                    now = time.time()
                    with _lock:
                        _latest_distance_mm = dist
                        _latest_distance_ts = now
                        _last_successful_measurement_ts = now
                        session = _active_session
                    if _sensor_offline:
                        _sensor_offline = False
                        _broadcast({"type": "sensor_online", "ts": now})
                        _send_notification("✅ Sensor weer online",
                                           "Metingen worden weer ontvangen", "white_check_mark")
                    if session is None:
                        time.sleep(5)
                        continue
                    baseline = session["baseline_mm"]
                    rise_mm  = analyzer.compute_rise(dist, baseline)
                    recent   = db.get_last_n(session["id"], n=60)
                    dummy    = recent + [{"ts": time.time(), "rise_mm": rise_mm,
                                          "distance_mm": dist, "speed_mm_h": 0}]
                    speed = analyzer.compute_speed(dummy)[-1]
                    db.log_measurement(session["id"], dist, rise_mm, speed)
                    all_m   = db.get_measurements(session["id"])
                    summary = analyzer.summarize(all_m)
                    _broadcast({"type": "measurement", "oven_on": _oven_on, **summary})
                    log.info(f"dist={dist}mm  rijs={rise_mm:.1f}mm  speed={speed:.2f}mm/u")
                    signal = analyzer.check_baking_moment(all_m)
                    if signal.triggered and not _signal_fired and _oven_timer is None and not _oven_on:
                        _signal_fired = True
                        _broadcast({"type": "oven_scheduled", "minutes": config.OVEN_PREHEAT_MIN,
                                    "reason": signal.reason, "ts": time.time()})
                        if _auto_oven_enabled:
                            _send_notification(
                                "🔥 Oven gepland!",
                                f"Oven gaat over {config.OVEN_PREHEAT_MIN} min automatisch aan\nRijs: {rise_mm:.1f}mm",
                                "fire",
                                priority="urgent",
                            )
                            delay_s = config.OVEN_PREHEAT_MIN * 60
                            _oven_timer = threading.Timer(delay_s, _trigger_oven, args=[session["id"]])
                            _oven_timer.start()
                        else:
                            _send_notification(
                                "🔥 Bakmoment bereikt!",
                                f"Zet de oven handmatig aan\nRijs: {rise_mm:.1f}mm",
                                "fire",
                                priority="urgent",
                            )
                        _last_signal_reminder_ts = time.time()
                    time.sleep(config.MEASURE_INTERVAL)
            except Exception as e:
                log.error(f"[sensor] {e} — herverbinden in 10s")
                traceback.print_exc()
                try:
                    sensor.close()
                except Exception:
                    pass
                time.sleep(10)
    except Exception:
        print("[sensor_loop] fatale fout, thread stopt:", flush=True)
        traceback.print_exc()


def _sensor_watchdog():
    global _sensor_offline
    while True:
        time.sleep(30)
        try:
            with _lock:
                session = _active_session
                last_ts = _last_successful_measurement_ts
            if session is None or last_ts == 0:
                continue
            gap = time.time() - last_ts
            if gap > 120 and not _sensor_offline:
                _sensor_offline = True
                last_str = time.strftime("%H:%M", time.localtime(last_ts))
                _broadcast({"type": "sensor_offline", "since": last_ts})
                _send_notification("⚠️ Sensor offline",
                                   f"Geen metingen sinds {last_str}", "warning")
        except Exception as e:
            log.warning(f"[watchdog] {e}")


def _signal_reminder_loop():
    """Stuurt periodieke urgent NTFY herinneringen zolang het bakmoment-
    signaal actief is, de oven nog uit staat en er een sessie loopt.
    Stopt automatisch zodra de oven aan gaat of de sessie eindigt.
    """
    global _last_signal_reminder_ts
    while True:
        time.sleep(60)
        try:
            with _lock:
                session = _active_session
            if not (_signal_fired and session and not _oven_on):
                continue
            interval_s = max(60, config.SIGNAL_REMINDER_MIN * 60)
            if time.time() - _last_signal_reminder_ts < interval_s:
                continue
            _last_signal_reminder_ts = time.time()
            _send_notification(
                "🔥 Bakmoment — herinnering",
                "Het deeg staat nog te wachten. Zet de oven aan zodra je kunt.",
                "fire",
                priority="urgent",
            )
        except Exception as e:
            log.warning(f"[signal-reminder] {e}")


def _trigger_oven(session_id):
    global _oven_on
    success = oven.turn_on()
    if success:
        _oven_on = True
        db.mark_oven_triggered(session_id)
        _send_notification("✅ Oven staat AAN", "Deeg kan zo de oven in!", "white_check_mark")
    else:
        _send_notification("⚠️ Oven fout", "Kon oven niet aanzetten", "warning")
    _broadcast({"type": "oven_on", "success": success, "oven_on": _oven_on, "ts": time.time()})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/history")
def history():
    return render_template("history.html")


@app.route("/stream")
def stream():
    client_q = queue.Queue(maxsize=50)
    with _lock:
        _sse_clients.append(client_q)

    def generate():
        with _lock:
            session = _active_session
        if session:
            history = _enrich_measurements(db.get_measurements(session["id"]))
            summary = analyzer.summarize(history)
            yield f"data: {json.dumps({'type': 'history', 'points': history, 'oven_on': _oven_on, 'oven_at': session.get('oven_at'), **summary})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'no_session'})}\n\n"
        try:
            while True:
                try:
                    yield client_q.get(timeout=25)
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            with _lock:
                try:
                    _sse_clients.remove(client_q)
                except ValueError:
                    pass

    return Response(generate(), content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/start", methods=["POST"])
def api_start():
    global _active_session, _oven_timer, _oven_on, _sensor_enabled, _signal_fired, _last_signal_reminder_ts, _latest_distance_mm, _latest_distance_ts, _sensor_offline, _last_successful_measurement_ts
    body = request.json or {}
    notes        = body.get("notes", "")
    flour_type   = body.get("flour_type") or None
    hydration    = body.get("hydration_pct")
    hydration    = int(hydration) if hydration is not None else None

    # Sluit ALLE open sessies af (ook sessies van voor een reboot)
    for sess in db.list_unclosed_sessions():
        db.end_session(sess["id"])

    with _lock:
        _latest_distance_mm = None
        _latest_distance_ts = 0.0
    _sensor_enabled = True

    request_ts = time.time()
    deadline = request_ts + 60
    dist = None
    while time.time() < deadline:
        with _lock:
            d = _latest_distance_mm
            ts = _latest_distance_ts
        if d is not None and d > 0 and ts > request_ts:
            dist = d
            break
        time.sleep(1)
    if dist is None:
        return jsonify({"ok": False, "error": "Geen sensordata beschikbaar (timeout)"}), 500

    session_id = db.start_session(float(dist), notes, flour_type, hydration)
    with _lock:
        _active_session = db.get_active_session()
        if _oven_timer:
            _oven_timer.cancel()
        _oven_timer = None
        _oven_on = False
        _signal_fired = False
        _last_signal_reminder_ts = 0.0
        _sensor_offline = False
        _last_successful_measurement_ts = 0.0
    return jsonify({"ok": True, "session_id": session_id, "baseline_mm": dist})


@app.route("/api/status")
def api_status():
    with _lock:
        session = _active_session
    if not session:
        return jsonify({"session": None})
    measurements = db.get_measurements(session["id"])
    summary = analyzer.summarize(measurements)
    return jsonify({"session": session, "oven_on": _oven_on, **summary})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    global _auto_oven_enabled
    if request.method == "GET":
        return jsonify({"auto_oven": _auto_oven_enabled,
                        "preheat_min": config.OVEN_PREHEAT_MIN,
                        "peak_speed_ratio": config.PEAK_SPEED_RATIO,
                        "smooth_window_min": config.SMOOTH_WINDOW_MIN})
    body = request.json or {}
    with _lock:
        if "auto_oven" in body:
            _auto_oven_enabled = bool(body["auto_oven"])
        if "preheat_min" in body:
            config.OVEN_PREHEAT_MIN = max(1, int(body["preheat_min"]))
    _broadcast({"type": "settings", "auto_oven": _auto_oven_enabled,
                "preheat_min": config.OVEN_PREHEAT_MIN,
                "peak_speed_ratio": config.PEAK_SPEED_RATIO,
                "smooth_window_min": config.SMOOTH_WINDOW_MIN})
    return jsonify({"ok": True, "auto_oven": _auto_oven_enabled,
                    "preheat_min": config.OVEN_PREHEAT_MIN,
                    "peak_speed_ratio": config.PEAK_SPEED_RATIO,
                    "smooth_window_min": config.SMOOTH_WINDOW_MIN})


@app.route("/api/oven", methods=["POST"])
def api_oven():
    global _oven_on
    action = (request.json or {}).get("action", "on")
    ok = oven.turn_on() if action == "on" else oven.turn_off()
    if ok:
        _oven_on = action == "on"
        ts = time.time()
        if action == "on":
            with _lock:
                session = _active_session
            if session:
                db.mark_oven_triggered(session["id"])
        _broadcast({"type": "oven_state", "oven_on": _oven_on, "ts": ts})
    return jsonify({"ok": ok})


@app.route("/api/history")
def api_history():
    with _lock:
        session = _active_session
    if not session:
        return jsonify([])
    return jsonify(_enrich_measurements(db.get_measurements(session["id"])))


# ── Sessie-geschiedenis API ────────────────────────────────

@app.route("/api/sessions")
def api_sessions():
    return jsonify(db.list_sessions())


@app.route("/api/sessions/<int:session_id>")
def api_session_detail(session_id):
    sessions = db.list_sessions()
    sess = next((s for s in sessions if s["id"] == session_id), None)
    if not sess:
        return jsonify({"error": "Niet gevonden"}), 404
    measurements = _enrich_measurements(db.get_measurements(session_id))
    return jsonify({"session": sess, "measurements": measurements})


@app.route("/api/sessions/<int:session_id>/verdict", methods=["POST"])
def api_session_verdict(session_id):
    body    = request.json or {}
    verdict = body.get("verdict", "")
    notes   = body.get("notes", "")
    if verdict not in ("early", "good", "late"):
        return jsonify({"ok": False, "error": "Ongeldig oordeel"}), 400
    db.set_session_verdict(session_id, verdict, notes)
    return jsonify({"ok": True})


@app.route("/api/sessions/<int:session_id>/export")
def api_session_export(session_id):
    measurements = db.get_measurements(session_id)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["ts", "distance_mm", "rise_mm", "speed_mm_h"],
                       extrasaction="ignore")
    w.writeheader()
    w.writerows(measurements)
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sessie_{session_id}.csv"},
    )


@app.route("/api/stop", methods=["POST"])
def api_stop():
    global _active_session, _oven_timer, _oven_on, _sensor_enabled, _latest_distance_mm, _latest_distance_ts, _signal_fired, _last_signal_reminder_ts, _sensor_offline, _last_successful_measurement_ts
    unclosed = db.list_unclosed_sessions()
    for sess in unclosed:
        db.end_session(sess["id"])
    with _lock:
        _active_session = None
        _latest_distance_mm = None
        _latest_distance_ts = 0.0
        _sensor_enabled = False
        if _oven_timer:
            _oven_timer.cancel()
        _oven_timer = None
        _oven_on = False
        _signal_fired = False
        _last_signal_reminder_ts = 0.0
        _sensor_offline = False
        _last_successful_measurement_ts = 0.0
    _broadcast({"type": "no_session"})
    return jsonify({"ok": True, "closed": len(unclosed)})


@app.route("/api/admin/cleanup", methods=["POST"])
def api_admin_cleanup():
    if (request.json or {}).get("confirm") != "cleanup":
        return jsonify({"ok": False, "error": "Stuur {confirm: 'cleanup'}"}), 400
    closed, deleted = db.cleanup_all_unclosed()
    return jsonify({"ok": True, "closed": closed, "deleted": deleted})


if __name__ == "__main__":
    db.init_db()

    # Hervat de meest recente open sessie na reboot; sluit eventuele
    # oudere openstaande sessies af (zou niet mogen, veiligheidsnet).
    unclosed = db.list_unclosed_sessions()
    if unclosed:
        resume = unclosed[0]  # ORDER BY id DESC
        for sess in unclosed[1:]:
            db.end_session(sess["id"])
        if len(unclosed) > 1:
            log.warning(f"[main] {len(unclosed) - 1} extra open sessie(s) afgesloten")
        _active_session = resume
        if resume.get("oven_triggered"):
            _signal_fired = True
        if config.TUYA_ENABLED:
            try:
                _oven_on = bool(oven.get_status().get("on"))
            except Exception:
                _oven_on = False
        log.info(f"[main] Sessie {resume['id']} hervat (signal_fired={_signal_fired}, oven_on={_oven_on})")

    threading.Thread(target=_sensor_loop, daemon=True).start()
    threading.Thread(target=_sensor_watchdog, daemon=True).start()
    threading.Thread(target=_signal_reminder_loop, daemon=True).start()
    print("[main] sensor thread aangemaakt", flush=True)
    log.info(f"Dashboard: http://0.0.0.0:{config.FLASK_PORT}")
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, threaded=True, debug=False)
