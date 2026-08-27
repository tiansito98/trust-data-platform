#!/usr/bin/env bash
# =============================================================================
# alert_failure.sh - se dispara cuando el pipeline falla (systemd OnFailure).
# =============================================================================
# Manda el motivo de la falla (tail del ultimo log) por:
#
#   1. Gmail (canal principal) -> notify_email.py, si estan SMTP_* en .env.
#   2. ALERT_WEBHOOK_URL  -> POST JSON {"text": "..."} (Slack / Discord / generico)
#   3. ALERT_TELEGRAM_TOKEN + ALERT_TELEGRAM_CHAT  -> mensaje a Telegram
#
# Todo se lee de /home/trust/trust-data-platform/.env. Si no hay ningun canal,
# solo escribe a journald (visible con `journalctl -u trust-pipeline.service`).
# El canary hosted de GitHub Actions es la red de seguridad que igual avisa.
# =============================================================================
set -uo pipefail

REPO="/home/trust/trust-data-platform"
ENV_FILE="$REPO/.env"
LOGFILE="$REPO/logs/last_failure.log"

# Cargar solo las claves de alerta del .env (sin volcar todo el entorno).
get_env() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"''; }
WEBHOOK="$(get_env ALERT_WEBHOOK_URL)"
TG_TOKEN="$(get_env ALERT_TELEGRAM_TOKEN)"
TG_CHAT="$(get_env ALERT_TELEGRAM_CHAT)"

HOST="$(hostname)"
WHEN="$(date -u '+%Y-%m-%d %H:%M:%S') UTC"
TAIL="$(tail -n 25 "$LOGFILE" 2>/dev/null || echo '(sin log)')"
MSG="[TRUST PIPELINE] FALLO en ${HOST} @ ${WHEN}

Ultimas lineas del log:
${TAIL}"

echo "$MSG"   # -> journald

# 1. Correo por Gmail (lee el tail de last_failure.log adentro). No rompe si falla.
if [ -x "$REPO/.venv/bin/python" ]; then
  "$REPO/.venv/bin/python" "$REPO/scripts/notify_email.py" --status failure \
    && echo "correo de falla enviado" || echo "WARN: no se pudo mandar el correo de falla"
fi

if [ -n "$WEBHOOK" ]; then
  # jq no garantizado: escapar a mano lo minimo para JSON.
  ESC="$(printf '%s' "$MSG" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
  curl -s --max-time 20 -H 'Content-Type: application/json' \
       -d "{\"text\": ${ESC}, \"content\": ${ESC}}" "$WEBHOOK" >/dev/null \
    && echo "alerta enviada a webhook" || echo "WARN: fallo el POST al webhook"
fi

if [ -n "$TG_TOKEN" ] && [ -n "$TG_CHAT" ]; then
  curl -s --max-time 20 \
       --data-urlencode "chat_id=${TG_CHAT}" \
       --data-urlencode "text=${MSG}" \
       "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" >/dev/null \
    && echo "alerta enviada a Telegram" || echo "WARN: fallo el envio a Telegram"
fi

exit 0
