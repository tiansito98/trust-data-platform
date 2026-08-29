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
# --skip-trm: la TRM la actualiza el workflow refresh-trm.yml en GitHub (23:00 UTC).
# El silver igual reconstruye dim_trm_diaria desde el bronze que dejo refresh-trm,
# asi que no perdemos TRM; solo evitamos el pull redundante a Banrep.
"$REPO/.venv/bin/python" scripts/run_pipeline.py --skip-trm >> "$LOG" 2>&1
rc=$?

ln -sf "$LOG" "$REPO/logs/latest.log"

if [ "$rc" -ne 0 ]; then
  echo "PIPELINE FALLO rc=$rc @ $(date -u '+%Y-%m-%d %H:%M:%S') UTC. Log: $LOG" >> "$LOG"
  cp "$LOG" "$REPO/logs/last_failure.log"
fi

# Disparar el reporte-diario en GitHub (lee Supabase y manda el correo). Se hace
# SIEMPRE (exito o falla) para que llegue el correo EXITOSO o ALERTA. El cron de
# GitHub es poco confiable, por eso la VM lo dispara por API (HTTPS, no bloqueado)
# justo despues de cada corrida -> timing controlado por la VM.
GH_TOKEN="$(grep -E '^GITHUB_DISPATCH_TOKEN=' "$REPO/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r')"
if [ -n "$GH_TOKEN" ]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 -X POST \
    -H "Authorization: Bearer $GH_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/tiansito98/trust-data-platform/actions/workflows/freshness_canary.yml/dispatches" \
    -d '{"ref":"main"}')
  echo "reporte-diario dispatch -> HTTP $code (204 = OK)" >> "$LOG"
else
  echo "reporte-diario dispatch: falta GITHUB_DISPATCH_TOKEN en .env, skip" >> "$LOG"
fi

# Registrar el resultado en Supabase (operational.pipeline_runs) para que el correo
# de ALERTA incluya el error sin que nadie tenga que hacer SSH a la VM.
"$REPO/.venv/bin/python" "$REPO/scripts/record_run.py" "$rc" >> "$LOG" 2>&1

# Retencion: dejar solo los ultimos 30 logs por-corrida.
ls -1t "$REPO"/logs/pipeline_*.log 2>/dev/null | tail -n +31 | xargs -r rm -f

exit "$rc"
