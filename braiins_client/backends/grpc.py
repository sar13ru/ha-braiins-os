from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Helper para ejecutar grpcurl
# -------------------------------------------------------------------

def _resolve_grpcurl_path(grpcurl_bin: str) -> Optional[str]:
    """
    Resuelve la ruta del binario grpcurl.
    Permite override con GRPCURL_BIN.
    """
    if os.path.isabs(grpcurl_bin) or "/" in grpcurl_bin:
        return grpcurl_bin if os.path.exists(grpcurl_bin) else None
    return shutil.which(grpcurl_bin)


async def _run_grpcurl(args: list[str], timeout: float, grpcurl_bin: str) -> tuple[int, str, str]:
    """
    Ejecuta `grpcurl` con los argumentos dados.
    Devuelve: (returncode, stdout_str, stderr_str)
    """
    grpcurl_path = _resolve_grpcurl_path(grpcurl_bin)
    if not grpcurl_path:
        return 127, "", "grpcurl no encontrado (instala grpcurl o define GRPCURL_BIN)."

    try:
        proc = await asyncio.create_subprocess_exec(
            grpcurl_path,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return 127, "", "grpcurl no encontrado (instala grpcurl o define GRPCURL_BIN)."
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 1, "", f"grpcurl timeout after {timeout}s"

    stdout = stdout_b.decode(errors="ignore") if stdout_b else ""
    stderr = stderr_b.decode(errors="ignore") if stderr_b else ""
    return proc.returncode, stdout, stderr


# -------------------------------------------------------------------
# Login PAPI gRPC — SIN CACHE
# -------------------------------------------------------------------

async def _papi_login(
    host: str,
    papi_user: str,
    papi_password: str,
    papi_port: int,
    papi_timeout: float,
    grpcurl_bin: str,
) -> Optional[str]:
    """
    Hace login en AuthenticationService/Login y extrae el token del header
    `authorization: ...` que aparece en la salida verbose de grpcurl (-v).

    NO usa cache: cada llamada obtiene un token nuevo.
    """
    target = f"{host}:{int(papi_port)}"
    payload = json.dumps({"username": papi_user, "password": papi_password})

    args = [
        "-plaintext",
        "-v",  # para ver headers
        "-d",
        payload,
        target,
        "braiins.bos.v1.AuthenticationService/Login",
    ]

    rc, stdout, stderr = await _run_grpcurl(args, timeout=papi_timeout, grpcurl_bin=grpcurl_bin)
    if rc != 0:
        log.warning(
            "Login PAPI falló en %s (rc=%s). stderr: %s",
            host,
            rc,
            stderr.strip(),
        )
        return None

    # grpcurl escribe headers en stderr cuando usas -v
    combined = f"{stdout}\n{stderr}"
    token: Optional[str] = None
    for line in combined.splitlines():
        line = line.strip()
        if line.lower().startswith("authorization:"):
            token = line.split(":", 1)[1].strip()
            break

    if not token:
        log.warning(
            "No se encontró header authorization en Login PAPI para %s. "
            "stdout=%r stderr=%r",
            host,
            stdout[:200],
            stderr[:200],
        )
        return None

    return token


# -------------------------------------------------------------------
# Llamadas PAPI genéricas
# -------------------------------------------------------------------

async def _papi_call(
    host: str,
    method: str,
    token: Optional[str],
    timeout: float,
    papi_port: int,
    grpcurl_bin: str,
) -> Optional[Dict[str, Any]]:
    """
    Llama a un método PAPI vía grpcurl y devuelve JSON parseado.
    Si falla o no es JSON, devuelve None.
    """
    target = f"{host}:{int(papi_port)}"
    args = ["-plaintext"]
    if token:
        args += ["-H", f"authorization:{token}"]
    args += [target, method]

    rc, stdout, stderr = await _run_grpcurl(args, timeout=timeout, grpcurl_bin=grpcurl_bin)
    if rc != 0:
        log.warning(
            "PAPI call %s falló en %s (rc=%s). stderr: %s",
            method,
            host,
            rc,
            stderr.strip(),
        )
        return None

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        log.warning(
            "Respuesta no JSON en %s para %s. stdout=%r",
            host,
            method,
            stdout[:200],
        )
        return None


# -------------------------------------------------------------------
# S19 / S21: estado vía PAPI (gRPC)
# -------------------------------------------------------------------

async def fetch_miner_status(
    host: str,
    *,
    timeout: Optional[float] = None,
    # parámetros antiguos ignorados por compatibilidad:
    user: Optional[str] = None,  # noqa: ARG001
    port: Optional[int] = None,  # noqa: ARG001
    cmd: Optional[str] = None,   # noqa: ARG001
) -> Dict[str, Any]:
    """
    Consulta PAPI vía grpcurl:

      1. AuthenticationService/Login -> token (header authorization)
      2. MinerService/GetMinerStats  -> hashrate
      3. CoolingService/GetCoolingState -> temperatura aprox.

    Si el minero no tiene PAPI (ej: S9, BOS viejo, puerto 50051 cerrado),
    devuelve ok=False con mensaje claro.
    """
    papi_user = os.getenv("PAPI_USER", "root")
    papi_password = os.getenv("PAPI_PASSWORD", "")
    papi_port = int(os.getenv("PAPI_PORT", "50051"))
    papi_timeout = float(os.getenv("PAPI_TIMEOUT", "8.0")) if timeout is None else float(timeout)
    grpcurl_bin = os.getenv("GRPCURL_BIN", "grpcurl")

    if not _resolve_grpcurl_path(grpcurl_bin):
        msg = (
            "grpcurl no está instalado en este servidor. "
            "Instálalo o define GRPCURL_BIN con la ruta al binario."
        )
        return {
            "ok": False,
            "error": msg,
            "host": host,
            "summary": {
                "hashrate_th": None,
                "temp_avg": None,
                "power_w": None,
                "fan_rpm": None,
                "efficiency_j_th": None,
                "model": None,
            },
            "raw": None,
        }
    # 1) Login
    token = await _papi_login(
        host,
        papi_user=papi_user,
        papi_password=papi_password,
        papi_port=papi_port,
        papi_timeout=papi_timeout,
        grpcurl_bin=grpcurl_bin,
    )
    if not token:
        msg = (
            "PAPI gRPC no disponible en este minero "
            "(firmware antiguo, ej. S9, o puerto 50051 cerrado)."
        )
        return {
            "ok": False,
            "error": msg,
            "host": host,
            "summary": {
                "hashrate_th": None,
                "temp_avg": None,
                "power_w": None,
                "fan_rpm": None,
                "efficiency_j_th": None,
                "model": None,
            },
            "raw": None,
        }

    # 2) GetMinerStats
    stats = await _papi_call(
        host,
        "braiins.bos.v1.MinerService/GetMinerStats",
        token,
        timeout=papi_timeout,
        papi_port=papi_port,
        grpcurl_bin=grpcurl_bin,
    )
    if not isinstance(stats, dict):
        msg = "No se pudo leer MinerService/GetMinerStats vía PAPI."
        return {
            "ok": False,
            "error": msg,
            "host": host,
            "summary": {
                "hashrate_th": None,
                "temp_avg": None,
                "power_w": None,
                "fan_rpm": None,
                "efficiency_j_th": None,
                "model": None,
            },
            "raw": None,
        }

    # 3) CoolingService/GetCoolingState (temperatura)
    cooling = await _papi_call(
        host,
        "braiins.bos.v1.CoolingService/GetCoolingState",
        token,
        timeout=papi_timeout,
        papi_port=papi_port,
        grpcurl_bin=grpcurl_bin,
    )

    summary = _extract_summary(stats, cooling)

    raw: Dict[str, Any] = {"stats": stats}
    if cooling is not None:
        raw["cooling"] = cooling

    return {
        "ok": True,
        "error": None,
        "host": host,
        "summary": summary,
        "raw": raw,
    }

def _extract_summary(
    stats: Dict[str, Any],
    cooling: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Intenta sacar hashrate (TH/s) y temperatura promedio (°C)
    de la respuesta JSON de:

      - MinerService/GetMinerStats
      - CoolingService/GetCoolingState

    Es tolerante con nombres de campos (camelCase/snake_case).
    """
    hashrate_th: Optional[float] = None
    temp_avg: Optional[float] = None
    power_w: Optional[float] = None
    fan_rpm: Optional[float] = None
    efficiency_j_th: Optional[float] = None
    model: Optional[str] = None

    def _to_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:  # noqa: BLE001
            return None

    # 1) HASHRATE
    try:
        ms = stats.get("minerStats") or stats.get("miner_stats") or {}
        real = ms.get("realHashrate") or ms.get("real_hashrate") or {}

        if isinstance(real, dict):
            hashrate_candidates = []

            for window_key in ("last15s", "last30s", "last1m", "last5m"):
                window = real.get(window_key)
                if isinstance(window, dict):
                    ghs = window.get("gigahashPerSecond") or window.get("gigahash_per_second")
                    hashrate_candidates.append(ghs)

            for ghs in hashrate_candidates:
                maybe = _to_float(ghs)
                if maybe is not None:
                    hashrate_th = maybe / 1000.0
                    break

        # Fallback nominal
        if hashrate_th is None:
            nominal = (
                ms.get("nominalHashrate")
                or ms.get("nominal_hashrate")
                or {}
            )
            ghs = (
                nominal.get("gigahashPerSecond")
                or nominal.get("gigahash_per_second")
            )
            maybe = _to_float(ghs)
            if maybe is not None:
                hashrate_th = maybe / 1000.0

    except Exception:  # noqa: BLE001
        pass

    # 2) TEMPERATURA (del CoolingState)
    try:
        if isinstance(cooling, dict):
            highest = cooling.get("highestTemperature") or cooling.get("highest_temperature")
            if isinstance(highest, dict):
                temp_node = highest.get("temperature") or {}
                if isinstance(temp_node, dict):
                    temp_avg = _to_float(temp_node.get("degreeC") or temp_node.get("degreesC"))

            temps: list[float] = []

            def _walk(obj: Any, key_path: str = "") -> None:
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        new_path = f"{key_path}.{k}" if key_path else k
                        _walk(v, new_path)
                elif isinstance(obj, (int, float)):
                    lp = key_path.lower()
                    if (
                        "temp" in lp
                        or "degreec" in lp
                        or "celsius" in lp
                    ):
                        if 0.0 < float(obj) < 130.0:
                            temps.append(float(obj))

            _walk(cooling)
            if temp_avg is None and temps:
                temp_avg = sum(temps) / len(temps)

    except Exception:  # noqa: BLE001
        pass

    # 3) POWER
    try:
        power_stats = stats.get("powerStats") or stats.get("power_stats") or {}
        if isinstance(power_stats, dict):
            approx = power_stats.get("approximatedConsumption") or power_stats.get("approximated_consumption") or {}
            if isinstance(approx, dict):
                power_w = _to_float(approx.get("watt"))
    except Exception:  # noqa: BLE001
        pass

    # 4) FAN RPM promedio
    try:
        if isinstance(cooling, dict):
            fans = cooling.get("fans")
            if isinstance(fans, list):
                rpms: list[float] = []
                for fan in fans:
                    if not isinstance(fan, dict):
                        continue
                    rpm = _to_float(fan.get("rpm"))
                    if rpm is not None:
                        rpms.append(rpm)
                if rpms:
                    fan_rpm = sum(rpms) / len(rpms)
    except Exception:  # noqa: BLE001
        pass

    # 5) Eficiencia (J/TH)
    try:
        power_stats = stats.get("powerStats") or stats.get("power_stats") or {}
        if isinstance(power_stats, dict):
            eff = power_stats.get("efficiency") or {}
            if isinstance(eff, dict):
                efficiency_j_th = _to_float(eff.get("joulePerTerahash") or eff.get("joule_per_terahash"))
    except Exception:  # noqa: BLE001
        pass

    # 6) Modelo (si ya viene en stats/cooling)
    try:
        candidates: list[str] = []

        def _collect_model(obj: Any) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    key = str(k).lower()
                    if key in {"model", "miner_model", "minermodel", "hwmodel", "device_model"}:
                        if isinstance(v, str) and v.strip():
                            candidates.append(v.strip())
                    _collect_model(v)
            elif isinstance(obj, list):
                for item in obj:
                    _collect_model(item)

        _collect_model(stats)
        if isinstance(cooling, dict):
            _collect_model(cooling)
        if candidates:
            model = candidates[0]
    except Exception:  # noqa: BLE001
        pass

    return {
        "hashrate_th": hashrate_th,
        "temp_avg": temp_avg,
        "power_w": power_w,
        "fan_rpm": fan_rpm,
        "efficiency_j_th": efficiency_j_th,
        "model": model,
    }

    
