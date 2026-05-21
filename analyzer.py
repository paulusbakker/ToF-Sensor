from __future__ import annotations
from functools import lru_cache
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


def avg_speed_2h_series(measurements: list) -> list:
    """Voortschrijdend 2u gemiddelde van de gladgemaakte rijs, in mm/uur.

    Per index i: (smoothed[i] - smoothed[j]) / dt_h, waarbij j de eerste
    index is met ts >= ts_i - 2u. Tijdens opstart (< ~2u data) is er geen
    geldig 2u-venster: dan 0.0, volgens de conventie van compute_speed
    en trend_speed_series.
    """
    if not measurements:
        return []
    smoothed = smooth_rise_series(measurements)
    window_s = 2 * 3600
    result = []
    start = 0
    for i, m in enumerate(measurements):
        ts_i = m["ts"]
        while measurements[start]["ts"] < ts_i - window_s:
            start += 1
        if ts_i - measurements[0]["ts"] < window_s:
            result.append(0.0)
            continue
        dt_h = (ts_i - measurements[start]["ts"]) / 3600.0
        if dt_h > 0:
            result.append((smoothed[i] - smoothed[start]) / dt_h)
        else:
            result.append(0.0)
    return result


def plateau_minutes(measurements: list) -> float | None:
    """Minuten sinds de laatste meting waarop raw rise_mm een strikt nieuw
    maximum bereikte. Werkt op raw rise (niet smoothed) — dat is wat de
    detectie robuust maakt tegen smoothing-lag. Retourneert None als er
    nog geen rijs is geweest (alle metingen rise_mm == 0).
    """
    if not measurements:
        return None
    prev_max = 0.0
    last_max_idx = None
    for i, m in enumerate(measurements):
        r = m["rise_mm"] or 0
        if r > prev_max:
            prev_max = r
            last_max_idx = i
    if last_max_idx is None:
        return None
    return (measurements[-1]["ts"] - measurements[last_max_idx]["ts"]) / 60.0


def smooth_trend_for_history(measurements: list, window_length: int = 121,
                             polyorder: int = 3) -> list:
    """Niet-causale Savitzky-Golay smoothing van de gladde trend-snelheid.

    SG fit per venster een lokale polynoom (graad `polyorder`) en gebruikt
    daarvan de waarde in het midden. Het kijkt vooruit én achteruit, dus
    alleen geschikt voor history-views; live dashboard moet causaal
    blijven en gebruikt smooth_trend_speed_series.

    Default window 121 samples = 60 min bij 30s sample-interval (oneven
    is vereist), polyorder 3 voor een S-curve. Aan begin/einde krimpt
    het venster symmetrisch met passend lagere polyorder.
    """
    if not measurements:
        return []
    raw = smooth_trend_speed_series(measurements)
    return _savgol_filter(raw, window_length, polyorder)


@lru_cache(maxsize=256)
def _savgol_coeffs(window_length: int, polyorder: int) -> tuple:
    """Symmetrische Savitzky-Golay smoothing-coëfficiënten (centrale
    output, derivative=0). Werkt voor uniforme sample-spacing.
    """
    half = window_length // 2
    n_cols = polyorder + 1
    js = list(range(-half, half + 1))
    # AtA[a][b] = sum_j j^(a+b)
    moments = [sum(j**p for j in js) for p in range(2 * polyorder + 1)]
    aug = [[moments[a + b] for b in range(n_cols)] + [1.0 if a == 0 else 0.0]
           for a in range(n_cols)]
    # Gauss-Jordan: lost (AtA) z = e0 op
    for i in range(n_cols):
        piv = aug[i][i]
        for j in range(n_cols + 1):
            aug[i][j] /= piv
        for k in range(n_cols):
            if k != i:
                f = aug[k][i]
                for j in range(n_cols + 1):
                    aug[k][j] -= f * aug[i][j]
    z = [aug[i][n_cols] for i in range(n_cols)]
    # h[j] = sum_k z_k * j^k → impulse response van het filter
    return tuple(sum(z[k] * (j**k) for k in range(n_cols)) for j in js)


def _savgol_filter(values: list, window_length: int, polyorder: int) -> list:
    n = len(values)
    if n == 0:
        return []
    wl = min(window_length, n if n % 2 == 1 else n - 1)
    if wl < 3:
        return list(values)
    if wl % 2 == 0:
        wl -= 1
    po = min(polyorder, wl - 1)
    half = wl // 2
    coeffs = _savgol_coeffs(wl, po)
    out = list(values)
    for i in range(half, n - half):
        out[i] = sum(coeffs[k] * values[i - half + k] for k in range(wl))
    # Randen: kleiner symmetrisch venster met aangepaste polyorder
    for i in range(half):
        w = 2 * i + 1
        if w < 3:
            continue
        po_e = min(po, w - 1)
        c = _savgol_coeffs(w, po_e)
        out[i]         = sum(c[k] * values[k]         for k in range(w))
        out[n - 1 - i] = sum(c[k] * values[n - w + k] for k in range(w))
    return out


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
    session_duration_min = (measurements[-1]["ts"] - measurements[0]["ts"]) / 60.0
    if session_duration_min < config.MIN_SESSION_DURATION_MIN:
        remaining = config.MIN_SESSION_DURATION_MIN - session_duration_min
        return BakingSignal(False,
                            f"Sessie nog te kort (nog {remaining:.0f} min vóór analyse)")
    speeds = smooth_trend_speed_series(measurements)
    warmup_s = (config.SMOOTH_WINDOW_MIN + config.TREND_WINDOW_MIN
                + config.SMOOTH_TREND_MIN) * 60
    peak_ignore_s = config.PEAK_IGNORE_EARLY_MIN * 60
    cutoff_ts = measurements[0]["ts"] + max(warmup_s, peak_ignore_s)
    valid_speeds = [s for i, s in enumerate(speeds)
                    if s > 0 and measurements[i]["ts"] >= cutoff_ts]
    if not valid_speeds:
        return BakingSignal(False, "Nog geen geldige piek-referentie")
    peak_speed = max(valid_speeds)
    current_speed = speeds[-1]
    ratio = current_speed / peak_speed if peak_speed > 0 else 1.0
    threshold = config.PEAK_SPEED_RATIO * peak_speed
    # Aaneengesloten vertraging: zoek het meest recente punt waarop de
    # gladde trend nog op/over de drempel zat. Eén dip telt niet — pas
    # als de hele suffix (lengte ≥ MIN_SLOWDOWN_DURATION_MIN) onder de
    # drempel blijft, accepteren we de trigger.
    last_above_ts = measurements[0]["ts"]
    for i in range(len(measurements) - 1, -1, -1):
        if speeds[i] >= threshold:
            last_above_ts = measurements[i]["ts"]
            break
    slowdown_min = (measurements[-1]["ts"] - last_above_ts) / 60.0
    if (current_speed >= 0 and ratio < config.PEAK_SPEED_RATIO
            and slowdown_min >= config.MIN_SLOWDOWN_DURATION_MIN):
        return BakingSignal(
            triggered=True,
            reason=(f"Snelheid {slowdown_min:.0f} min < {config.PEAK_SPEED_RATIO:.0%} "
                    f"van piek ({ratio:.0%}) — oven aan!"),
            minutes_until_bake=config.OVEN_PREHEAT_MIN,
        )
    return BakingSignal(
        False,
        f"Snelheid {current_speed:.1f} mm/u ({ratio:.0%} van piek {peak_speed:.1f} mm/u)",
    )


def summarize(measurements: list, dough_height_cm: float = None) -> dict:
    if not measurements:
        return {"rise_mm": 0, "rise_mm_smoothed": 0, "speed_mm_h": 0,
                "status": "waiting", "status_label": "Wacht op start…",
                "plateau_min": None}
    last = measurements[-1]
    smoothed = smooth_rise_series(measurements)
    last_smoothed = smoothed[-1]
    avg2h = avg_speed_2h_series(measurements)
    current_speed = avg2h[-1] if avg2h else 0.0
    plateau = plateau_minutes(measurements)
    signal = check_baking_moment(measurements)
    if signal.triggered:
        status, label = "baking", "🔥 Bakmoment nadert!"
    elif current_speed > 0.5:
        status, label = "rising", "📈 Rijst actief"
    elif last_smoothed > config.MIN_RISE_MM:
        status, label = "slowing", "📉 Rijs vertraagt"
    else:
        status, label = "waiting", "⏳ Wacht op rijs…"
    out = {
        "rise_mm":          round(last["rise_mm"] or 0, 1),
        "rise_mm_smoothed": round(last_smoothed, 1),
        "speed_mm_h":       round(current_speed, 2),
        "distance_mm":      last["distance_mm"],
        "status":           status,
        "status_label":     label,
        "signal":           signal.triggered,
        "signal_reason":    signal.reason,
        "plateau_min":      round(plateau, 1) if plateau is not None else None,
        "ts":               last["ts"],
    }
    if dough_height_cm and dough_height_cm > 0:
        rise_mm_val = last["rise_mm"] or 0
        out["rise_pct_of_dough"] = round(rise_mm_val / (dough_height_cm * 10) * 100)
    return out
