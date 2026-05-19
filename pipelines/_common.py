"""
Trust Data Platform - utilidades compartidas (target: Supabase Postgres).

Centraliza:
- Carga de credenciales via scripts/get_secret.py (Streamlit secrets / env / .env)
- Apertura del SSH tunnel hacia el bastion de Sixt
- Conexion redshift-connector contra el cluster (a traves del tunel)
- Conexion SQLAlchemy/psycopg2 a Supabase Postgres (bronze + silver + operational)
- Carga de la config YAML de tablas

Toda la logica de conexion vive AQUI. Los pipelines la importan.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Para que `from scripts.get_secret import get_secret` resuelva.
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import redshift_connector
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sshtunnel import SSHTunnelForwarder

from scripts.get_secret import get_secret  # noqa: E402


# -------- Paths del proyecto --------
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"

DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)


# -------- Validacion temprana de variables criticas --------
# Las creds Redshift solo se necesitan para los pipelines bronze (no para silver
# build o dashboard). Validamos solo lo minimo aqui (Supabase) y dejamos que
# open_redshift() valide cuando se invoque.
def _ensure_pg() -> str:
    url = get_secret("SUPABASE_DB_URL", default=None)
    if not url:
        raise ValueError(
            "SUPABASE_DB_URL no esta configurado. "
            "Ponlo en .env o como GitHub secret."
        )
    return url


# ============================================================
# Conexion a Redshift via SSH tunnel (source)
# ============================================================

@contextmanager
def open_redshift() -> Iterator[redshift_connector.Connection]:
    """
    Abre SSH tunnel hacia bastion de Sixt + conexion Redshift.
    Cierra ambos al salir del 'with'.
    """
    ssh_host = get_secret("SIXT_SSH_HOST")
    ssh_port = int(get_secret("SIXT_SSH_PORT", default=22))
    ssh_user = get_secret("SIXT_SSH_USER")
    ssh_key_path = get_secret("SIXT_SSH_KEY_PATH")
    redshift_host = get_secret("SIXT_REDSHIFT_HOST")
    redshift_port = int(get_secret("SIXT_REDSHIFT_PORT", default=5439))
    redshift_db = get_secret("SIXT_REDSHIFT_DB")
    redshift_user = get_secret("SIXT_REDSHIFT_USER")
    redshift_password = get_secret("SIXT_REDSHIFT_PASSWORD")
    local_port = int(get_secret("LOCAL_PORT", default=8990))
    passphrase = get_secret("SIXT_SSH_KEY_PASSPHRASE", default="") or None

    ssh_kwargs = dict(
        ssh_address_or_host=(ssh_host, ssh_port),
        ssh_username=ssh_user,
        ssh_pkey=ssh_key_path,
        remote_bind_address=(redshift_host, redshift_port),
        local_bind_address=("127.0.0.1", local_port),
        set_keepalive=30.0,
    )
    if passphrase:
        ssh_kwargs["ssh_private_key_password"] = passphrase

    tunnel = SSHTunnelForwarder(**ssh_kwargs)
    tunnel.start()
    try:
        conn = redshift_connector.connect(
            host="127.0.0.1",
            port=tunnel.local_bind_port,
            database=redshift_db,
            user=redshift_user,
            password=redshift_password,
            sslmode="require",
        )
        try:
            yield conn
        finally:
            conn.close()
    finally:
        tunnel.stop()


def query_redshift(conn, sql: str, params=None) -> pd.DataFrame:
    """Ejecuta SQL contra una conexion abierta y retorna DataFrame."""
    return pd.read_sql(sql, conn, params=params)


# ============================================================
# Supabase Postgres (target: bronze + silver + operational)
# ============================================================

_engine_cache: dict[str, Engine] = {}


def get_engine(schema: str | None = None) -> Engine:
    """
    Devuelve un SQLAlchemy Engine apuntando a Supabase. Si `schema` se pasa,
    setea search_path apropiado para que las queries que mencionan tablas
    sin schema resuelvan al schema correcto.

    Cacheado por schema para reusar pool de conexiones.

    Schemas tipicos:
      - "bronze": pipelines bronze
      - "silver,bronze": silver build (lee bronze, escribe silver)
      - "silver": dashboard (solo lectura silver + operational)
      - None: search_path por defecto del role (silver, bronze, operational, public)
    """
    key = schema or "__default__"
    if key in _engine_cache:
        return _engine_cache[key]

    url = _ensure_pg()

    # Supabase aplica statement_timeout=2min por defecto al role postgres; el
    # build de silver tiene queries (vw_rentals_detail, vw_kpi_*) que tardan
    # mas. Subimos a 15 min para esta conexion. Tambien seteamos search_path.
    options = ["-cstatement_timeout=900000"]  # 15 min en ms
    if schema:
        options.append(f"-csearch_path={schema},operational,public")
    connect_args = {"options": " ".join(options)}

    engine = create_engine(
        url,
        pool_pre_ping=True,        # detecta conexiones dead antes de usarlas
        pool_recycle=300,          # recicla cada 5 min (evita timeouts del pooler)
        connect_args=connect_args,
    )
    _engine_cache[key] = engine
    return engine


@contextmanager
def open_pg(schema: str | None = None) -> Iterator:
    """
    Devuelve una conexion psycopg2 raw (compatible con cursor.execute(...) etc.)
    Util cuando el codigo legacy llama .execute() / .executemany() / .fetchone()
    como si fuera sqlite3.

    Uso:
        with open_pg("bronze") as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
    """
    engine = get_engine(schema)
    raw = engine.raw_connection()
    try:
        yield raw
    finally:
        raw.close()


# ============================================================
# Configuracion YAML
# ============================================================

def load_tables_config() -> list[dict]:
    """Lee config/tables.yml y retorna la lista de tablas a procesar."""
    path = CONFIG_DIR / "tables.yml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["tables"]


# ============================================================
# Helpers
# ============================================================

def mandant_code() -> int:
    return int(get_secret("TRUST_MNDT_CODE", default=409))


def page_size() -> int:
    return int(get_secret("BRONZE_PAGE_SIZE", default=50_000))


def initial_lookback_days() -> int:
    return int(get_secret("BRONZE_INITIAL_LOOKBACK_DAYS", default=365))


def log_path(prefix: str) -> Path:
    """Genera path de log con timestamp."""
    from datetime import datetime
    return LOG_DIR / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
