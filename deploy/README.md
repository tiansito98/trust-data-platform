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
| `scripts/notify_email.py` | Correo por Gmail SMTP: EXITO (con frescura de datos) o FALLA (con el error). |
| `scripts/alert_failure.sh` | Se dispara en falla (systemd `OnFailure`). Manda el correo de falla + webhook/Telegram si estan en `.env`; si no, a journald. |
| `deploy/trust-pipeline.service` | Unit oneshot que corre el wrapper como user `trust`. |
| `deploy/trust-pipeline.timer` | Dispara **1x/dia: 05:00 UTC (00:00 COT)**, tras el cierre core 04:30 UTC. |
| `deploy/trust-pipeline-alert@.service` | Unit de alerta que systemd invoca en `OnFailure`. |
| `scripts/freshness_canary.py` + `.github/workflows/freshness_canary.yml` | Red de seguridad **hosted**: si el pipeline no refresco hace >20h, el job falla y GitHub manda email. Atrapa "VM muerta". |

## Correo (exito + falla)

Un correo por resultado, sin duplicados:
- **EXITO** -> lo manda `run_pipeline.py` al final, con la frescura de datos
  (hasta que fecha llegaron rentas / cargos / reservas / TRM y el lag en dias).
- **FALLA** -> lo manda systemd `OnFailure` -> `alert_failure.sh` -> `notify_email.py`
  (asi tambien cubre un crash duro donde el pipeline no alcanza a avisar).

Requiere en el `.env` de la VM un **Gmail App Password** (NO la clave normal):

```
SMTP_USER=sebastiangonzalezarango98@gmail.com
SMTP_PASSWORD=xxxxxxxxxxxxxxxx        # App Password de 16 chars
ALERT_EMAIL_TO=sebastiangonzalezarango98@gmail.com
# SMTP_HOST/SMTP_PORT tienen default smtp.gmail.com:587
```

Como generar el App Password: cuenta de Google -> Seguridad -> Verificacion en 2
pasos (debe estar activa) -> Contrasenas de aplicaciones -> crear una nueva.
Si faltan `SMTP_USER`/`SMTP_PASSWORD`, el correo se omite en silencio (no rompe nada).

Probar el correo sin correr todo el pipeline:
```bash
sudo -u trust /home/trust/trust-data-platform/.venv/bin/python \
     /home/trust/trust-data-platform/scripts/notify_email.py --status success
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

Tres capas, independientes:

1. **Correo Gmail (principal):** exito + falla desde el pipeline (ver seccion
   "Correo" arriba). El de exito trae la frescura de datos; el de falla, el error.

2. **VM webhook/Telegram (opcional, extra):** para un ping adicional en el momento,
   agregar al `.env` de la VM `ALERT_WEBHOOK_URL=` (Slack/Discord) o
   `ALERT_TELEGRAM_TOKEN=` + `ALERT_TELEGRAM_CHAT=`. Sin esto, la falla igual sale
   por correo, `journalctl` y `last_failure.log`.

3. **Canary hosted (respaldo anti "VM muerta"):** el workflow de GitHub Actions
   corre 1x/dia (06:00 UTC) y **falla + manda email** si el pipeline no refresco en
   >20h. Cubre el caso que las capas 1 y 2 no pueden (VM apagada no manda nada).
   Requiere el secret de repo `SUPABASE_DB_URL` (ya existe) y Settings ->
   Notifications -> Actions ("Send notifications for failed workflows only").
