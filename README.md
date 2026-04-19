# ToF Sensor – VL53L1X (Raspberry Pi)

Eenvoudig testproject om de VL53L1X Time-of-Flight afstandssensor te testen op een Raspberry Pi.
Gebruikt pure `smbus2` — geen Adafruit stack of GPIO library nodig.

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

# Controleer of de sensor zichtbaar is (adres 0x29)
i2cdetect -y 1

# Maak venv en installeer
python3 -m venv venv
source venv/bin/activate
pip install smbus2
```

## Gebruik

```bash
source venv/bin/activate
python test_sensor.py
```

Verwachte output:

```
Chip ID: 0xEA  (verwacht: 0xEA)
Afstand: 312 mm
Afstand: 315 mm
...
```

Stop met `Ctrl+C`.
