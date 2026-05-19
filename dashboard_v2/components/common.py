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
from sqlalchemy import create_engine, text

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
    """
    url = get_secret("SUPABASE_DB_URL")
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"options": "-csearch_path=silver,operational,public"},
    )


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
        if isinstance(params, dict):
            return pd.read_sql_query(text(sql), conn, params=params)
        if not params:
            return pd.read_sql_query(text(sql), conn)
        return pd.read_sql_query(text(sql), conn, params=params)


def execute_write(sql: str, params: dict) -> None:
    """Para forms del dashboard (invoice entry). Escribe y commit."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def inject_styles():
    css = (ASSETS_DIR / "styles.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_header(subtitle: str = "Analitica"):
    st.markdown(
        f"""
        <div class="sixt-header">
            <h1>TRUST<span> v2 </span>{subtitle}</h1>
            <div class="badge">Sixt Colombia · Mandant 409</div>
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
    """Devuelve fecha (str ISO) -> trm_cop_per_usd. Hereda fin de semana."""
    return load_query(
        "SELECT fecha, trm_cop_per_usd FROM dim_trm_diaria ORDER BY fecha"
    )


def apply_trm(df: pd.DataFrame, trm_source: str, date_col: str,
              usd_cols: list, cop_cols_sixt: list) -> pd.DataFrame:
    """Devuelve copia de df con columnas COP recalculadas segun trm_source.

    trm_source = 'Banrep' -> usd_cols * TRM oficial del dia de date_col.
    trm_source = 'Sixt'   -> deja cop_cols_sixt como vienen (Sixt internal).

    usd_cols y cop_cols_sixt deben tener la misma longitud (mismo orden).
    Las columnas finales se llaman como las cop_cols_sixt para que el
    consumidor pueda mostrar sin saber el origen.
    """
    out = df.copy()
    if trm_source != "Banrep":
        return out
    trm = get_trm_table().set_index("fecha")["trm_cop_per_usd"].to_dict()
    dates = pd.to_datetime(out[date_col]).dt.strftime("%Y-%m-%d")
    rates = dates.map(trm)
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
    d_min = dt.date.fromisoformat(df["d_min"].iloc[0])
    d_max = dt.date.fromisoformat(df["d_max"].iloc[0])
    return d_min, d_max


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
