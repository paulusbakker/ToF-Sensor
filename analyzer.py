from __future__ import annotations
import config


def _moving_avg(values: list, window: int = 5) -> list:
    result = []
    for i, v in enumerate(values):
        start = max(0, i - window + 1)
        result.append(sum(values[start:i + 1]) / (i - start + 1))
    return result


def compute_rise(distance_mm: int, baseline_mm: float) -> float:
    return max(0.0, baseline_mm - distance_mm)


def compute_rise_pct(rise_mm: float, baseline_mm: float,
                     container_bottom_mm=None) -> float:
    if container_bottom_mm and container_bottom_mm > baseline_mm:
        initial_height = container_bottom_mm - baseline_mm
    else:
        initial_height = 50.0
    if initial_height <= 0:
        return 0.0
    return (rise_mm / initial_height) * 100.0


def compute_speed(measurements: list) -> list:
    if len(measurements) < 2:
        return [0.0] * len(measurements)
    rises = _moving_avg([m["rise_mm"] for m in measurements], window=5)
    speeds = [0.0]
    for i in range(1, len(measurements)):
        dt_h = (measurements[i]["ts"] - measurements[i - 1]["ts"]) / 3600.0
        if dt_h > 0:
            speeds.append((rises[i] - rises[i - 1]) / dt_h)
        else:
            speeds.append(0.0)
    return speeds


class BakingSignal:
    def __init__(self, triggered: bool, reason: str = "", minutes_until_bake: int = 0):
        self.triggered = triggered
        self.reason = reason
        self.minutes_until_bake = minutes_until_bake


def check_baking_moment(measurements: list) -> BakingSignal:
    if len(measurements) < 10:
        return BakingSignal(False, "Te weinig data")
    if measurements[-1]["rise_mm"] < config.MIN_RISE_MM:
        return BakingSignal(False, f"Rijs < {config.MIN_RISE_MM} mm minimum")
    speeds = compute_speed(measurements)
    positive_speeds = [s for s in speeds if s > 0]
    if not positive_speeds:
        return BakingSignal(False, "Nog geen positieve rijssnelheid")
    peak_speed = max(positive_speeds)
    current_speed = speeds[-1]
    ratio = current_speed / peak_speed if peak_speed > 0 else 1.0
    if ratio < config.PEAK_SPEED_RATIO and current_speed >= 0:
        return BakingSignal(
            triggered=True,
            reason=f"Snelheid daalt ({ratio:.0%} van piek) — oven aan!",
            minutes_until_bake=config.OVEN_PREHEAT_MIN,
        )
    return BakingSignal(
        False,
        f"Snelheid {current_speed:.1f} mm/u ({ratio:.0%} van piek {peak_speed:.1f} mm/u)",
    )


def summarize(measurements: list) -> dict:
    if not measurements:
        return {"rise_mm": 0, "rise_pct": 0, "speed_mm_h": 0,
                "status": "waiting", "status_label": "Wacht op start…", "peak_speed": 0}
    last = measurements[-1]
    speeds = compute_speed(measurements)
    peak_speed = max((s for s in speeds if s > 0), default=0)
    signal = check_baking_moment(measurements)
    if signal.triggered:
        status, label = "baking", "🔥 Bakmoment nadert!"
    elif last.get("speed_mm_h") and last["speed_mm_h"] > 0.5:
        status, label = "rising", "📈 Rijst actief"
    elif last["rise_mm"] > config.MIN_RISE_MM:
        status, label = "slowing", "📉 Rijs vertraagt"
    else:
        status, label = "waiting", "⏳ Wacht op rijs…"
    return {
        "rise_mm":       round(last["rise_mm"] or 0, 1),
        "rise_pct":      round(last["rise_pct"] or 0, 1),
        "speed_mm_h":    round(last["speed_mm_h"] or 0, 2),
        "distance_mm":   last["distance_mm"],
        "status":        status,
        "status_label":  label,
        "signal":        signal.triggered,
        "signal_reason": signal.reason,
        "peak_speed":    round(peak_speed, 2),
        "ts":            last["ts"],
    }
