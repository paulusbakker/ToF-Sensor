import board, busio, adafruit_vl53l1x
import time

i2c = busio.I2C(board.SCL, board.SDA)
sensor = adafruit_vl53l1x.VL53L1X(i2c)
sensor.start_ranging()

while True:
    if sensor.data_ready:
        print(f'Afstand: {sensor.distance} cm')
        sensor.clear_interrupt()
    time.sleep(0.5)
