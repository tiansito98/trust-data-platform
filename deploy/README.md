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
| `scripts/alert_failure.sh` | Se dispara en falla (systemd `OnFailure`). Manda el motivo por webhook/Telegram si estan en `.env`; si no, a journald. |
| `deploy/trust-pipeline.service` | Unit oneshot que corre el wrapper como user `trust`. |
| `deploy/trust-pipeline.timer` | Dispara 2x/dia: 11:00 y 01:00 UTC (06:00 y 20:00 COT). |
| `deploy/trust-pipeline-alert@.service` | Unit de alerta que systemd invoca en `OnFailure`. |
| `scripts/freshness_canary.py` + `.github/workflows/freshness_canary.yml` | Red de seguridad **hosted**: si el pipeline no refresco hace >20h, el job falla y GitHub manda email. Atrapa "VM muerta". |

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

Dos capas, independientes:

1. **VM (inmediata, opcional):** para recibir el error en el momento, agregar al
   `.env` de la VM **una** de estas:
   - `ALERT_WEBHOOK_URL=` (Slack/Discord/webhook generico), o
   - `ALERT_TELEGRAM_TOKEN=` + `ALERT_TELEGRAM_CHAT=`.

   Sin esto, la falla igual queda en `journalctl` y en `last_failure.log`.

2. **Hosted (siempre activa, sin setup):** el canary de GitHub Actions corre 2x/dia
   y **falla + manda email** si el pipeline no refresco. Requiere el secret de repo
   `SUPABASE_DB_URL` (ya existe) y tener activado Settings -> Notifications ->
   Actions ("Send notifications for failed workflows only").
