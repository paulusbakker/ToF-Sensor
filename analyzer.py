from __future__ import annotations
import config


def smooth_rise_series(measurements: list) -> list:
    """Tijd-gebaseerde rolling mean van rise_mm over SMOOTH_WINDOW_MIN minuten.

    Voor elke meting wordt het gemiddelde berekend over alle eerdere metingen
    (incl. zichzelf) binnen het venster. Tijdens opstart is het venster
    progressief: gebruik wat er beschikbaar is.
    """
    if not measurements:
        return []
    window_s = config.SMOOTH_WINDOW_MIN * 60
    result = []
    start = 0
    for i, m in enumerate(measurements):
        ts_i = m["ts"]
        while measurements[start]["ts"] < ts_i - window_s:
            start += 1
        window = measurements[start:i + 1]
        result.append(sum(w["rise_mm"] for w in window) / len(window))
    return result


def compute_rise(distance_mm: int, baseline_mm: float) -> float:
    return max(0.0, baseline_mm - distance_mm)


def compute_speed(measurements: list) -> list:
    if len(measurements) < 2:
        return [0.0] * len(measurements)
    rises = smooth_rise_series(measurements)
    speeds = [0.0]
    for i in range(1, len(measurements)):
        dt_h = (measurements[i]["ts"] - measurements[i - 1]["ts"]) / 3600.0
        if dt_h > 0:
            speeds.append((rises[i] - rises[i - 1]) / dt_h)
        else:
            speeds.append(0.0)
    return speeds


def trend_speed_series(measurements: list) -> list:
    """Rolling lineaire-regressie helling van de gladgemaakte rijs over de
    laatste TREND_WINDOW_MIN minuten. Geeft mm/uur per meetpunt.

    Robuuster dan punt-tot-punt afgeleide: de noise van de 30 s sampling
    middelt uit, maar de trend volgt nog steeds binnen ~minuten.
    """
    if not measurements:
        return []
    smoothed = smooth_rise_series(measurements)
    window_s = config.TREND_WINDOW_MIN * 60
    result = []
    start = 0
    for i, m in enumerate(measurements):
        ts_i = m["ts"]
        while measurements[start]["ts"] < ts_i - window_s:
            start += 1
        n = i - start + 1
        if n < 3:
            result.append(0.0)
            continue
        ts_mean = sum(measurements[k]["ts"] for k in range(start, i + 1)) / n
        s_mean  = sum(smoothed[k] for k in range(start, i + 1)) / n
        num = den = 0.0
        for k in range(start, i + 1):
            dt = measurements[k]["ts"] - ts_mean
            num += dt * (smoothed[k] - s_mean)
            den += dt * dt
        slope_per_s = (num / den) if den > 0 else 0.0
        result.append(slope_per_s * 3600.0)
    return result


def smooth_trend_speed_series(measurements: list) -> list:
    """Tijd-gebaseerde rolling mean over trend_speed_series, breedte
    SMOOTH_TREND_MIN minuten. Tweede smoothing-laag: de eerste laag
    (smooth_rise_series) verandert de discrete 1mm-trapfunctie van de
    sensor in een trapfunctie met kleinere stappen, waarvan de
    regressie-afgeleide alsnog spikes vertoont bij elke trap. Een
    rolling mean over die afgeleide middelt die spikes uit.
    """
    if not measurements:
        return []
    raw = trend_speed_series(measurements)
    window_s = config.SMOOTH_TREND_MIN * 60
    result = []
    start = 0
    for i, m in enumerate(measurements):
        ts_i = m["ts"]
        while measurements[start]["ts"] < ts_i - window_s:
            start += 1
        window = raw[start:i + 1]
        result.append(sum(window) / len(window))
    return result


def smooth_trend_for_history(measurements: list, window_min: int = 60) -> list:
    """Niet-causale gecentreerde rolling mean (±window_min/2) over de
    gladde trend-snelheid. Geeft de S-curve die een mens met de pen
    door de puntenwolk zou trekken.

    LET OP: gebruikt toekomstige meetwaarden en is daarom alleen
    geschikt voor history-views waar de hele sessie beschikbaar is.
    Het live dashboard moet causaal blijven en gebruikt
    smooth_trend_speed_series.

    Aan begin en einde krimpt het venster asymmetrisch.
    """
    if not measurements:
        return []
    raw = smooth_trend_speed_series(measurements)
    half_s = (window_min / 2) * 60
    n = len(measurements)
    result = []
    lo = 0
    hi = 0
    for i, m in enumerate(measurements):
        ts_i = m["ts"]
        while lo < n and measurements[lo]["ts"] < ts_i - half_s:
            lo += 1
        while hi < n and measurements[hi]["ts"] <= ts_i + half_s:
            hi += 1
        window = raw[lo:hi]
        result.append(sum(window) / len(window) if window else 0.0)
    return result


class BakingSignal:
    def __init__(self, triggered: bool, reason: str = "", minutes_until_bake: int = 0):
        self.triggered = triggered
        self.reason = reason
        self.minutes_until_bake = minutes_until_bake


def check_baking_moment(measurements: list) -> BakingSignal:
    if len(measurements) < 10:
        return BakingSignal(False, "Te weinig data")
    last_smoothed = smooth_rise_series(measurements)[-1]
    if last_smoothed < config.MIN_RISE_MM:
        return BakingSignal(False, f"Rijs < {config.MIN_RISE_MM} mm minimum")
    speeds = smooth_trend_speed_series(measurements)
    warmup_s = (config.SMOOTH_WINDOW_MIN + config.TREND_WINDOW_MIN
                + config.SMOOTH_TREND_MIN) * 60
    window_full_after = measurements[0]["ts"] + warmup_s
    valid_speeds = [s for i, s in enumerate(speeds)
                    if s > 0 and measurements[i]["ts"] >= window_full_after]
    if not valid_speeds:
        return BakingSignal(False, "Nog geen positieve rijssnelheid")
    peak_speed = max(valid_speeds)
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
        return {"rise_mm": 0, "rise_mm_smoothed": 0, "speed_mm_h": 0,
                "status": "waiting", "status_label": "Wacht op start…",
                "peak_speed": 0, "pct_of_peak": 0}
    last = measurements[-1]
    smoothed = smooth_rise_series(measurements)
    last_smoothed = smoothed[-1]
    trend = smooth_trend_speed_series(measurements)
    current_trend = trend[-1] if trend else 0.0
    warmup_s = (config.SMOOTH_WINDOW_MIN + config.TREND_WINDOW_MIN
                + config.SMOOTH_TREND_MIN) * 60
    window_full_after = measurements[0]["ts"] + warmup_s
    valid = [s for i, s in enumerate(trend)
             if s > 0 and measurements[i]["ts"] >= window_full_after]
    peak_speed = max(valid, default=0.0)
    pct_of_peak = (current_trend / peak_speed * 100.0) if peak_speed > 0 else 0.0
    signal = check_baking_moment(measurements)
    if signal.triggered:
        status, label = "baking", "🔥 Bakmoment nadert!"
    elif current_trend > 0.5:
        status, label = "rising", "📈 Rijst actief"
    elif last_smoothed > config.MIN_RISE_MM:
        status, label = "slowing", "📉 Rijs vertraagt"
    else:
        status, label = "waiting", "⏳ Wacht op rijs…"
    return {
        "rise_mm":          round(last["rise_mm"] or 0, 1),
        "rise_mm_smoothed": round(last_smoothed, 1),
        "speed_mm_h":       round(current_trend, 2),
        "distance_mm":      last["distance_mm"],
        "status":           status,
        "status_label":     label,
        "signal":           signal.triggered,
        "signal_reason":    signal.reason,
        "peak_speed":       round(peak_speed, 2),
        "pct_of_peak":      round(pct_of_peak, 0),
        "ts":               last["ts"],
    }
