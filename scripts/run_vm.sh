#!/usr/bin/env bash
# =============================================================================
# run_vm.sh - wrapper que corre el pipeline en la VM (DigitalOcean).
# =============================================================================
# Lo dispara systemd (trust-pipeline.service / .timer). Hace:
#   1. git pull --ff-only  (los push del usuario a main fluyen solos)
#   2. corre scripts/run_pipeline.py con el venv
#   3. deja log por-corrida en logs/ + logs/latest.log
#   4. si falla, copia el log a logs/last_failure.log y sale con rc != 0
#      -> systemd dispara OnFailure=trust-pipeline-alert@.service
#
# git pull que falla NO es fatal (corre con el codigo actual y avisa en el log);
# el pipeline que falla SI es fatal (para que salte la alerta).
# =============================================================================
set -uo pipefail

REPO="/home/trust/trust-data-platform"
cd "$REPO" || { echo "FATAL: no pude cd a $REPO" >&2; exit 1; }

mkdir -p "$REPO/logs"
TS="$(date -u +%Y%m%d_%H%M%S)"
LOG="$REPO/logs/pipeline_${TS}.log"

{
  echo "======================================================================"
  echo "  run_vm.sh @ $(date -u '+%Y-%m-%d %H:%M:%S') UTC"
  echo "======================================================================"
  echo "--- git pull --ff-only origin main ---"
  if git pull --ff-only origin main; then
    echo "git en: $(git log --oneline -1)"
  else
    echo "WARN: git pull fallo (arbol sucio o red); corriendo con el codigo actual."
  fi
  echo "--- pipeline ---"
} >> "$LOG" 2>&1

# El pipeline es lo que decide el exit code (la alerta depende de esto).
"$REPO/.venv/bin/python" scripts/run_pipeline.py >> "$LOG" 2>&1
rc=$?

ln -sf "$LOG" "$REPO/logs/latest.log"

if [ "$rc" -ne 0 ]; then
  echo "PIPELINE FALLO rc=$rc @ $(date -u '+%Y-%m-%d %H:%M:%S') UTC. Log: $LOG" >> "$LOG"
  cp "$LOG" "$REPO/logs/last_failure.log"
fi

# Retencion: dejar solo los ultimos 30 logs por-corrida.
ls -1t "$REPO"/logs/pipeline_*.log 2>/dev/null | tail -n +31 | xargs -r rm -f

exit "$rc"
