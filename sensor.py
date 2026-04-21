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

    def _read_ambient(self) -> int:
        buf = bytearray(2)
        while not self._i2c.try_lock():
            pass
        try:
            self._i2c.writeto(config.SENSOR_ADDR, bytes([0x00, 0x90]))
            self._i2c.readfrom_into(config.SENSOR_ADDR, buf)
        finally:
            self._i2c.unlock()
        return (buf[0] << 8) | buf[1]

    def read_distance_mm(self, samples: int = 5) -> tuple:
        distances = []
        ambients = []
        for _ in range(samples):
            timeout = 0
            while not self._sensor.data_ready:
                time.sleep(0.1)
                timeout += 1
                if timeout > 30:
                    break
            if self._sensor.data_ready:
                raw_cm = self._sensor.distance
                ambients.append(self._read_ambient())
                self._sensor.clear_interrupt()
                if raw_cm is not None and raw_cm > 0:
                    distances.append(round(raw_cm * 10))
            time.sleep(0.1)

        ambient_avg = round(sum(ambients) / len(ambients)) if ambients else 0

        if not distances:
            return (-1, ambient_avg)

        mean = sum(distances) / len(distances)
        std_dev = (sum((d - mean) ** 2 for d in distances) / len(distances)) ** 0.5
        if std_dev > 15:
            return (-2, ambient_avg)

        distances.sort()
        return (distances[len(distances) // 2], ambient_avg)

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
