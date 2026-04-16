from __future__ import annotations

from typing import Any, Dict, Optional

class BraiinsClient:
    def __init__(self, host: str, backend: str):
        self.host = host
        self.backend = backend

    async def async_get_summary(self) -> dict:
        normalized: Dict[str, Any] = {
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

        backend = (self.backend or "").strip().lower()
        if backend not in {"grpc", "s9"}:
            normalized["error"] = f"Backend no soportado: {self.backend}"
            return normalized

        try:
            if backend == "grpc":
                from .backends.grpc import fetch_miner_status

                data = await fetch_miner_status(self.host)
            else:
                from .backends.graphql_s9 import fetch_miner_status_s9

                data = await fetch_miner_status_s9(self.host)
        except Exception as exc:  # noqa: BLE001
            normalized["error"] = str(exc)
            return normalized

        return self._normalize_backend_response(data)

    def _normalize_backend_response(self, data: Any) -> dict:
        backend_value = self.backend

        if not isinstance(data, dict):
            return {
                "ok": False,
                "host": self.host,
                "backend": backend_value,
                "hashrate_th": None,
                "temp_avg": None,
                "power_w": None,
                "fan_rpm": None,
                "efficiency_j_th": None,
                "error": "Respuesta invalida del backend",
                "model": None,
            }

        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        error = data.get("error")
        ok = bool(data.get("ok")) and not error

        return {
            "ok": ok,
            "host": str(data.get("host") or self.host),
            "backend": backend_value,
            "hashrate_th": self._to_float(summary.get("hashrate_th")),
            "temp_avg": self._to_float(summary.get("temp_avg")),
            "power_w": self._to_float(summary.get("power_w")),
            "fan_rpm": self._to_float(summary.get("fan_rpm")),
            "efficiency_j_th": self._to_float(summary.get("efficiency_j_th")),
            "error": str(error) if error else None,
            "model": summary.get("model") if isinstance(summary.get("model"), str) else self._extract_model(data),
        }

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _extract_model(self, data: Dict[str, Any]) -> Optional[str]:
        raw = data.get("raw")
        if not isinstance(raw, dict):
            return None

        candidates: list[str] = []

        def _walk(obj: Any) -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    kl = str(key).lower()
                    if kl in {"model", "miner_model", "minermodel", "hwmodel", "device_model"}:
                        if isinstance(value, str) and value.strip():
                            candidates.append(value.strip())
                    _walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)

        _walk(raw)
        return candidates[0] if candidates else None
