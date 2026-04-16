from .backends import fetch_miner_status, fetch_miner_status_s9


class BraiinsClient:
    def __init__(self, host: str, backend: str = "grpc") -> None:
        self.host = host
        self.backend = backend

    async def async_get_summary(self) -> dict:
        summary = {
            "ok": False,
            "host": self.host,
            "backend": self.backend,
            "hashrate_th": None,
            "temp_avg": None,
            "power_w": None,
            "fan_rpm": None,
            "efficiency_j_th": None,
            "error": None,
            "model": None,
        }

        if self.backend == "grpc":
            result = await fetch_miner_status(self.host)
        elif self.backend == "s9":
            result = await fetch_miner_status_s9(self.host)
        else:
            summary["error"] = f"Unsupported backend: {self.backend}"
            return summary

        summary.update(result)
        if not summary.get("host"):
            summary["host"] = self.host
        summary["backend"] = self.backend
        return summary
