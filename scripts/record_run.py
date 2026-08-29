#!/usr/bin/env python3
"""
record_run.py - registra el resultado de la corrida del pipeline en Supabase
(operational.pipeline_runs), para que el correo (freshness_canary / reporte-diario)
pueda incluir el ERROR sin que nadie tenga que hacer SSH a la VM.

Lo llama scripts/run_vm.sh al final de cada corrida:  record_run.py <rc>
- rc == 0  -> status SUCCESS
- rc != 0  -> status FAILED, con el tail de logs/last_failure.log

Nunca rompe la corrida (todo en try/except).
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import psycopg2

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")


def main() -> int:
    rc = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    status = "SUCCESS" if rc == 0 else "FAILED"
    tail = None
    if rc != 0:
        try:
            p = REPO / "logs" / "last_failure.log"
            tail = "\n".join(
                p.read_text(encoding="utf-8", errors="replace").splitlines()[-45:])
        except Exception:
            tail = "(no se pudo leer last_failure.log)"

    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        print(">> record_run: falta SUPABASE_DB_URL, skip.")
        return 0
    try:
        conn = psycopg2.connect(url, connect_timeout=15)
        conn.autocommit = True
        with conn.cursor() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS operational.pipeline_runs (
                    id        BIGSERIAL PRIMARY KEY,
                    run_datm  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    status    TEXT NOT NULL,
                    rc        INT,
                    log_tail  TEXT
                )""")
            c.execute(
                "INSERT INTO operational.pipeline_runs (status, rc, log_tail) "
                "VALUES (%s, %s, %s)", (status, rc, tail))
            # retencion: dejar solo las ultimas 200 corridas
            c.execute("""
                DELETE FROM operational.pipeline_runs WHERE id < (
                    SELECT MIN(id) FROM (
                        SELECT id FROM operational.pipeline_runs ORDER BY id DESC LIMIT 200
                    ) t)""")
        conn.close()
        print(f">> run registrado en Supabase: {status} (rc={rc})")
    except Exception as e:  # noqa: BLE001
        print(f">> record_run fallo (ignorado): {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
