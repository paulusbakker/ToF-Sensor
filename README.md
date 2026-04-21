# ToF Sensor – VL53L1X (Raspberry Pi)

Testproject voor de VL53L1X Time-of-Flight afstandssensor op een Raspberry Pi met de Adafruit library.

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

# Installeer systeemafhankelijkheden
sudo apt install swig liblgpio-dev python3-lgpio

# Maak venv aan
python3 -m venv --system-site-packages ~/myenv
source ~/myenv/bin/activate
pip install adafruit-circuitpython-vl53l1x
```

## Gebruik

```bash
source ~/myenv/bin/activate
cd ~/tof-sensor
python test_sensor.py
```

Verwachte output:

```
Afstand: 31.2 cm
Afstand: 31.5 cm
...
```

Stop met `Ctrl+C`.

## Extern bereikbaar via Tailscale

Met Tailscale is het dashboard ook buiten je thuisnetwerk bereikbaar (bijv. via 4G/5G), zonder poorten te openen in je router.

### Installatie op de Pi

```bash
# Tailscale installeren
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
# Volg de inlog-URL die verschijnt
```

### App automatisch starten bij opstarten

```bash
sudo cp zuurdesem.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zuurdesem

# Status controleren
sudo systemctl status zuurdesem
```

### Telefoon koppelen

1. Installeer de **Tailscale**-app op je telefoon (iOS/Android)
2. Log in op hetzelfde Tailscale-account als de Pi
3. Open `http://<tailscale-ip-van-pi>:5000` in de browser

Het Tailscale-IP van de Pi vind je met: `tailscale ip -4`
