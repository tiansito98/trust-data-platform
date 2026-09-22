"""
Presupuesto de ventas (SOLO tarifa, codigo T) — solo trust_admin.

El presupuesto se calcula UNICAMENTE sobre las rentas de carro (cargo T), sin
adicionales, coberturas ni tax. Fuente: silver.gold_carro_dia (columna tar_usd/
tar_cop = tarifa T prorrateada por dia 24h+gracia, lado RENTAL_COUNTER).

Modelo bottom-up por (sede x categoria ACRISS):
    presupuesto = flota x dias_mes x ocupacion_esperada x RPD_tarifa

- Ocupacion base: run-rate de los ultimos 3 meses completos, ajustado por
  estacionalidad (mes objetivo vs ese mismo mes el anio anterior).
- RPD tarifa: tarifa T por dia rentado (ultimos 3 meses), con fallback al promedio
  de la categoria si la celda sede x categoria tiene pocos datos.

Interactivo:
  1. Editar la ocupacion esperada por sede -> recalcula en vivo (escenarios).
  2. Guardar cambios (operational.presupuesto_ocupacion) / Volver a lo pre-calculado.
  3. Comparacion contra el mismo mes del anio anterior (delta).
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

# --- Tabla de overrides (self-healing) ---
@st.cache_resource
def _ensure_table():
    try:
        execute_write("""
            CREATE TABLE IF NOT EXISTS operational.presupuesto_ocupacion (
                mes           date NOT NULL,
                sede          text NOT NULL,
                ocupacion_pct numeric,
                updated_by    text,
                updated_at    timestamptz DEFAULT now(),
                PRIMARY KEY (mes, sede)
            )
        """, {})
    except Exception:
        pass
_ensure_table()

filtros = render_sidebar_filters(default_days=30)
MON = filtros.moneda                          # "USD" o "COP"
SUF = "cop" if MON == "COP" else "usd"

# =============================================================================
# Mes objetivo + ventana reciente
# =============================================================================
today = dt.date.today()
def _add_month(d: dt.date, k: int) -> dt.date:
    m = d.month - 1 + k
    return dt.date(d.year + m // 12, m % 12 + 1, 1)

# opciones: este mes, proximo, +2  (default = proximo)
_opts = [_add_month(dt.date(today.year, today.month, 1), k) for k in (0, 1, 2)]
_labels = {d: d.strftime("%B %Y").capitalize() for d in _opts}
target = st.selectbox("Mes a presupuestar", options=_opts,
                      index=1, format_func=lambda d: _labels[d])
DAYS = calendar.monthrange(target.year, target.month)[1]

# ventana reciente = 3 meses completos terminando en el ultimo mes COMPLETO
_last_complete = dt.date(today.year, today.month, 1) - dt.timedelta(days=1)   # ultimo dia mes pasado
win_end = dt.date(_last_complete.year, _last_complete.month,
                  calendar.monthrange(_last_complete.year, _last_complete.month)[1])
win_start = _add_month(dt.date(win_end.year, win_end.month, 1), -2)

st.caption(
    f"Presupuestando **{_labels[target]}** ({DAYS} dias). Base: run-rate "
    f"**{win_start:%b %Y} – {win_end:%b %Y}** (3 meses completos). Moneda: **{MON}**. "
    f"Solo tarifa (cargo T), sin adicionales ni coberturas."
)

SEDE_ORDER = ["BOGOTA", "MEDELLIN", "BUCARAMANGA", "PEREIRA"]
SEDE_NICE = {"BOGOTA": "Bogota", "MEDELLIN": "Medellin",
             "BUCARAMANGA": "Bucaramanga", "PEREIRA": "Pereira"}
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
    # metricas por (sede, acriss) en la ventana
    m = load_query(f"""
        SELECT sede, acriss,
               SUM(rented_day)  AS rented,
               COUNT(*)         AS fleet_days,
               SUM(tar_{suf})   AS t_val
        FROM silver.gold_carro_dia
        WHERE fecha BETWEEN :a AND :b
        GROUP BY sede, acriss
    """, {"a": win_start, "b": win_end})
    m["g"] = m["sede"].map(_grp)
    for c in ("rented", "fleet_days", "t_val"):
        m[c] = pd.to_numeric(m[c], errors="coerce").fillna(0.0)

    # fallback categoria-nivel (rpd + occ) para celdas con pocos datos
    cat = m.groupby("acriss").agg(rented=("rented", "sum"),
                                  fleet_days=("fleet_days", "sum"),
                                  t_val=("t_val", "sum")).reset_index()
    cat["occ_c"] = cat["rented"] / cat["fleet_days"].replace(0, pd.NA)
    cat["rpd_c"] = cat["t_val"] / cat["rented"].replace(0, pd.NA)
    catm = cat.set_index("acriss")[["occ_c", "rpd_c"]].to_dict("index")

    # flota por (sede, cat): cada placa a su sede+cat dominante en la ventana
    fl = load_query("""
        WITH j AS (
            SELECT placa, acriss, sede, COUNT(*) d,
                   ROW_NUMBER() OVER (PARTITION BY placa ORDER BY COUNT(*) DESC) rn
            FROM silver.gold_carro_dia
            WHERE fecha BETWEEN :a AND :b
            GROUP BY placa, acriss, sede)
        SELECT sede, acriss, COUNT(*) n FROM j WHERE rn = 1 GROUP BY sede, acriss
    """, {"a": win_start, "b": win_end})
    fl["g"] = fl["sede"].map(_grp)
    fleet = fl.groupby(["g", "acriss"])["n"].sum().reset_index()

    # factor estacional del mes objetivo (anio anterior): occ(mes) / occ(ventana)
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
        FROM silver.gold_carro_dia
        WHERE fecha BETWEEN :wa AND :tb
    """, {"ta": tgt_prev_a, "tb": tgt_prev_b, "wa": ws_prev, "wb": we_prev})
    occ_t = sf.iloc[0]["occ_tgt"]; occ_w = sf.iloc[0]["occ_win"]
    factor = float(occ_t / occ_w) if occ_t and occ_w else 1.0
    factor = max(0.5, min(1.5, factor))       # clamp defensivo

    # ensamblar por (sede, cat): occ base (estacional), rpd_t, flota
    m["occ"] = m["rented"] / m["fleet_days"].replace(0, pd.NA)
    m["rpd"] = m["t_val"] / m["rented"].replace(0, pd.NA)
    sc = m.set_index(["g", "acriss"])[["rented", "occ", "rpd"]].to_dict("index")

    rows = []
    for _, fr in fleet.iterrows():
        g, a, n = fr["g"], fr["acriss"], int(fr["n"])
        cell = sc.get((g, a), {})
        occ = cell.get("occ"); rpd = cell.get("rpd"); rented = cell.get("rented", 0)
        src = "sede"
        if pd.isna(occ) or rented is None or rented < 20:
            occ = catm.get(a, {}).get("occ_c"); src = "cat"
        if pd.isna(rpd) or rented is None or rented < 20:
            rpd = catm.get(a, {}).get("rpd_c"); src = "cat"
        occ = float(occ) if pd.notna(occ) else 0.0
        rpd = float(rpd) if pd.notna(rpd) else 0.0
        rows.append({"sede": g, "acriss": a, "n": n,
                     "occ_season": min(occ * factor, 0.98), "rpd": rpd, "src": src})
    return pd.DataFrame(rows), factor

base_df, factor = _base_inputs(win_start.isoformat(), win_end.isoformat(),
                               target.isoformat(), SUF)

if base_df.empty:
    st.info("No hay datos suficientes en la ventana reciente para presupuestar.")
    st.stop()

# ocupacion base ponderada por sede (para el editor)
def _sede_occ(df, col):
    g = df.groupby("sede").apply(
        lambda x: (x["n"] * x[col]).sum() / x["n"].sum() if x["n"].sum() else 0.0)
    return g
base_sede_occ = _sede_occ(base_df, "occ_season")   # ocupacion pre-calculada por sede


# =============================================================================
# Overrides guardados + editor de ocupacion esperada
# =============================================================================
saved = load_query(
    "SELECT sede, ocupacion_pct FROM operational.presupuesto_ocupacion WHERE mes = :m",
    {"m": target.isoformat()})
saved_map = dict(zip(saved["sede"], pd.to_numeric(saved["ocupacion_pct"], errors="coerce")))

sedes_present = [s for s in SEDE_ORDER if s in set(base_df["sede"])]
editor_rows = []
for s in sedes_present:
    pre = round(float(base_sede_occ.get(s, 0)) * 100, 1)
    val = float(saved_map[s]) if s in saved_map and pd.notna(saved_map[s]) else pre
    editor_rows.append({"Sede": SEDE_NICE.get(s, s),
                        "Ocupacion pre-calculada (%)": pre,
                        "Ocupacion esperada (%)": round(val, 1)})
editor_df = pd.DataFrame(editor_rows)

section("Ocupacion esperada por sede")
st.caption(
    "La ocupacion **pre-calculada** = run-rate reciente ajustado por estacionalidad "
    f"(factor {factor:.2f} vs {target.strftime('%B')} del anio pasado). Edita la "
    "columna **esperada** para tus escenarios; el presupuesto recalcula al instante.")

edited = st.data_editor(
    editor_df,
    hide_index=True, use_container_width=True,
    disabled=["Sede", "Ocupacion pre-calculada (%)"],
    column_config={
        "Ocupacion esperada (%)": st.column_config.NumberColumn(
            "Ocupacion esperada (%)", min_value=0.0, max_value=100.0,
            step=0.5, format="%.1f"),
    },
    key=f"occ_editor_{target.isoformat()}",
)
exp_occ = {}   # sede (grupo) -> ocupacion esperada (fraccion)
for _, r in edited.iterrows():
    g = next((k for k, v in SEDE_NICE.items() if v == r["Sede"]), r["Sede"].upper())
    exp_occ[g] = float(r["Ocupacion esperada (%)"]) / 100.0

c1, c2, _ = st.columns([1.2, 1.5, 3])
if c1.button("Guardar cambios", type="primary"):
    for _, r in edited.iterrows():
        g = next((k for k, v in SEDE_NICE.items() if v == r["Sede"]), r["Sede"].upper())
        execute_write("""
            INSERT INTO operational.presupuesto_ocupacion (mes, sede, ocupacion_pct, updated_by, updated_at)
            VALUES (:m, :s, :o, :u, NOW())
            ON CONFLICT (mes, sede) DO UPDATE
              SET ocupacion_pct = EXCLUDED.ocupacion_pct, updated_by = EXCLUDED.updated_by, updated_at = NOW()
        """, {"m": target.isoformat(), "s": g,
              "o": float(r["Ocupacion esperada (%)"]), "u": _u.get("username")})
    load_query.clear()
    st.success("Escenario guardado.")
    st.rerun()
if c2.button("Volver a lo pre-calculado"):
    execute_write("DELETE FROM operational.presupuesto_ocupacion WHERE mes = :m",
                  {"m": target.isoformat()})
    st.session_state.pop(f"occ_editor_{target.isoformat()}", None)
    load_query.clear()
    st.info("Escenario borrado — se muestra lo pre-calculado.")
    st.rerun()

_hay_override = any(s in saved_map for s in sedes_present)


# =============================================================================
# Calculo del presupuesto (con la ocupacion editada)
# =============================================================================
df = base_df.copy()
# factor por sede = ocupacion esperada / ocupacion pre-calculada
df["factor_sede"] = df["sede"].map(
    lambda s: (exp_occ.get(s, base_sede_occ.get(s, 0)) / base_sede_occ.get(s, 1))
    if base_sede_occ.get(s, 0) else 1.0)
df["occ_final"] = (df["occ_season"] * df["factor_sede"]).clip(upper=0.98)
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
kpi(k2, "Flota", fmt_int(tot_fleet), f"{fmt_int(tot_cardays)} carro-dias")
kpi(k3, "Ocupacion", f"{occ_glob*100:.1f}%", f"{fmt_int(round(tot_rented))} dias rentados")
kpi(k4, f"RPD tarifa ({MON})", fmt_money(tot_rev / tot_rented if tot_rented else 0, MON),
    "tarifa por dia rentado")

# --- rango de escenarios alrededor del editado ---
def _rev_at(mult):
    occ = (df["occ_season"] * df["factor_sede"] * mult).clip(upper=0.98)
    return (df["n"] * DAYS * occ * df["rpd"]).sum()
section("Escenarios")
sc1, sc2, sc3 = st.columns(3)
kpi(sc1, "Conservador (-10% ocup)", fmt_money(_rev_at(0.90), MON))
kpi(sc2, "Base (editado)", fmt_money(tot_rev, MON))
kpi(sc3, "Optimista (+10% ocup)", fmt_money(_rev_at(1.10), MON))


# =============================================================================
# Por sede
# =============================================================================
section("Por sede")
by_sede = df.groupby("sede").agg(
    n=("n", "sum"), rented=("rented", "sum"), rev=("rev", "sum")).reindex(sedes_present)
by_sede["cardays"] = by_sede["n"] * DAYS
by_sede["ocup"] = (by_sede["rented"] / by_sede["cardays"] * 100).round(1)
by_sede["rpd"] = (by_sede["rev"] / by_sede["rented"]).round(1)
vs = by_sede.reset_index()
vs["Sede"] = vs["sede"].map(SEDE_NICE)
vs["Presupuesto"] = vs["rev"].map(lambda v: fmt_money(v, MON))
vs["RPD"] = vs["rpd"].map(lambda v: fmt_money(v, MON))
vs["Ocupacion"] = vs["ocup"].map(lambda v: f"{v:.1f}%")
vs["Flota"] = vs["n"].astype(int)
vs["Dias rent."] = vs["rented"].round(0).astype(int)
st.dataframe(vs[["Sede", "Flota", "Ocupacion", "RPD", "Dias rent.", "Presupuesto"]],
             hide_index=True, use_container_width=True)


# =============================================================================
# Por categoria
# =============================================================================
section("Por categoria (ACRISS)")
st.caption("El RPD de tarifa manda: una camioneta rinde mucho mas por dia que un economico.")
by_cat = df.groupby("acriss").agg(
    n=("n", "sum"), rented=("rented", "sum"), rev=("rev", "sum")).reset_index()
by_cat["cardays"] = by_cat["n"] * DAYS
by_cat["ocup"] = (by_cat["rented"] / by_cat["cardays"] * 100).round(1)
by_cat["rpd"] = (by_cat["rev"] / by_cat["rented"]).round(1)
by_cat["revpau"] = (by_cat["rev"] / by_cat["cardays"]).round(1)
by_cat = by_cat.sort_values("revpau", ascending=False)
cv = pd.DataFrame({
    "Categoria": by_cat["acriss"],
    "Flota": by_cat["n"].astype(int),
    "Ocupacion": by_cat["ocup"].map(lambda v: f"{v:.1f}%"),
    "RPD tarifa": by_cat["rpd"].map(lambda v: fmt_money(v, MON)),
    "RevPAU": by_cat["revpau"].map(lambda v: fmt_money(v, MON)),
    "Presupuesto": by_cat["rev"].map(lambda v: fmt_money(v, MON)),
})
st.dataframe(cv, hide_index=True, use_container_width=True)


# =============================================================================
# Comparacion vs el mismo mes del anio anterior (delta)
# =============================================================================
section(f"Comparacion vs {target.strftime('%B %Y')} — 1 anio")
py = target.year - 1
prev_a = dt.date(py, target.month, 1)
prev_b = dt.date(py, target.month, calendar.monthrange(py, target.month)[1])
prev = load_query(f"""
    SELECT sede, SUM(tar_{SUF}) AS t_val, SUM(rented_day) AS rented, COUNT(*) AS cardays
    FROM silver.gold_carro_dia WHERE fecha BETWEEN :a AND :b GROUP BY sede
""", {"a": prev_a.isoformat(), "b": prev_b.isoformat()})
if prev.empty or pd.to_numeric(prev["t_val"], errors="coerce").fillna(0).sum() == 0:
    st.info(f"No hay datos de {target.strftime('%B %Y')} del anio pasado para comparar.")
else:
    prev["g"] = prev["sede"].map(_grp)
    prev_rev = pd.to_numeric(prev.groupby("g")["t_val"].sum(), errors="coerce")
    prev_tot = float(prev_rev.sum())
    dcol1, dcol2, dcol3 = st.columns(3)
    kpi(dcol1, f"Presupuesto {target.strftime('%b %Y')}", fmt_money(tot_rev, MON))
    kpi(dcol2, f"Real {prev_a.strftime('%b %Y')}", fmt_money(prev_tot, MON))
    _delta = (tot_rev / prev_tot - 1) * 100 if prev_tot else 0
    kpi(dcol3, "Delta", f"{_delta:+.1f}%",
        "presupuesto vs mismo mes anio pasado")
    # tabla por sede
    comp = by_sede.reset_index()[["sede", "rev"]].rename(columns={"rev": "presup"})
    comp["real_prev"] = comp["sede"].map(prev_rev.to_dict()).fillna(0.0)
    comp["delta_%"] = ((comp["presup"] / comp["real_prev"].replace(0, pd.NA) - 1) * 100).round(1)
    comp["Sede"] = comp["sede"].map(SEDE_NICE)
    comp["Presupuesto"] = comp["presup"].map(lambda v: fmt_money(v, MON))
    comp[f"Real {py}"] = comp["real_prev"].map(lambda v: fmt_money(v, MON))
    comp["Delta"] = comp["delta_%"].map(lambda v: f"{v:+.1f}%" if pd.notna(v) else "nuevo")
    st.dataframe(comp[["Sede", "Presupuesto", f"Real {py}", "Delta"]],
                 hide_index=True, use_container_width=True)

st.caption(
    "Presupuesto = flota x dias x ocupacion esperada x RPD de tarifa (solo cargo T, "
    "sin adicionales/coberturas/tax). Fuente: silver.gold_carro_dia. "
    + ("**Escenario guardado activo.**" if _hay_override else "Estado pre-calculado."))
