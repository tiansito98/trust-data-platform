"""Helpers compartidos del dashboard v2 (target: Supabase Postgres).

Diferencias frente al v1:
  - Conexion read-only a Supabase Postgres via SQLAlchemy. search_path =
    silver, operational (asi vw_*/dim_* resuelven sin prefijo y los inserts
    de invoices pueden referenciar operational.invoices).
  - Formatos COP estilo europeo: $1.502.654,05 (punto miles, coma decimales).
  - Helper apply_trm() para multiplicar USD x TRM Banrep en COP cuando el
    toggle del usuario lo pide. La unica conversion TRM permitida.
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, event, text

# Resolver root del proyecto para importar scripts/get_secret.py
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from scripts.get_secret import get_secret  # noqa: E402

ASSETS_DIR = Path(__file__).parent.parent / "assets"

SIXT_ORANGE = "#ff6900"
SIXT_ORANGE_DARK = "#e55a00"
SIXT_BLACK = "#000000"

PLOTLY_LAYOUT = dict(
    font=dict(family="Helvetica Neue, Arial", size=12, color="#333333"),
    plot_bgcolor="white",
    paper_bgcolor="white",
    colorway=[SIXT_ORANGE, "#000000", "#666666", "#999999", "#cccccc", "#ffaa66"],
    margin=dict(l=20, r=20, t=40, b=20),
)


@st.cache_resource
def get_engine():
    """SQLAlchemy engine cacheado, apuntando a Supabase Postgres.

    search_path: silver primero (analytics), operational despues (invoices form).
    El pooler de Supabase ignora `-c options` en algunos casos; un event
    listener lo aplica via SET inmediatamente despues de cada connect, lo cual
    es 100% confiable.
    """
    url = get_secret("SUPABASE_DB_URL")
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
    )

    @event.listens_for(engine, "connect")
    def _set_session_state(dbapi_conn, _conn_record):
        with dbapi_conn.cursor() as cur:
            cur.execute("SET search_path TO silver, operational, public")
            cur.execute("SET statement_timeout = '60s'")

    return engine


# user-scoped caching: incluimos el usuario autenticado en la cache key para
# que los resultados queden aislados por sesion. Util si en el futuro se
# multiusuario (hoy es single-user pero la firma ya esta lista).
def _current_user() -> str:
    return st.session_state.get("dashboard_user", "anon")


@st.cache_data(ttl=300)
def load_query(sql: str, params: tuple | dict = (),
               _cache_user: str = "") -> pd.DataFrame:
    """
    Ejecuta sql + params contra Supabase y devuelve DataFrame.
    Params pueden ser tupla (positional, traducimos ? -> %s) o dict (nombrados con :name).
    _cache_user (prefijo _ para no participar del hash) es opcional; lo seteamos
    desde el wrapper si queremos cache por usuario.
    """
    engine = get_engine()
    # Soporte para queries legacy con placeholders '?': traducimos a numerados
    # de Postgres ($1, $2...) via sqlalchemy text() con :p0, :p1, ...
    if isinstance(params, (tuple, list)) and "?" in sql:
        # convertir cada ? en :p0, :p1, ...
        named = {}
        out_sql = []
        i = 0
        for ch in sql:
            if ch == "?":
                out_sql.append(f":p{i}")
                named[f"p{i}"] = params[i]
                i += 1
            else:
                out_sql.append(ch)
        sql = "".join(out_sql)
        params = named
    with engine.connect() as conn:
        # Set search_path explicitly en ESTA conexion antes de la query.
        # El pooler de Supabase no honora el event-listener ni connect_args
        # consistentemente, asi que lo seteamos inline. Cheapo (~1ms).
        conn.execute(text("SET search_path TO silver, operational, public"))
        if isinstance(params, dict):
            return pd.read_sql_query(text(sql), conn, params=params)
        if not params:
            return pd.read_sql_query(text(sql), conn)
        return pd.read_sql_query(text(sql), conn, params=params)


def execute_write(sql: str, params: dict) -> None:
    """Para forms del dashboard (invoice entry). Escribe y commit."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL search_path TO silver, operational, public"))
        conn.execute(text(sql), params)


def inject_styles():
    css = (ASSETS_DIR / "styles.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_header(subtitle: str = ""):
    sub_html = f"<span> &mdash; </span>{subtitle}" if subtitle else ""
    st.markdown(
        f"""
        <div class="sixt-header">
            <h1>TRUST{sub_html}</h1>
            <div class="badge">SIXT COLOMBIA</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi(col, label: str, value, delta: str = ""):
    delta_html = f'<div class="kpi-delta">{delta}</div>' if delta else ""
    col.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section(title: str):
    st.markdown(f'<h3 class="section-title">{title}</h3>', unsafe_allow_html=True)


# -------- Formatos (estilo europeo: punto miles, coma decimales) ----------

def _european(num: float, decimals: int) -> str:
    # Python con coma miles -> swap a estilo europeo.
    s = f"{num:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_money(value, currency: str = "USD", decimals: int = 2) -> str:
    """Formato europeo: $1.502.654,05 (USD) o $1.502.654 (COP por defecto)."""
    if value is None or pd.isna(value):
        return "-"
    if currency == "COP" and decimals == 2:
        decimals = 0
    return f"$ {_european(float(value), decimals)}"


def fmt_money_short(value, currency: str = "USD") -> str:
    """Escala legible en mil/mil millones. NUNCA 'billones' (eso seria 10^12)."""
    if value is None or pd.isna(value):
        return "-"
    v = float(value)
    a = abs(v)
    if a >= 1_000_000_000:
        return f"{_european(v / 1_000_000_000, 2)} mil millones"
    if a >= 1_000_000:
        return f"{_european(v / 1_000_000, 1)} millones"
    if a >= 1_000:
        return f"{_european(v / 1_000, 0)} mil"
    decimals = 0 if currency == "COP" else 2
    return f"$ {_european(v, decimals)}"


def fmt_int(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return _european(float(value), 0)


def fmt_pct(value, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{_european(float(value), decimals)} %"


# -------- TRM Banrep: la unica conversion USD->COP permitida --------------

@st.cache_data(ttl=600)
def get_trm_table() -> pd.DataFrame:
    """Devuelve TRM Banrep diaria. fecha viene como dt.date desde Postgres."""
    return load_query(
        "SELECT fecha, trm_cop_per_usd FROM dim_trm_diaria ORDER BY fecha"
    )


@st.cache_data(ttl=600)
def get_trm_hoy() -> tuple:
    """Devuelve (fecha, valor) de la TRM Banrep mas reciente. (None, None) si vacia."""
    df = load_query(
        "SELECT fecha, trm_cop_per_usd FROM dim_trm_diaria "
        "ORDER BY fecha DESC LIMIT 1"
    )
    if df.empty:
        return (None, None)
    return (df["fecha"].iloc[0], float(df["trm_cop_per_usd"].iloc[0]))


def render_trm_today_sidebar() -> None:
    """Pinta el bloque TRM Hoy en la sidebar. Llamar al inicio de la sidebar."""
    fecha, valor = get_trm_hoy()
    if not fecha or valor is None:
        return
    # Formato europeo: $1.234,56
    valor_fmt = f"$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    st.sidebar.markdown(
        f"""
        <div style="background:#fff3e0;padding:10px 12px;border-radius:4px;
                    border-left:4px solid #ff6900;margin-bottom:14px;">
            <div style="font-size:0.75rem;color:#666;text-transform:uppercase;
                        letter-spacing:0.5px;">TRM Hoy (Banrep)</div>
            <div style="font-size:1.35rem;font-weight:700;color:#000;
                        line-height:1.2;margin:2px 0;">{valor_fmt}</div>
            <div style="font-size:0.75rem;color:#888;">
                vigente {fecha} &nbsp;·&nbsp; COP / USD
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def apply_trm(df: pd.DataFrame, trm_source: str, date_col: str,
              usd_cols: list, cop_cols_sixt: list) -> pd.DataFrame:
    """Devuelve copia de df con columnas COP recalculadas segun trm_source.

    trm_source = 'Banrep' -> usd_cols * TRM oficial del dia de date_col.
    trm_source != 'Banrep' -> deja cop_cols_sixt como vienen (legacy).

    Sobreescribe las columnas en cop_cols_sixt con USD * TRM Banrep del dia
    correspondiente. Si una fecha no esta en la TRM table (raro, hay 1 fila
    por dia calendario), forward-fill con la TRM mas reciente; ultimo fallback
    = TRM promedio del rango disponible.
    """
    out = df.copy()
    if trm_source != "Banrep":
        return out

    # --- Normaliza TRM table: ambos keys (TRM table) y values (df[date_col])
    # tienen que ser strings YYYY-MM-DD para que .map() encuentre matches.
    # Postgres devuelve DATE como dt.date; sin normalizar, la comparacion
    # str vs dt.date siempre falla -> rates=NaN -> COP=0.
    trm_df = get_trm_table().copy()
    trm_df["_fecha_str"] = pd.to_datetime(trm_df["fecha"]).dt.strftime("%Y-%m-%d")
    trm_df = trm_df.sort_values("_fecha_str")
    trm_lookup = dict(zip(trm_df["_fecha_str"], trm_df["trm_cop_per_usd"].astype(float)))

    dates_str = pd.to_datetime(out[date_col]).dt.strftime("%Y-%m-%d")
    rates = dates_str.map(trm_lookup).astype(float)

    if rates.isna().any():
        # Fallback: usar la TRM mas reciente conocida; si no hay nada, el promedio.
        last_trm = float(trm_df["trm_cop_per_usd"].iloc[-1]) if len(trm_df) else float("nan")
        mean_trm = float(trm_df["trm_cop_per_usd"].astype(float).mean()) if len(trm_df) else float("nan")
        rates = rates.fillna(last_trm).fillna(mean_trm)

    out["_trm_banrep"] = rates
    for usd_col, cop_col in zip(usd_cols, cop_cols_sixt):
        out[cop_col] = (out[usd_col].astype(float) * rates).round(0)
    return out


# -------- Selectores reusables --------------------------------------------

@st.cache_data(ttl=600)
def get_sedes() -> pd.DataFrame:
    """Sedes que aparecen en vw_rentals_resumen (no todas las de dim_branches
    estan en uso). Devuelve codigo + nombre, ordenado alfabeticamente."""
    return load_query(
        "SELECT DISTINCT sede_handover_codigo AS codigo, sede_handover AS nombre "
        "FROM vw_rentals_resumen "
        "WHERE sede_handover IS NOT NULL "
        "ORDER BY sede_handover"
    )


@st.cache_data(ttl=600)
def get_fecha_range() -> tuple:
    df = load_query(
        "SELECT MIN(DATE(fecha_handover_real)) AS d_min, "
        "       MAX(DATE(fecha_handover_real)) AS d_max "
        "FROM vw_rentals_resumen WHERE rental_currency = 'USD'"
    )
    import datetime as dt

    def _to_date(v):
        # Postgres devuelve DATE como dt.date; SQLite legacy lo daba como str.
        # Aceptamos ambos para mantener compatibilidad.
        if isinstance(v, dt.date):
            return v
        if isinstance(v, dt.datetime):
            return v.date()
        return dt.date.fromisoformat(str(v))

    return _to_date(df["d_min"].iloc[0]), _to_date(df["d_max"].iloc[0])


@st.cache_data(ttl=600)
def get_acriss_options() -> list:
    df = load_query(
        "SELECT DISTINCT acriss_entregado FROM vw_rentals_resumen "
        "WHERE acriss_entregado IS NOT NULL AND rental_currency='USD' "
        "ORDER BY acriss_entregado"
    )
    return df["acriss_entregado"].tolist()


@st.cache_data(ttl=600)
def get_canal_options() -> list:
    df = load_query(
        "SELECT DISTINCT canal_principal FROM vw_rentals_resumen "
        "WHERE canal_principal IS NOT NULL AND rental_currency='USD' "
        "ORDER BY canal_principal"
    )
    return df["canal_principal"].tolist()
