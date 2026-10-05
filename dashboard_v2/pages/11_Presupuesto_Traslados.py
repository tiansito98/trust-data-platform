"""
Presupuesto con traslados (SOLO tarifa, codigo T) — solo trust_admin.

Mismo modelo y mismas tasas que 10_Presupuesto, pero la flota se cuenta en
CARRO-DIAS reales por ciudad en vez de "flota de la foto x dias del mes":

    presupuesto = SUM sobre cada dia del mes de (carros en la ciudad ese dia)
                  x ocupacion x RPD_tarifa      (por ciudad x categoria)

Ejemplo (mes de 10 dias, 10 carros por ciudad, 10 por carro-dia): sin movimientos
cada ciudad presupuesta 10 x 10 x 10 = 1.000. Si el dia 5 un carro pasa de Medellin
a Pereira, Medellin lo tiene los dias 1-4 (96 carro-dias = 960) y Pereira del 5 al 10
(106 carro-dias = 1.060).

- Dias que ya pasaron: la ciudad de cada placa sale de gold_carro_dia, dia por dia.
  Es la misma atribucion con la que se miden la ocupacion y el RPD (en un dia rentado
  cuenta la sede que entrego el carro), asi que carro-dias y tasas son coherentes.
- Dias que todavia no pasaron: se proyectan con la ubicacion actual (la misma regla
  de la foto de 10_Presupuesto).
- Mes futuro: no hay dias reales, asi que coincide con 10_Presupuesto.
- Usa el ESCENARIO GUARDADO (operational.presupuesto_ocupacion); las ediciones sin
  guardar de 10_Presupuesto no se ven aca.
"""
import sys
import calendar
import datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.common import (
    inject_styles, render_header, section, kpi, fmt_money, fmt_int,
    xlsx_download_button, PLOTLY_LAYOUT,
)
from components.filters import render_sidebar_filters
from components.auth import require_auth, require_page, logout_button, get_current_user
from components import presupuesto as P

# Streamlit Cloud puede seguir sirviendo una version VIEJA de components/presupuesto
# despues de un push (recarga la pagina, no siempre los modulos ya importados). Si el
# modulo cargado es anterior a lo que esta pagina necesita, se recarga.
P_API_REQUERIDA = 6
if getattr(P, "API_VERSION", 0) < P_API_REQUERIDA:
    import importlib
    P = importlib.reload(P)

st.set_page_config(page_title="TRUST - Presupuesto con traslados", layout="wide")
require_auth()
require_page("11_Presupuesto_Traslados")
inject_styles()
logout_button()

_u = get_current_user()
if not _u or _u.get("username") != "trust_admin":
    render_header("Presupuesto con traslados")
    st.warning("Solo el perfil **trust_admin** puede ver el presupuesto.")
    st.stop()

render_header("Presupuesto con traslados — tarifa (T)")

filtros = render_sidebar_filters(default_days=30)
MON = filtros.moneda
SUF = "cop" if MON == "COP" else "usd"
NICE, MES = P.SEDE_NICE, P.MES_ES

# =============================================================================
# Mes, ventana, foto y escenario (identicos a 10_Presupuesto)
# =============================================================================
today = dt.date.today()
target = P.month_selector(today)
DAYS = calendar.monthrange(target.year, target.month)[1]
mstart, mend = target, target + dt.timedelta(days=DAYS - 1)
win_start, win_end = P.window_for(target, today)
last_day = P.last_gold_day()
snap = P.snapshot_date(target, last_day)

EXCL = P.excluded_plates(target.isoformat())   # mismas exclusiones que Presupuesto
RECAT = P.recat_map()                          # mismas categorias corregidas
base_df, factor, _plates_snap, rates = P.base_inputs(
    win_start.isoformat(), win_end.isoformat(), target.isoformat(), SUF, snap.isoformat(),
    EXCL, RECAT)
if base_df.empty:
    st.info("No hay datos suficientes en la ventana para presupuestar.")
    st.stop()
saved_sede, saved_cat, saved_cell = P.saved_overrides(target.isoformat())
occ_final = P.scenario_occ(base_df, rates, factor, saved_sede, saved_cat, saved_cell)
_hay_override = bool(saved_sede or saved_cat or saved_cell)

# =============================================================================
# Carro-dias: reales (dias que ya pasaron) + proyectados (dias que faltan)
# =============================================================================
real_end = min(mend, last_day)
parts = []
# Se carga tambien el dia ANTERIOR al mes para detectar un cambio de ciudad el dia 1.
if real_end >= mstart:
    _r = P.daily_rows((mstart - dt.timedelta(days=1)).isoformat(), real_end.isoformat(),
                      EXCL, RECAT)
    _r["tipo"] = "real"
    parts.append(_r)
if real_end < mend:
    # Proyeccion: cada placa activa al ultimo dia de gold se queda donde esta hoy.
    _now = P.fleet_snapshot(last_day.isoformat(), win_start.isoformat(), win_end.isoformat(),
                            EXCL, RECAT)
    _fut = pd.date_range(max(mstart, last_day + dt.timedelta(days=1)), mend).date
    _p = _now[["placa", "g", "acriss", "acriss_sixt"]].merge(
        pd.DataFrame({"fecha": _fut}), how="cross")
    _p["rented_day"] = 0
    _p["tipo"] = "proyectado"
    parts.append(_p)
daily_all = pd.concat(parts, ignore_index=True)
daily = daily_all[(daily_all["fecha"] >= mstart) & (daily_all["fecha"] <= mend)].copy()

# Valor esperado de cada carro-dia en su ciudad x categoria = ocupacion x RPD.
_cells = daily[["g", "acriss"]].drop_duplicates()
_cells["occ"] = [occ_final(g, a) for g, a in zip(_cells["g"], _cells["acriss"])]
_cells["rpd"] = [P.cell_rpd(rates, g, a) for g, a in zip(_cells["g"], _cells["acriss"])]
# una ocupacion por escenario (Conservador / Base / Optimista), misma regla que Presupuesto
for _k, _lbl, _m in P.ESCENARIOS:
    _cells[f"occ_{_k}"] = [occ_final(g, a, _m) for g, a in zip(_cells["g"], _cells["acriss"])]
daily = daily.merge(_cells, on=["g", "acriss"], how="left")
daily["val"] = daily["occ"] * daily["rpd"]
for _k, _lbl, _m in P.ESCENARIOS:
    daily[f"val_{_k}"] = daily[f"occ_{_k}"] * daily["rpd"]

# Base = 10_Presupuesto: flota de la foto x todos los dias del mes.
base = base_df.copy()
base["occ"] = [occ_final(g, a) for g, a in zip(base["sede"], base["acriss"])]
base["carro_dias"] = base["n"] * DAYS
base["rev"] = base["carro_dias"] * base["occ"] * base["rpd"]
for _k, _lbl, _m in P.ESCENARIOS:
    base[f"rev_{_k}"] = base["carro_dias"] * [
        occ_final(g, a, _m) for g, a in zip(base["sede"], base["acriss"])] * base["rpd"]

# --- alcance: filtro de sedes del sidebar (agrupado por ciudad) ---
sel = {P.grp(n) for n in (filtros.sedes_nombres or [])} - {"OTRA"}
ciudades = [g for g in P.SEDE_ORDER
            if (not sel or g in sel) and (g in set(base["sede"]) or g in set(daily["g"]))]
daily = daily[daily["g"].isin(ciudades)]
base = base[base["sede"].isin(ciudades)]

st.caption(
    f"Presupuestando **{P.mes_label(target)}** ({DAYS} días), moneda **{MON}**, solo "
    "tarifa (cargo T). Mismas tasas y mismo escenario que la página Presupuesto; lo "
    "único que cambia es cómo se cuenta la flota: **carro-días reales en cada ciudad** "
    f"en vez de la foto del {snap} por {DAYS} días. "
    + (f"Días reales: del 1 al {real_end.day} (último dato de gold: {last_day}); "
       f"del {min(mend, real_end + dt.timedelta(days=1)).day} al {DAYS} se proyecta con la "
       "ubicación actual. " if mstart <= real_end < mend
       else "Mes cerrado: todos los días son reales. " if real_end >= mend
       else "Mes futuro: todavía no hay días reales, así que coincide con la página "
            "Presupuesto. ")
    + ("**Escenario guardado activo.** " if _hay_override else "Sin escenario guardado (pre-calculado). ")
    + (f"**{len(EXCL)} placas excluidas** del presupuesto para este mes (se gestionan en la "
       f"página Presupuesto): {', '.join(EXCL)}." if EXCL else ""))

# =============================================================================
# KPIs
# =============================================================================
tot_base = float(base["rev"].sum())
tot_tras = float(daily["val"].sum())
cut = min(mend, last_day - dt.timedelta(days=1))   # ultimo dia COMPLETO de gold
real_rev = (P.real_t(mstart.isoformat(), cut.isoformat(), SUF) if cut >= mstart
            else pd.Series(dtype=float))
real_rev = real_rev[real_rev.index.isin(ciudades)]
presup_al_corte = (daily[daily["fecha"] <= cut].groupby("g")["val"].sum()
                   if cut >= mstart else pd.Series(dtype=float))
# Mes en curso: NO se calcula cumplimiento. gold_cargo_dia reparte un contrato ABIERTO
# solo sobre los dias ya transcurridos (LEAST(devolucion, NOW())), asi que el real a la
# fecha sale inflado al principio del mes (una renta de 30 dias entregada ayer carga
# todo su valor en 1-2 dias) y se corrige solo cuando el contrato cierra. Visto el
# 2-oct-2026: "cumplimiento" de 272% en Bogota con 1 dia de datos.
parcial = cut < mend

k1, k2, k3, k4 = st.columns(4)
kpi(k1, f"Presupuesto foto ({MON})", fmt_money(tot_base, MON),
    f"flota al {snap} × {DAYS} días")
kpi(k2, f"Con traslados ({MON})", fmt_money(tot_tras, MON),
    f"{fmt_int(len(daily))} carro-días reales/proyectados")
_d = tot_tras - tot_base
kpi(k3, "Efecto de los movimientos", fmt_money(_d, MON),
    f"{(_d / tot_base * 100) if tot_base else 0:+.2f}% vs la foto")
if len(real_rev):
    _pc = float(presup_al_corte.sum())
    _rr = float(real_rev.sum())
    kpi(k4, f"Real al {cut.day}-{MES[cut.month][:3]}", fmt_money(_rr, MON),
        "mes en curso: todavía no comparable (ver nota)" if parcial
        else f"{_rr / _pc * 100:.1f}% del presupuesto con traslados" if _pc else "")
else:
    kpi(k4, "Real", "-", "el mes todavía no empezó")


# =============================================================================
# Escenarios (mismos de Presupuesto, sobre los carro-dias con traslados)
# =============================================================================
section("Escenarios (± ocupación)")
st.caption(
    "Los mismos escenarios de la página Presupuesto (la ocupación esperada × "
    "multiplicador, tope 98%), pero calculados con los carro-días reales de cada "
    "ciudad. Debajo de cada uno, el valor con la foto: es el número que muestra "
    "Presupuesto para ese escenario.")
for _col, (_k, _lbl, _m) in zip(st.columns(len(P.ESCENARIOS)), P.ESCENARIOS):
    _tt = float(daily[f"val_{_k}"].sum())
    _tb = float(base[f"rev_{_k}"].sum())
    _sub = f"foto: {fmt_money(_tb, MON)}"
    if len(real_rev) and not parcial:
        _pc_k = float(daily.loc[daily["fecha"] <= cut, f"val_{_k}"].sum())
        _sub += f" · real = {float(real_rev.sum()) / _pc_k * 100:.1f}% de este escenario" if _pc_k else ""
    kpi(_col, _lbl, fmt_money(_tt, MON), _sub)

_esc_city = pd.DataFrame(index=ciudades)
for _k, _lbl, _m in P.ESCENARIOS:
    _esc_city[_lbl] = daily.groupby("g")[f"val_{_k}"].sum()
_esc_city = _esc_city.fillna(0.0)
_out_esc = pd.DataFrame({"Ciudad": [NICE[g] for g in _esc_city.index]})
for _k, _lbl, _m in P.ESCENARIOS:
    _out_esc[_lbl] = [fmt_money(v, MON) for v in _esc_city[_lbl]]
if len(real_rev) and not parcial:
    _rr_c = [float(real_rev.get(g, 0.0)) for g in _esc_city.index]
    _out_esc[f"Real {MES[target.month]}"] = [fmt_money(v, MON) for v in _rr_c]
    for _k, _lbl, _m in P.ESCENARIOS:
        _pc_c = daily[daily["fecha"] <= cut].groupby("g")[f"val_{_k}"].sum()
        _out_esc[f"Cumpl. {_lbl.split(' ')[0].lower()}"] = [
            f"{r / _pc_c.get(g, 0.0) * 100:.1f}%" if _pc_c.get(g, 0.0) else "-"
            for r, g in zip(_rr_c, _esc_city.index)]
st.markdown("**Escenarios por ciudad (con traslados)**")
st.dataframe(_out_esc, hide_index=True, use_container_width=True)

# =============================================================================
# Por ciudad
# =============================================================================
section("Por ciudad")
bc = base.groupby("sede").agg(n=("n", "sum"), cd_base=("carro_dias", "sum"), rev_base=("rev", "sum"))
dc = daily.groupby("g").agg(cd=("placa", "size"), rev=("val", "sum"))
city = pd.DataFrame(index=ciudades).join(bc).join(dc).fillna(0.0)
city["delta"] = city["rev"] - city["rev_base"]
# Ocupacion esperada por ciudad: el MISMO numero que muestra la tabla "Por sede" de
# Presupuesto (lo guardado, o lo pre-calculado si nadie lo edito).
_bso = P.wocc(base_df, "sede")
_occ_city = [saved_sede.get(g, _bso.get(g, 0.0) * 100) for g in city.index]
out_city = pd.DataFrame({
    "Ciudad": [NICE[g] for g in city.index],
    "Ocupación esperada (%)": [round(float(v), 1) for v in _occ_city],
    "Flota foto": city["n"].astype(int).values,
    "Carro-días foto": city["cd_base"].astype(int).values,
    "Carro-días con traslados": city["cd"].astype(int).values,
    "Flota promedio": (city["cd"] / DAYS).round(2).values,
    "Presupuesto foto": city["rev_base"].map(lambda v: fmt_money(v, MON)).values,
    "Con traslados": city["rev"].map(lambda v: fmt_money(v, MON)).values,
    "Diferencia": city["delta"].map(lambda v: fmt_money(v, MON)).values,
})
if len(real_rev):
    _pcc = city.index.map(lambda g: presup_al_corte.get(g, 0.0))
    _rrc = city.index.map(lambda g: real_rev.get(g, 0.0))
    out_city[f"Presupuesto al {cut.day}-{MES[cut.month][:3]}"] = [fmt_money(v, MON) for v in _pcc]
    out_city[f"Real al {cut.day}-{MES[cut.month][:3]}"] = [fmt_money(v, MON) for v in _rrc]
    if not parcial:
        out_city["Cumplimiento"] = [f"{r / p * 100:.1f}%" if p else "-" for r, p in zip(_rrc, _pcc)]
st.dataframe(out_city, hide_index=True, use_container_width=True)
if len(real_rev) and parcial:
    st.warning(
        "**Mes en curso: el real a la fecha todavía no se puede comparar.** La capa gold "
        "reparte cada contrato abierto solo sobre los días que ya pasaron, así que una "
        "renta larga entregada hace poco carga todo su valor en esos pocos días y el real "
        "sale inflado. Se corrige solo a medida que los contratos cierran; el "
        "cumplimiento aparece cuando el mes termina.")
st.caption(
    "**Ocupación esperada** = la misma de la página Presupuesto (lo editado o lo "
    "pre-calculado); los ajustes por categoría se ven en *Por ciudad × categoría*. "
    "**Flota promedio** = carro-días / días del mes: un carro que estuvo medio mes "
    "suma 0,5. Si un carro pasa a una ciudad con otra ocupación o RPD, el total "
    "cambia, no solo se reparte. **Real** = cargo T de `silver.gold_cargo_dia` hasta el "
    "último día completo (el día del refresh trae las rentas a medias); es una "
    "transformación de silver y puede diferir de COBRA.")

# =============================================================================
# Carros por ciudad, dia a dia
# =============================================================================
section("Carros por ciudad, día a día")
_dd = daily.groupby(["fecha", "g"]).size().rename("carros").reset_index()
fig = go.Figure()
for g in ciudades:
    s_ = _dd[_dd["g"] == g]
    fig.add_trace(go.Scatter(x=s_["fecha"], y=s_["carros"], name=NICE[g],
                             mode="lines+markers", line_shape="hv"))
if mstart <= last_day < mend:
    fig.add_vline(x=last_day.isoformat(), line_dash="dash", line_color="#999999")
    fig.add_annotation(x=last_day.isoformat(), y=1, yref="paper", text="desde acá, proyección",
                       showarrow=False, xanchor="left", font=dict(size=11, color="#666666"))
fig.update_layout(**PLOTLY_LAYOUT, height=340, yaxis_title="carros",
                  legend=dict(orientation="h", y=-0.2))
st.plotly_chart(fig, use_container_width=True)

# =============================================================================
# Movimientos del mes
# =============================================================================
section("Movimientos de ciudad en el mes")
# Placas que pasaron por alguna ciudad del alcance; se listan sus cambios que
# entran o salen de esas ciudades.
_pl_scope = set(daily_all.loc[daily_all["g"].isin(ciudades), "placa"])
_m = daily_all[daily_all["placa"].isin(_pl_scope)].sort_values(["placa", "fecha"]).copy()
_m["prev"] = _m.groupby("placa")["g"].shift()
_m["run"] = (_m["g"] != _m["prev"]).groupby(_m["placa"]).cumsum()
_runs = (_m[(_m["fecha"] >= mstart) & (_m["fecha"] <= mend)]
         .groupby(["placa", "run"]).agg(dias=("fecha", "size"), desde=("fecha", "min"))
         .reset_index())
mov = _m[_m["prev"].notna() & (_m["g"] != _m["prev"]) & (_m["fecha"] >= mstart)
         & (_m["fecha"] <= mend)
         & (_m["g"].isin(ciudades) | _m["prev"].isin(ciudades))
         ].merge(_runs, on=["placa", "run"], how="left")
if mov.empty:
    st.info("Ningún carro cambió de ciudad en este mes "
            + ("(todavía no hay días reales)." if real_end < mstart else "."))
else:
    mov = mov.sort_values(["fecha", "placa"])
    out_mov = pd.DataFrame({
        "Fecha": mov["fecha"].values,
        "Placa": mov["placa"].values,
        "Categoría": mov["acriss"].values,
        "ACRISS Sixt": mov["acriss_sixt"].values,
        "De": mov["prev"].map(NICE).values,
        "A": mov["g"].map(NICE).values,
        "Días en la nueva ciudad (este mes)": mov["dias"].astype(int).values,
        "Tipo": ["Provisional (día del refresh)" if f == last_day
                 else "Entregado en renta en la otra ciudad" if r == 1
                 else "Traslado / reubicación"
                 for f, r in zip(mov["fecha"], mov["rented_day"])],
    })
    st.dataframe(out_mov, hide_index=True, use_container_width=True)
    st.caption(
        "Un cambio de ciudad aparece el día en que el carro amanece en otra ciudad. "
        "**Traslado / reubicación**: el carro estaba libre (traslado interno o llegó "
        "sin renta). **Entregado en renta en la otra ciudad**: ese día lo rentó la "
        "otra sede (p. ej. llegó por un one-way y salió de nuevo desde ahí); ese día "
        "cuenta para la sede que lo rentó, igual que en la ocupación. Un carro que va y "
        "viene aparece varias veces. Los movimientos dentro de Medellín (aeropuerto - "
        "El Poblado) no se listan porque el presupuesto es por ciudad. **Provisional**: "
        "el último día de gold es el del refresh y todavía no trae las rentas de ese día, "
        "así que el tipo se confirma en el próximo refresh.")
    xlsx_download_button(out_mov, file_name=f"presupuesto_movimientos_{target.isoformat()}",
                         sheet_name="Movimientos", key="presup_mov_xlsx")

# =============================================================================
# Por ciudad x categoria
# =============================================================================
section("Por ciudad × categoría")
bcell = base.groupby(["sede", "acriss"]).agg(n=("n", "sum"), rev_base=("rev", "sum"))
bcell.index.names = ["g", "acriss"]
dcell = daily.groupby(["g", "acriss"]).agg(cd=("placa", "size"), rev=("val", "sum"),
                                           occ=("occ", "first"), rpd=("rpd", "first"))
cell = bcell.join(dcell, how="outer").fillna(0.0).reset_index()
cell["delta"] = cell["rev"] - cell["rev_base"]
cell["_o"] = cell["g"].map({g: i for i, g in enumerate(P.SEDE_ORDER)})
cell = cell.sort_values(["_o", "acriss"])
solo = st.checkbox("Mostrar solo las celdas que cambian por movimientos", value=True)
if solo:
    cell = cell[(cell["cd"] - cell["n"] * DAYS).abs() > 0]
if cell.empty:
    st.info("Ninguna celda cambia: la flota de cada ciudad × categoría es la misma "
            "todos los días del mes.")
else:
    st.dataframe(pd.DataFrame({
        "Ciudad": cell["g"].map(NICE).values,
        "Categoría": cell["acriss"].values,
        "Flota foto": cell["n"].astype(int).values,
        "Carro-días foto": (cell["n"] * DAYS).astype(int).values,
        "Carro-días con traslados": cell["cd"].astype(int).values,
        "Ocupación (%)": (cell["occ"] * 100).round(1).values,
        "RPD": cell["rpd"].map(lambda v: fmt_money(v, MON)).values,
        "Presupuesto foto": cell["rev_base"].map(lambda v: fmt_money(v, MON)).values,
        "Con traslados": cell["rev"].map(lambda v: fmt_money(v, MON)).values,
        "Diferencia": cell["delta"].map(lambda v: fmt_money(v, MON)).values,
    }), hide_index=True, use_container_width=True)

st.caption(
    "Presupuesto con traslados = suma, día por día, de los carros en cada ciudad × "
    "categoría por su ocupación esperada × RPD de tarifa. Ocupación, RPD, factores "
    f"estacionales (ocupación {rates['f_occ']:.3f}, RPD {rates['f_rpd']:.3f}) y escenario "
    "guardado son los de la página Presupuesto. "
    "Fuente: silver.gold_carro_dia; real: silver.gold_cargo_dia.")
