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

_lock = threading.Lock()
_active_session = None
_oven_timer = None
_oven_on = False
_auto_oven_enabled = config.AUTO_OVEN_ENABLED
_sse_clients = []
_latest_distance_mm = None
_sensor_enabled = True


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


def _send_notification(title: str, message: str, tags: str = "bread"):
    if not config.NTFY_ENABLED:
        return
    try:
        headers = {}
        if config.NTFY_TOKEN:
            headers["Authorization"] = f"Bearer {config.NTFY_TOKEN}"
        requests.post(
            f"{config.NTFY_URL}/{config.NTFY_TOPIC}",
            json={"title": title, "message": message, "tags": [tags]},
            headers=headers,
            timeout=5,
        )
    except Exception as e:
        log.warning(f"[ntfy] Fout: {e}")


def _sensor_loop():
    global _oven_timer, _oven_on, _latest_distance_mm, _sensor_enabled
    print("[sensor_loop] thread gestart", flush=True)
    try:
        from sensor import VL53L1X
        sensor = VL53L1X()
        while True:
            try:
                sensor.connect()
                AMBIENT_THRESHOLD = 10
                JUMP_RESET_THRESHOLD = 10
                prev_dist = None
                reject_streak = 0
                jump_streak = 0
                fridge_open = False
                no_data_streak = 0
                while True:
                    if not _sensor_enabled:
                        time.sleep(5)
                        continue
                    dist, ambient = sensor.read_distance_mm()
                    print(f"[debug] dist={dist} ambient={ambient}", flush=True)
                    if dist == -1:
                        no_data_streak += 1
                        if no_data_streak >= 5:
                            raise RuntimeError(f"Sensor {no_data_streak}x geen data — herverbinden")
                        time.sleep(config.MEASURE_INTERVAL)
                        continue
                    no_data_streak = 0
                    if dist == -2:
                        log.warning("[sensor] hoge spreiding")
                        reject_streak += 1
                        if reject_streak >= 4 and not fridge_open:
                            log.info("[sensor] koelkast open gedetecteerd")
                            fridge_open = True
                        time.sleep(config.MEASURE_INTERVAL)
                        continue
                    if ambient > AMBIENT_THRESHOLD:
                        log.info(f"[sensor] koelkast open (ambient): ambient={ambient}")
                        _broadcast({"type": "fridge_open", "ambient": ambient})
                        reject_streak += 1
                        jump_streak = 0
                        if reject_streak >= 4 and not fridge_open:
                            fridge_open = True
                        time.sleep(config.MEASURE_INTERVAL)
                        continue
                    if prev_dist is not None and abs(dist - prev_dist) > 80:
                        jump_streak += 1
                        reject_streak += 1
                        log.info(f"[sensor] koelkast open (jump): dist={dist}, prev={prev_dist}, jump_streak={jump_streak}")
                        if reject_streak >= 4 and not fridge_open:
                            fridge_open = True
                        if jump_streak >= JUMP_RESET_THRESHOLD:
                            log.warning(f"[sensor] {jump_streak}x jump rejected — force-reset prev_dist {prev_dist}→{dist}")
                            prev_dist = dist
                            jump_streak = 0
                            reject_streak = 0
                            if fridge_open:
                                _broadcast({"type": "fridge_closed"})
                                fridge_open = False
                        time.sleep(config.MEASURE_INTERVAL)
                        continue
                    if fridge_open:
                        log.info("[sensor] koelkast dicht")
                        _broadcast({"type": "fridge_closed"})
                        time.sleep(60)
                        fridge_open = False
                    reject_streak = 0
                    jump_streak = 0
                    prev_dist = dist
                    with _lock:
                        _latest_distance_mm = dist
                        session = _active_session
                    if session is None:
                        time.sleep(5)
                        continue
                    baseline = session["baseline_mm"]
                    rise_mm  = analyzer.compute_rise(dist, baseline)
                    rise_pct = analyzer.compute_rise_pct(rise_mm, baseline)
                    recent   = db.get_last_n(session["id"], n=20)
                    dummy    = recent + [{"ts": time.time(), "rise_mm": rise_mm,
                                          "rise_pct": rise_pct, "distance_mm": dist,
                                          "speed_mm_h": 0}]
                    speed = analyzer.compute_speed(dummy)[-1]
                    db.log_measurement(session["id"], dist, rise_mm, rise_pct, speed)
                    all_m   = db.get_measurements(session["id"])
                    summary = analyzer.summarize(all_m)
                    _broadcast({"type": "measurement", "ambient": ambient, "oven_on": _oven_on, **summary})
                    log.info(f"dist={dist}mm  rijs={rise_mm:.1f}mm  speed={speed:.2f}mm/u")
                    signal = analyzer.check_baking_moment(all_m)
                    if signal.triggered and _oven_timer is None and not _oven_on:
                        _broadcast({"type": "oven_scheduled", "minutes": config.OVEN_PREHEAT_MIN,
                                    "reason": signal.reason})
                        if _auto_oven_enabled:
                            _send_notification(
                                "🔥 Oven gepland!",
                                f"Oven gaat over {config.OVEN_PREHEAT_MIN} min automatisch aan\nRijs: {rise_mm:.1f}mm",
                                "fire",
                            )
                            delay_s = config.OVEN_PREHEAT_MIN * 60
                            _oven_timer = threading.Timer(delay_s, _trigger_oven, args=[session["id"]])
                            _oven_timer.start()
                        else:
                            _send_notification(
                                "🔥 Bakmoment bereikt!",
                                f"Zet de oven handmatig aan\nRijs: {rise_mm:.1f}mm",
                                "fire",
                            )
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


def _trigger_oven(session_id):
    global _oven_on
    success = oven.turn_on()
    if success:
        _oven_on = True
        db.mark_oven_triggered(session_id)
        _send_notification("✅ Oven staat AAN", "Deeg kan zo de oven in!", "white_check_mark")
    else:
        _send_notification("⚠️ Oven fout", "Kon oven niet aanzetten", "warning")
    _broadcast({"type": "oven_on", "success": success, "oven_on": _oven_on})


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
            history = db.get_measurements(session["id"])
            summary = analyzer.summarize(history)
            yield f"data: {json.dumps({'type': 'history', 'points': history, 'oven_on': _oven_on, **summary})}\n\n"
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
    global _active_session, _oven_timer, _oven_on, _sensor_enabled
    body = request.json or {}
    notes        = body.get("notes", "")
    flour_type   = body.get("flour_type") or None
    hydration    = body.get("hydration_pct")
    hydration    = int(hydration) if hydration is not None else None

    # Sluit ALLE open sessies af (ook sessies van voor een reboot)
    for sess in db.list_unclosed_sessions():
        db.end_session(sess["id"])

    _sensor_enabled = True

    deadline = time.time() + 60
    while time.time() < deadline:
        with _lock:
            dist = _latest_distance_mm
        if dist is not None and dist > 0:
            break
        time.sleep(1)
    else:
        return jsonify({"ok": False, "error": "Geen sensordata beschikbaar (timeout)"}), 500

    session_id = db.start_session(float(dist), notes, flour_type, hydration)
    with _lock:
        _active_session = db.get_active_session()
        if _oven_timer:
            _oven_timer.cancel()
        _oven_timer = None
        _oven_on = False
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
                        "preheat_min": config.OVEN_PREHEAT_MIN})
    body = request.json or {}
    with _lock:
        if "auto_oven" in body:
            _auto_oven_enabled = bool(body["auto_oven"])
        if "preheat_min" in body:
            config.OVEN_PREHEAT_MIN = max(1, int(body["preheat_min"]))
    _broadcast({"type": "settings", "auto_oven": _auto_oven_enabled,
                "preheat_min": config.OVEN_PREHEAT_MIN})
    return jsonify({"ok": True, "auto_oven": _auto_oven_enabled,
                    "preheat_min": config.OVEN_PREHEAT_MIN})


@app.route("/api/oven", methods=["POST"])
def api_oven():
    global _oven_on
    action = (request.json or {}).get("action", "on")
    ok = oven.turn_on() if action == "on" else oven.turn_off()
    if ok:
        _oven_on = action == "on"
        _broadcast({"type": "oven_state", "oven_on": _oven_on})
    return jsonify({"ok": ok})


@app.route("/api/history")
def api_history():
    with _lock:
        session = _active_session
    if not session:
        return jsonify([])
    return jsonify(db.get_measurements(session["id"]))


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
    measurements = db.get_measurements(session_id)
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
    w = csv.DictWriter(buf, fieldnames=["ts", "distance_mm", "rise_mm", "rise_pct", "speed_mm_h"])
    w.writeheader()
    w.writerows(measurements)
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sessie_{session_id}.csv"},
    )


@app.route("/api/stop", methods=["POST"])
def api_stop():
    global _active_session, _oven_timer, _oven_on, _sensor_enabled, _latest_distance_mm
    unclosed = db.list_unclosed_sessions()
    for sess in unclosed:
        db.end_session(sess["id"])
    with _lock:
        _active_session = None
        _latest_distance_mm = None
        _sensor_enabled = False
        if _oven_timer:
            _oven_timer.cancel()
        _oven_timer = None
        _oven_on = False
    _broadcast({"type": "sensor_paused"})
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

    # Sluit bij opstart alle niet-afgesloten sessies af
    unclosed = db.list_unclosed_sessions()
    for sess in unclosed:
        db.end_session(sess["id"])
    if unclosed:
        log.info(f"[main] {len(unclosed)} open sessie(s) afgesloten bij opstart")

    threading.Thread(target=_sensor_loop, daemon=True).start()
    print("[main] sensor thread aangemaakt", flush=True)
    log.info(f"Dashboard: http://0.0.0.0:{config.FLASK_PORT}")
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, threaded=True, debug=False)
