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

# Controleer of de sensor zichtbaar is (adres 0x29)
i2cdetect -y 1

# Installeer lgpio via apt (vereist op Pi 5)
sudo apt install python3-lgpio

# Maak venv aan met toegang tot systeempakketten
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install adafruit-circuitpython-vl53l1x
```

## Gebruik

```bash
source venv/bin/activate
python test_sensor.py
```

Verwachte output:

```
Afstand: 31.2 cm
Afstand: 31.5 cm
...
```

Stop met `Ctrl+C`.
