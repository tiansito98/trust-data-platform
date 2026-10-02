"""
Presupuesto de ventas (SOLO tarifa, codigo T) — solo trust_admin.

El presupuesto se calcula UNICAMENTE sobre las rentas de carro (cargo T), sin
adicionales, coberturas ni tax. Fuente: silver.gold_carro_dia (tar_usd/tar_cop =
tarifa T prorrateada por dia 24h+gracia, lado RENTAL_COUNTER).

Modelo bottom-up por (sede x categoria ACRISS):
    presupuesto = flota x dias_mes x ocupacion_final x RPD_tarifa
    ocupacion_final = ocupacion_base x factor_sede x factor_categoria

- FLOTA: foto del padron ACTIVO al ultimo dia de gold_carro_dia, NO un conteo de la
  ventana de 3 meses (fix 2026-09-22). Antes, un carro que ingresaba despues del
  cierre de la ventana contaba 0 y la flota solo crecia con ~2 meses de retraso.
  La sede de cada placa sale de su ULTIMO DIA LIBRE, asi que un TRASLADO entre
  ciudades mueve la flota el mismo dia (la sede modal de 30 dias tardaba ~15).
- Ocupacion base y RPD: run-rate 3 meses completos x factor estacional (mes objetivo
  vs ese mismo mes el ano anterior). Son tasas; lo que multiplica es la flota de hoy.
- La ocupacion esperada se puede editar POR SEDE y POR CATEGORIA; ambos ajustes se
  combinan (multiplican) sobre la base.
- La pagina respeta el FILTRO DE SEDES del sidebar (agrupado por ciudad). Con una
  sola ciudad en alcance, la tabla de categorias es por (sede x ACRISS) y se guarda
  con dimension 'sede_cat' / clave 'GRUPO|ACRISS'; ese override por celda manda
  sobre el ajuste global de la categoria en cualquier alcance.
- Guardar (operational.presupuesto_ocupacion) / Volver a lo pre-calculado.
- ACRISS unificados SOLO para el presupuesto: SDAH -> EDAH, CDMR -> EDMR (ACRISS_CANON).
- Listado auditable de las placas que entran al calculo (mismo DataFrame que el
  conteo de flota), con descarga a Excel.
- Selector con TODOS los meses del ano en curso (historico) + los 2 siguientes. Para
  un mes pasado, ventana y foto de flota se toman como al inicio de ese mes.
- La version con traslados (carro-dias reales por ciudad) esta en
  11_Presupuesto_Traslados; comparte toda la logica via components/presupuesto.py.
- Comparacion contra el mismo mes del ano anterior (delta). El "Real" sale de
  gold_cargo_dia codigo T (no de gold_carro_dia, que pierde los carros defleeteados).
"""
import sys
import calendar
import datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from components.common import (
    inject_styles, render_header, section, kpi, fmt_money, fmt_int,
    load_query, execute_write, xlsx_download_button,
)
from components.filters import render_sidebar_filters
from components import presupuesto as P
from components.auth import require_auth, require_page, logout_button, get_current_user

st.set_page_config(page_title="TRUST - Presupuesto", layout="wide")
require_auth()
require_page("10_Presupuesto")
inject_styles()
logout_button()

# --- Gate: SOLO el perfil trust_admin ---
_u = get_current_user()
if not _u or _u.get("username") != "trust_admin":
    render_header("Presupuesto")
    st.warning("Solo el perfil **trust_admin** puede ver el presupuesto.")
    st.stop()

render_header("Presupuesto de ventas — tarifa (T)")

@st.cache_resource
def _ensure_table():
    try:
        execute_write("""
            CREATE TABLE IF NOT EXISTS operational.presupuesto_ocupacion (
                mes           date NOT NULL,
                dimension     text NOT NULL,
                clave         text NOT NULL,
                ocupacion_pct numeric,
                updated_by    text,
                updated_at    timestamptz DEFAULT now(),
                PRIMARY KEY (mes, dimension, clave)
            )
        """, {})
    except Exception:
        pass
_ensure_table()

filtros = render_sidebar_filters(default_days=30)
MON = filtros.moneda
SUF = "cop" if MON == "COP" else "usd"

# =============================================================================
# Mes objetivo + ventana + foto de flota (logica compartida en components/presupuesto)
# =============================================================================
SEDE_ORDER, SEDE_NICE, _MES_ES = P.SEDE_ORDER, P.SEDE_NICE, P.MES_ES
_grp, _mes_label = P.grp, P.mes_label

today = dt.date.today()
target = P.month_selector(today)
DAYS = calendar.monthrange(target.year, target.month)[1]
win_start, win_end = P.window_for(target, today)
_last_day = P.last_gold_day()
snap_date = P.snapshot_date(target, _last_day)

_es_pasado = target < dt.date(today.year, today.month, 1)
_cap_base = (
    f"Presupuestando **{_mes_label(target)}** ({DAYS} días). Base: run-rate "
    f"**{_MES_ES[win_start.month]} {win_start.year} – {_MES_ES[win_end.month]} "
    f"{win_end.year}** (los 3 meses cerrados anteriores al mes). Moneda: **{MON}**. Solo "
    "tarifa (cargo T), sin adicionales ni coberturas ni tax.")

base_df_all, factor, plates_all, _rates = P.base_inputs(
    win_start.isoformat(), win_end.isoformat(), target.isoformat(), SUF, snap_date.isoformat())
if base_df_all.empty:
    st.info("No hay datos suficientes en la ventana reciente para presupuestar.")
    st.stop()

# --- Alcance: filtro de sedes del sidebar -------------------------------------
# El presupuesto agrupa por CIUDAD (las dos sedes de Medellin cuentan juntas), asi
# que seleccionar cualquier sede de Medellin trae la ciudad completa.
sel_grupos = {_grp(n) for n in (filtros.sedes_nombres or [])} - {"OTRA"}
if sel_grupos:
    base_df = base_df_all[base_df_all["sede"].isin(sel_grupos)].copy()
else:
    base_df = base_df_all.copy()
if base_df.empty:
    st.info("La seleccion de sedes no tiene flota con historia para presupuestar.")
    st.stop()

# ocupaciones base ponderadas por flota (defaults del editor)
_wocc = P.wocc
base_sede_occ = _wocc(base_df, "sede")         # grupo -> frac (en alcance)
base_cat_occ = _wocc(base_df, "acriss")        # acriss -> frac (en alcance)
base_cat_occ_all = _wocc(base_df_all, "acriss")  # acriss -> frac (global, para overrides 'cat')
fleet_sede = base_df.groupby("sede")["n"].sum()
fleet_cat = base_df.groupby("acriss")["n"].sum()
# ocupacion base de cada celda (sede, acriss): referencia de los overrides por celda
cell_occ = base_df.set_index(["sede", "acriss"])["occ_base"].to_dict()

sedes_present = [s for s in SEDE_ORDER if s in set(base_df["sede"])]
cats_present = list(base_df.groupby("acriss")["n"].sum().sort_values(ascending=False).index)

# Una sola ciudad en el alcance -> la tabla de categorias es POR SEDE: lo que se
# edita y guarda es la ocupacion esperada de esa (sede x categoria).
SINGLE = len(sedes_present) == 1
SCOPE_G = sedes_present[0] if SINGLE else None
SCOPE_TAG = SCOPE_G if SINGLE else "all"

_alcance = (SEDE_NICE[SCOPE_G] if SINGLE
            else (", ".join(SEDE_NICE[s] for s in sedes_present) if sel_grupos
                  else "todas las sedes"))
st.caption(
    _cap_base
    + f" Alcance: **{_alcance}** (filtro de sedes del sidebar)."
    + f" Flota: foto del padrón al **{snap_date}**"
    + (" (cierre del mes anterior)." if snap_date == target - dt.timedelta(days=1)
       else " (la más reciente disponible).")
    + (" Mes ya cerrado: el presupuesto se reconstruye con la información que había "
       "al inicio del mes." if _es_pasado else ""))
try:
    st.page_link("pages/11_Presupuesto_Traslados.py",
                 label="Ver este mes con traslados (carros que cambian de ciudad dentro del mes)")
except Exception:   # fuera de la app multipagina (p. ej. AppTest) no hay registro de paginas
    st.caption("Este mes con traslados: página **Presupuesto con traslados** del menú.")

# =============================================================================
# Overrides guardados (sede + categoria)
# =============================================================================
saved_sede, saved_cat, saved_cell = P.saved_overrides(target.isoformat())
_cell_en_alcance = {k for k in saved_cell if k.split("|")[0] in set(sedes_present)}
_hay_override = bool(
    {s for s in saved_sede if s in set(sedes_present)} or saved_cat or _cell_en_alcance)

# Factor de un override global de categoria (se mide contra la base GLOBAL, no la
# del alcance, para que ver una sola sede no cambie el numero del escenario guardado).
def _fcat_saved(a):
    b = base_cat_occ_all.get(a, 0)
    return (saved_cat[a] / 100.0) / b if (a in saved_cat and b) else 1.0

CAT_DIM = "sede_cat" if SINGLE else "cat"
def _catkey(a): return f"{SCOPE_G}|{a}" if SINGLE else a

def _def_cat_pct(a):
    """Default del editor de categorias, en % de ocupacion esperada."""
    if SINGLE:
        k = _catkey(a)
        if k in saved_cell:
            return saved_cell[k]
        # sin override de celda: la base de ESTA sede ajustada por el override global
        return base_cat_occ.get(a, 0) * 100 * _fcat_saved(a)
    return saved_cat.get(a, base_cat_occ.get(a, 0) * 100)

# Sin redondear: si nadie edita, el factor queda exactamente en 1 (el editor ya
# muestra 1 decimal por su format). Antes el redondeo metia ~0,02% de ruido y el
# total no coincidia al centavo con la pagina de traslados.
def_sede_pct = {s: float(saved_sede.get(s, base_sede_occ.get(s, 0) * 100)) for s in sedes_present}
def_cat_pct = {a: float(_def_cat_pct(a)) for a in cats_present}

# El alcance cambia el conjunto de filas de los editores; si la key no cambia,
# session_state["edited_rows"] mapearia indices a la categoria/sede equivocada.
KEY_SEDE = f"occ_sede_{target.isoformat()}_{SCOPE_TAG}"
KEY_CAT = f"occ_cat_{target.isoformat()}_{SCOPE_TAG}"

def _live_occ(key, claves, defaults_pct):
    """Lee las ediciones del data_editor desde session_state y devuelve {clave: frac}."""
    out = dict(defaults_pct)
    stt = st.session_state.get(key)
    if isinstance(stt, dict):
        for ridx, ch in stt.get("edited_rows", {}).items():
            if "Ocupación esperada (%)" in ch:
                try:
                    out[claves[int(ridx)]] = float(ch["Ocupación esperada (%)"])
                except Exception:
                    pass
    return {c: (v or 0) / 100.0 for c, v in out.items()}

occ_sede = _live_occ(KEY_SEDE, sedes_present, def_sede_pct)
occ_cat = _live_occ(KEY_CAT, cats_present, def_cat_pct)
factor_sede = {s: (occ_sede[s] / base_sede_occ[s]) if base_sede_occ.get(s, 0) else 1.0
               for s in sedes_present}
factor_cat = {a: (occ_cat[a] / base_cat_occ[a]) if base_cat_occ.get(a, 0) else 1.0
              for a in cats_present}

# =============================================================================
# Calculo del presupuesto
# =============================================================================
def _fc(row):
    """Factor de categoria de la celda. Un override por CELDA (sede x categoria)
    manda sobre el factor global de la categoria, en cualquier alcance."""
    if not SINGLE:
        k = f"{row['sede']}|{row['acriss']}"
        if k in saved_cell:
            b = cell_occ.get((row["sede"], row["acriss"]), 0)
            if b:
                return (saved_cell[k] / 100.0) / b
    return factor_cat.get(row["acriss"], 1.0)

df = base_df.copy()
df["fs"] = df["sede"].map(factor_sede).fillna(1.0)
df["fc"] = df.apply(_fc, axis=1).astype(float) if not df.empty else 1.0
df["occ_final"] = (df["occ_base"] * df["fs"] * df["fc"]).clip(upper=0.98)
df["rented"] = df["n"] * DAYS * df["occ_final"]
df["rev"] = df["rented"] * df["rpd"]

tot_rev = df["rev"].sum()
tot_fleet = int(df["n"].sum())
tot_cardays = tot_fleet * DAYS
tot_rented = df["rented"].sum()
occ_glob = tot_rented / tot_cardays if tot_cardays else 0

k1, k2, k3, k4 = st.columns(4)
kpi(k1, f"Presupuesto tarifa ({MON})", fmt_money(tot_rev, MON),
    "escenario editado" if _hay_override else "pre-calculado")
kpi(k2, "Flota", fmt_int(tot_fleet), f"{fmt_int(tot_cardays)} carro-días")
kpi(k3, "Ocupación", f"{occ_glob*100:.1f}%", f"{fmt_int(round(tot_rented))} días rentados")
kpi(k4, f"RPD tarifa ({MON})", fmt_money(tot_rev / tot_rented if tot_rented else 0, MON),
    "tarifa por día rentado")

def _rev_at(mult):
    occ = (df["occ_base"] * df["fs"] * df["fc"] * mult).clip(upper=0.98)
    return (df["n"] * DAYS * occ * df["rpd"]).sum()
section("Escenarios (± ocupación)")
sc1, sc2, sc3 = st.columns(3)
kpi(sc1, "Conservador (−10%)", fmt_money(_rev_at(0.90), MON))
kpi(sc2, "Base (editado)", fmt_money(tot_rev, MON))
kpi(sc3, "Optimista (+10%)", fmt_money(_rev_at(1.10), MON))

st.info("Editá la columna **Ocupación esperada (%)** en cualquiera de las dos tablas "
        "(por sede y por categoría). Los ajustes se **combinan** y el presupuesto "
        "recalcula al instante. Luego **Guardar** para fijar el escenario.")


# =============================================================================
# Por sede (editable)
# =============================================================================
section("Por sede")
bs = df.groupby("sede").agg(n=("n", "sum"), rented=("rented", "sum"), rev=("rev", "sum"))
sede_ed_df = pd.DataFrame({
    "Sede": [SEDE_NICE[s] for s in sedes_present],
    "Flota": [int(fleet_sede.get(s, 0)) for s in sedes_present],
    "Ocupación esperada (%)": [def_sede_pct[s] for s in sedes_present],
    "RPD": [fmt_money(bs.loc[s, "rev"] / bs.loc[s, "rented"] if bs.loc[s, "rented"] else 0, MON)
            for s in sedes_present],
    "Presupuesto": [fmt_money(bs.loc[s, "rev"], MON) for s in sedes_present],
})
st.data_editor(
    sede_ed_df, hide_index=True, use_container_width=True, key=KEY_SEDE,
    disabled=["Sede", "Flota", "RPD", "Presupuesto"],
    column_config={"Ocupación esperada (%)": st.column_config.NumberColumn(
        min_value=0.0, max_value=100.0, step=0.5, format="%.1f")},
)

# =============================================================================
# Por categoria (editable)
# =============================================================================
if SINGLE:
    section(f"Por categoría (ACRISS) — {SEDE_NICE[SCOPE_G]}")
    st.caption(
        f"Flota, ocupación y RPD **solo de {SEDE_NICE[SCOPE_G]}**. Lo que edites y "
        "guardes acá queda como la ocupación esperada de esa sede × categoría, y "
        "manda sobre el ajuste global de la categoría. Para volver a la vista "
        "consolidada, limpiá el filtro de sedes del sidebar.")
else:
    section("Por categoría (ACRISS)")
    st.caption(
        "Consolidado de todas las sedes en alcance. Para desglosar por sede, elegí "
        "una sede en el sidebar. El RPD de tarifa manda: una camioneta rinde mucho "
        "más por día que un económico.")
    if sel_grupos:
        st.warning(
            "Con varias sedes seleccionadas, lo que guardes en esta tabla queda como "
            "ajuste **global** de la categoría (aplica también a las sedes fuera del "
            "filtro). Para guardar una ocupación propia de una sede, seleccioná esa "
            "sola sede en el sidebar.")
bc = df.groupby("acriss").agg(n=("n", "sum"), rented=("rented", "sum"), rev=("rev", "sum"))
bc["revpau"] = bc["rev"] / (bc["n"] * DAYS)
# El editor usa el orden ESTABLE cats_present (por flota), para que el mapeo
# fila->categoria en _live_occ no cambie al editar.
cat_ed_df = pd.DataFrame({
    "Categoría": cats_present,
    "Flota": [int(fleet_cat.get(a, 0)) for a in cats_present],
    "Ocupación esperada (%)": [def_cat_pct.get(a, 0) for a in cats_present],
    "RPD tarifa": [fmt_money(bc.loc[a, "rev"] / bc.loc[a, "rented"] if bc.loc[a, "rented"] else 0, MON)
                   for a in cats_present],
    "RevPAU": [fmt_money(bc.loc[a, "revpau"], MON) for a in cats_present],
    "Presupuesto": [fmt_money(bc.loc[a, "rev"], MON) for a in cats_present],
})
st.data_editor(
    cat_ed_df, hide_index=True, use_container_width=True, key=KEY_CAT,
    disabled=["Categoría", "Flota", "RPD tarifa", "RevPAU", "Presupuesto"],
    column_config={"Ocupación esperada (%)": st.column_config.NumberColumn(
        min_value=0.0, max_value=100.0, step=0.5, format="%.1f")},
)


# =============================================================================
# Guardar / Volver a lo pre-calculado
# =============================================================================
_msg = st.session_state.pop("_presup_msg", None)
if _msg:
    st.success(_msg)

c1, c2, _ = st.columns([1.3, 1.6, 3])
_UPSERT_OCC = """
    INSERT INTO operational.presupuesto_ocupacion (mes, dimension, clave, ocupacion_pct, updated_by, updated_at)
    VALUES (:m,:d,:k,:o,:u,NOW())
    ON CONFLICT (mes,dimension,clave) DO UPDATE SET ocupacion_pct=EXCLUDED.ocupacion_pct,
        updated_by=EXCLUDED.updated_by, updated_at=NOW()
"""

if c1.button("Guardar cambios", type="primary"):
    # UNA sola transaccion (lista de dicts -> executemany): o entra el escenario
    # completo o no entra nada. Antes era un execute_write por fila y un fallo a
    # mitad de camino dejaba la mitad del escenario guardado.
    # float() explicito: los valores vienen de Series de pandas (np.float64) y
    # psycopg2 los serializa con repr() -> 'np.float64(65.4)' en numpy 2.x, que
    # Postgres lee como funcion del schema 'np'. common.to_py() ya lo cubre, esto
    # lo deja evidente en el call site.
    _usr = _u.get("username")
    rows = [{"m": target.isoformat(), "d": "sede", "k": s,
             "o": round(float(occ_sede[s]) * 100, 2), "u": _usr} for s in sedes_present]
    rows += [{"m": target.isoformat(), "d": CAT_DIM, "k": _catkey(a),
              "o": round(float(occ_cat[a]) * 100, 2), "u": _usr} for a in cats_present]
    try:
        execute_write(_UPSERT_OCC, rows)
    except Exception as ex:
        st.error(f"No se pudo guardar el escenario: {type(ex).__name__}. "
                 "No se guardo nada (la escritura es atomica).")
        st.exception(ex)
        st.stop()
    load_query.clear()
    # El mensaje va a session_state: st.success() antes de un st.rerun() se pierde
    # (la pagina se vuelve a pintar de cero y el usuario no ve ninguna confirmacion).
    st.session_state["_presup_msg"] = (
        f"Escenario guardado ({SEDE_NICE[SCOPE_G]}): {len(rows)} filas."
        if SINGLE else f"Escenario guardado: {len(rows)} filas.")
    st.rerun()
if c2.button("Volver a lo pre-calculado"):
    # Con una sede en alcance se borra SOLO lo de esa sede; en consolidado, todo el mes.
    if SINGLE:
        execute_write("""
            DELETE FROM operational.presupuesto_ocupacion
            WHERE mes = :m AND ((dimension = 'sede' AND clave = :g)
                             OR (dimension = 'sede_cat' AND clave LIKE :p))
        """, {"m": target.isoformat(), "g": SCOPE_G, "p": f"{SCOPE_G}|%"})
    else:
        execute_write("DELETE FROM operational.presupuesto_ocupacion WHERE mes = :m",
                      {"m": target.isoformat()})
    st.session_state.pop(KEY_SEDE, None)
    st.session_state.pop(KEY_CAT, None)
    load_query.clear()
    st.session_state["_presup_msg"] = (
        f"Escenario de {SEDE_NICE[SCOPE_G]} borrado — se muestra lo pre-calculado."
        if SINGLE else "Escenario borrado — se muestra lo pre-calculado.")
    st.rerun()


# =============================================================================
# Placas en el calculo (auditable)
# =============================================================================
# Mismo DataFrame del que sale el conteo de flota, asi que la cantidad de filas por
# ciudad x categoria es EXACTAMENTE la columna Flota de las tablas de arriba.
_pl = plates_all[plates_all["g"].isin(sedes_present)].copy()
_pl["_o"] = _pl["g"].map({s: i for i, s in enumerate(SEDE_ORDER)})
_pl = _pl.sort_values(["_o", "acriss", "acriss_sixt", "placa"])
_pl["occ_win"] = _pl["dias_rentados"] / _pl["dias_flota"].replace(0, pd.NA)
section("Placas en el cálculo")
st.caption(
    f"Las **{len(_pl)} placas** con las que se calcula la flota del presupuesto "
    f"(padrón activo al {snap_date}), por ciudad × categoría. **ACRISS Sixt** es la "
    "categoría original; **Categoría** es la del presupuesto (SDAH se cuenta como "
    "EDAH y CDMR como EDMR). La ciudad sale del último día libre de la placa. "
    f"Días rentados / en flota: ventana {_MES_ES[win_start.month]}–"
    f"{_MES_ES[win_end.month]} {win_end.year} (0 = la placa entró después).")
with st.expander(f"Ver listado ({len(_pl)} placas)", expanded=False):
    _res = (_pl.groupby(["g", "acriss"]).size().rename("Placas").reset_index()
            .assign(Ciudad=lambda x: x["g"].map(SEDE_NICE))
            .pivot_table(index="acriss", columns="Ciudad", values="Placas",
                         aggfunc="sum", fill_value=0))
    _res = _res[[SEDE_NICE[s] for s in sedes_present if SEDE_NICE[s] in _res.columns]]
    _res["Total"] = _res.sum(axis=1)
    st.markdown("**Resumen: placas por categoría × ciudad**")
    st.dataframe(_res.rename_axis("Categoría").reset_index(),
                 hide_index=True, use_container_width=True)
    _out = pd.DataFrame({
        "Ciudad": _pl["g"].map(SEDE_NICE),
        "Categoría": _pl["acriss"],
        "ACRISS Sixt": _pl["acriss_sixt"],
        "Placa": _pl["placa"],
        "Sede": _pl["sede"],
        "Último día libre": _pl["ult_dia_libre"],
        "Última renta": _pl["ult_renta"],
        "Días rentados (ventana)": _pl["dias_rentados"].astype(int),
        "Días en flota (ventana)": _pl["dias_flota"].astype(int),
        "Ocupación ventana (%)": (_pl["occ_win"] * 100).astype(float).round(1),
    })
    st.dataframe(_out, hide_index=True, use_container_width=True,
                 height=min(600, 38 + 35 * len(_out)))
    xlsx_download_button(_out, file_name=f"presupuesto_placas_{target.isoformat()}",
                         sheet_name="Placas", key="presup_placas_xlsx")


# =============================================================================
# Comparacion vs el mismo mes del ano anterior (delta)
# =============================================================================
py = target.year - 1
section(f"Comparación vs {_MES_ES[target.month]} {py}"
        + ("" if target > dt.date(today.year, today.month, 1) else f" y real {target.year}"))
prev_a = dt.date(py, target.month, 1)
prev_b = dt.date(py, target.month, calendar.monthrange(py, target.month)[1])
# Fuente: gold_cargo_dia codigo T (la misma que el desglose de Analitica), NO
# gold_carro_dia.tar_. gold_carro_dia solo trae placas del roster ACTIVO de hoy, asi
# que el ingreso de los carros que salieron de la flota desaparece del pasado: la
# brecha crece con la antiguedad (carro/cargo = 99,7% en 2026, 95% en 2025, 85% en
# sep-2024) y subestimaba el "Real" del ano anterior. Ej. Bogota sep-2025:
# 19.768,28 (carro_dia) vs 20.327,60 (cargo_dia) USD.
prev_rev = P.real_t(prev_a.isoformat(), prev_b.isoformat(), SUF)
prev_rev = prev_rev[prev_rev.index.isin(sedes_present)]   # mismo alcance

# Real del MISMO mes del ano presupuestado (historico / mes en curso). Corte en el
# ultimo dia COMPLETO de gold: el dia del refresh trae las rentas a medias.
_mend = target + dt.timedelta(days=DAYS - 1)
_cut = min(_mend, _last_day - dt.timedelta(days=1))
cur_rev = (P.real_t(target.isoformat(), _cut.isoformat(), SUF)
           if _cut >= target else pd.Series(dtype=float))
cur_rev = cur_rev[cur_rev.index.isin(sedes_present)]
_parcial = _cut < _mend
_lbl_cur = f"Real {target.year}" + (f" (al {_cut.day}-{_MES_ES[_cut.month][:3]})" if _parcial else "")

if prev_rev.sum() == 0 and cur_rev.sum() == 0:
    st.info(f"No hay datos de {_MES_ES[target.month]} {py} para comparar.")
else:
    prev_tot = float(prev_rev.sum())
    cols = st.columns(4 if len(cur_rev) else 3)
    kpi(cols[0], f"Presupuesto {_MES_ES[target.month]} {target.year}", fmt_money(tot_rev, MON))
    kpi(cols[1], f"Real {_MES_ES[target.month]} {py}", fmt_money(prev_tot, MON))
    _delta = (tot_rev / prev_tot - 1) * 100 if prev_tot else 0
    kpi(cols[2], "Delta vs año anterior", f"{_delta:+.1f}%", "presupuesto vs mismo mes año pasado")
    if len(cur_rev):
        _cur_tot = float(cur_rev.sum())
        kpi(cols[3], _lbl_cur, fmt_money(_cur_tot, MON),
            ("a la fecha; el avance contra lo presupuestado al día está en la página "
             "con traslados") if _parcial
            else f"{_cur_tot / tot_rev * 100:.1f}% del presupuesto" if tot_rev else "")
    comp = bs.reset_index()[["sede", "rev"]].rename(columns={"rev": "presup"})
    comp["real_prev"] = comp["sede"].map(prev_rev.to_dict()).fillna(0.0)
    comp["delta"] = comp["presup"] / comp["real_prev"].replace(0, pd.NA) - 1
    comp = comp.set_index("sede").reindex(sedes_present).reset_index()
    tbl = {
        "Sede": [SEDE_NICE[s] for s in comp["sede"]],
        "Presupuesto": comp["presup"].map(lambda v: fmt_money(v, MON)),
        f"Real {py}": comp["real_prev"].map(lambda v: fmt_money(v, MON)),
        "Delta vs año anterior": comp["delta"].map(
            lambda v: f"{v*100:+.1f}%" if pd.notna(v) else "nuevo"),
    }
    if len(cur_rev):
        _cr = comp["sede"].map(cur_rev.to_dict()).fillna(0.0)
        tbl[_lbl_cur] = _cr.map(lambda v: fmt_money(v, MON))
        if not _parcial:
            tbl["Cumplimiento"] = [f"{r / p_ * 100:.1f}%" if p_ else "-"
                                   for r, p_ in zip(_cr, comp["presup"])]
    st.dataframe(pd.DataFrame(tbl), hide_index=True, use_container_width=True)
    st.caption(
        f"**Real** = cargo T de `silver.gold_cargo_dia` (todos los contratos, incluidos "
        "los carros que ya salieron de la flota), el mismo número que el desglose por "
        "código de Analítica para ese mes y año. Ojo: es una transformación de la capa "
        "silver y puede tener diferencias con COBRA; se va revisando.")

st.caption(
    "Presupuesto = flota × días × ocupación esperada × RPD de tarifa (solo cargo T). "
    f"Factor estacional {factor:.2f} vs {_MES_ES[target.month]} {py}. La **flota** es "
    f"la foto del padrón al {snap_date} y se usa entera los {DAYS} días; los carros que "
    "cambian de ciudad DENTRO del mes se ven en la página **Presupuesto con traslados**. "
    "La **ocupación** y el **RPD** son tasas de la ventana de 3 meses. Fuente: "
    "silver.gold_carro_dia. "
    + ("**Escenario guardado activo.**" if _hay_override else "Estado pre-calculado."))
