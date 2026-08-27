"""
Analitica (gold) - metricas acidas del periodo, solo trust_admin.

TODO prorrateado por dia efectivo 24h segun el rango de fechas del sidebar, y
comparado contra el mismo periodo del anio anterior (YoY). Lee la capa gold:

  - silver.gold_carro_dia  -> ocupacion (rentado vs flota), revenue/RPD por ciudad
  - silver.gold_cargo_dia  -> cargos por codigo prorrateados

Convencion: dia efectivo = bloque de 24h (CEIL duracion/24h), el conteo mas acido.
Vista REALIZADA: capada a hoy (no proyecta dias futuros de rentas abiertas).
Moneda: USD a valor normal; COP a la TRM Banrep del dia de ENTREGA (se fija ahi
para prorratear correctamente), segun el toggle del sidebar.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st

from components.common import (
    inject_styles, render_header, section, kpi, fmt_money, fmt_int,
    load_query, xlsx_download_button, PLOTLY_LAYOUT, SIXT_ORANGE,
)
from components.filters import render_sidebar_filters, render_active_filters_banner
from components.auth import require_auth, require_page, logout_button

st.set_page_config(page_title="TRUST - Analitica", layout="wide")
require_auth()
require_page("9_Analitica")   # solo admin (pages=["*"]); rol sede queda bloqueado
inject_styles()
logout_button()
render_header("Analitica del periodo (acida, prorrateada 24h)")

filtros = render_sidebar_filters(default_days=30)
render_active_filters_banner(filtros)
desde, hasta = filtros.fecha_desde, filtros.fecha_hasta
MON = filtros.moneda                       # "USD" o "COP"
SUF = "cop" if MON == "COP" else "usd"      # sufijo de columna en gold


def _minus_year(d: dt.date) -> dt.date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:      # 29-feb
        return d.replace(year=d.year - 1, day=28)


desde_prev, hasta_prev = _minus_year(desde), _minus_year(hasta)

st.caption(
    f"Periodo: **{desde} → {hasta}** vs mismo rango {desde.year - 1} "
    f"(**{desde_prev} → {hasta_prev}**). Dias en bloques de 24h. Moneda: **{MON}** "
    f"(COP a TRM Banrep del dia de entrega)."
)

# =============================================================================
# Ocupacion / revenue / RPD por ciudad (gold_carro_dia)
# =============================================================================
CARRO_SQL = """
    SELECT sede,
           COUNT(DISTINCT placa)  AS flota,
           SUM(rented_day)        AS rented_days,
           COUNT(*)               AS fleet_days,
           SUM(rev_usd) AS rev_usd, SUM(rev_cop) AS rev_cop,
           SUM(tar_usd) AS tar_usd, SUM(tar_cop) AS tar_cop,
           SUM(adi_usd) AS adi_usd, SUM(adi_cop) AS adi_cop
    FROM silver.gold_carro_dia
    WHERE fecha BETWEEN :desde AND :hasta
    GROUP BY sede
"""

_NUMCOLS = ("flota", "rented_days", "fleet_days",
            "rev_usd", "rev_cop", "tar_usd", "tar_cop", "adi_usd", "adi_cop")


def _carro(desde_, hasta_) -> pd.DataFrame:
    df = load_query(CARRO_SQL, {"desde": desde_.isoformat(), "hasta": hasta_.isoformat()})
    for c in _NUMCOLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["revenue"] = df[f"rev_{SUF}"]      # columna activa segun moneda
    return df


cur = _carro(desde, hasta)
prev = _carro(desde_prev, hasta_prev)


def _tot(df: pd.DataFrame) -> dict:
    fd = float(df["fleet_days"].sum())
    rd = float(df["rented_days"].sum())
    rev = float(df["revenue"].sum())
    return {
        "fleet_days": fd, "rented_days": rd, "revenue": rev,
        "util": (100.0 * rd / fd) if fd else 0.0,
        "rpd": (rev / rd) if rd else 0.0,
        "revpau": (rev / fd) if fd else 0.0,
    }


tc, tp = _tot(cur), _tot(prev)


def _delta_pct(now: float, before: float) -> str:
    if before == 0:
        return "s/base" if now == 0 else "nuevo"
    return f"{(now / before - 1) * 100:+.1f}% YoY"


# ---------- KPIs con YoY ----------
section("KPIs del periodo (vs año anterior)")
k1, k2, k3, k4 = st.columns(4)
kpi(k1, "Ocupacion acida", f"{tc['util']:.1f}%", _delta_pct(tc["util"], tp["util"]))
kpi(k2, f"Revenue del periodo ({MON})", fmt_money(tc["revenue"], MON),
    _delta_pct(tc["revenue"], tp["revenue"]))
kpi(k3, f"RPD ({MON})", fmt_money(tc["rpd"], MON), _delta_pct(tc["rpd"], tp["rpd"]))
kpi(k4, f"RevPAU ({MON})", fmt_money(tc["revpau"], MON),
    _delta_pct(tc["revpau"], tp["revpau"]))
st.caption(
    f"Dias rentados: **{fmt_int(tc['rented_days'])}** / flota-dias "
    f"**{fmt_int(tc['fleet_days'])}**. RevPAU = revenue / carro-dia = Ocupacion × RPD."
)

# =============================================================================
# Por ciudad
# =============================================================================
section("Por ciudad")


def _por_ciudad(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["util"] = (100.0 * d["rented_days"] / d["fleet_days"].replace(0, pd.NA)).astype(float)
    d["rpd"] = (d["revenue"] / d["rented_days"].replace(0, pd.NA)).astype(float)
    return d


cur_c = _por_ciudad(cur)
prev_rev = prev.set_index("sede")["revenue"].to_dict()
cur_c["rev_prev"] = cur_c["sede"].map(prev_rev).fillna(0.0)
cur_c["yoy_rev"] = cur_c.apply(
    lambda r: (r["revenue"] / r["rev_prev"] - 1) * 100 if r["rev_prev"] else float("nan"),
    axis=1,
)
cur_c = cur_c.sort_values("revenue", ascending=False)

view = cur_c.copy()
view["Flota"] = view["flota"].astype(int)
view["Util %"] = view["util"].map(lambda v: f"{v:.1f}%" if pd.notna(v) else "-")
view["Dias rentados"] = view["rented_days"].map(fmt_int)
view["Flota-dias"] = view["fleet_days"].map(fmt_int)
view["RPD"] = view["rpd"].map(lambda v: fmt_money(v, MON) if pd.notna(v) else "-")
view["Revenue"] = view["revenue"].map(lambda v: fmt_money(v, MON))
view["YoY revenue"] = view["yoy_rev"].map(lambda v: f"{v:+.1f}%" if pd.notna(v) else "nuevo")
st.dataframe(
    view[["sede", "Flota", "Util %", "Dias rentados", "Flota-dias", "RPD", "Revenue", "YoY revenue"]]
    .rename(columns={"sede": "Ciudad"}),
    use_container_width=True, hide_index=True,
)

# grafico ocupacion por ciudad
_fig = px.bar(
    cur_c, x="sede", y="util",
    text=cur_c["util"].map(lambda v: f"{v:.0f}%" if pd.notna(v) else ""),
    labels={"sede": "", "util": "Ocupacion %"},
)
_fig.update_traces(marker_color=SIXT_ORANGE, textposition="outside")
_fig.update_layout(**PLOTLY_LAYOUT, showlegend=False)
st.plotly_chart(_fig, use_container_width=True)

# =============================================================================
# Desglose de cargos por codigo (gold_cargo_dia), prorrateado, con YoY
# =============================================================================
section("Desglose de cargos (prorrateado) vs año anterior")

CARGO_SQL = """
    SELECT cargo_codigo, SUM(subtotal_usd) AS val_usd, SUM(subtotal_cop) AS val_cop
    FROM silver.gold_cargo_dia
    WHERE fecha BETWEEN :desde AND :hasta
    GROUP BY cargo_codigo
"""

COBERTURAS = {"BF", "LD", "SL"}
VENTAS = {"T"}
TAX = {"Y"}


def _bucket(code: str) -> str:
    if code in VENTAS:
        return "VENTAS (tarifa)"
    if code in COBERTURAS:
        return "COBERTURAS"
    if code in TAX:
        return "TAX (surcharge aeropuerto)"
    return "ADICIONALES"


def _cargos(desde_, hasta_) -> pd.DataFrame:
    df = load_query(CARGO_SQL, {"desde": desde_.isoformat(), "hasta": hasta_.isoformat()})
    df["val"] = pd.to_numeric(df[f"val_{SUF}"], errors="coerce").fillna(0.0)
    df["bucket"] = df["cargo_codigo"].map(_bucket)
    return df


cc, cp = _cargos(desde, hasta), _cargos(desde_prev, hasta_prev)

# --- por bucket ---
b_cur = cc.groupby("bucket")["val"].sum()
b_prev = cp.groupby("bucket")["val"].sum()
brows = []
for b in ["VENTAS (tarifa)", "COBERTURAS", "ADICIONALES", "TAX (surcharge aeropuerto)"]:
    v, vp = float(b_cur.get(b, 0.0)), float(b_prev.get(b, 0.0))
    brows.append({
        "Bucket": b,
        f"Periodo ({MON})": fmt_money(v, MON),
        f"Año anterior ({MON})": fmt_money(vp, MON),
        "YoY": f"{(v / vp - 1) * 100:+.1f}%" if vp else "nuevo",
    })
st.markdown("**Por bucket (COBRA):**")
st.dataframe(pd.DataFrame(brows), use_container_width=True, hide_index=True)

# --- por codigo ---
code_cur = cc.groupby("cargo_codigo")["val"].sum()
code_prev = cp.groupby("cargo_codigo")["val"].sum()
codes = sorted(set(code_cur.index) | set(code_prev.index),
               key=lambda k: float(code_cur.get(k, 0.0)), reverse=True)
crows = []
for k in codes:
    v, vp = float(code_cur.get(k, 0.0)), float(code_prev.get(k, 0.0))
    if v == 0 and vp == 0:
        continue
    crows.append({
        "Codigo": k, "Bucket": _bucket(k),
        f"Periodo ({MON})": fmt_money(v, MON),
        f"Año anterior ({MON})": fmt_money(vp, MON),
        "YoY": f"{(v / vp - 1) * 100:+.1f}%" if vp else "nuevo",
    })
st.markdown("**Por codigo:**")
st.dataframe(pd.DataFrame(crows), use_container_width=True, hide_index=True)

xlsx_download_button(
    cur_c[["sede", "flota", "util", "rented_days", "fleet_days", "rpd", "revenue", "yoy_rev"]],
    file_name=f"analitica_ciudad_{desde}_{hasta}_{MON}",
    sheet_name="Por ciudad",
    key="xlsx_analitica_ciudad",
)
