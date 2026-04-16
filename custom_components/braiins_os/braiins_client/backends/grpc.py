"""Cliente gRPC Braiins OS vía grpcurl (PAPI).

Los tokens de sesión caducan (~1 h sin actividad). Hay que obtenerlos con
AuthenticationService/Login; un token fijo en código deja de ser válido.
Opcional: BRAIINS_GRPC_TOKEN en el entorno para forzar un token concreto.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading

DEFAULT_GRPC_PORT = 50051

LOGIN_METHOD = "braiins.bos.v1.AuthenticationService/Login"
MINER_STATS_METHOD = "braiins.bos.v1.MinerService/GetMinerStats"
COOLING_STATE_METHOD = "braiins.bos.v1.CoolingService/GetCoolingState"

_token_lock = threading.Lock()
_cached: tuple[str, str] | None = None  # (target, token)


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_grpc_target(host: str) -> str:
    host = host.strip()
    if not host:
        raise RuntimeError("Host gRPC vacio")

    if host.startswith("[") and "]:" in host:
        return host
    if ":" in host and not host.startswith("["):
        return host
    if host.startswith("[") and host.endswith("]"):
        return f"{host}:{DEFAULT_GRPC_PORT}"
    return f"{host}:{DEFAULT_GRPC_PORT}"


def _grpcurl_stderr_stdout(completed: subprocess.CompletedProcess[str]) -> str:
    stderr_text = (completed.stderr or "").strip()
    stdout_text = (completed.stdout or "").strip()
    if stderr_text and stdout_text:
        return f"{stderr_text}\n{stdout_text}"
    return stderr_text or stdout_text or ""


def _run_grpcurl_plain(
    target: str,
    service_method: str,
    *,
    request_json: str | None,
    auth_header: str | None,
) -> dict:
    cmd: list[str] = ["grpcurl", "-plaintext"]
    if auth_header is not None:
        cmd.extend(["-H", auth_header])
    if request_json is not None:
        cmd.extend(["-d", request_json])
    cmd.extend([target, service_method])

    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        combined = _grpcurl_stderr_stdout(completed)
        lowered = combined.lower()
        if "unauthenticated" in lowered or "missing or invalid authentication token" in lowered:
            raise RuntimeError(
                f"Authentication failed for {service_method} on {target}: {combined}"
            )
        raise RuntimeError(
            f"grpcurl failed for {service_method} on {target} "
            f"(exit {completed.returncode}): {combined}"
        )

    output = (completed.stdout or "").strip()
    if not output:
        return {}

    try:
        return json.loads(output)
    except json.JSONDecodeError as err:
        raise RuntimeError(
            f"Invalid JSON response from {service_method}: {err}. Raw output: {output}"
        ) from err


def _env_grpc_token() -> str | None:
    token = (os.environ.get("BRAIINS_GRPC_TOKEN") or "").strip()
    return token or None


def _login(target: str) -> str:
    username = (os.environ.get("PAPI_USER") or "root").strip()
    password = os.environ.get("PAPI_PASSWORD") or ""
    body = json.dumps({"username": username, "password": password})
    data = _run_grpcurl_plain(target, LOGIN_METHOD, request_json=body, auth_header=None)
    token = data.get("token")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError(
            f"Login en {target} no devolvio token valido: {json.dumps(data)[:500]}"
        )
    return token.strip()


def _auth_header_for_token(token: str) -> str:
    return f"authorization:{token}"


def _get_token(target: str, *, force_refresh: bool) -> str:
    env_token = _env_grpc_token()
    if env_token and not force_refresh:
        return env_token

    global _cached
    with _token_lock:
        if not force_refresh and _cached and _cached[0] == target:
            return _cached[1]
        token = _login(target)
        _cached = (target, token)
        return token


def _invalidate_token_cache() -> None:
    global _cached
    with _token_lock:
        _cached = None


def _call_authenticated(target: str, method: str) -> dict:
    last_err: Exception | None = None
    for force_refresh in (False, True):
        try:
            token = _get_token(target, force_refresh=force_refresh)
            return _run_grpcurl_plain(
                target,
                method,
                request_json="{}",
                auth_header=_auth_header_for_token(token),
            )
        except RuntimeError as err:
            msg = str(err).lower()
            last_err = err
            if (
                "unauthenticated" in msg
                or "missing or invalid authentication token" in msg
            ) and not force_refresh:
                _invalidate_token_cache()
                continue
            raise
    assert last_err is not None
    raise last_err


async def fetch_miner_status(host: str) -> dict:
    target = _normalize_grpc_target(host)
    summary: dict = {
        "ok": False,
        "host": target,
        "hashrate_th": None,
        "temp_avg": None,
        "power_w": None,
        "fan_rpm": None,
        "efficiency_j_th": None,
        "error": None,
        "model": None,
    }

    try:
        miner_response = await asyncio.to_thread(_call_authenticated, target, MINER_STATS_METHOD)
        cooling_response = await asyncio.to_thread(
            _call_authenticated, target, COOLING_STATE_METHOD
        )
    except Exception as err:  # noqa: BLE001
        summary["error"] = str(err)
        return summary

    miner_stats = miner_response.get("minerStats", {})
    if not isinstance(miner_stats, dict):
        miner_stats = {}
    power_stats = miner_response.get("powerStats", {})
    if not isinstance(power_stats, dict):
        power_stats = {}
    cooling_state = cooling_response if isinstance(cooling_response, dict) else {}

    ghps = (
        miner_stats.get("realHashrate", {})
        .get("last5m", {})
        .get("gigahashPerSecond")
    )
    ghps_value = _safe_float(ghps)
    if ghps_value is not None:
        summary["hashrate_th"] = ghps_value / 1000.0

    watt = power_stats.get("approximatedConsumption", {}).get("watt")
    summary["power_w"] = _safe_float(watt)

    temp = (
        cooling_state.get("highestTemperature", {})
        .get("temperature", {})
        .get("degreeC")
    )
    summary["temp_avg"] = _safe_float(temp)

    fans = cooling_state.get("fans", [])
    if isinstance(fans, list):
        rpm_values = [
            _safe_float(fan.get("rpm")) for fan in fans if isinstance(fan, dict)
        ]
        rpm_values = [rpm for rpm in rpm_values if rpm is not None]
        if rpm_values:
            summary["fan_rpm"] = sum(rpm_values) / len(rpm_values)

    efficiency = power_stats.get("efficiency", {}).get("joulePerTerahash")
    summary["efficiency_j_th"] = _safe_float(efficiency)

    model = miner_stats.get("minerInfo", {}).get("model")
    if isinstance(model, str):
        summary["model"] = model

    summary["ok"] = True
    return summary
