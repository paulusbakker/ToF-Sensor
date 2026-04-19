import time
import board
import adafruit_vl53l1x

i2c = board.I2C()
vl53 = adafruit_vl53l1x.VL53L1X(i2c)
vl53.start_ranging()

try:
    while True:
        if vl53.data_ready:
            distance_cm = vl53.distance
            if distance_cm is not None:
                print(f"Afstand: {distance_cm:.1f} cm")
            vl53.clear_interrupt()
        time.sleep(0.1)
except KeyboardInterrupt:
    pass
finally:
    vl53.stop_ranging()
