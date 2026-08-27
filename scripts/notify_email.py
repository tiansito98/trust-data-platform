#!/usr/bin/env python3
"""
notify_email.py - correo de estado del pipeline (exito o falla) por Gmail SMTP.

Lee la config SMTP del entorno (.env). Si faltan credenciales, NO hace nada y
retorna False (para no romper corridas de dev que no tienen correo configurado).

Env vars (en el .env de la VM y, si quieres probar local, en tu .env):
  SMTP_HOST       (default smtp.gmail.com)
  SMTP_PORT       (default 587, STARTTLS)
  SMTP_USER       remitente (tu Gmail)
  SMTP_PASSWORD   Gmail App Password de 16 chars (NO la clave normal de Gmail)
  ALERT_EMAIL_TO  destinatario (default = SMTP_USER)

Uso como libreria (lo llama run_pipeline.py en exito, alert_failure.sh en falla):
  from notify_email import send_pipeline_email
  send_pipeline_email(summary_dict)

Prueba directa desde la terminal:
  python scripts/notify_email.py --status success     # manda correo de exito real
  python scripts/notify_email.py --status failure      # correo de falla (lee last_failure.log)
"""
from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Cargar .env dondequiera que corramos (systemd, cron, terminal). Idempotente.
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass

COT = timezone(timedelta(hours=-5))  # Colombia, fijo (sin horario de verano)


def _smtp_config():
    user = os.getenv("SMTP_USER")
    pwd = os.getenv("SMTP_PASSWORD")
    if not user or not pwd:
        return None
    return {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": user,
        "password": pwd,
        "to": os.getenv("ALERT_EMAIL_TO", user),
    }


def _freshness_lines() -> list[str]:
    """Consulta liviana a Supabase: hasta que fecha llego cada dominio de datos."""
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from pipelines._common import get_engine
        from sqlalchemy import text
    except Exception as e:  # noqa: BLE001
        return [f"  (no pude importar get_engine: {e})"]

    # (etiqueta, SQL que devuelve max_date, min_date, count). Cada uno es defensivo:
    # si una columna cambia de nombre, se salta esa linea en vez de romper el correo.
    # Rentas/Cargos: topar el MAX a hoy. Hay contratos con entrega futura
    # (pre-reservas / leases largos) que si no, dan un lag negativo sin sentido.
    probes = [
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
         "SELECT MAX(fecha)::date, MIN(fecha)::date, COUNT(*) "
         "FROM silver.dim_trm_diaria"),
    ]
    today = datetime.now(timezone.utc).date()
    lines: list[str] = []
    try:
        eng = get_engine("silver,bronze")
        with eng.connect() as c:
            for label, sql in probes:
                try:
                    mx, mn, n = c.execute(text(sql)).fetchone()
                    if mx is None:
                        continue
                    lag = (today - mx).days
                    lines.append(
                        f"  {label:<18} hasta {mx}  (desde {mn}, {n:,} filas, lag {lag}d)")
                except Exception as e:  # noqa: BLE001
                    lines.append(f"  {label:<18} (no disponible: {e})")
            try:
                r = c.execute(text(
                    "SELECT MAX(run_datm) FROM bronze.ctrl_extraction_log "
                    "WHERE status IN ('OK','EMPTY')")).fetchone()
                if r and r[0]:
                    lines.append(f"  {'Ultima corrida OK':<18} {r[0]:%Y-%m-%d %H:%M} UTC")
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001
        lines.append(f"  (no pude consultar frescura: {e})")
    return lines or ["  (sin datos de frescura)"]


def _rentas_check_line() -> str | None:
    """Check clave: la ultima entrega real deberia ser ayer (lag<=1)."""
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from pipelines._common import get_engine
        from sqlalchemy import text
        eng = get_engine("silver,bronze")
        with eng.connect() as c:
            row = c.execute(text(
                "SELECT fecha_handover_real::date, COUNT(*) FROM silver.vw_rentals_full "
                "WHERE fecha_handover_real <= CURRENT_DATE "
                "GROUP BY 1 ORDER BY 1 DESC LIMIT 1")).fetchone()
        if not row or row[0] is None:
            return None
        dia, n = row
        lag = (datetime.now(timezone.utc).date() - dia).days
        cuando = {0: "hoy", 1: "ayer"}.get(lag, f"hace {lag} dias")
        estado = "SI" if lag <= 1 else f"REVISAR ({lag} dias de atraso)"
        return f"Rentas al dia: {estado}  ->  ultima entrega {dia} ({cuando}), {n} rentas ese dia."
    except Exception:
        return None


def _last_failure_tail(n: int = 25) -> str:
    p = REPO_ROOT / "logs" / "last_failure.log"
    try:
        return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except Exception:
        return "(sin last_failure.log)"


def build_email(summary: dict | None):
    summary = summary or {}
    status = summary.get("status", "SUCCESS")
    ok = status == "SUCCESS"
    now = datetime.now(timezone.utc)
    now_cot = now.astimezone(COT)
    subject = (f"[Trust Pipeline] {'EXITOSO' if ok else 'FALLO'} - "
               f"{now:%Y-%m-%d %H:%M} UTC")

    L: list[str] = []
    L.append("Pipeline de datos Trust: "
             + ("corrio correctamente." if ok else "FALLO."))
    if ok:
        chk = _rentas_check_line()
        if chk:
            L.append(chk)
    L.append("")
    L.append(f"Corrida: {now:%Y-%m-%d %H:%M} UTC  ({now_cot:%H:%M} COT)")

    steps = summary.get("steps") or []
    if steps:
        dur = ",  ".join(f"{s['name']} {s['elapsed_sec']}s" for s in steps)
        L.append(f"Pasos:   {dur}")
    if summary.get("total_elapsed_sec") is not None:
        L.append(f"Total:   {summary['total_elapsed_sec']}s")

    if ok:
        L.append("")
        L.append("INFORMACION DISPONIBLE (datos ya sincronizados desde Alemania):")
        L.extend(_freshness_lines())
        L.append("")
        L.append("Nota: el pipeline corre con ~1 dia de lag; la fecha 'hasta' de arriba")
        L.append("es el dato mas reciente que Sixt ya cerro y nosotros bajamos.")
    else:
        L.append("")
        L.append(f"ERROR: {summary.get('error', '(sin detalle)')}")
        L.append("")
        L.append("Ultimas lineas del log:")
        L.append(_last_failure_tail())
        L.append("")
        L.append("Diagnostico en la VM:")
        L.append("  journalctl -u trust-pipeline.service -n 80 --no-pager")
        L.append("  cat /home/trust/trust-data-platform/logs/last_failure.log")

    return subject, "\n".join(L)


def send_pipeline_email(summary: dict | None = None) -> bool:
    """Manda el correo. Nunca lanza excepcion (el pipeline no debe romperse por esto)."""
    cfg = _smtp_config()
    if not cfg:
        print(">> email: SMTP no configurado (faltan SMTP_USER/SMTP_PASSWORD), skip.",
              flush=True)
        return False
    try:
        subject, body = build_email(summary)
        msg = MIMEText(body, _charset="utf-8")
        msg["Subject"] = subject
        msg["From"] = cfg["user"]
        msg["To"] = cfg["to"]
        ctx = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as s:
            s.starttls(context=ctx)
            s.login(cfg["user"], cfg["password"])
            s.sendmail(cfg["user"], [cfg["to"]], msg.as_string())
        print(f">> email enviado a {cfg['to']}", flush=True)
        return True
    except Exception as e:  # noqa: BLE001
        print(f">> email FALLO (ignorado): {e}", flush=True)
        return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", choices=["success", "failure"], default="success")
    ap.add_argument("--error", default=None,
                    help="Detalle de error para --status failure (default: lee last_failure.log).")
    a = ap.parse_args()

    if a.status == "success":
        demo = {"status": "SUCCESS",
                "steps": [{"name": "prueba", "elapsed_sec": 0}],
                "total_elapsed_sec": 0}
    else:
        demo = {"status": "FAILED",
                "error": a.error or "(ver log)",
                "total_elapsed_sec": 0}
    ok = send_pipeline_email(demo)
    sys.exit(0 if ok else 1)
