# ToF Sensor – VL53L1X (Raspberry Pi)

Eenvoudig testproject om de VL53L1X Time-of-Flight afstandssensor te testen op een Raspberry Pi.

## Bedrading (I2C)

| Sensor pin | Raspberry Pi pin |
|------------|------------------|
| VCC        | 3.3V (pin 1)     |
| GND        | GND (pin 6)      |
| SDA        | GPIO2 (pin 3)    |
| SCL        | GPIO3 (pin 5)    |

## Installatie

```bash
# Zet I2C aan (eenmalig)
sudo raspi-config  # → Interface Options → I2C → Enable

# Controleer of de sensor zichtbaar is op het I2C-bus (adres 0x29)
i2cdetect -y 1

# Installeer Python bibliotheek
pip install vl53l1x
```

## Gebruik

```bash
python test_sensor.py
```

Verwachte output (waarden in mm):

```
Afstand: 312 mm
Afstand: 315 mm
Afstand: 311 mm
...
```

Stop met `Ctrl+C`.

## Meetbereik modi

| Mode | Bereik      |
|------|-------------|
| 1    | ~1.3 m      |
| 2    | ~3 m        |
| 3    | ~4 m        |

Pas `start_ranging(1)` aan in `test_sensor.py` om van modus te wisselen.
