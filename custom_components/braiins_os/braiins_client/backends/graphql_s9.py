async def fetch_miner_status_s9(host: str) -> dict:
    return {
        "ok": False,
        "host": host,
        "hashrate_th": None,
        "temp_avg": None,
        "power_w": None,
        "fan_rpm": None,
        "efficiency_j_th": None,
        "error": "S9 backend not implemented yet",
        "model": None,
    }
