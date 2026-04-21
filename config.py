# ─── Sensor ───────────────────────────────────────────────
I2C_BUS         = 1
SENSOR_ADDR     = 0x29
MEASURE_INTERVAL = 30          # seconden tussen metingen

# ─── Database ─────────────────────────────────────────────
DB_PATH = "dough.db"

# ─── Rijslogica ───────────────────────────────────────────
OVEN_PREHEAT_MIN  = 45         # minuten voorverwarmen
MIN_RISE_MM       = 8          # minimale rijs voordat analyse start
PEAK_SPEED_RATIO  = 0.30       # snelheid < 30% van piek → bijna klaar

# ─── Oven (Tuya/tinytuya) ─────────────────────────────────
# Stap 1: pip install tinytuya
# Stap 2: python -m tinytuya wizard   → volg de stappen
# Stap 3: vul onderstaande waarden in
TUYA_ENABLED   = True
TUYA_DEVICE_ID = "30713841c4dd57240ba9"
TUYA_LOCAL_KEY = "74dbf028808a88ee"
TUYA_IP        = "192.168.2.1"
TUYA_VERSION   = 3.3

# ─── Web ──────────────────────────────────────────────────
FLASK_PORT = 5000
FLASK_HOST = "0.0.0.0"
