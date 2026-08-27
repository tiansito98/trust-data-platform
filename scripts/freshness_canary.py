#!/usr/bin/env python3
"""
freshness_canary.py - reporte diario del pipeline + canary, desde GitHub Actions.

Corre en el runner hosted de GitHub (que SI llega a Supabase y SI puede mandar
correo por SMTP; la VM DigitalOcean NO puede: DO bloquea los puertos SMTP).

Que hace:
  1. Lee bronze.ctrl_extraction_log -> cuanto hace que hubo una corrida OK.
  2. Lee la frescura de negocio en silver (hasta que fecha llego cada dominio).
  3. Manda un correo (si estan las credenciales SMTP):
       - FRESCO  -> "EXITOSO", con las fechas disponibles.
       - VIEJO   -> "ALERTA", el pipeline no refresco (VM muerta / timer no disparo).
  4. Sale 0 si fresco, 1 si viejo -> el workflow tambien queda en rojo y GitHub
     manda su propio email de "workflow failed" como respaldo.

Env:
  SUPABASE_DB_URL   (obligatorio)
  SMTP_USER         Gmail remitente (opcional; sin el, no manda correo, solo exit code)
  SMTP_PASSWORD     Gmail App Password
  ALERT_EMAIL_TO    destinatario (default = SMTP_USER)
  SMTP_HOST/PORT    default smtp.gmail.com:587
"""
import argparse
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

import psycopg2

COT = timezone(timedelta(hours=-5))

# Rentas/Cargos topan el MAX a hoy: hay entregas futuras (pre-reservas / leases
# largos) que si no, dan un lag negativo sin sentido.
FRESHNESS_PROBES = [
    ("Rentas (entrega)",
     "SELECT (MAX(fecha_handover_real) FILTER (WHERE fecha_handover_real <= CURRENT_DATE))::date, "
     "MIN(fecha_handover_real)::date, COUNT(*) FROM silver.vw_rentals_full"),
    ("Cargos (entrega)",
     "SELECT (MAX(fecha_handover_real) FILTER (WHERE fecha_handover_real <= CURRENT_DATE))::date, "
     "MIN(fecha_handover_real)::date, COUNT(*) FROM silver.vw_rentals_detail"),
    ("Reservas",
     "SELECT MAX(rsrv_date)::date, MIN(rsrv_date)::date, COUNT(*) "
     "FROM silver.vw_reservation_enriched"),
    ("TRM Banrep",
     "SELECT MAX(fecha)::date, MIN(fecha)::date, COUNT(*) FROM silver.dim_trm_diaria"),
]


def gather(conn):
    conn.autocommit = True
    out = {"last_run": None, "fresh": []}
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(run_datm) FROM bronze.ctrl_extraction_log "
                    "WHERE status IN ('OK','EMPTY')")
        out["last_run"] = cur.fetchone()[0]
        for label, sql in FRESHNESS_PROBES:
            try:
                cur.execute(sql)
                mx, mn, n = cur.fetchone()
                out["fresh"].append((label, mx, mn, n))
            except Exception as e:  # noqa: BLE001
                out["fresh"].append((label, None, None, f"err: {e}"))
    return out


def build_email(fresh_ok: bool, age_h, data, max_age_h):
    now = datetime.now(timezone.utc)
    now_cot = now.astimezone(COT)
    today = now.date()
    tag = "EXITOSO" if fresh_ok else "ALERTA"
    subject = f"[Trust Pipeline] {tag} - {now:%Y-%m-%d} (reporte diario)"

    L = []
    if fresh_ok:
        L.append("Pipeline de datos Trust: al dia.")
    else:
        L.append("ALERTA: el pipeline NO refresco a tiempo.")
    L.append("")
    lr = data["last_run"]
    lr_s = f"{lr:%Y-%m-%d %H:%M} UTC" if lr else "(nunca)"
    age_s = f"hace {age_h:.1f} h" if age_h is not None else "n/d"
    L.append(f"Reporte:          {now:%Y-%m-%d %H:%M} UTC  ({now_cot:%H:%M} COT)")
    L.append(f"Ultima corrida OK: {lr_s}  ({age_s})")

    if fresh_ok:
        L.append("")
        L.append("INFORMACION DISPONIBLE (datos ya sincronizados desde Alemania):")
        for label, mx, mn, n in data["fresh"]:
            if mx is None:
                L.append(f"  {label:<18} (no disponible)")
                continue
            lag = (today - mx).days
            n_s = f"{n:,}" if isinstance(n, int) else str(n)
            L.append(f"  {label:<18} hasta {mx}  (desde {mn}, {n_s} filas, lag {lag}d)")
        L.append("")
        L.append("Nota: el pipeline corre con ~1 dia de lag; la fecha 'hasta' es el")
        L.append("dato mas reciente que Sixt ya cerro (04:30 UTC) y nosotros bajamos.")
    else:
        L.append("")
        L.append(f"Supera el umbral de {max_age_h} h sin una corrida OK. Probables causas:")
        L.append("  - la VM (138.197.12.62) esta apagada o sin red,")
        L.append("  - el timer systemd no disparo, o")
        L.append("  - el pipeline fallo (revisar el correo de falla / journald).")
        L.append("")
        L.append("Diagnostico en la VM:")
        L.append("  systemctl list-timers trust-pipeline.timer")
        L.append("  journalctl -u trust-pipeline.service -n 80 --no-pager")
    return subject, "\n".join(L)


def send_email(subject, body):
    user = os.getenv("SMTP_USER")
    pwd = os.getenv("SMTP_PASSWORD")
    if not user or not pwd:
        print(">> SMTP no configurado (faltan SMTP_USER/SMTP_PASSWORD): no mando correo.")
        return
    to = os.getenv("ALERT_EMAIL_TO", user)
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, pwd)
            s.sendmail(user, [to], msg.as_string())
        print(f">> correo enviado a {to}")
    except Exception as e:  # noqa: BLE001
        print(f">> correo FALLO: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-hours", type=float, default=20.0)
    args = ap.parse_args()

    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        print("ERROR: falta SUPABASE_DB_URL.", file=sys.stderr)
        return 1
    try:
        conn = psycopg2.connect(url, connect_timeout=20)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: no pude conectar a Supabase: {e}", file=sys.stderr)
        return 1
    try:
        data = gather(conn)
    finally:
        conn.close()

    last = data["last_run"]
    if last is None:
        age_h = None
        fresh_ok = False
    else:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
        fresh_ok = age_h <= args.max_age_hours

    subject, body = build_email(fresh_ok, age_h, data, args.max_age_hours)
    print(subject)
    print(body)
    send_email(subject, body)

    return 0 if fresh_ok else 1


if __name__ == "__main__":
    sys.exit(main())
