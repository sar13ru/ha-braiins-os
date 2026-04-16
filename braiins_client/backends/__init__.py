from .graphql_s9 import fetch_miner_status_s9
from .grpc import fetch_miner_status

__all__ = ["fetch_miner_status", "fetch_miner_status_s9"]
