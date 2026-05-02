import logging
import config

log = logging.getLogger(__name__)

_simulated_state = False


def _get_device():
    import tinytuya
    d = tinytuya.OutletDevice(
        dev_id=config.TUYA_DEVICE_ID,
        address=config.TUYA_IP,
        local_key=config.TUYA_LOCAL_KEY,
    )
    d.set_version(config.TUYA_VERSION)
    return d


def turn_on() -> bool:
    global _simulated_state
    if not config.TUYA_ENABLED:
        _simulated_state = True
        print("🔌 [oven] SIMULATIE: oven aan")
        return True
    try:
        _get_device().turn_on()
        log.info("[oven] Oven aangezet ✓")
        return True
    except Exception as e:
        log.error(f"[oven] Fout: {e}")
        return False


def turn_off() -> bool:
    global _simulated_state
    if not config.TUYA_ENABLED:
        _simulated_state = False
        print("🔌 [oven] SIMULATIE: oven uit")
        return True
    try:
        _get_device().turn_off()
        return True
    except Exception as e:
        log.error(f"[oven] Fout: {e}")
        return False


def get_status() -> dict:
    if not config.TUYA_ENABLED:
        return {"on": _simulated_state, "simulated": True}
    try:
        data = _get_device().status()
        return {"on": bool(data.get("dps", {}).get("1", False))}
    except Exception as e:
        return {"on": False, "error": str(e)}
