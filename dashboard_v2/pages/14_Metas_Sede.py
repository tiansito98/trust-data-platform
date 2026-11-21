"""
Metas de la sede — cumplimiento del presupuesto del mes, total y por SEMANA.

Para los asesores de cada sede (y el admin). Solo LECTURA: el presupuesto lo arma la
direccion en 10_Presupuesto (escenario guardado); aqui se reparte por semana y se
compara con lo vendido.

- Meta = presupuesto CONGELADO del mes (operational.presupuesto_congelado, P.meta_ciudad;
  se congela solo la primera vez que se abre la pagina en el mes, o desde 10_Presupuesto).
  El valor congelado es el presupuesto de la CIUDAD, SOLO tarifa (cargo T: renta del
  carro, sin adicionales, coberturas ni tax), = total de 10_Presupuesto sin filtro de
  sedes en ese momento (P.presupuesto_ciudad). Medellin tiene dos sedes y UNA meta.
- Meta semanal = meta del mes x dias de la semana / dias del mes. Semanas lunes-domingo;
  un pedazo de menos de 4 dias al inicio o al final del mes se une a la semana vecina.
- Real = silver.gold_tarifa_dia: tarifa T repartida por dia 24h sobre la duracion
  COMPLETA del contrato (programada si sigue abierto). No usa gold_cargo_dia porque
  ese infla el mes en curso (reparte una renta abierta solo sobre los dias pasados).
- Corte = ayer (el pipeline carga los datos de madrugada). Los dias despues del corte
  de las rentas que ya estan abiertas son "ya vendido": todavia no es real, pero ya
  esta en la calle.
- Acceso: abierta a todos (auth.PAGINAS_PARA_TODOS). Un usuario de sede queda fijo en
  su ciudad por el filtro del sidebar.
"""
import sys
import calendar
import datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from components.common import inject_styles, render_header, section, kpi, fmt_money, fmt_pct
from components.filters import render_sidebar_filters
from components import presupuesto as P

P_API_REQUERIDA = 10
if getattr(P, "API_VERSION", 0) < P_API_REQUERIDA:
    import importlib
    P = importlib.reload(P)
from components import auth as _auth
if not hasattr(_auth, "PAGINAS_PARA_TODOS"):   # Streamlit Cloud con el auth viejo en memoria
    import importlib
    _auth = importlib.reload(_auth)
from components.auth import require_auth, require_page, logout_button, is_admin, get_current_user

st.set_page_config(page_title="TRUST - Metas de la sede", layout="wide")
require_auth()
require_page("14_Metas_Sede")
inject_styles()
logout_button()

render_header("Metas de la sede — tarifa (T)")

filtros = render_sidebar_filters(default_days=30)
MON = filtros.moneda
SUF = "cop" if MON == "COP" else "usd"

# --- Mes: los del ano en curso hasta el actual --------------------------------
today = dt.date.today()
mes_actual = dt.date(today.year, today.month, 1)
meses = [m for m in P.month_options(today) if m <= mes_actual]
if st.session_state.get("metas_mes") not in meses:
    st.session_state["metas_mes"] = mes_actual
c_mes, c_ciudad = st.columns(2)
target = c_mes.selectbox("Mes", options=meses, format_func=P.mes_label, key="metas_mes")
DAYS = calendar.monthrange(target.year, target.month)[1]
fin_mes = dt.date(target.year, target.month, DAYS)

# --- Ciudad: la del usuario de sede, o a elegir (admin) -----------------------
grupos = [g for g in P.SEDE_ORDER if g in {P.grp(n) for n in (filtros.sedes_nombres or [])}]
if not grupos:
    if not is_admin():
        st.warning("Tu usuario no tiene una sede con presupuesto. Avisá al administrador.")
        st.stop()
    grupos = list(P.SEDE_ORDER)
TODAS = "TODAS"
opciones = grupos + ([TODAS] if is_admin() and len(grupos) > 1 else [])
ciudad = c_ciudad.selectbox(
    "Ciudad", options=opciones,
    format_func=lambda g: "Todas las ciudades" if g == TODAS else P.SEDE_NICE[g],
    disabled=len(opciones) == 1,
    help="La meta es por ciudad: en Medellín las dos sedes comparten una sola meta.")
alcance = grupos if ciudad == TODAS else [ciudad]

# --- Meta del mes ------------------------------------------------------------
_usr = (get_current_user() or {}).get("username", "sistema")
ppto, congelada = P.meta_ciudad(target, SUF, today, _usr)
meta_mes = float(ppto.reindex(alcance).fillna(0).sum())
if meta_mes <= 0:
    st.info(f"Todavía no hay presupuesto para {P.mes_label(target)} en esta ciudad.")
    st.stop()
meta_dia = meta_mes / DAYS

# --- Real y "ya vendido" -----------------------------------------------------
corte = min(today - dt.timedelta(days=1), fin_mes)   # el pipeline carga de madrugada
td = P.tarifa_dia(target.isoformat(), fin_mes.isoformat(), SUF)
td = td[td["g"].isin(alcance)]
real_d = td[td["fecha"] <= corte].groupby("fecha")["t_val"].sum()
vendido_d = td[td["fecha"] > corte].groupby("fecha")["t_val"].sum()   # rentas abiertas, dias futuros

dias_corridos = max(0, (corte - target).days + 1) if corte >= target else 0
real = float(real_d.sum())
vendido = float(vendido_d.sum())
meta_a_fecha = meta_dia * dias_corridos
cerrado = corte >= fin_mes

st.caption(
    f"**{P.mes_label(target)}** · {', '.join(P.SEDE_NICE.get(g, g) for g in alcance)} · {MON}. "
    "Solo **tarifa** (renta del carro, cargo T): sin adicionales, coberturas ni tax. "
    + ("La meta es el presupuesto que definió la dirección para el mes, **congelado el "
       f"{pd.to_datetime(congelada['congelado_at']).tz_convert('America/Bogota'):%d/%m/%Y}**: "
       "no cambia aunque se actualicen los datos. " if congelada is not None
       else "Meta calculada con los datos de hoy (este mes no se congeló). ")
    + (f"Datos hasta el **{corte:%d/%m/%Y}** (ayer; se actualiza cada madrugada)."
       if not cerrado else "Mes cerrado.")
    + " El rango de fechas del menú lateral no aplica en esta página.")

k1, k2, k3, k4 = st.columns(4)
kpi(k1, "Meta del mes", fmt_money(meta_mes, MON), f"{DAYS} días")
kpi(k2, "Vendido a la fecha", fmt_money(real, MON),
    f"{fmt_pct(real / meta_mes * 100)} de la meta del mes")
if cerrado:
    kpi(k3, "Cumplimiento del mes", fmt_pct(real / meta_mes * 100),
        "cumplida" if real >= meta_mes else f"faltaron {fmt_money(meta_mes - real, MON)}")
    kpi(k4, "Diferencia", fmt_money(real - meta_mes, MON), "vendido − meta")
else:
    kpi(k3, "Cumplimiento a la fecha",
        fmt_pct(real / meta_a_fecha * 100) if meta_a_fecha else "-",
        f"meta a la fecha {fmt_money(meta_a_fecha, MON)} ({dias_corridos} de {DAYS} días)")
    falta = max(meta_mes - real - vendido, 0.0)
    dias_rest = DAYS - dias_corridos
    kpi(k4, "Ya vendido para lo que queda", fmt_money(vendido, MON),
        (f"faltan {fmt_money(falta, MON)} · {fmt_money(falta / dias_rest, MON)} por día"
         if falta > 0 and dias_rest else "con esto la meta del mes queda cubierta"))

if not cerrado and meta_mes:
    st.progress(min(real / meta_mes, 1.0),
                text=f"Mes: {fmt_pct(real / meta_mes * 100)} vendido · "
                     f"{fmt_pct(dias_corridos / DAYS * 100)} del mes transcurrido")

# --- Por semana --------------------------------------------------------------
section("Metas semanales")
filas = []
for n, a, b in P.semanas_mes(target):
    dias = (b - a).days + 1
    meta_s = meta_dia * dias
    r = float(real_d[(real_d.index >= a) & (real_d.index <= b)].sum())
    v = float(vendido_d[(vendido_d.index >= a) & (vendido_d.index <= b)].sum())
    if b <= corte:
        estado, base = ("Cumplida" if r >= meta_s else "No cumplida"), meta_s
    elif a <= corte:
        d_corr = (corte - a).days + 1
        base = meta_dia * d_corr
        estado = f"En curso ({d_corr} de {dias} días)"
    else:
        estado, base = "Por venir", 0.0
    filas.append({
        "Semana": f"Semana {n}",
        "Fechas": f"{a:%d/%m} – {b:%d/%m}",
        "Días": dias,
        "Meta": meta_s,
        "Vendido": r,
        "Cumplimiento (%)": (r / base * 100) if base else None,
        "Ya vendido (rentas abiertas)": v,
        "Estado": estado,
    })
sem = pd.DataFrame(filas)

def _fmt_col(c):
    return sem[c].map(lambda x: fmt_money(x, MON))

vista = sem.copy()
for c in ("Meta", "Vendido", "Ya vendido (rentas abiertas)"):
    vista[c] = _fmt_col(c)
st.dataframe(
    vista, hide_index=True, width="stretch",
    column_config={
        "Cumplimiento (%)": st.column_config.ProgressColumn(
            "Cumplimiento (%)", min_value=0, max_value=100, format="%.1f%%",
            help="Vendido ÷ meta. En la semana en curso se compara contra la meta de "
                 "los días que ya pasaron."),
        "Ya vendido (rentas abiertas)": st.column_config.TextColumn(
            help="Días que todavía no pasaron de rentas que ya están abiertas: ya están "
                 "vendidos, pero pueden cambiar si el cliente devuelve antes o extiende."),
    })
st.caption("Meta semanal = meta del mes repartida por días. Semanas de lunes a domingo; "
           "si el mes empieza o termina con menos de 4 días sueltos, esos días se suman "
           "a la semana de al lado.")

# --- Por dia -----------------------------------------------------------------
with st.expander("Ver día por día"):
    dias_mes = [target + dt.timedelta(days=i) for i in range(DAYS)]
    dd = pd.DataFrame({"Fecha": dias_mes})
    dd["Meta"] = meta_dia
    dd["Vendido"] = dd["Fecha"].map(real_d).fillna(0.0)
    dd.loc[dd["Fecha"] > corte, "Vendido"] = None
    dd["Ya vendido (rentas abiertas)"] = dd["Fecha"].map(vendido_d).fillna(0.0)
    dd["Meta acumulada"] = dd["Meta"].cumsum()
    dd["Vendido acumulado"] = dd["Vendido"].fillna(0.0).cumsum()
    dd.loc[dd["Fecha"] > corte, "Vendido acumulado"] = None
    vd = dd.copy()
    vd["Fecha"] = vd["Fecha"].map(lambda d: f"{d:%d/%m} {['lun','mar','mié','jue','vie','sáb','dom'][d.weekday()]}")
    for c in ("Meta", "Vendido", "Ya vendido (rentas abiertas)", "Meta acumulada", "Vendido acumulado"):
        vd[c] = vd[c].map(lambda x: fmt_money(x, MON) if pd.notna(x) else "")
    st.dataframe(vd, hide_index=True, width="stretch")

# --- Por sede (Medellin = 2 sedes) -------------------------------------------
sedes_real = td[td["fecha"] <= corte].groupby("sede")["t_val"].sum()
if len(sedes_real) > 1:
    section("Vendido por sede")
    st.dataframe(
        pd.DataFrame({"Sede": sedes_real.index,
                      "Vendido": [fmt_money(v, MON) for v in sedes_real.values],
                      "Participación": [fmt_pct(v / real * 100) if real else "-"
                                        for v in sedes_real.values]}),
        hide_index=True, width="stretch")
    st.caption("La meta es de la ciudad completa; esta tabla solo muestra cuánto aporta cada sede.")

st.caption("Vendido = tarifa de los contratos entregados en la ciudad, repartida por día de "
           "renta (bloques de 24 h con 1 hora de gracia). Una renta que cruza de mes aporta "
           "a cada mes solo sus días. Puede tener pequeñas diferencias con COBRA.")
