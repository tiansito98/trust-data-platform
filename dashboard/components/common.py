"""Componentes y utilidades compartidas del dashboard.

Conexion SQLite read-only contra data/silver.db. read_only=True via URI mode evita
chocar con el rebuild de Silver cada 6h (PRAGMA journal_mode=WAL ya activo).
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
    """Abre silver.db en modo read-only via URI - corre en paralelo al refresh."""
    return sqlite3.connect(
        f"file:{SILVER_DB.as_posix()}?mode=ro",
        uri=True,
        check_same_thread=False,
    )


@st.cache_data(ttl=300)
def load_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = get_conn()
    return pd.read_sql_query(sql, conn, params=params)


def inject_styles():
    css = (ASSETS_DIR / "styles.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_header(subtitle: str = "Operacion Diaria"):
    st.markdown(
        f"""
        <div class="sixt-header">
            <h1>TRUST<span> · </span>{subtitle}</h1>
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


# ---- BSC helpers (semaforos para perspectiva Balanced Scorecard) ----

_BSC_STATUS_COLORS = {
    "green":  "#2e7d32",
    "yellow": "#f59e0b",
    "red":    "#d32f2f",
    "gray":   "#888888",
}


def kpi_bsc(col, label: str, value, status: str = "gray", target: str = ""):
    """KPI card con borde lateral coloreado segun semaforo BSC.

    status: 'green' | 'yellow' | 'red' | 'gray' (sin meta o sin data).
    target: texto debajo (ej. 'Meta: >= 95%').
    """
    border = _BSC_STATUS_COLORS.get(status, _BSC_STATUS_COLORS["gray"])
    target_html = f'<div class="kpi-delta">{target}</div>' if target else ""
    col.markdown(
        f"""
        <div class="kpi-card" style="border-left: 6px solid {border}; padding-left: 14px;">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div>
            {target_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def bsc_status(value, green: float, yellow: float, comparator: str = ">=") -> str:
    """Devuelve 'green'/'yellow'/'red'/'gray' segun rango sencillo.

    comparator '>=' (mas grande = mejor):
        value >= green  -> green
        value >= yellow -> yellow
        otherwise       -> red
    comparator '<=' (mas chico = mejor):
        value <= green  -> green
        value <= yellow -> yellow
        otherwise       -> red
    """
    if value is None or pd.isna(value):
        return "gray"
    v = float(value)
    if comparator == ">=":
        if v >= green:
            return "green"
        if v >= yellow:
            return "yellow"
        return "red"
    if v <= green:
        return "green"
    if v <= yellow:
        return "yellow"
    return "red"


def bsc_status_range(value, green_lo: float, green_hi: float,
                     yellow_lo: float, yellow_hi: float) -> str:
    """Para metricas con banda 'optima' (verde) y bandas alrededor (amarillo)
    fuera de la cual queda rojo. Util para utilizacion (80-88% verde,
    70-92% amarillo, fuera = rojo).
    """
    if value is None or pd.isna(value):
        return "gray"
    v = float(value)
    if green_lo <= v <= green_hi:
        return "green"
    if yellow_lo <= v <= yellow_hi:
        return "yellow"
    return "red"


def section(title: str):
    st.markdown(f'<h3 class="section-title">{title}</h3>', unsafe_allow_html=True)


_FILTERS_BANNER_CSS_INJECTED = "_filters_banner_css_injected"


def render_active_filters(brnc_name: str, fi=None, ff=None, extra: str = ""):
    """Banner persistente que muestra sede + rango activos, sticky al top.

    Usa st.container(key=...) (API nativa de Streamlit) que agrega una clase
    CSS .st-key-<key> al container. Inyecta el CSS sticky una sola vez por
    sesion via st.session_state flag.

    Args:
        brnc_name: nombre de la sede ('Todas las sedes' o nombre real).
        fi, ff: fechas inicio/fin del rango (date o str ISO). Opcional.
        extra: texto adicional. Opcional.
    """
    parts = [f"<strong>Sede:</strong> {brnc_name}"]
    if fi is not None and ff is not None:
        fi_s = fi.isoformat() if hasattr(fi, "isoformat") else str(fi)
        ff_s = ff.isoformat() if hasattr(ff, "isoformat") else str(ff)
        ndias = ""
        try:
            import datetime as _dt
            d1 = _dt.date.fromisoformat(fi_s) if isinstance(fi_s, str) else fi
            d2 = _dt.date.fromisoformat(ff_s) if isinstance(ff_s, str) else ff
            ndias = f" &nbsp;({(d2 - d1).days + 1} dias)"
        except Exception:
            pass
        parts.append(f"<strong>Rango:</strong> {fi_s} &rarr; {ff_s}{ndias}")
    if extra:
        parts.append(extra)
    html = " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(parts)

    # Inyectamos el CSS sticky apuntando a la clase .st-key-active_filters
    # que Streamlit agrega automaticamente cuando pasas key= a st.container.
    # Lo hacemos en cada render: barato y robusto a re-runs.
    st.markdown(
        f"""
        <style>
        .st-key-active_filters {{
            position: sticky;
            top: 3.5rem;
            z-index: 999;
            background: #fff3e0;
            border-left: 4px solid {SIXT_ORANGE};
            padding: 8px 14px;
            margin: 4px 0 16px 0;
            font-size: 0.95rem;
            color: #333;
            box-shadow: 0 2px 6px rgba(0,0,0,0.08);
            border-radius: 2px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="active_filters"):
        st.markdown(html, unsafe_allow_html=True)


def get_branches() -> pd.DataFrame:
    return load_query("SELECT brnc_code, brnc_name, brnc_city FROM dim_branches ORDER BY brnc_name")


def branch_filter(label="Sede", include_all=True, key="global_branch"):
    """Selectbox de sede. Por defecto usa la key global 'global_branch' para
    que la seleccion persista entre paginas via st.session_state.
    """
    branches = get_branches()
    options = ["Todas las sedes"] if include_all else []
    options += [f"{r['brnc_name']}" for _, r in branches.iterrows()]
    # Streamlit persiste el valor automaticamente cuando reusamos la misma key.
    sel = st.selectbox(label, options, key=key)
    if sel == "Todas las sedes":
        return None, "Todas las sedes"
    code = int(branches[branches["brnc_name"] == sel]["brnc_code"].iloc[0])
    return code, sel


def date_range_filter(default_days=30, key="global_dates"):
    """Rango de fechas. Persiste entre paginas via st.session_state cuando se
    usa la key default 'global_dates'. El maximo es hoy (clipped al maximo de
    dim_dates por si el calendario se queda corto).
    """
    import datetime as dt
    row = pd.read_sql_query(
        "SELECT MAX(full_date) AS d FROM dim_dates WHERE full_date <= DATE('now')",
        get_conn(),
    )
    today_str = row["d"].iloc[0] if len(row) and row["d"].iloc[0] else None
    today = dt.date.fromisoformat(today_str) if today_str else dt.date.today()
    default_value = (today - dt.timedelta(days=default_days), today)
    # Solo seteamos el default la primera vez; despues Streamlit usa session_state.
    if key not in st.session_state:
        st.session_state[key] = default_value
    return st.date_input("Rango de fechas", key=key)


def status_badge(status: str, mapping: dict) -> str:
    cls = mapping.get(status, "status-info")
    return f'<span class="{cls}">{status}</span>'


def fmt_cop(value) -> str:
    """Pesos colombianos con punto como separador de miles. Ej: $ 6.356.724.934"""
    if value is None or pd.isna(value):
        return "—"
    return f"$ {value:,.0f}".replace(",", ".")


def fmt_cop_short(value) -> str:
    """Pesos colombianos en escala legible. Ej: 6.357 millones, 854 mil, $ 1.230"""
    if value is None or pd.isna(value):
        return "—"
    v = float(value)
    if abs(v) >= 1_000_000:
        millones = v / 1_000_000
        return f"{millones:,.0f} millones".replace(",", ".")
    if abs(v) >= 1_000:
        miles = v / 1_000
        return f"{miles:,.0f} mil".replace(",", ".")
    return f"$ {v:,.0f}".replace(",", ".")


def fmt_int(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{int(value):,}".replace(",", ".")
