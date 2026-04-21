"""
sensor.py — VL53L1X wrapper via Adafruit CircuitPython library.
"""

import time
import board
import busio
import adafruit_vl53l1x
import config


class VL53L1X:
    def __init__(self):
        self._sensor = None
        self._i2c = None

    def connect(self):
        if self._i2c is not None:
            self._safe_close()
        time.sleep(1.0)
        self._i2c = busio.I2C(board.SCL, board.SDA)
        self._sensor = adafruit_vl53l1x.VL53L1X(self._i2c)
        self._sensor.distance_mode = 1
        self._sensor.timing_budget = 50
        self._sensor.start_ranging()
        print("[sensor] Verbonden via Adafruit library — distance_mode=Short, budget=50ms")

    def read_distance_mm(self, samples: int = 5) -> tuple:
        distances = []
        ambients = []
        for _ in range(samples):
            waited = 0
            while not self._sensor.data_ready:
                time.sleep(0.010)
                waited += 1
                if waited > 100:
                    break
            if self._sensor.data_ready:
                raw_cm = self._sensor.distance
                ambient = self._sensor.ambient_count
                self._sensor.clear_interrupt()
                if raw_cm is not None and raw_cm > 0:
                    distances.append(round(raw_cm * 10))
                ambients.append(int(ambient) if ambient is not None else 0)
            time.sleep(0.02)
        ambient_avg = round(sum(ambients) / len(ambients)) if ambients else 0
        if not distances:
            return (-1, ambient_avg)
        mean = sum(distances) / len(distances)
        std_dev = (sum((d - mean) ** 2 for d in distances) / len(distances)) ** 0.5
        if std_dev > 15:
            return (-2, ambient_avg)
        distances.sort()
        median = distances[len(distances) // 2]
        return (median, ambient_avg)

    def close(self):
        self._safe_close()

    def _safe_close(self):
        if self._sensor:
            try:
                self._sensor.stop_ranging()
            except Exception:
                pass
            self._sensor = None
        if self._i2c:
            try:
                self._i2c.deinit()
            except Exception:
                pass
            self._i2c = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()
