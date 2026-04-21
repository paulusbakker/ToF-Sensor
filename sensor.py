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
        self._sensor.start_ranging()
        print("[sensor] Verbonden via Adafruit library")

    def read_distance_mm(self, samples: int = 5) -> tuple:
        distances = []
        for _ in range(samples):
            timeout = 0
            while not self._sensor.data_ready:
                time.sleep(0.1)
                timeout += 1
                if timeout > 30:
                    break
            if self._sensor.data_ready:
                raw_cm = self._sensor.distance
                self._sensor.clear_interrupt()
                if raw_cm is not None and raw_cm > 0:
                    distances.append(round(raw_cm * 10))
            time.sleep(0.1)

        if not distances:
            return (-1, 0)

        mean = sum(distances) / len(distances)
        std_dev = (sum((d - mean) ** 2 for d in distances) / len(distances)) ** 0.5
        if std_dev > 15:
            return (-2, 0)

        distances.sort()
        return (distances[len(distances) // 2], 0)

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
