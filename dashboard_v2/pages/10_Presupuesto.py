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
- Ocupacion base y RPD: run-rate 3 meses completos x factor estacional (mes objetivo
  vs ese mismo mes el ano anterior). Son tasas; lo que multiplica es la flota de hoy.
- La ocupacion esperada se puede editar POR SEDE y POR CATEGORIA; ambos ajustes se
  combinan (multiplican) sobre la base.
- La pagina respeta el FILTRO DE SEDES del sidebar (agrupado por ciudad). Con una
  sola ciudad en alcance, la tabla de categorias es por (sede x ACRISS) y se guarda
  con dimension 'sede_cat' / clave 'GRUPO|ACRISS'; ese override por celda manda
  sobre el ajuste global de la categoria en cualquier alcance.
- Guardar (operational.presupuesto_ocupacion) / Volver a lo pre-calculado.
- Comparacion contra el mismo mes del ano anterior (delta).
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
    load_query, execute_write,
)
from components.filters import render_sidebar_filters
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
# Mes objetivo + ventana reciente
# =============================================================================
today = dt.date.today()
def _add_month(d: dt.date, k: int) -> dt.date:
    m = d.month - 1 + k
    return dt.date(d.year + m // 12, m % 12 + 1, 1)

_opts = [_add_month(dt.date(today.year, today.month, 1), k) for k in (0, 1, 2)]
_MES_ES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
           "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
def _mes_label(d): return f"{_MES_ES[d.month].capitalize()} {d.year}"
target = st.selectbox("Mes a presupuestar", options=_opts, index=1, format_func=_mes_label)
DAYS = calendar.monthrange(target.year, target.month)[1]

_last_complete = dt.date(today.year, today.month, 1) - dt.timedelta(days=1)
win_end = dt.date(_last_complete.year, _last_complete.month,
                  calendar.monthrange(_last_complete.year, _last_complete.month)[1])
win_start = _add_month(dt.date(win_end.year, win_end.month, 1), -2)

_cap_base = (
    f"Presupuestando **{_mes_label(target)}** ({DAYS} días). Base: run-rate "
    f"**{_MES_ES[win_start.month]} – {_MES_ES[win_end.month]} {win_end.year}** "
    f"(3 meses completos). Moneda: **{MON}**. Solo tarifa (cargo T), sin adicionales "
    f"ni coberturas ni tax.")

SEDE_ORDER = ["BOGOTA", "MEDELLIN", "BUCARAMANGA", "PEREIRA"]
SEDE_NICE = {"BOGOTA": "Bogotá", "MEDELLIN": "Medellín",
             "BUCARAMANGA": "Bucaramanga", "PEREIRA": "Pereira"}
NICE_TO_GRP = {v: k for k, v in SEDE_NICE.items()}
def _grp(sede: str) -> str:
    u = (sede or "").upper()
    for k in SEDE_ORDER:
        if k in u:
            return k
    return "OTRA"


# =============================================================================
# Datos base (cache): metricas por (sede, categoria) de la ventana reciente
# =============================================================================
@st.cache_data(ttl=600)
def _base_inputs(win_start: str, win_end: str, target_iso: str, suf: str):
    m = load_query(f"""
        SELECT sede, acriss, SUM(rented_day) AS rented, COUNT(*) AS fleet_days,
               SUM(tar_{suf}) AS t_val
        FROM silver.gold_carro_dia WHERE fecha BETWEEN :a AND :b
        GROUP BY sede, acriss
    """, {"a": win_start, "b": win_end})
    m["g"] = m["sede"].map(_grp)
    for c in ("rented", "fleet_days", "t_val"):
        m[c] = pd.to_numeric(m[c], errors="coerce").fillna(0.0)

    cat = m.groupby("acriss").agg(rented=("rented", "sum"),
                                  fleet_days=("fleet_days", "sum"),
                                  t_val=("t_val", "sum")).reset_index()
    cat["occ_c"] = cat["rented"] / cat["fleet_days"].replace(0, pd.NA)
    cat["rpd_c"] = cat["t_val"] / cat["rented"].replace(0, pd.NA)
    catm = cat.set_index("acriss")[["occ_c", "rpd_c"]].to_dict("index")

    # FLOTA = snapshot del padron ACTIVO al ultimo dia disponible de gold_carro_dia,
    # NO un conteo de la ventana historica. Un carro que entra despues del cierre de
    # la ventana (p.ej. el 24-sep cuando la ventana es jun-ago) tiene CERO dias ahi y
    # antes contaba 0 en el presupuesto; la flota solo crecia con ~2 meses de retraso.
    # (La baja si era inmediata: el roster de gold_carro_dia es el activo actual, asi
    # que un defleeteado desaparece retroactivamente de la ventana.) Ocupacion y RPD
    # siguen saliendo de la ventana de 3 meses -- son tasas; lo que multiplica es la
    # flota de hoy. La sede se toma como la sede MODAL de los ultimos 30 dias (mas
    # estable que la del dia exacto, que para un carro en renta es la de su contrato).
    fl = load_query("""
        WITH last AS (SELECT MAX(fecha) AS f FROM silver.gold_carro_dia),
        act AS (
            SELECT DISTINCT g.placa, g.acriss
            FROM silver.gold_carro_dia g, last WHERE g.fecha = last.f),
        loc AS (
            SELECT g.placa, g.sede,
                   ROW_NUMBER() OVER (PARTITION BY g.placa
                                      ORDER BY COUNT(*) DESC, MAX(g.fecha) DESC) rn
            FROM silver.gold_carro_dia g, last
            WHERE g.fecha > last.f - 30 GROUP BY g.placa, g.sede)
        SELECT l.sede, a.acriss, COUNT(*) AS n
        FROM act a JOIN loc l ON l.placa = a.placa AND l.rn = 1
        GROUP BY l.sede, a.acriss
    """, {})
    fl["g"] = fl["sede"].map(_grp)
    fleet = fl.groupby(["g", "acriss"], as_index=False)["n"].sum()
    snap = load_query("SELECT MAX(fecha) AS f FROM silver.gold_carro_dia", {})
    snap_date = snap.iloc[0]["f"] if not snap.empty else None

    # factor estacional del mes objetivo (ano anterior): occ(mes) / occ(ventana)
    ty, tm = int(target_iso[:4]), int(target_iso[5:7])
    py = ty - 1
    ws_prev = f"{py}-{win_start[5:7]}-01"
    we_prev = f"{py}-{win_end[5:7]}-{win_end[8:10]}"
    tgt_prev_a = f"{py}-{tm:02d}-01"
    tgt_prev_b = f"{py}-{tm:02d}-{calendar.monthrange(py, tm)[1]:02d}"
    sf = load_query("""
        SELECT
          SUM(rented_day) FILTER (WHERE fecha BETWEEN :ta AND :tb)::float
            / NULLIF(COUNT(*) FILTER (WHERE fecha BETWEEN :ta AND :tb),0) AS occ_tgt,
          SUM(rented_day) FILTER (WHERE fecha BETWEEN :wa AND :wb)::float
            / NULLIF(COUNT(*) FILTER (WHERE fecha BETWEEN :wa AND :wb),0) AS occ_win
        FROM silver.gold_carro_dia WHERE fecha BETWEEN :wa AND :tb
    """, {"ta": tgt_prev_a, "tb": tgt_prev_b, "wa": ws_prev, "wb": we_prev})
    occ_t = sf.iloc[0]["occ_tgt"]; occ_w = sf.iloc[0]["occ_win"]
    factor = float(occ_t / occ_w) if occ_t and occ_w else 1.0
    factor = max(0.5, min(1.5, factor))

    mg = m.groupby(["g", "acriss"], as_index=False).agg(
        rented=("rented", "sum"), fleet_days=("fleet_days", "sum"), t_val=("t_val", "sum"))
    mg["occ"] = mg["rented"] / mg["fleet_days"].replace(0, pd.NA)
    mg["rpd"] = mg["t_val"] / mg["rented"].replace(0, pd.NA)
    scd = mg.set_index(["g", "acriss"])[["rented", "occ", "rpd"]].to_dict("index")

    # fallback global: una categoria/sede recien incorporada puede no tener NADA de
    # historia en la ventana. Sin este piso quedaria con occ=0 y aportaria $0.
    occ_glob_win = float(m["rented"].sum() / m["fleet_days"].sum()) if m["fleet_days"].sum() else 0.0
    rpd_glob_win = float(m["t_val"].sum() / m["rented"].sum()) if m["rented"].sum() else 0.0

    rows = []
    for _, fr in fleet.iterrows():
        g, a, n = fr["g"], fr["acriss"], int(fr["n"])
        cell = scd.get((g, a), {})
        occ = cell.get("occ"); rpd = cell.get("rpd"); rented = cell.get("rented", 0) or 0
        if pd.isna(occ) or rented < 20:
            occ = catm.get(a, {}).get("occ_c")
        if pd.isna(rpd) or rented < 20:
            rpd = catm.get(a, {}).get("rpd_c")
        occ = float(occ) if pd.notna(occ) else occ_glob_win
        rpd = float(rpd) if pd.notna(rpd) else rpd_glob_win
        rows.append({"sede": g, "acriss": a, "n": n,
                     "occ_base": min(occ * factor, 0.98), "rpd": rpd})
    return pd.DataFrame(rows), factor, snap_date

base_df_all, factor, snap_date = _base_inputs(win_start.isoformat(), win_end.isoformat(),
                                              target.isoformat(), SUF)
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
def _wocc(df, by):
    num = (df["n"] * df["occ_base"]).groupby(df[by]).sum()
    den = df.groupby(by)["n"].sum()
    return (num / den.replace(0, pd.NA)).fillna(0.0)
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
    + (f" Flota: foto del padrón activo al **{snap_date}**." if snap_date else ""))

# =============================================================================
# Overrides guardados (sede + categoria)
# =============================================================================
_ov = load_query(
    "SELECT dimension, clave, ocupacion_pct FROM operational.presupuesto_ocupacion WHERE mes = :m",
    {"m": target.isoformat()})
saved_sede = {r["clave"]: float(r["ocupacion_pct"]) for _, r in _ov.iterrows()
              if r["dimension"] == "sede" and pd.notna(r["ocupacion_pct"])}
saved_cat = {r["clave"]: float(r["ocupacion_pct"]) for _, r in _ov.iterrows()
             if r["dimension"] == "cat" and pd.notna(r["ocupacion_pct"])}
# overrides por CELDA (sede x categoria), clave 'GRUPO|ACRISS'
saved_cell = {r["clave"]: float(r["ocupacion_pct"]) for _, r in _ov.iterrows()
              if r["dimension"] == "sede_cat" and pd.notna(r["ocupacion_pct"])}
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

def_sede_pct = {s: round(saved_sede.get(s, base_sede_occ.get(s, 0) * 100), 1) for s in sedes_present}
def_cat_pct = {a: round(_def_cat_pct(a), 1) for a in cats_present}

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
c1, c2, _ = st.columns([1.3, 1.6, 3])
if c1.button("Guardar cambios", type="primary"):
    for s in sedes_present:
        execute_write("""
            INSERT INTO operational.presupuesto_ocupacion (mes, dimension, clave, ocupacion_pct, updated_by, updated_at)
            VALUES (:m,'sede',:k,:o,:u,NOW())
            ON CONFLICT (mes,dimension,clave) DO UPDATE SET ocupacion_pct=EXCLUDED.ocupacion_pct, updated_by=EXCLUDED.updated_by, updated_at=NOW()
        """, {"m": target.isoformat(), "k": s, "o": round(occ_sede[s] * 100, 2), "u": _u.get("username")})
    for a in cats_present:
        execute_write(f"""
            INSERT INTO operational.presupuesto_ocupacion (mes, dimension, clave, ocupacion_pct, updated_by, updated_at)
            VALUES (:m,'{CAT_DIM}',:k,:o,:u,NOW())
            ON CONFLICT (mes,dimension,clave) DO UPDATE SET ocupacion_pct=EXCLUDED.ocupacion_pct, updated_by=EXCLUDED.updated_by, updated_at=NOW()
        """, {"m": target.isoformat(), "k": _catkey(a), "o": round(occ_cat[a] * 100, 2),
              "u": _u.get("username")})
    load_query.clear()
    st.success(f"Escenario guardado ({SEDE_NICE[SCOPE_G]})." if SINGLE else "Escenario guardado.")
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
    st.info("Escenario borrado — se muestra lo pre-calculado.")
    st.rerun()


# =============================================================================
# Comparacion vs el mismo mes del ano anterior (delta)
# =============================================================================
py = target.year - 1
section(f"Comparación vs {_MES_ES[target.month]} {py}")
prev_a = dt.date(py, target.month, 1)
prev_b = dt.date(py, target.month, calendar.monthrange(py, target.month)[1])
prev = load_query(f"""
    SELECT sede, SUM(tar_{SUF}) AS t_val FROM silver.gold_carro_dia
    WHERE fecha BETWEEN :a AND :b GROUP BY sede
""", {"a": prev_a.isoformat(), "b": prev_b.isoformat()})
prev["t_val"] = pd.to_numeric(prev["t_val"], errors="coerce").fillna(0.0)
prev["g"] = prev["sede"].map(_grp)
prev = prev[prev["g"].isin(sedes_present)]   # mismo alcance que el presupuesto
if prev["t_val"].sum() == 0:
    st.info(f"No hay datos de {_MES_ES[target.month]} {py} para comparar.")
else:
    prev_rev = prev.groupby("g")["t_val"].sum()
    prev_tot = float(prev_rev.sum())
    d1, d2, d3 = st.columns(3)
    kpi(d1, f"Presupuesto {_MES_ES[target.month]} {target.year}", fmt_money(tot_rev, MON))
    kpi(d2, f"Real {_MES_ES[target.month]} {py}", fmt_money(prev_tot, MON))
    _delta = (tot_rev / prev_tot - 1) * 100 if prev_tot else 0
    kpi(d3, "Delta", f"{_delta:+.1f}%", "presupuesto vs mismo mes año pasado")
    comp = bs.reset_index()[["sede", "rev"]].rename(columns={"rev": "presup"})
    comp["real_prev"] = comp["sede"].map(prev_rev.to_dict()).fillna(0.0)
    comp["delta"] = comp["presup"] / comp["real_prev"].replace(0, pd.NA) - 1
    comp = comp.set_index("sede").reindex(sedes_present).reset_index()
    st.dataframe(pd.DataFrame({
        "Sede": [SEDE_NICE[s] for s in comp["sede"]],
        "Presupuesto": comp["presup"].map(lambda v: fmt_money(v, MON)),
        f"Real {py}": comp["real_prev"].map(lambda v: fmt_money(v, MON)),
        "Delta": comp["delta"].map(lambda v: f"{v*100:+.1f}%" if pd.notna(v) else "nuevo"),
    }), hide_index=True, use_container_width=True)

st.caption(
    "Presupuesto = flota × días × ocupación esperada × RPD de tarifa (solo cargo T). "
    f"Factor estacional {factor:.2f} vs {_MES_ES[target.month]} {py}. La **flota** es "
    f"el padrón activo al {snap_date} (un carro que ingresa hoy entra al presupuesto "
    "tras el próximo refresh del pipeline); la **ocupación** y el **RPD** son tasas "
    "de la ventana de 3 meses. Fuente: silver.gold_carro_dia. "
    + ("**Escenario guardado activo.**" if _hay_override else "Estado pre-calculado."))
