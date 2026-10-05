"""Logica compartida del presupuesto de tarifa (paginas 10_Presupuesto y
11_Presupuesto_Traslados).

Modelo por (ciudad x categoria ACRISS):
    presupuesto = carro-dias x ocupacion x RPD_tarifa

- 10_Presupuesto: carro-dias = flota de la FOTO x dias del mes (la foto es el padron
  al cierre del mes anterior, o la mas reciente si ese dia todavia no llego).
- 11_Presupuesto_Traslados: carro-dias = los dias que cada placa estuvo REALMENTE en
  cada ciudad (gold_carro_dia, dia por dia); los dias que todavia no pasaron se
  proyectan con la ubicacion actual. Si un carro se traslada el dia 5, la ciudad de
  origen se queda con los dias 1-4 y la de destino con el 5 en adelante.

Las tasas (ocupacion y RPD) y los escenarios guardados son los MISMOS en las dos
paginas: la unica diferencia es como se cuentan los carro-dias.

Estacionalidad: ocupacion Y RPD de la ventana reciente se multiplican cada uno por su
factor estacional = valor del mes objetivo el ano anterior / valor de la misma ventana
el ano anterior (tope 0,5-1,5). El de RPD se agrego el 2026-10-02: antes solo se
ajustaba la ocupacion y la tarifa de temporada baja quedaba sobreestimada (sep-2026:
factor RPD 0,894 sin aplicar; cumplimiento real 93,5%).

Exclusiones (operational.presupuesto_exclusion_placa): placas que el presupuesto
trata como si NO HUBIERAN EXISTIDO desde `desde_mes` (decision de negocio
2026-10-02: carros por salir de la flota o casi sin uso). Para todo mes >=
desde_mes se sacan de la flota, de la ventana de tasas, del factor estacional y de
los carro-dias de la pagina de traslados. Es lo mismo que hace gold solo cuando
Sixt los da de baja (borra su historia), asi que al salir no cambia nada mas. El
REAL (gold_cargo_dia) no se toca.

Reclasificaciones (operational.presupuesto_categoria_placa): placa -> ACRISS correcto
para el presupuesto (p.ej. cargadas mal en COBRA). Se aplican en la subconsulta _GC,
por la que pasan las lecturas de gold_carro_dia del presupuesto que usan la categoria.
"""
import calendar
import datetime as dt

import pandas as pd
import streamlit as st

from .common import load_query, execute_write

# Version del API de este modulo. SUBIRLA cada vez que cambie lo que las paginas
# esperan (nuevas funciones, nuevas claves en `rates`, etc.) y subir tambien
# P_API_REQUERIDA en las paginas. Motivo: tras un push, Streamlit Cloud recarga la
# pagina pero puede seguir sirviendo este modulo VIEJO desde sys.modules; la pagina
# nueva + el modulo viejo revento con KeyError: 'f_occ' (2026-10-02). Con la version,
# la pagina detecta el modulo viejo y lo recarga (ver load_presupuesto_module()).
API_VERSION = 5

SEDE_ORDER = ["BOGOTA", "MEDELLIN", "BUCARAMANGA", "PEREIRA"]
SEDE_NICE = {"BOGOTA": "Bogotá", "MEDELLIN": "Medellín",
             "BUCARAMANGA": "Bucaramanga", "PEREIRA": "Pereira"}
MES_ES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# Categorias que el presupuesto trata como UNA sola (decision de negocio 2026-10-02):
# en la operacion son el mismo producto y por separado partian la flota en celdas
# demasiado chicas para tener ocupacion/RPD estables. Aplica SOLO al presupuesto;
# el resto del dashboard sigue mostrando el ACRISS de Sixt. SDMR queda aparte.
ACRISS_CANON = {"SDAH": "EDAH", "CDMR": "EDMR"}

# Una celda (ciudad x categoria) necesita al menos estos dias rentados en la ventana
# para usar sus propias tasas; si no, cae a la tasa nacional de la categoria.
MIN_RENTED_CELL = 20

MES_KEY = "presup_mes"   # selector de mes compartido entre las dos paginas


EXCL_TABLE = "operational.presupuesto_exclusion_placa"


@st.cache_resource
def ensure_exclusion_table() -> None:
    execute_write(f"""
        CREATE TABLE IF NOT EXISTS {EXCL_TABLE} (
            placa       text PRIMARY KEY,
            desde_mes   date NOT NULL,
            motivo      text,
            created_by  text,
            created_at  timestamptz DEFAULT now()
        )
    """, {})


RECAT_TABLE = "operational.presupuesto_categoria_placa"


@st.cache_resource
def ensure_recat_table() -> None:
    execute_write(f"""
        CREATE TABLE IF NOT EXISTS {RECAT_TABLE} (
            placa       text PRIMARY KEY,
            acriss      text NOT NULL,
            motivo      text,
            created_by  text,
            created_at  timestamptz DEFAULT now()
        )
    """, {})


def recat_map() -> tuple:
    """Reclasificaciones de categoria SOLO para el presupuesto: ((placa, acriss), ...)
    ordenada. Caso de uso (2026-10-05): placas cargadas mal en COBRA (NPM571, NGW352,
    NPQ347 figuran EDMR y son SDMR). Se aplica a TODA la historia de la placa en las
    lecturas del presupuesto (flota, tasas, carro-dias), igual que ACRISS_CANON; el
    resto del dashboard sigue con el ACRISS de Sixt. Tupla -> sirve de llave de cache."""
    ensure_recat_table()
    d = load_query(f"SELECT placa, acriss FROM {RECAT_TABLE}", {})
    if not len(d):
        return ()
    return tuple(sorted(zip(d["placa"].astype(str).str.strip(),
                            d["acriss"].astype(str).str.strip().str.upper())))


def recategorizations_all() -> pd.DataFrame:
    ensure_recat_table()
    return load_query(f"""
        SELECT placa, acriss, motivo, created_by, created_at
        FROM {RECAT_TABLE} ORDER BY placa""", {})


# gold_carro_dia con la categoria reclasificada (si la placa tiene ajuste). Todas las
# lecturas del presupuesto que usan la categoria pasan por aca; acriss_orig = Sixt.
_GC = """(SELECT g0.placa, g0.fecha, g0.sede, g0.rented_day, g0.tar_usd, g0.tar_cop,
             g0.acriss AS acriss_orig,
             COALESCE((CAST(:ra AS text[]))[array_position(CAST(:rp AS text[]), g0.placa)],
                      g0.acriss) AS acriss
         FROM silver.gold_carro_dia g0)"""


def _rp(recat: tuple) -> dict:
    return {"rp": [p for p, _ in recat], "ra": [a for _, a in recat]}


def excluded_plates(target_iso: str) -> tuple:
    """Placas excluidas para el mes `target_iso` (desde_mes <= mes). Tupla ordenada:
    se pasa a las funciones cacheadas, asi el cache se invalida si cambia la lista."""
    ensure_exclusion_table()
    d = load_query(f"SELECT placa FROM {EXCL_TABLE} WHERE desde_mes <= :m",
                   {"m": target_iso})
    return tuple(sorted(d["placa"].astype(str).str.strip().unique())) if len(d) else ()


def exclusions_all() -> pd.DataFrame:
    ensure_exclusion_table()
    return load_query(f"""
        SELECT placa, desde_mes, motivo, created_by, created_at
        FROM {EXCL_TABLE} ORDER BY desde_mes, placa""", {})


def grp(sede: str) -> str:
    u = (sede or "").upper()
    for k in SEDE_ORDER:
        if k in u:
            return k
    return "OTRA"


def canon(a: str) -> str:
    return ACRISS_CANON.get(a, a)


def add_month(d: dt.date, k: int) -> dt.date:
    m = d.month - 1 + k
    return dt.date(d.year + m // 12, m % 12 + 1, 1)


def mes_label(d: dt.date) -> str:
    return f"{MES_ES[d.month].capitalize()} {d.year}"


def month_options(today: dt.date) -> list:
    """Todos los meses del ano en curso (para ver el historico) + los 2 siguientes."""
    d, end, out = dt.date(today.year, 1, 1), add_month(dt.date(today.year, today.month, 1), 2), []
    while d <= end:
        out.append(d)
        d = add_month(d, 1)
    return out


def month_selector(today: dt.date) -> dt.date:
    """Selectbox de mes. Persiste entre las dos paginas de presupuesto (misma key,
    pre-sembrada en session_state, mismo patron que components/filters.py)."""
    opts = month_options(today)
    nxt = add_month(dt.date(today.year, today.month, 1), 1)
    if st.session_state.get(MES_KEY) not in opts:
        st.session_state[MES_KEY] = nxt if nxt in opts else opts[-1]
    return st.selectbox("Mes a presupuestar", options=opts, format_func=mes_label, key=MES_KEY,
                        help="Todos los meses del año en curso (histórico) y los dos siguientes.")


def window_for(target: dt.date, today: dt.date) -> tuple:
    """Ventana de 3 meses completos ANTERIOR al mes presupuestado. Para un mes futuro
    no hay meses cerrados en el medio, asi que se usan los ultimos 3 cerrados."""
    ref = min(target, dt.date(today.year, today.month, 1))
    win_end = ref - dt.timedelta(days=1)
    win_start = add_month(dt.date(win_end.year, win_end.month, 1), -2)
    return win_start, win_end


@st.cache_data(ttl=600)
def last_gold_day() -> dt.date:
    d = load_query("SELECT MAX(fecha) AS f FROM silver.gold_carro_dia", {})
    return pd.to_datetime(d.iloc[0]["f"]).date()


def snapshot_date(target: dt.date, last_day: dt.date) -> dt.date:
    """Foto de flota: el PRIMER DIA del mes presupuestado (las placas con las que
    arranca el mes), o la mas reciente si ese dia todavia no llego.
    Hasta el 2026-10-05 era el cierre del mes anterior: un carro que amanecia el dia 1
    en otra ciudad quedaba mal (QKP640: al 31-ago figuraba en Bucaramanga y el 1-sep
    ya estaba en Bogota -> Bogota salia con 5 IDAH y Bucaramanga con 1, cuando el mes
    arranco con 6 y 0)."""
    return min(target, last_day)


@st.cache_data(ttl=600)
def fleet_snapshot(as_of_iso: str, win_start: str, win_end: str, excl: tuple = (),
                   recat: tuple = ()) -> pd.DataFrame:
    """UNA FILA POR PLACA activa en `as_of` (no conteos): el listado auditable y el
    conteo de flota salen del mismo DataFrame, asi que no pueden diferir.

    Ciudad = la del ULTIMO DIA LIBRE (rented_day=0) hasta `as_of`: un carro quieto
    esta parado en su sede real, y en gold esa sede solo se mueve con un TRASLADO.
    Se ignoran los dias rentados (ruido de one-way) y se cae a la sede del dia si la
    placa estuvo rentada los 120 dias. DISTINCT ON (placa) es una proteccion: hoy
    gold_carro_dia es unico por (placa, fecha).

    Sesgo conocido: gold_carro_dia solo trae placas del roster ACTIVO de hoy, asi que
    en una foto vieja faltan los carros que ya salieron de la flota (en 2026 es
    ~0,3% del ingreso; crece hacia atras).
    """
    plates = load_query("""
        WITH act AS (
            SELECT DISTINCT ON (g.placa) g.placa, g.acriss, g.acriss_orig, g.sede AS sede_snap
            FROM {GC} g WHERE g.fecha = CAST(:asof AS date)
              AND NOT (g.placa = ANY(:ex))
            ORDER BY g.placa, g.rented_day DESC),
        idle AS (
            SELECT DISTINCT ON (g.placa) g.placa, g.sede, g.fecha
            FROM {GC} g
            WHERE g.rented_day = 0 AND g.fecha > CAST(:asof AS date) - 120
              AND g.fecha <= CAST(:asof AS date)
            ORDER BY g.placa, g.fecha DESC),
        rec AS (
            SELECT g.placa, MAX(g.fecha) FILTER (WHERE g.rented_day = 1) AS ult_renta
            FROM {GC} g
            WHERE g.fecha > CAST(:asof AS date) - 120 AND g.fecha <= CAST(:asof AS date)
            GROUP BY g.placa),
        win AS (
            SELECT placa, SUM(rented_day) AS dias_rentados, COUNT(*) AS dias_flota
            FROM {GC} gc WHERE fecha BETWEEN :a AND :b GROUP BY placa)
        SELECT a.placa, COALESCE(i.sede, a.sede_snap) AS sede, a.acriss_orig AS acriss_sixt,
               a.acriss AS acriss_ppto,
               i.fecha AS ult_dia_libre, r.ult_renta,
               COALESCE(w.dias_rentados, 0) AS dias_rentados,
               COALESCE(w.dias_flota, 0) AS dias_flota
        FROM act a
        LEFT JOIN idle i ON i.placa = a.placa
        LEFT JOIN rec  r ON r.placa = a.placa
        LEFT JOIN win  w ON w.placa = a.placa
    """.replace("{GC}", _GC), {"asof": as_of_iso, "a": win_start, "b": win_end,
                               "ex": list(excl), **_rp(recat)})
    plates["g"] = plates["sede"].map(grp)
    plates["acriss"] = plates["acriss_ppto"].map(canon)
    return plates


def rate_lookup(rates: dict, g: str, a: str) -> tuple:
    """(ocupacion, RPD) crudos de una celda, con el fallback celda -> categoria
    nacional -> global. La ocupacion NO trae el factor estacional."""
    cell = rates["cell"].get((g, a), {})
    occ, rpd, rented = cell.get("occ"), cell.get("rpd"), cell.get("rented", 0) or 0
    if pd.isna(occ) or rented < MIN_RENTED_CELL:
        occ = rates["cat"].get(a, {}).get("occ_c")
    if pd.isna(rpd) or rented < MIN_RENTED_CELL:
        rpd = rates["cat"].get(a, {}).get("rpd_c")
    occ = float(occ) if pd.notna(occ) else rates["occ_glob"]
    rpd = float(rpd) if pd.notna(rpd) else rates["rpd_glob"]
    return occ, rpd


def cell_rpd(rates: dict, g: str, a: str) -> float:
    """RPD de tarifa de la celda YA con el factor estacional de RPD. Usar siempre este
    (no rate_lookup()[1]) para presupuestar."""
    return rate_lookup(rates, g, a)[1] * rates["f_rpd"]


@st.cache_data(ttl=600)
def base_inputs(win_start: str, win_end: str, target_iso: str, suf: str, as_of_iso: str,
                excl: tuple = (), recat: tuple = ()):
    """Tasas de la ventana + flota de la foto. Devuelve
    (base_df, factor_estacional_ocupacion, plates, rates); base_df = 1 fila por celda
    de la foto con n (placas), occ_base (con factor estacional, tope 98%) y rpd (con
    factor estacional de RPD). rates["f_occ"] / rates["f_rpd"] = los dos factores."""
    m = load_query(f"""
        SELECT sede, acriss, SUM(rented_day) AS rented, COUNT(*) AS fleet_days,
               SUM(tar_{suf}) AS t_val
        FROM {_GC} gc WHERE fecha BETWEEN :a AND :b
          AND NOT (placa = ANY(:ex))
        GROUP BY sede, acriss
    """, {"a": win_start, "b": win_end, "ex": list(excl), **_rp(recat)})
    m["g"] = m["sede"].map(grp)
    m["acriss"] = m["acriss"].map(canon)   # los groupby de abajo suman las unidas
    for c in ("rented", "fleet_days", "t_val"):
        m[c] = pd.to_numeric(m[c], errors="coerce").fillna(0.0)

    cat = m.groupby("acriss").agg(rented=("rented", "sum"), fleet_days=("fleet_days", "sum"),
                                  t_val=("t_val", "sum")).reset_index()
    cat["occ_c"] = cat["rented"] / cat["fleet_days"].replace(0, pd.NA)
    cat["rpd_c"] = cat["t_val"] / cat["rented"].replace(0, pd.NA)
    mg = m.groupby(["g", "acriss"], as_index=False).agg(
        rented=("rented", "sum"), fleet_days=("fleet_days", "sum"), t_val=("t_val", "sum"))
    mg["occ"] = mg["rented"] / mg["fleet_days"].replace(0, pd.NA)
    mg["rpd"] = mg["t_val"] / mg["rented"].replace(0, pd.NA)
    rates = {
        "cell": mg.set_index(["g", "acriss"])[["rented", "occ", "rpd"]].to_dict("index"),
        "cat": cat.set_index("acriss")[["occ_c", "rpd_c"]].to_dict("index"),
        # piso global: una categoria/ciudad sin NADA de historia no queda en $0
        "occ_glob": float(m["rented"].sum() / m["fleet_days"].sum()) if m["fleet_days"].sum() else 0.0,
        "rpd_glob": float(m["t_val"].sum() / m["rented"].sum()) if m["rented"].sum() else 0.0,
    }

    # factores estacionales del mes objetivo (ano anterior): valor(mes) / valor(ventana),
    # uno para ocupacion y otro para RPD. El de RPD SIEMPRE en USD, aunque se presupueste
    # en COP: en COP el cociente mezclaria la temporada con la variacion de la TRM entre
    # los dos periodos. El factor es una razon, asi que aplica igual al RPD en COP.
    ty, tm = int(target_iso[:4]), int(target_iso[5:7])
    py = ty - 1
    ws, we = dt.date.fromisoformat(win_start), dt.date.fromisoformat(win_end)
    ws_prev = dt.date(ws.year - 1, ws.month, 1).isoformat()
    we_prev = dt.date(we.year - 1, we.month, calendar.monthrange(we.year - 1, we.month)[1]).isoformat()
    tgt_prev_a = f"{py}-{tm:02d}-01"
    tgt_prev_b = f"{py}-{tm:02d}-{calendar.monthrange(py, tm)[1]:02d}"
    sf = load_query("""
        SELECT
          SUM(rented_day) FILTER (WHERE fecha BETWEEN :ta AND :tb)::float
            / NULLIF(COUNT(*) FILTER (WHERE fecha BETWEEN :ta AND :tb),0) AS occ_tgt,
          SUM(rented_day) FILTER (WHERE fecha BETWEEN :wa AND :wb)::float
            / NULLIF(COUNT(*) FILTER (WHERE fecha BETWEEN :wa AND :wb),0) AS occ_win,
          SUM(tar_usd) FILTER (WHERE fecha BETWEEN :ta AND :tb)::float
            / NULLIF(SUM(rented_day) FILTER (WHERE fecha BETWEEN :ta AND :tb),0) AS rpd_tgt,
          SUM(tar_usd) FILTER (WHERE fecha BETWEEN :wa AND :wb)::float
            / NULLIF(SUM(rented_day) FILTER (WHERE fecha BETWEEN :wa AND :wb),0) AS rpd_win
        FROM silver.gold_carro_dia
        WHERE fecha BETWEEN LEAST(CAST(:wa AS date), CAST(:ta AS date))
                        AND GREATEST(CAST(:wb AS date), CAST(:tb AS date))
          AND NOT (placa = ANY(:ex))
    """, {"ta": tgt_prev_a, "tb": tgt_prev_b, "wa": ws_prev, "wb": we_prev, "ex": list(excl)})
    occ_t, occ_w = sf.iloc[0]["occ_tgt"], sf.iloc[0]["occ_win"]
    factor = float(occ_t / occ_w) if pd.notna(occ_t) and pd.notna(occ_w) and occ_w else 1.0
    factor = max(0.5, min(1.5, factor))
    rpd_t, rpd_w = sf.iloc[0]["rpd_tgt"], sf.iloc[0]["rpd_win"]
    f_rpd = float(rpd_t / rpd_w) if pd.notna(rpd_t) and pd.notna(rpd_w) and rpd_w else 1.0
    f_rpd = max(0.5, min(1.5, f_rpd))
    rates["f_occ"], rates["f_rpd"] = factor, f_rpd

    plates = fleet_snapshot(as_of_iso, win_start, win_end, excl, recat)
    fleet = plates.groupby(["g", "acriss"], as_index=False).size().rename(columns={"size": "n"})
    rows = []
    for _, fr in fleet.iterrows():
        occ, _ = rate_lookup(rates, fr["g"], fr["acriss"])
        rows.append({"sede": fr["g"], "acriss": fr["acriss"], "n": int(fr["n"]),
                     "occ_base": min(occ * factor, 0.98),
                     "rpd": cell_rpd(rates, fr["g"], fr["acriss"])})
    return pd.DataFrame(rows), factor, plates, rates


def saved_overrides(target_iso: str) -> tuple:
    """Escenario guardado del mes: (por sede, por categoria, por celda 'GRUPO|ACRISS')."""
    ov = load_query(
        "SELECT dimension, clave, ocupacion_pct FROM operational.presupuesto_ocupacion WHERE mes = :m",
        {"m": target_iso})
    out = {"sede": {}, "cat": {}, "sede_cat": {}}
    for _, r in ov.iterrows():
        if r["dimension"] in out and pd.notna(r["ocupacion_pct"]):
            out[r["dimension"]][r["clave"]] = float(r["ocupacion_pct"])
    return out["sede"], out["cat"], out["sede_cat"]


OCC_COL = "Ocupación esperada (%)"
_UPSERT_OCC = """
    INSERT INTO operational.presupuesto_ocupacion
        (mes, dimension, clave, ocupacion_pct, updated_by, updated_at)
    VALUES (:m, :d, :k, :o, :u, NOW())
    ON CONFLICT (mes, dimension, clave) DO UPDATE SET ocupacion_pct = EXCLUDED.ocupacion_pct,
        updated_by = EXCLUDED.updated_by, updated_at = NOW()
"""


def override_rows(edited_rows: dict, claves: list, mes_iso: str, dimension: str,
                  user: str, keyfn=lambda c: c) -> list:
    """Filas a guardar a partir del `edited_rows` de un st.data_editor de ocupacion.
    Solo las filas EDITADAS: lo que nadie toco sigue siendo pre-calculado y acompana
    los datos de cada refresh. Celda vaciada -> se ignora."""
    rows = []
    for ridx, ch in (edited_rows or {}).items():
        v = ch.get(OCC_COL) if isinstance(ch, dict) else None
        i = int(ridx)
        if v is None or i >= len(claves):
            continue
        rows.append({"m": mes_iso, "d": dimension, "k": keyfn(claves[i]),
                     "o": round(float(v), 2), "u": user})
    return rows


def save_overrides(rows: list) -> None:
    """Guarda la ocupacion esperada editada (una transaccion). La lee la pagina con
    traslados via saved_overrides()."""
    if rows:
        execute_write(_UPSERT_OCC, rows)
        # load_query esta cacheado y el cache es GLOBAL (todas las sesiones): sin esto
        # la otra pagina (o otro usuario) seguiria viendo el escenario anterior.
        load_query.clear()


def wocc(df: pd.DataFrame, by: str) -> pd.Series:
    """Ocupacion base ponderada por flota, agrupada por `by`."""
    num = (df["n"] * df["occ_base"]).groupby(df[by]).sum()
    den = df.groupby(by)["n"].sum()
    return (num / den.replace(0, pd.NA)).fillna(0.0)


def scenario_occ(base_df_all, rates, factor, saved_sede, saved_cat, saved_cell):
    """Devuelve occ_final(g, a): la ocupacion del ESCENARIO GUARDADO para cualquier
    celda, incluso una que no esta en la foto (un carro que llego a una ciudad donde
    esa categoria no existia). Misma regla que 10_Presupuesto sin ediciones en vivo:
    factor_sede x factor_categoria sobre la base, y el override por celda manda sobre
    el de la categoria."""
    bso = wocc(base_df_all, "sede")
    bco = wocc(base_df_all, "acriss")
    cell_occ = base_df_all.set_index(["sede", "acriss"])["occ_base"].to_dict()
    fs = {g: (v / 100.0) / bso[g] for g, v in saved_sede.items() if bso.get(g, 0)}

    def occ_final(g, a):
        ob = cell_occ.get((g, a))
        if ob is None:
            ob = min(rate_lookup(rates, g, a)[0] * factor, 0.98)
        k = f"{g}|{a}"
        if k in saved_cell and cell_occ.get((g, a)):
            fc = (saved_cell[k] / 100.0) / cell_occ[(g, a)]
        elif a in saved_cat and bco.get(a, 0):
            fc = (saved_cat[a] / 100.0) / bco[a]
        else:
            fc = 1.0
        return min(ob * fs.get(g, 1.0) * fc, 0.98)
    return occ_final


@st.cache_data(ttl=600)
def daily_rows(desde_iso: str, hasta_iso: str, excl: tuple = (), recat: tuple = ()) -> pd.DataFrame:
    """gold_carro_dia crudo (placa x dia) en el rango, con ciudad y ACRISS unificado.
    La ciudad del dia es la de gold (`sede`): en un dia rentado es la sede que entrego
    el carro. Es la MISMA atribucion con la que se miden la ocupacion y el RPD, asi que
    los carro-dias y las tasas quedan coherentes."""
    d = load_query(f"""
        SELECT placa, fecha, sede, acriss, acriss_orig, rented_day
        FROM {_GC} gc WHERE fecha BETWEEN :a AND :b
          AND NOT (placa = ANY(:ex))
    """, {"a": desde_iso, "b": hasta_iso, "ex": list(excl), **_rp(recat)})
    d["fecha"] = pd.to_datetime(d["fecha"]).dt.date
    d["g"] = d["sede"].map(grp)
    d["acriss_sixt"] = d["acriss_orig"]
    d["acriss"] = d["acriss"].map(canon)
    return d


@st.cache_data(ttl=600)
def real_t(desde_iso: str, hasta_iso: str, suf: str) -> pd.Series:
    """Ingreso REAL de tarifa (cargo T) por ciudad, de gold_cargo_dia (todos los
    contratos, incluidos los carros que ya salieron de la flota). Es una
    transformacion de silver: puede tener diferencias con COBRA."""
    d = load_query(f"""
        SELECT sede, SUM(subtotal_{suf}) AS t_val FROM silver.gold_cargo_dia
        WHERE fecha BETWEEN :a AND :b AND cargo_codigo = 'T' GROUP BY sede
    """, {"a": desde_iso, "b": hasta_iso})
    d["t_val"] = pd.to_numeric(d["t_val"], errors="coerce").fillna(0.0)
    d["g"] = d["sede"].map(grp)
    return d.groupby("g")["t_val"].sum()
