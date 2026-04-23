# ─── Sensor ───────────────────────────────────────────────
I2C_BUS         = 1
SENSOR_ADDR     = 0x29
MEASURE_INTERVAL = 30          # seconden tussen metingen

# ─── Database ─────────────────────────────────────────────
DB_PATH = "dough.db"

# ─── Rijslogica ───────────────────────────────────────────
OVEN_PREHEAT_MIN  = 45         # minuten voorverwarmen
AUTO_OVEN_ENABLED = False       # automatisch oven aansturen bij bakmoment
MIN_RISE_MM       = 8          # minimale rijs voordat analyse start
PEAK_SPEED_RATIO  = 0.30       # snelheid < 30% van piek → bijna klaar

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
