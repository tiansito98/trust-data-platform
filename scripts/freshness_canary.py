#!/usr/bin/env python3
"""
freshness_canary.py - verifica que el pipeline haya corrido recientemente.

Corre en GitHub Actions (runner hosted, que SI llega a Supabase aunque no a Sixt).
No depende de la VM: consulta bronze.ctrl_extraction_log y mide cuanto hace que
hubo una corrida exitosa. Si excede el umbral, sale con codigo 1 -> el workflow
falla -> GitHub manda email automatico. Asi se atrapa el caso silencioso de "la
VM murio / el timer no disparo y nadie se entero".

Uso:
    SUPABASE_DB_URL=... python scripts/freshness_canary.py [--max-age-hours 20]

Sale 0 si fresco, 1 si viejo o si no puede conectar.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import psycopg2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-hours", type=float, default=20.0,
                    help="Edad maxima aceptable de la ultima corrida OK (horas).")
    args = ap.parse_args()

    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        print("ERROR: falta SUPABASE_DB_URL en el entorno.", file=sys.stderr)
        return 1

    try:
        conn = psycopg2.connect(url, connect_timeout=20)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: no pude conectar a Supabase: {e}", file=sys.stderr)
        return 1

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(run_datm)
                FROM bronze.ctrl_extraction_log
                WHERE status IN ('OK', 'EMPTY')
                """
            )
            row = cur.fetchone()
    finally:
        conn.close()

    last = row[0] if row else None
    if last is None:
        print("CANARY FAIL: no hay ninguna corrida OK en ctrl_extraction_log.")
        return 1

    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0

    print(f"ultima corrida OK: {last.isoformat()}  (hace {age_h:.1f} h)")
    if age_h > args.max_age_hours:
        print(f"CANARY FAIL: excede el umbral de {args.max_age_hours} h. "
              f"El pipeline no corrio o fallo. Revisar la VM "
              f"(journalctl -u trust-pipeline.service).")
        return 1

    print(f"CANARY OK: dentro del umbral de {args.max_age_hours} h.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
