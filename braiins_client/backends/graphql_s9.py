from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

log = logging.getLogger(__name__)

# -------------------------------------------------------------------
# S9: estado vía GraphQL (/graphql)
# -------------------------------------------------------------------

async def fetch_miner_status_s9(
    host: str,
    *,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """
    Consulta el S9 vía GraphQL en /graphql, con login previo:

      1) mutation Login { auth { login(username, password) { __typename } } }
         - Login OK => __typename == "VoidResult"
         - Usa cookie de sesión (mantenida por httpx.AsyncClient).

      2) query MinerStatus {
           bosminer {
             info {
               summary {
                 realHashrate { mhs5S mhs1M mhsAv }
                 temperature { degreesC }
               }
             }
           }
         }

    Convierte mhsX (MH/s) a TH/s y promedia temperaturas en °C.
    """
    s9_gql_user = os.getenv("S9_GQL_USER", "root")
    s9_gql_password = os.getenv("S9_GQL_PASSWORD", "root")

    url = f"http://{host}/graphql"

    login_query = """
    mutation Login($u: String!, $p: String!) {
      auth {
        login(username: $u, password: $p) {
          __typename
        }
      }
    }
    """

    stats_query = """
    query MinerStatus {
      bosminer {
        info {
          summary {
            realHashrate {
              mhs5S
              mhs1M
              mhsAv
            }
            temperature {
              degreesC
            }
          }
        }
      }
    }
    """

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # 1) LOGIN (para obtener cookie de sesión)
            resp_login = await client.post(
                url,
                json={
                    "query": login_query,
                    "variables": {
                        "u": s9_gql_user,
                        "p": s9_gql_password,
                    },
                },
            )
            resp_login.raise_for_status()
            data_login = resp_login.json()

            if "errors" in data_login and data_login["errors"]:
                msg = f"GraphQL login error: {data_login['errors'][0].get('message')}"
                return {
                    "ok": False,
                    "error": msg,
                    "host": host,
                    "summary": {"hashrate_th": None, "temp_avg": None},
                    "raw": data_login,
                }

            try:
                typename = data_login["data"]["auth"]["login"]["__typename"]
            except Exception:
                return {
                    "ok": False,
                    "error": "Respuesta de login inesperada (falta data.auth.login.__typename).",
                    "host": host,
                    "summary": {"hashrate_th": None, "temp_avg": None},
                    "raw": data_login,
                }

            if typename != "VoidResult":
                msg = f"Login GraphQL fallido en S9 (tipo={typename})."
                return {
                    "ok": False,
                    "error": msg,
                    "host": host,
                    "summary": {"hashrate_th": None, "temp_avg": None},
                    "raw": data_login,
                }

            # 2) QUERY DE STATS (con la cookie de sesión que ya guarda httpx)
            resp_stats = await client.post(
                url,
                json={"query": stats_query},
            )
            resp_stats.raise_for_status()
            data_stats = resp_stats.json()

    except Exception as exc:  # noqa: BLE001
        msg = f"Error HTTP/GraphQL: {exc}"
        return {
            "ok": False,
            "error": msg,
            "host": host,
            "summary": {"hashrate_th": None, "temp_avg": None},
            "raw": None,
        }

    if "errors" in data_stats and data_stats["errors"]:
        msg = f"GraphQL stats error: {data_stats['errors'][0].get('message')}"
        return {
            "ok": False,
            "error": msg,
            "host": host,
            "summary": {"hashrate_th": None, "temp_avg": None},
            "raw": data_stats,
        }

    # Extraer summary
    try:
        summary = (
            data_stats["data"]["bosminer"]["info"]["summary"]
        )
    except Exception:
        msg = "Respuesta GraphQL inesperada (falta data.bosminer.info.summary)."
        return {
            "ok": False,
            "error": msg,
            "host": host,
            "summary": {"hashrate_th": None, "temp_avg": None},
            "raw": data_stats,
        }

    # ---- Hashrate en TH/s (a partir de mhsX = MH/s) ----
    h_th: Optional[float] = None
    try:
        rh = summary.get("realHashrate") or {}
        mhs_candidates = [
            rh.get("mhs5S"),
            rh.get("mhs1M"),
            rh.get("mhsAv"),
        ]
        for mhs in mhs_candidates:
            if mhs is not None:
                # mhsX = mega hashes por segundo -> TH/s = MH/s / 1e6
                h_th = float(mhs) / 1_000_000.0
                break
    except Exception:
        pass

    # ---- Temperatura promedio ----
    t_avg: Optional[float] = None
    try:
        temps_node = summary.get("temperature")
        temps: list[float] = []

        if isinstance(temps_node, list):
            for t in temps_node:
                if isinstance(t, dict) and "degreesC" in t:
                    try:
                        temps.append(float(t["degreesC"]))
                    except Exception:
                        continue
        elif isinstance(temps_node, dict) and "degreesC" in temps_node:
            temps.append(float(temps_node["degreesC"]))

        if temps:
            t_avg = sum(temps) / len(temps)
    except Exception:
        pass

    return {
        "ok": True,
        "error": None,
        "host": host,
        "summary": {"hashrate_th": h_th, "temp_avg": t_avg},
        "raw": data_stats,
    }
