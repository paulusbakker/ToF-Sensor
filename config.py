# ─── Sensor ───────────────────────────────────────────────
I2C_BUS         = 1
MEASURE_INTERVAL = 30          # seconden tussen metingen

# ─── Database ─────────────────────────────────────────────
DB_PATH = "dough.db"

# ─── Rijslogica ───────────────────────────────────────────
OVEN_PREHEAT_MIN  = 45         # minuten voorverwarmen
AUTO_OVEN_ENABLED = False       # automatisch oven aansturen bij bakmoment
MIN_RISE_MM       = 8          # minimale rijs voordat analyse start
PEAK_SPEED_RATIO  = 0.30       # snelheid < 30% van piek → bijna klaar
SMOOTH_WINDOW_MIN = 15         # rolling mean window (minuten) voor rijs-smoothing
TREND_WINDOW_MIN  = 40         # window (minuten) voor trend-snelheid (lin. regressie)
SMOOTH_TREND_MIN  = 30         # rolling mean window (minuten) over de trend-snelheid
SIGNAL_REMINDER_MIN = 20       # interval (minuten) voor herhaalde bakmoment-melding
MIN_SLOWDOWN_DURATION_MIN = 60 # snelheid moet zo lang aaneengesloten onder de drempel blijven
PEAK_IGNORE_EARLY_MIN     = 90 # eerste minuten van sessie negeren bij peak-bepaling
MIN_SESSION_DURATION_MIN  = 240# minimumduur van sessie voordat triggeren is toegestaan
RESUME_SPEED_RATIO        = 0.50 # > deze fractie van piek na trigger → "echt weer aan het rijzen"

# ─── Verdachte sprong-detectie ────────────────────────────
# Afstand t.o.v. baseline: dist > baseline + X mm = fysiek onmogelijk
# tijdens rijzen (deeg kan niet verder van sensor af bewegen).
JUMP_BASELINE_INCREASE_MM = 12
# Sprong t.o.v. recente mediaan: grote discrete verschuiving van het mandje
# of de sensor. Asymmetrisch: ↑ is verdachter dan ↓ (rijzen gaat snel).
JUMP_RECENT_INCREASE_MM   = 15
JUMP_RECENT_DECREASE_MM   = 30
JUMP_RECENT_WINDOW        = 5   # aantal recente metingen voor mediaan
# Minimuminterval tussen waarschuwingen om spam te voorkomen.
JUMP_SUPPRESS_MIN         = 5

# ─── Oven (Tuya/tinytuya) ─────────────────────────────────
# Stap 1: pip install tinytuya
# Stap 2: python -m tinytuya wizard   → volg de stappen
# Stap 3: vul onderstaande waarden in
TUYA_ENABLED   = False
TUYA_DEVICE_ID = "YOUR_DEVICE_ID"
TUYA_LOCAL_KEY = "YOUR_LOCAL_KEY"
TUYA_IP        = "192.168.1.x"
TUYA_VERSION   = 3.3

# ─── Notificaties (ntfy.sh) ───────────────────────────────
NTFY_ENABLED = False
NTFY_TOPIC   = "zuurdesem"
NTFY_URL     = "https://ntfy.sh"

# ─── Web ──────────────────────────────────────────────────
FLASK_PORT = 5000
FLASK_HOST = "0.0.0.0"

# ─── Lokale overrides (nooit committen) ───────────────────
try:
    from config_local import *
except ImportError:
    pass
