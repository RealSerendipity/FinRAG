"""Dev-only: keep the Neon free-tier compute warm during long eval runs.

Neon scale-to-zero suspends idle compute, turning each subsequent query into a
multi-minute cold start and making sequential eval runs unusable. Pinging every
~20s keeps the compute awake. Not part of the product — purely an eval-runtime aid.

Usage: uv run python experiments/_keepalive.py   (run in background during evals)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import config  # noqa: E402


def main() -> None:
    url = config.database_url()
    conn = None
    while True:
        try:
            if conn is None or conn.closed:
                conn = psycopg.connect(
                    url, connect_timeout=20, autocommit=True,
                    keepalives=1, keepalives_idle=10, keepalives_interval=5, keepalives_count=3,
                )
            conn.execute("SELECT 1")
            print(f"{time.strftime('%H:%M:%S')} ping ok", flush=True)
        except Exception as exc:  # noqa: BLE001 — dev aid, log and retry forever
            print(f"{time.strftime('%H:%M:%S')} ERR {type(exc).__name__}", flush=True)
            conn = None
        time.sleep(20)


if __name__ == "__main__":
    main()
