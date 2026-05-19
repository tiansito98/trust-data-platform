"""
Top-level orchestrator del pipeline. Lo invoca:
  - .github/workflows/refresh.yml (3x al dia)
  - scripts/refresh.bat (corrida manual local)

Flujo:
  1. Si SIXT_SSH_PRIVATE_KEY esta poblado (GitHub Actions), escribe la llave
     a archivo temporal y setea SIXT_SSH_KEY_PATH para que _common.py la use.
  2. Corre bronze incremental (o full si --full)
  3. Corre bronze external_trm
  4. Corre silver build
  5. Imprime resumen JSON al stdout (lo capturan los logs del runner).

Salida: exit code 0 si todo OK, !=0 si algun paso fallo.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def stage(name: str):
    """Decorator-style logger para cada paso."""
    print(f"\n{'=' * 70}\n  {name}\n{'=' * 70}", flush=True)


def materialize_ssh_key_if_needed() -> None:
    """
    Si SIXT_SSH_PRIVATE_KEY (contenido) esta poblado pero SIXT_SSH_KEY_PATH no,
    escribe la llave a un archivo temporal con permisos 600 y setea el path.
    Util en GitHub Actions donde no hay filesystem persistente.
    """
    if os.getenv("SIXT_SSH_KEY_PATH"):
        return
    key_content = os.getenv("SIXT_SSH_PRIVATE_KEY")
    if not key_content:
        return
    # Normaliza newlines (los secrets a veces vienen con \r\n o \\n literal).
    key_content = key_content.replace("\\n", "\n").replace("\r\n", "\n")
    if not key_content.endswith("\n"):
        key_content += "\n"

    fd, path = tempfile.mkstemp(prefix="sixt_ssh_", suffix=".pem")
    with os.fdopen(fd, "w") as f:
        f.write(key_content)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except Exception:
        pass  # Windows runners no aplican chmod tradicional
    os.environ["SIXT_SSH_KEY_PATH"] = path
    print(f">> SSH key materialized at {path}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="Full load bronze (en lugar de incremental). Lento.")
    parser.add_argument("--skip-trm", action="store_true",
                        help="No correr external_trm (debug).")
    parser.add_argument("--skip-silver", action="store_true",
                        help="No correr silver build (debug).")
    args = parser.parse_args()

    started_total = time.time()
    summary: dict = {"steps": []}

    try:
        materialize_ssh_key_if_needed()

        # 1. Bronze
        if args.full:
            stage("BRONZE FULL LOAD")
            from pipelines.bronze import full_load
            t = time.time()
            full_load.main()
            summary["steps"].append({"name": "bronze_full_load",
                                     "elapsed_sec": round(time.time() - t, 1)})
        else:
            stage("BRONZE INCREMENTAL")
            from pipelines.bronze import incremental
            t = time.time()
            incremental.main()
            summary["steps"].append({"name": "bronze_incremental",
                                     "elapsed_sec": round(time.time() - t, 1)})

        # 2. TRM externa
        if not args.skip_trm:
            stage("EXTERNAL TRM (Banrep via datos.gov.co)")
            from pipelines.bronze import external_trm
            t = time.time()
            external_trm.run(mode="incremental")
            summary["steps"].append({"name": "external_trm",
                                     "elapsed_sec": round(time.time() - t, 1)})

        # 3. Silver
        if not args.skip_silver:
            stage("SILVER BUILD")
            from pipelines.silver import build
            t = time.time()
            build.main()
            summary["steps"].append({"name": "silver_build",
                                     "elapsed_sec": round(time.time() - t, 1)})

        summary["status"] = "SUCCESS"
        summary["total_elapsed_sec"] = round(time.time() - started_total, 1)

    except Exception as e:
        summary["status"] = "FAILED"
        summary["error"] = str(e)
        summary["total_elapsed_sec"] = round(time.time() - started_total, 1)
        print(f"\nPIPELINE FAILED: {e}", flush=True)
        traceback.print_exc()
        print("\n=== SUMMARY ===")
        print(json.dumps(summary, indent=2), flush=True)
        sys.exit(1)

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
