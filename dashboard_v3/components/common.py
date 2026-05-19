"""Componentes compartidos para dashboard_v3 (Vision Historica).

Conexion read-only contra data/silver.db. Copiado y adaptado de
dashboard/components/common.py para que el v3 pueda evolucionar sin
romper el v1.
"""
import sqlite3
from pathlib import Path
import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).parent.parent.parent / "data"
SILVER_DB = DATA_DIR / "silver.db"
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
def get_conn():
    return sqlite3.connect(
        f"file:{SILVER_DB.as_posix()}?mode=ro",
        uri=True,
        check_same_thread=False,
    )


@st.cache_data(ttl=300)
def load_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, get_conn(), params=params)


def inject_styles():
    css_path = ASSETS_DIR / "styles.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def render_header(subtitle: str = "Vision Historica"):
    st.markdown(
        f"""
        <div class="sixt-header">
            <h1>TRUST<span> &middot; </span>{subtitle}</h1>
            <div class="badge">Sixt Colombia &middot; Mandant 409 &middot; Dashboard v3</div>
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


# ------------------ formato ------------------

def fmt_usd(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    v = float(value)
    if abs(v) >= 1_000_000:
        return f"USD {v/1_000_000:,.2f}M".replace(",", ".")
    if abs(v) >= 1_000:
        return f"USD {v/1_000:,.1f}K".replace(",", ".")
    return f"USD {v:,.0f}".replace(",", ".")


def fmt_int(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{int(value):,}".replace(",", ".")


def fmt_pct(value, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{decimals}f}%"


# ------------------ filtros ------------------

@st.cache_data(ttl=3600)
def get_year_range() -> tuple[int, int]:
    """Min/max anios con data de rentals."""
    df = load_query("SELECT MIN(anio) AS lo, MAX(anio) AS hi FROM vw_kpi_anual")
    if df.empty:
        return 2021, 2026
    return int(df["lo"].iloc[0]), int(df["hi"].iloc[0])


def year_filter(label: str = "Rango de anios", key: str = "v3_year_range"):
    lo, hi = get_year_range()
    if key not in st.session_state:
        st.session_state[key] = (lo, hi)
    return st.slider(label, min_value=lo, max_value=hi, key=key)
