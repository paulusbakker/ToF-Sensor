import time
from smbus2 import SMBus, i2c_msg
import config

_DEFAULT_CONFIG = bytes([
    0x00, 0x00, 0x00, 0x01, 0x02, 0x00, 0x02, 0x08,
    0x00, 0x08, 0x10, 0x01, 0x01, 0x00, 0x00, 0x00,
    0x00, 0xff, 0x00, 0x0F, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x20, 0x0b, 0x00, 0x00, 0x02, 0x0a, 0x21,
    0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x00, 0xc8,
    0x00, 0x00, 0x38, 0xff, 0x01, 0x00, 0x08, 0x00,
    0x00, 0x01, 0xdb, 0x0f, 0x01, 0xf1, 0x0d, 0x01,
    0x68, 0x00, 0x80, 0x08, 0xb8, 0x00, 0x00, 0x00,
    0x00, 0x0f, 0x89, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x01, 0x0f, 0x0d, 0x0e, 0x0e, 0x00,
    0x00, 0x02, 0xc7, 0xff, 0x9b, 0x00, 0x00, 0x00,
    0x01, 0x00, 0x00,
])


class VL53L1X:
    def __init__(self):
        self._bus = None

    def _write(self, reg, data):
        if isinstance(data, int):
            data = bytes([data])
        payload = bytes([(reg >> 8) & 0xFF, reg & 0xFF]) + bytes(data)
        self._bus.i2c_rdwr(i2c_msg.write(config.SENSOR_ADDR, payload))

    def _read(self, reg, n=1):
        self._bus.i2c_rdwr(
            i2c_msg.write(config.SENSOR_ADDR, [(reg >> 8) & 0xFF, reg & 0xFF])
        )
        r = i2c_msg.read(config.SENSOR_ADDR, n)
        self._bus.i2c_rdwr(r)
        return bytes(r)

    def connect(self):
        if self._bus is not None:
            try:
                self._bus.close()
            except Exception:
                pass
            self._bus = None
        time.sleep(1.0)
        self._bus = SMBus(config.I2C_BUS)
        chip_id = self._read(0x010F)[0]
        if chip_id != 0xEA:
            raise RuntimeError(f"Onverwacht chip ID: 0x{chip_id:02X} (verwacht 0xEA)")
        print(f"[sensor] Verbonden — chip ID 0x{chip_id:02X}")
        for _ in range(200):
            if self._read(0x00E5)[0] == 0x03:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("Sensor niet opgestart binnen timeout")
        self._write(0x002D, _DEFAULT_CONFIG)
        self._write(0x005E, bytes([0x40, 0x0D, 0x03, 0x00]))
        self._write(0x0087, 0x40)
        time.sleep(0.5)
        print("[sensor] Continuous ranging gestart")

    def close(self):
        if self._bus:
            try:
                self._write(0x0087, 0x00)
            except Exception:
                pass
            self._bus.close()
            self._bus = None

    def _read_once(self) -> int:
        for _ in range(100):
            if (self._read(0x0031)[0] & 0x01) == 0:
                break
            time.sleep(0.005)
        else:
            return -1
        data = self._read(0x0096, 2)
        self._write(0x0086, 0x01)
        return (data[0] << 8) | data[1]

    def read_ambient(self) -> int:
        data = self._read(0x0090, 2)
        return (data[0] << 8) | data[1]

    def read_distance_mm(self, samples=5):
        distances = []
        ambients = []
        for _ in range(samples):
            v = self._read_once()
            if v > 0:
                distances.append(v)
            ambients.append(self.read_ambient())
            time.sleep(0.02)

        ambient_avg = round(sum(ambients) / len(ambients)) if ambients else 0

        if not distances:
            return (-1, 0)

        mean = sum(distances) / len(distances)
        std_dev = (sum((d - mean) ** 2 for d in distances) / len(distances)) ** 0.5
        if std_dev > 15:
            return (-2, ambient_avg)

        distances.sort()
        median = distances[len(distances) // 2]
        return (median, ambient_avg)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()
