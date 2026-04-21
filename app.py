import json
import logging
import queue
import threading
import time
import traceback

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
_sse_clients = []
_latest_distance_mm = None


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


def _sensor_loop():
    global _oven_timer, _oven_on, _latest_distance_mm
    print("[sensor_loop] thread gestart", flush=True)
    try:
        from sensor import VL53L1X
        sensor = VL53L1X()
        while True:
            try:
                sensor.connect()
                while True:
                    dist = sensor.read_distance_mm()
                    if dist < 0:
                        time.sleep(config.MEASURE_INTERVAL)
                        continue
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
                    _broadcast({"type": "measurement", **summary})
                    log.info(f"dist={dist}mm  rijs={rise_mm:.1f}mm  speed={speed:.2f}mm/u")
                    signal = analyzer.check_baking_moment(all_m)
                    if signal.triggered and _oven_timer is None and not _oven_on:
                        delay_s = config.OVEN_PREHEAT_MIN * 60
                        _oven_timer = threading.Timer(delay_s, _trigger_oven, args=[session["id"]])
                        _oven_timer.start()
                        _broadcast({"type": "oven_scheduled", "minutes": config.OVEN_PREHEAT_MIN,
                                    "reason": signal.reason})
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
    _broadcast({"type": "oven_on", "success": success})


@app.route("/")
def index():
    return render_template("index.html")


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
            yield f"data: {json.dumps({'type': 'history', 'points': history, **summary})}\n\n"
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
    global _active_session, _oven_timer, _oven_on
    notes = (request.json or {}).get("notes", "")
    deadline = time.time() + 60
    while time.time() < deadline:
        with _lock:
            dist = _latest_distance_mm
        if dist is not None and dist > 0:
            break
        time.sleep(1)
    else:
        return jsonify({"ok": False, "error": "Geen sensordata beschikbaar (timeout)"}), 500
    baseline = dist
    session_id = db.start_session(float(baseline), notes)
    with _lock:
        _active_session = db.get_active_session()
        if _oven_timer:
            _oven_timer.cancel()
        _oven_timer = None
        _oven_on = False
    return jsonify({"ok": True, "session_id": session_id, "baseline_mm": baseline})


@app.route("/api/status")
def api_status():
    with _lock:
        session = _active_session
    if not session:
        return jsonify({"session": None})
    measurements = db.get_measurements(session["id"])
    summary = analyzer.summarize(measurements)
    return jsonify({"session": session, **summary})


@app.route("/api/oven", methods=["POST"])
def api_oven():
    action = (request.json or {}).get("action", "on")
    ok = oven.turn_on() if action == "on" else oven.turn_off()
    return jsonify({"ok": ok})


@app.route("/api/history")
def api_history():
    with _lock:
        session = _active_session
    if not session:
        return jsonify([])
    return jsonify(db.get_measurements(session["id"]))


if __name__ == "__main__":
    db.init_db()
    threading.Thread(target=_sensor_loop, daemon=True).start()
    print("[main] sensor thread aangemaakt", flush=True)
    log.info(f"Dashboard: http://0.0.0.0:{config.FLASK_PORT}")
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, threaded=True, debug=False)
