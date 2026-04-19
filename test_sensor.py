import time
import VL53L1X  # pip install vl53l1x

tof = VL53L1X.VL53L1X(i2c_bus=1, i2c_address=0x29)
tof.open()
tof.start_ranging(1)  # 1 = short (~1.3m), 2 = medium (~3m), 3 = long (~4m)

try:
    while True:
        distance_mm = tof.get_distance()
        print(f"Afstand: {distance_mm} mm")
        time.sleep(0.1)
except KeyboardInterrupt:
    pass
finally:
    tof.stop_ranging()
    tof.close()
