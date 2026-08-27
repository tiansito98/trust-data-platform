# Despliegue del pipeline en la VM (DigitalOcean)

Corre `scripts/run_pipeline.py` de forma **desatendida** en la VM `trust-pipeline`
(IP fija `138.197.12.62`, whitelisteada por Sixt). Scheduler = **systemd timer**
(no un runner de GitHub: el repo es publico y un self-hosted runner seria un
riesgo de seguridad). Los push del usuario a `main` fluyen solos porque el
wrapper hace `git pull` antes de cada corrida.

## Piezas

| Archivo | Rol |
|---|---|
| `scripts/run_vm.sh` | Wrapper: `git pull` + `run_pipeline.py` + logs + copia `last_failure.log` si falla. |
| `scripts/notify_email.py` | Correo por Gmail SMTP. Usable **solo donde SMTP no este bloqueado** (tu maquina local, corridas manuales). En la VM NO, ver abajo. |
| `scripts/alert_failure.sh` | Se dispara en falla (systemd `OnFailure`). Manda webhook/Telegram (HTTPS, sirve en la VM) + journald. |
| `deploy/trust-pipeline.service` | Unit oneshot que corre el wrapper como user `trust`. |
| `deploy/trust-pipeline.timer` | Dispara **1x/dia: 05:00 UTC (00:00 COT)**, tras el cierre core 04:30 UTC. |
| `deploy/trust-pipeline-alert@.service` | Unit de alerta que systemd invoca en `OnFailure`. |
| `scripts/freshness_canary.py` + `.github/workflows/freshness_canary.yml` | **Reporte diario + canary**, hosted en GitHub. Manda el correo (EXITOSO con fechas / ALERTA si no refresco) y queda en rojo si esta viejo. |

## Correo (por que va desde GitHub y no desde la VM)

**DigitalOcean bloquea los puertos SMTP salientes (25/465/587)** en el droplet
(politica anti-spam). Probado: 587 da timeout, 465 y 25 tambien. Por eso **la VM
no puede mandar correo**. La solucion: el correo lo manda el **runner hosted de
GitHub** (su red si permite SMTP), reusando la misma Gmail App Password.

El workflow `reporte-diario` corre 1x/dia (06:00 UTC, 1h despues del pipeline):
lee `bronze.ctrl_extraction_log` + la frescura en silver y manda:
- **EXITOSO** -> con las fechas disponibles (hasta que dia llego cada dominio + lag).
- **ALERTA** -> si el pipeline no refresco en >20h (VM muerta / timer no disparo /
  pipeline fallo). Ademas el job queda en rojo -> GitHub manda su email de fallo.

**Secrets de repo que hay que cargar** (Settings -> Secrets and variables -> Actions):
- `SUPABASE_DB_URL` (ya existe)
- `SMTP_USER` = el Gmail remitente
- `SMTP_PASSWORD` = Gmail App Password de 16 chars (Google -> Seguridad -> Verif.
  en 2 pasos -> Contrasenas de aplicaciones)
- `ALERT_EMAIL_TO` (opcional; default = `SMTP_USER`)

Probar sin esperar al cron: pestaña **Actions -> reporte-diario -> Run workflow**.

`notify_email.py` (el modulo local) sirve para probar el correo desde tu maquina
o para que una corrida manual `python scripts/run_pipeline.py` local tambien avise:
```bash
python scripts/notify_email.py --status success   # local, red que si permite SMTP
```

## Instalacion (una sola vez, como root en la VM)

```bash
# 1. Traer el codigo mas reciente
sudo -u trust git -C /home/trust/trust-data-platform pull --ff-only origin main

# 2. Permisos de ejecucion a los scripts
chmod +x /home/trust/trust-data-platform/scripts/run_vm.sh \
         /home/trust/trust-data-platform/scripts/alert_failure.sh

# 3. Instalar las units de systemd
cp /home/trust/trust-data-platform/deploy/trust-pipeline.service \
   /home/trust/trust-data-platform/deploy/trust-pipeline.timer \
   /home/trust/trust-data-platform/deploy/trust-pipeline-alert@.service \
   /etc/systemd/system/
systemctl daemon-reload

# 4. Activar el timer (arranca en cada boot y dispara a la hora)
systemctl enable --now trust-pipeline.timer
```

## Operacion

```bash
# Correr YA (integracion / a mano):
systemctl start trust-pipeline.service

# Ver el proximo disparo:
systemctl list-timers trust-pipeline.timer

# Log de la ultima corrida (por systemd):
journalctl -u trust-pipeline.service -n 50 --no-pager

# Log detallado por-corrida:
tail -f /home/trust/trust-data-platform/logs/latest.log

# Motivo de la ultima falla:
cat /home/trust/trust-data-platform/logs/last_failure.log
```

## Alertas

Capas independientes:

1. **Correo Gmail desde GitHub (principal):** el `reporte-diario` (ver seccion
   "Correo" arriba) manda EXITOSO con las fechas, o ALERTA si el pipeline no
   refresco. Es tambien la deteccion de falla (llega ~1h despues del run).

2. **VM webhook/Telegram (opcional, ping inmediato):** como la VM no puede SMTP
   pero SI HTTPS, para un aviso al instante con el traceback agregar al `.env` de la
   VM `ALERT_WEBHOOK_URL=` (Slack/Discord) o `ALERT_TELEGRAM_TOKEN=` +
   `ALERT_TELEGRAM_CHAT=`. Sin esto, la falla queda en `journalctl` +
   `last_failure.log` y sale por el correo del reporte-diario.

3. **Email de "workflow failed" de GitHub (respaldo):** si el reporte-diario sale
   en rojo (pipeline viejo) o el workflow revienta, GitHub manda su propio email.
   Activar en Settings -> Notifications -> Actions ("failed workflows only").
