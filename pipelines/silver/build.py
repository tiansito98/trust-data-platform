"""
Silver build (target: Supabase Postgres schema 'silver').

Lee bronze.* (mismo Supabase, schema separado), reconstruye dim_/fact_/views
en silver, y crea schema vacio para op_* (Tramo 2) sin tocarlas si ya existen.

Estrategia:
  1. dim_*  y fact_*  -> rebuild completo (DROP + CREATE AS SELECT desde bronze).
  2. op_*           -> CREATE TABLE IF NOT EXISTS (Trust las llena por su lado).
  3. vw_*           -> rebuild como TABLE (DROP TABLE/VIEW + CREATE TABLE AS).
  4. dim_dates      -> generada localmente con calendario 2020-2030 + festivos CO.

Bronze y silver viven en el mismo Postgres como schemas distintos; no hace
falta ATTACH. search_path se setea a "silver, bronze" para que queries sin
prefijo resuelvan correctamente.

Correr:
    python -m pipelines.silver.build
"""
from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipelines._common import get_engine, log_path  # noqa: E402


SCRIPT_DIR = Path(__file__).parent
DDL_DIR = SCRIPT_DIR / "ddl"
LOG_FILE = log_path("silver_build")


def log(msg: str):
    print(msg, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()}  {msg}\n")


def _exec(engine, sql: str):
    with engine.begin() as conn:
        # Apaga el statement_timeout para esta transaccion. Necesario para
        # queries grandes como vw_rentals_detail (~100K rows + self-joins).
        # Requiere que ALTER ROLE postgres SET statement_timeout='15min'
        # se haya corrido una vez via setup_postgres.sql.
        conn.execute(text("SET LOCAL statement_timeout = 0"))
        conn.execute(text(sql))


def _scalar(engine, sql: str):
    with engine.connect() as conn:
        row = conn.execute(text(sql)).fetchone()
    return row[0] if row else None


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(
        line for line in sql.splitlines()
        if not line.lstrip().startswith("--")
    )


def run_ddl(engine, ddl_file: Path):
    log(f"\n>> Ejecutando {ddl_file.name}")
    if not ddl_file.exists():
        log("   (skip - no existe)")
        return
    sql = _strip_sql_comments(ddl_file.read_text(encoding="utf-8"))
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    fails = 0
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                fails += 1
                log(f"   FAIL en statement: {stmt[:120].replace(chr(10), ' ')}...")
                log(f"   error: {e}")
    log(f"   {len(statements)} statements ejecutados ({fails} con error)")


# =============================================================================
# Festivos CO + ACRISS decoder (logica pura Python)
# =============================================================================

HOLIDAYS_CO = {
    "01-01": "Anio Nuevo", "05-01": "Dia del Trabajo",
    "07-20": "Dia de la Independencia", "08-07": "Batalla de Boyaca",
    "12-08": "Inmaculada Concepcion", "12-25": "Navidad",
}


def is_holiday_co(d: date) -> tuple[int, str | None]:
    key = f"{d.month:02d}-{d.day:02d}"
    if key in HOLIDAYS_CO:
        return (1, HOLIDAYS_CO[key])
    return (0, None)


_ACRISS_L1 = {
    "M": "Mini", "N": "Mini Elite", "E": "Economy", "H": "Economy Elite",
    "C": "Compact", "D": "Compact Elite", "I": "Intermediate",
    "J": "Intermediate Elite", "S": "Standard", "R": "Standard Elite",
    "F": "Fullsize", "G": "Fullsize Elite", "P": "Premium", "U": "Premium Elite",
    "L": "Luxury", "W": "Luxury Elite", "O": "Oversize", "X": "Special",
}
_ACRISS_L2 = {
    "B": "2-3 puertas", "C": "2-4 puertas", "D": "4-5 puertas", "W": "Wagon",
    "V": "Van", "L": "Limousine", "S": "Sport", "T": "Convertible", "F": "SUV",
    "J": "Open Air", "X": "Especial", "P": "Pickup regular",
    "Q": "Pickup cabina extendida", "Z": "Especial", "E": "Coupe",
    "M": "Monospace", "R": "Recreational", "H": "Motorhome", "Y": "2 ruedas",
    "N": "Roadster", "G": "Crossover", "K": "Truck",
}
_ACRISS_L3 = {
    "M": "Manual", "N": "Manual 4WD", "C": "Manual AWD",
    "A": "Automatica", "B": "Automatica 4WD", "D": "Automatica AWD",
}
_ACRISS_L4 = {
    "R": ("Gasolina", 1),    "N": ("Gasolina", 0),
    "D": ("Diesel", 1),      "Q": ("Diesel", 0),
    "H": ("Hibrido", 1),     "I": ("Hibrido", 0),
    "E": ("Electrico", 1),   "C": ("Electrico", 0),
    "L": ("LPG/GLP", 1),     "S": ("LPG/GLP", 0),
    "A": ("Hidrogeno", 1),   "B": ("Hidrogeno", 0),
    "M": ("Multi-fuel", 1),  "F": ("Multi-fuel", 0),
    "V": ("Hibrido enchufable", 1), "Z": ("Hibrido enchufable", 0),
    "U": ("Etanol", 1),      "X": ("Etanol", 0),
}


def _decode_acriss(crs: str) -> tuple:
    if not crs or len(crs) != 4:
        return (None, None, None, None, None, crs or None)
    l1, l2, l3, l4 = crs[0].upper(), crs[1].upper(), crs[2].upper(), crs[3].upper()
    cat = _ACRISS_L1.get(l1)
    tipo = _ACRISS_L2.get(l2)
    trans = _ACRISS_L3.get(l3)
    fuel, ac = _ACRISS_L4.get(l4, (None, None))
    parts = [p for p in [cat, tipo, trans, fuel] if p]
    label = " · ".join(parts) if parts else crs
    return (cat, tipo, trans, fuel, ac, label)


# =============================================================================
# Builders
# =============================================================================

def build_dim_vehicle_groups_decoded(engine):
    log("\n>> Construyendo dim_vehicle_groups_decoded (ACRISS parseado)")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.dim_vehicle_groups_decoded CASCADE")
    _exec(engine, """
        CREATE TABLE silver.dim_vehicle_groups_decoded (
            vhgr_crs            TEXT PRIMARY KEY,
            categoria           TEXT,
            tipo_vehiculo       TEXT,
            transmision         TEXT,
            combustible         TEXT,
            aire_acondicionado  INTEGER,
            label_humano        TEXT,
            categoria_level1    TEXT,
            categoria_level2    TEXT,
            categoria_level3    TEXT
        )
    """)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT vhgr_crs, vhgr_category_level1, vhgr_category_level2, vhgr_category_level3
            FROM silver.dim_vehicle_groups
            WHERE vhgr_crs IS NOT NULL
        """)).fetchall()
    payload = []
    for crs, l1, l2, l3 in rows:
        cat, tipo, trans, fuel, ac, label = _decode_acriss(crs)
        payload.append({
            "vhgr_crs": crs, "categoria": cat, "tipo_vehiculo": tipo,
            "transmision": trans, "combustible": fuel,
            "aire_acondicionado": ac, "label_humano": label,
            "categoria_level1": l1, "categoria_level2": l2, "categoria_level3": l3,
        })
    if payload:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO silver.dim_vehicle_groups_decoded
                (vhgr_crs, categoria, tipo_vehiculo, transmision, combustible,
                 aire_acondicionado, label_humano,
                 categoria_level1, categoria_level2, categoria_level3)
                VALUES (:vhgr_crs, :categoria, :tipo_vehiculo, :transmision,
                        :combustible, :aire_acondicionado, :label_humano,
                        :categoria_level1, :categoria_level2, :categoria_level3)
            """), payload)
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.dim_vehicle_groups_decoded")
    log(f"   {n} grupos decodificados ({time.time()-started:.1f}s)")


def build_rentals_enriched(engine):
    log("\n>> Construyendo vw_rentals_enriched")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_rentals_enriched CASCADE")
    _exec(engine, """
        CREATE TABLE silver.vw_rentals_enriched AS
        SELECT
            r.rntl_mvnr, r.rsrv_resn, r.rntl_status,
            r.brnc_code_handover, bh.brnc_name AS sede_handover,
            r.brnc_code_return, br.brnc_name AS sede_return,
            r.rntl_handover_date, r.rntl_return_date,
            r.rntl_rental_days AS dias,
            r.rntl_payment_type AS tipo_pago,
            r.rntl_payment_type_code AS tipo_pago_code,
            r.vhcl_int_num, v.vhcl_plate AS matricula,
            r.vhgr_crs, g.categoria, g.tipo_vehiculo, g.transmision,
            g.combustible, g.aire_acondicionado, g.label_humano AS categoria_label,
            ROUND(r.rntl_revenue_main_local::numeric, 0)        AS revenue_base_cop,
            ROUND(r.rntl_revenue_secondary_local::numeric, 0)   AS revenue_extras_cop,
            ROUND(r.rntl_revenue_local_currency::numeric, 0)    AS revenue_total_cop,
            ROUND(r.rntl_revenue_main::numeric, 2)              AS revenue_base_eur,
            ROUND(r.rntl_revenue_secondary::numeric, 2)         AS revenue_extras_eur,
            ROUND(r.rntl_revenue::numeric, 2)                   AS revenue_total_eur,
            r.rntl_rental_currency_code                AS rental_currency,
            ROUND(r.rntl_revenue_main_rental::numeric, 2)       AS revenue_base_rental,
            ROUND(r.rntl_revenue_secondary_rental::numeric, 2)  AS revenue_extras_rental,
            ROUND(r.rntl_revenue_rental::numeric, 2)            AS revenue_total_rental,
            CASE WHEN r.rntl_rental_currency_code = 'USD'
                 THEN ROUND(r.rntl_revenue_main_rental::numeric, 2) END  AS revenue_base_usd,
            CASE WHEN r.rntl_rental_currency_code = 'USD'
                 THEN ROUND(r.rntl_revenue_secondary_rental::numeric, 2) END AS revenue_extras_usd,
            CASE WHEN r.rntl_rental_currency_code = 'USD'
                 THEN ROUND(r.rntl_revenue_rental::numeric, 2) END  AS revenue_total_usd,
            ROUND(r.rntl_revenue_main_paid::numeric, 2)         AS pagado_base,
            ROUND(r.rntl_revenue_secondary_paid::numeric, 2)    AS pagado_extras,
            r.rntl_paid_m_currency_code                AS paid_currency,
            ROUND(r.rntl_exchange_rate::numeric, 4)             AS xr_eur_to_cop,
            ROUND(r.rntl_exchange_rate_rental::numeric, 4)      AS xr_rentalcurr_to_cop
        FROM silver.fact_rentals r
        LEFT JOIN silver.dim_branches bh ON bh.brnc_code = r.brnc_code_handover
        LEFT JOIN silver.dim_branches br ON br.brnc_code = r.brnc_code_return
        LEFT JOIN silver.dim_vehicles v  ON v.vhcl_int_num = r.vhcl_int_num
        LEFT JOIN silver.dim_vehicle_groups_decoded g ON g.vhgr_crs = r.vhgr_crs
    """)
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_rent_enr_mvnr ON silver.vw_rentals_enriched(rntl_mvnr)")
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_rent_enr_resn ON silver.vw_rentals_enriched(rsrv_resn)")
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_rent_enr_brnc_h ON silver.vw_rentals_enriched(brnc_code_handover)")
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_rent_enr_handover ON silver.vw_rentals_enriched(rntl_handover_date)")
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_rentals_enriched")
    log(f"   {n:,} filas en vw_rentals_enriched ({time.time()-started:.1f}s)")


def build_cierre_diario_sede_table(engine):
    log("\n>> Materializando vw_cierre_diario_sede")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_cierre_diario_sede CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.vw_cierre_diario_sede CASCADE")
    _exec(engine, """
        CREATE TABLE silver.vw_cierre_diario_sede AS
        WITH
        fleet_per_branch AS (
            SELECT brnc_code, COUNT(*) AS total
            FROM silver.dim_vehicles_current
            WHERE brnc_code IS NOT NULL
            GROUP BY brnc_code
        ),
        rental_days AS (
            SELECT r.vhcl_int_num, d.full_date AS fecha
            FROM silver.fact_rentals r
            JOIN silver.dim_dates d
              ON d.full_date >= r.rntl_handover_date::date
             AND d.full_date <= COALESCE(r.rntl_return_date::date, CURRENT_DATE)
            WHERE r.vhcl_int_num IS NOT NULL AND r.rntl_handover_date IS NOT NULL
        ),
        rented_per_branch_day AS (
            SELECT vc.brnc_code, rd.fecha,
                   COUNT(DISTINCT rd.vhcl_int_num) AS rentados
            FROM rental_days rd
            JOIN silver.dim_vehicles_current vc ON vc.vhcl_int_num = rd.vhcl_int_num
            WHERE vc.brnc_code IS NOT NULL
            GROUP BY vc.brnc_code, rd.fecha
        ),
        reservations_pending_per_branch_day AS (
            SELECT r.brnc_code_handover AS brnc_code, d.full_date AS fecha,
                   COUNT(*) AS reservations_pending
            FROM silver.fact_reservations r
            JOIN silver.dim_dates d
              ON d.full_date >= r.rsrv_handover_date::date
             AND d.full_date <= COALESCE(r.rsrv_return_date::date, DATE '9999-12-31')
            WHERE r.rsrv_status = 'Open'
              AND r.brnc_code_handover IS NOT NULL
              AND r.rsrv_handover_date IS NOT NULL
            GROUP BY r.brnc_code_handover, d.full_date
        ),
        handovers_per_branch_day AS (
            SELECT brnc_code_handover AS brnc_code,
                   rntl_handover_date::date AS fecha, COUNT(*) AS rentals_count
            FROM silver.fact_rentals
            WHERE brnc_code_handover IS NOT NULL AND rntl_handover_date IS NOT NULL
            GROUP BY brnc_code_handover, rntl_handover_date::date
        ),
        returns_per_branch_day AS (
            SELECT brnc_code_return AS brnc_code,
                   rntl_return_date::date AS fecha, COUNT(*) AS returns_count
            FROM silver.fact_rentals
            WHERE brnc_code_return IS NOT NULL AND rntl_return_date IS NOT NULL
            GROUP BY brnc_code_return, rntl_return_date::date
        ),
        revenue_per_branch_day AS (
            SELECT r.brnc_code_handover AS brnc_code,
                   r.rntl_handover_date::date AS fecha,
                   COALESCE(SUM(c.chra_value_local), 0) AS revenue
            FROM silver.fact_rentals r
            LEFT JOIN silver.fact_charges_ra c ON c.chra_mvnr = r.rntl_mvnr
            WHERE r.brnc_code_handover IS NOT NULL AND r.rntl_handover_date IS NOT NULL
            GROUP BY r.brnc_code_handover, r.rntl_handover_date::date
        ),
        keys AS (
            SELECT brnc_code, fecha FROM rented_per_branch_day
            UNION SELECT brnc_code, fecha FROM reservations_pending_per_branch_day
            UNION SELECT brnc_code, fecha FROM handovers_per_branch_day
            UNION SELECT brnc_code, fecha FROM returns_per_branch_day
            UNION SELECT brnc_code, fecha FROM revenue_per_branch_day
        )
        SELECT
            k.brnc_code,
            k.fecha AS cier_date,
            (TO_CHAR(k.fecha, 'YYYYMMDD'))::INTEGER       AS cier_dtid,
            COALESCE(h.rentals_count, 0)                  AS cier_rentals_count,
            COALESCE(rt.returns_count, 0)                 AS cier_returns_count,
            COALESCE(rv.revenue, 0)                       AS cier_revenue_total,
            COALESCE(f.total, 0)                          AS cier_vehicles_in_branch,
            COALESCE(rd.rentados, 0)                      AS cier_vehicles_rented,
            COALESCE(rsv.reservations_pending, 0)         AS cier_reservations_pending,
            GREATEST(0, COALESCE(f.total, 0) - COALESCE(rd.rentados, 0)) AS cier_vehicles_available,
            GREATEST(0,
                COALESCE(f.total, 0)
                - COALESCE(rd.rentados, 0)
                - COALESCE(rsv.reservations_pending, 0)
            )                                             AS cier_vehicles_available_net,
            'DERIVED'                                     AS cier_status
        FROM keys k
        LEFT JOIN handovers_per_branch_day h ON h.brnc_code = k.brnc_code AND h.fecha = k.fecha
        LEFT JOIN returns_per_branch_day rt  ON rt.brnc_code = k.brnc_code AND rt.fecha = k.fecha
        LEFT JOIN revenue_per_branch_day rv  ON rv.brnc_code = k.brnc_code AND rv.fecha = k.fecha
        LEFT JOIN rented_per_branch_day rd   ON rd.brnc_code = k.brnc_code AND rd.fecha = k.fecha
        LEFT JOIN reservations_pending_per_branch_day rsv ON rsv.brnc_code = k.brnc_code AND rsv.fecha = k.fecha
        LEFT JOIN fleet_per_branch f         ON f.brnc_code = k.brnc_code
    """)
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_vw_cier_brnc_date ON silver.vw_cierre_diario_sede(brnc_code, cier_date)")
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_cierre_diario_sede")
    log(f"   {n:,} filas en vw_cierre_diario_sede ({time.time()-started:.1f}s)")


def build_dim_dates(engine, start: date = date(2020, 1, 1), end: date = date(2030, 12, 31)):
    """Idempotente: si dim_dates ya tiene el rango completo, hace skip.

    El calendario es estatico (no depende de bronze), asi que reconstruirlo
    cada silver.build es desperdicio. Solo lo llena si esta vacia o si el
    conteo de filas no coincide con el rango esperado (por si el rango
    cambia en el futuro).
    """
    expected = (end - start).days + 1
    current = _scalar(engine, "SELECT COUNT(*) FROM silver.dim_dates") or 0
    if current == expected:
        log(f"\n>> dim_dates ya esta completa ({current:,} dias) — skip")
        return

    log(f"\n>> Poblando dim_dates de {start} a {end} "
        f"(tenia {current:,}, esperado {expected:,})")
    _exec(engine, "DELETE FROM silver.dim_dates")
    es_months = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    es_days = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
    rows = []
    d = start
    while d <= end:
        dtid = int(d.strftime("%Y%m%d"))
        dow_iso = d.isoweekday()
        is_weekend = 1 if dow_iso in (6, 7) else 0
        is_hol, hol_name = is_holiday_co(d)
        rows.append({
            "dtid": dtid, "full_date": d,
            "year": d.year, "month": d.month, "month_name": es_months[d.month - 1],
            "day": d.day, "day_of_week": dow_iso, "day_name": es_days[dow_iso - 1],
            "week_of_year": int(d.strftime("%V")), "quarter": (d.month - 1) // 3 + 1,
            "is_weekend": is_weekend, "is_holiday_co": is_hol, "holiday_name": hol_name,
        })
        d += timedelta(days=1)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO silver.dim_dates
            (dtid, full_date, year, month, month_name, day, day_of_week,
             day_name, week_of_year, quarter, is_weekend, is_holiday_co, holiday_name)
            VALUES (:dtid, :full_date, :year, :month, :month_name, :day,
                    :day_of_week, :day_name, :week_of_year, :quarter,
                    :is_weekend, :is_holiday_co, :holiday_name)
        """), rows)
    log(f"   {len(rows):,} filas en dim_dates")


def report_counts(engine):
    log("\n" + "=" * 70)
    log("  RESUMEN SILVER")
    log("=" * 70)
    with engine.connect() as conn:
        tables = [r[0] for r in conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'silver' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)).fetchall()]
        views = [r[0] for r in conn.execute(text("""
            SELECT table_name FROM information_schema.views
            WHERE table_schema = 'silver'
            ORDER BY table_name
        """)).fetchall()]
    log("\n  Tablas:")
    for t in tables:
        try:
            n = _scalar(engine, f'SELECT COUNT(*) FROM silver."{t}"')
            log(f"    {t:45} {n:>10,} filas")
        except Exception as e:
            log(f"    {t:45} ERROR: {e}")
    if views:
        log("\n  Views:")
        for v in views:
            try:
                n = _scalar(engine, f'SELECT COUNT(*) FROM silver."{v}"')
                log(f"    {v:45} {n:>10,} filas")
            except Exception as e:
                log(f"    {v:45} ERROR: {e}")


def build_dim_charge_types(engine):
    """Idempotente: skip si el seed (30 codigos) ya esta cargado.

    Si necesitas actualizar el seed (agregar/cambiar codigos), borra la tabla
    manualmente o ajusta la lista abajo + drop. La tabla es estatica (seed
    confirmado), no depende de bronze.
    """
    started = time.time()
    # Crea tabla si no existe (no la dropea)
    _exec(engine, """
        CREATE TABLE IF NOT EXISTS silver.dim_charge_types (
            chra_chco    TEXT PRIMARY KEY,
            descripcion  TEXT NOT NULL,
            categoria    TEXT NOT NULL,
            confianza    TEXT NOT NULL,
            notas        TEXT
        )
    """)
    current = _scalar(engine, "SELECT COUNT(*) FROM silver.dim_charge_types") or 0
    if current >= 30:
        log(f"\n>> dim_charge_types ya esta cargada ({current} codigos) — skip")
        return
    log("\n>> Materializando dim_charge_types (seed inicial)")
    rows = [
        ("T",  "Time and mileage (tarifa por tiempo + kilometros)",      "TARIFA",       "CONFIRMADO", None),
        ("Y",  "Location fee (recargo por ubicacion, ej. aeropuerto)",   "CONTEXTO",     "CONFIRMADO", None),
        ("BF", "Full coverage (cobertura completa del vehiculo)",        "COBERTURA",    "CONFIRMADO", None),
        ("LD", "Loss Damage Waiver (cobertura por danos)",               "COBERTURA",    "CONFIRMADO", None),
        ("SL", "Supplemental Liability (responsabilidad civil extra)",   "COBERTURA",    "CONFIRMADO", None),
        ("OW", "One-way fee (entrega en sede distinta)",                 "CONTEXTO",     "CONFIRMADO", None),
        ("OH", "Out of hours (apertura fuera de horario)",               "CONTEXTO",     "CONFIRMADO", None),
        ("AE", "Recargo menor de 25 anios (young driver fee)",           "CONTEXTO",     "CONFIRMADO", None),
        ("DL", "Delivery (entrega a domicilio)",                         "CONTEXTO",     "CONFIRMADO", None),
        ("CO", "Collection (cobranza/pickup post-rental)",               "CONTEXTO",     "CONFIRMADO", "Variante de CL"),
        ("CL", "Collection (recogida del vehiculo)",                     "CONTEXTO",     "CONFIRMADO", "Variante de CO"),
        ("AD", "Conductor adicional",                                    "EXTRA",        "CONFIRMADO", None),
        ("CS", "Silla para nino (child seat)",                           "EXTRA",        "CONFIRMADO", None),
        ("BC", "Asistencia en carretera (road assistance)",              "EXTRA",        "CONFIRMADO", None),
        ("UP", "Upgrade de categoria",                                   "EXTRA",        "CONFIRMADO", None),
        ("PF", "Prepaid fuel (combustible prepagado)",                   "EXTRA",        "CONFIRMADO", None),
        ("VA", "Lavada del vehiculo",                                    "EXTRA",        "CONFIRMADO", None),
        ("FI", "Fee administrativo",                                     "AJUSTE",       "CONFIRMADO", None),
        ("PP", "Prepaid difference",                                     "AJUSTE",       "CONFIRMADO", None),
        ("DC", "Damage Charge (cobro por dano tras devolucion)",         "PENALIZACION", "CONFIRMADO", None),
        ("RL", "Late return",                                            "PENALIZACION", "CONFIRMADO", None),
        ("OT", "Otros cargos varios",                                    "OTROS",        "CONFIRMADO", None),
        ("D9", "(sin info)", "OTROS", "NO_CONFIRMADO", "Pendiente"),
        ("X",  "(ajuste especial)", "OTROS", "NO_CONFIRMADO", "Pendiente"),
        ("BS", "(sin info)", "OTROS", "NO_CONFIRMADO", "Pendiente"),
        ("NV", "(sin info)", "OTROS", "NO_CONFIRMADO", "Pendiente"),
        ("FC", "(sin info)", "OTROS", "NO_CONFIRMADO", "Pendiente"),
        ("RU", "(sin info)", "OTROS", "NO_CONFIRMADO", "Pendiente"),
        ("DV", "(sin info)", "OTROS", "NO_CONFIRMADO", "Pendiente"),
        ("RF", "(sin info)", "OTROS", "NO_CONFIRMADO", "Pendiente"),
    ]
    payload = [{"chra_chco": r[0], "descripcion": r[1], "categoria": r[2],
                "confianza": r[3], "notas": r[4]} for r in rows]
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO silver.dim_charge_types (chra_chco, descripcion, categoria, confianza, notas) "
            "VALUES (:chra_chco, :descripcion, :categoria, :confianza, :notas)"
        ), payload)
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.dim_charge_types")
    log(f"   {n} codigos en seed ({time.time()-started:.1f}s)")


def build_charges_ra_enriched_view(engine):
    log("\n>> Creando vw_charges_ra_enriched")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_charges_ra_enriched CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.vw_charges_ra_enriched CASCADE")
    _exec(engine, """
        CREATE VIEW silver.vw_charges_ra_enriched AS
        SELECT
            c.chra_mvnr                                          AS rental,
            c.chra_inty                                          AS inty,
            c.chra_chco                                          AS code,
            ct.descripcion                                       AS descripcion,
            ct.categoria                                         AS categoria,
            ct.confianza                                         AS confianza_decode,
            c.chra_pos                                           AS posicion,
            c.chra_unit_num                                      AS cantidad,
            ROUND(c.chra_unit_value_local::numeric, 0)           AS unit_cop,
            ROUND(c.chra_value_local::numeric, 0)                AS total_cop,
            ROUND(c.chra_unit_value::numeric, 2)                 AS unit_eur,
            ROUND(c.chra_value::numeric, 2)                      AS total_eur,
            c.rntl_rental_currency_code                          AS rental_currency,
            ROUND(c.chra_unit_value_rental::numeric, 2)          AS unit_rental,
            ROUND(c.chra_value_rental::numeric, 2)               AS total_rental,
            CASE WHEN c.rntl_rental_currency_code = 'USD'
                 THEN ROUND(c.chra_value_rental::numeric, 2) END AS total_usd,
            ROUND(c.rntl_exchange_rate::numeric, 4)              AS xr_eur_to_cop,
            ROUND(c.rntl_exchange_rate_rental::numeric, 4)       AS xr_rentalcurr_to_cop
        FROM silver.fact_charges_ra c
        INNER JOIN (
            SELECT b.chra_mvnr, b.chra_inty, b.chra_pos, b.max_konr
            FROM (
                SELECT chra_mvnr, chra_inty, chra_pos, MAX(chra_konr) AS max_konr
                FROM silver.fact_charges_ra
                GROUP BY chra_mvnr, chra_inty, chra_pos
            ) b
            JOIN (
                SELECT chra_mvnr, MAX(chra_konr) AS max_global
                FROM silver.fact_charges_ra
                GROUP BY chra_mvnr
            ) g ON g.chra_mvnr = b.chra_mvnr
            WHERE b.max_konr = g.max_global
        ) lk
               ON lk.chra_mvnr = c.chra_mvnr
              AND lk.chra_inty = c.chra_inty
              AND lk.chra_pos  = c.chra_pos
              AND lk.max_konr  = c.chra_konr
        LEFT JOIN silver.dim_charge_types ct ON ct.chra_chco = c.chra_chco
    """)
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_charges_ra_enriched")
    log(f"   {n} filas accesibles ({time.time()-started:.1f}s)")


def build_charges_rs_enriched_view(engine):
    log("\n>> Creando vw_charges_rs_enriched")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_charges_rs_enriched CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.vw_charges_rs_enriched CASCADE")
    _exec(engine, """
        CREATE VIEW silver.vw_charges_rs_enriched AS
        SELECT
            c.chrs_resn                                          AS reserva,
            c.chrs_inty                                          AS inty,
            c.chrs_chco                                          AS code,
            ct.descripcion                                       AS descripcion,
            ct.categoria                                         AS categoria,
            ct.confianza                                         AS confianza_decode,
            c.chrs_pos                                           AS posicion,
            c.chrs_unit_num                                      AS cantidad,
            ROUND(c.chrs_unit_value_local::numeric, 0)           AS unit_cop,
            ROUND(c.chrs_value_local::numeric, 0)                AS total_cop,
            ROUND(c.chrs_unit_value::numeric, 2)                 AS unit_eur,
            ROUND(c.chrs_value::numeric, 2)                      AS total_eur,
            c.rsrv_rental_currency_code                          AS rental_currency,
            ROUND(c.chrs_unit_value_rental::numeric, 2)          AS unit_rental,
            ROUND(c.chrs_value_rental::numeric, 2)               AS total_rental,
            CASE WHEN c.rsrv_rental_currency_code = 'USD'
                 THEN ROUND(c.chrs_value_rental::numeric, 2) END AS total_usd,
            ROUND(c.rsrv_exchange_rate::numeric, 4)              AS xr_eur_to_cop,
            ROUND(c.rsrv_exchange_rate_rental::numeric, 4)       AS xr_rentalcurr_to_cop
        FROM silver.fact_charges_rs c
        INNER JOIN (
            SELECT b.chrs_resn, b.chrs_inty, b.chrs_pos, b.max_konr
            FROM (
                SELECT chrs_resn, chrs_inty, chrs_pos, MAX(chrs_konr) AS max_konr
                FROM silver.fact_charges_rs
                GROUP BY chrs_resn, chrs_inty, chrs_pos
            ) b
            JOIN (
                SELECT chrs_resn, MAX(chrs_konr) AS max_global
                FROM silver.fact_charges_rs
                GROUP BY chrs_resn
            ) g ON g.chrs_resn = b.chrs_resn
            WHERE b.max_konr = g.max_global
        ) lk
               ON lk.chrs_resn = c.chrs_resn
              AND lk.chrs_inty = c.chrs_inty
              AND lk.chrs_pos  = c.chrs_pos
              AND lk.max_konr  = c.chrs_konr
        LEFT JOIN silver.dim_charge_types ct ON ct.chra_chco = c.chrs_chco
    """)
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_charges_rs_enriched")
    log(f"   {n} filas accesibles ({time.time()-started:.1f}s)")


def build_dim_trm_diaria(engine):
    log("\n>> Construyendo dim_trm_diaria")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.dim_trm_diaria CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.dim_trm_diaria CASCADE")
    exists = _scalar(engine, """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'bronze' AND table_name = 'external_trm_diaria'
    """)
    if not exists:
        log("   bronze.external_trm_diaria no existe -- saltando")
        return
    _exec(engine, """
        CREATE TABLE silver.dim_trm_diaria AS
        SELECT
            d.full_date                                      AS fecha,
            t.valor                                          AS trm_cop_per_usd,
            t.vigenciadesde::date                            AS vigenciadesde,
            CASE WHEN t.vigenciadesde::date = d.full_date THEN 1
                 ELSE 0 END                                  AS dia_publicacion
        FROM bronze.external_trm_diaria t
        JOIN silver.dim_dates d
          ON d.full_date BETWEEN t.vigenciadesde::date AND t.vigenciahasta::date
    """)
    _exec(engine, "CREATE UNIQUE INDEX IF NOT EXISTS idx_dim_trm_fecha ON silver.dim_trm_diaria(fecha)")
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.dim_trm_diaria")
    rng = _scalar(engine, "SELECT MIN(fecha)::text || ' a ' || MAX(fecha)::text FROM silver.dim_trm_diaria")
    log(f"   {n:,} dias ({rng}) ({time.time()-started:.1f}s)")


def build_rentals_full(engine):
    log("\n>> Construyendo vw_rentals_full")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_rentals_full CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.vw_rentals_full CASCADE")
    _exec(engine, """
        CREATE TABLE silver.vw_rentals_full AS
        WITH
        counter_extras AS (
            SELECT
                c.chra_mvnr AS rntl_mvnr,
                STRING_AGG(c.chra_chco, ', ')                              AS codigos,
                STRING_AGG(COALESCE(ct.descripcion, c.chra_chco), '; ')    AS descripciones,
                STRING_AGG(DISTINCT COALESCE(ct.categoria, 'OTROS'), ',')  AS categorias,
                SUM(c.chra_value_local)                                    AS total_cop
            FROM silver.fact_charges_ra c
            INNER JOIN (
                SELECT b.chra_mvnr, b.chra_inty, b.chra_pos, b.max_konr
                FROM (
                    SELECT chra_mvnr, chra_inty, chra_pos, MAX(chra_konr) AS max_konr
                    FROM silver.fact_charges_ra
                    WHERE chra_inty = 'S'
                    GROUP BY chra_mvnr, chra_inty, chra_pos
                ) b
                JOIN (
                    SELECT chra_mvnr, MAX(chra_konr) AS max_global
                    FROM silver.fact_charges_ra
                    GROUP BY chra_mvnr
                ) g ON g.chra_mvnr = b.chra_mvnr
                WHERE b.max_konr = g.max_global
            ) lk
                   ON lk.chra_mvnr = c.chra_mvnr
                  AND lk.chra_inty = c.chra_inty
                  AND lk.chra_pos  = c.chra_pos
                  AND lk.max_konr  = c.chra_konr
            LEFT JOIN silver.dim_charge_types ct ON ct.chra_chco = c.chra_chco
            WHERE c.chra_inty = 'S'
            GROUP BY c.chra_mvnr
        ),
        reserva_extras AS (
            SELECT
                c.chrs_resn AS rsrv_resn,
                STRING_AGG(c.chrs_chco, ', ')                              AS codigos,
                STRING_AGG(COALESCE(ct.descripcion, c.chrs_chco), '; ')    AS descripciones,
                STRING_AGG(DISTINCT COALESCE(ct.categoria, 'OTROS'), ',')  AS categorias,
                SUM(c.chrs_value_local)                                    AS total_cop
            FROM silver.fact_charges_rs c
            LEFT JOIN silver.dim_charge_types ct ON ct.chra_chco = c.chrs_chco
            GROUP BY c.chrs_resn
        ),
        canal_ra AS (
            SELECT rntl_mvnr,
                   MAX(rntl_scd_level0) AS canal_principal,
                   MAX(rntl_scd_level1) AS canal_subcanal,
                   MAX(rntl_scd_level2) AS canal_detalle
            FROM silver.dim_channels_ra
            GROUP BY rntl_mvnr
        )
        SELECT
            r.rntl_mvnr                                       AS numero_contrato,
            NULLIF(r.rsrv_resn, 0)                            AS numero_reserva,
            (rsv.rsrv_status || ' - ' || rsv.rsrv_status_extended) AS estado_reserva,
            r.rntl_status                                     AS estado_rental,

            r.rntl_handover_date                              AS fecha_handover_real,
            rsv.rsrv_handover_date                            AS fecha_handover_planificada,
            r.rntl_return_date                                AS fecha_devolucion_real,
            rsv.rsrv_return_date                              AS fecha_devolucion_planificada,
            r.rntl_handover_datm                              AS hora_handover,
            r.rntl_return_datm                                AS hora_devolucion,
            r.rntl_rental_days                                AS dias_renta,

            r.brnc_code_handover                              AS sede_handover_codigo,
            bh.brnc_name                                      AS sede_handover,
            r.brnc_code_return                                AS sede_devolucion_codigo,
            br.brnc_name                                      AS sede_devolucion,

            r.vhcl_int_num                                    AS vehiculo_int_num,
            v.vhcl_plate                                      AS placa,
            TRIM(COALESCE(vm.vhmd_brand_name,'') || ' ' || COALESCE(vm.vhmd_generic_model,''))
                                                              AS vehiculo,
            vm.vhmd_brand_name                                AS vehiculo_marca,
            vm.vhmd_generic_model                             AS vehiculo_modelo,
            vm.vhmd_deriv_model                               AS vehiculo_version,

            r.vhgr_crs                                        AS categoria_entregada_acriss,
            ge.label_humano                                   AS categoria_entregada,
            ge.transmision                                    AS transmision,
            ge.combustible                                    AS combustible,
            ge.tipo_vehiculo                                  AS tipo_vehiculo,

            rsv.vhgr_crs                                      AS categoria_reservada_acriss,
            gr.label_humano                                   AS categoria_reservada,

            CASE
                WHEN rsv.vhgr_crs IS NULL OR r.vhgr_crs IS NULL THEN NULL
                WHEN rsv.vhgr_crs = r.vhgr_crs THEN 'MATCH'
                ELSE
                    CASE
                        WHEN STRPOS('MECISRFPL', SUBSTRING(r.vhgr_crs FROM 1 FOR 1))
                           > STRPOS('MECISRFPL', SUBSTRING(rsv.vhgr_crs FROM 1 FOR 1))
                        THEN 'UPGRADE'
                        WHEN STRPOS('MECISRFPL', SUBSTRING(r.vhgr_crs FROM 1 FOR 1))
                           < STRPOS('MECISRFPL', SUBSTRING(rsv.vhgr_crs FROM 1 FOR 1))
                        THEN 'DOWNGRADE'
                        ELSE 'CAMBIO_LATERAL'
                    END
            END                                               AS reserved_group_class,
            CASE
                WHEN rsv.vhgr_crs IS NULL OR r.vhgr_crs IS NULL THEN NULL
                WHEN rsv.vhgr_crs = r.vhgr_crs THEN 'Reserva y entrega misma categoria'
                ELSE 'Reservo ' || COALESCE(gr.label_humano, rsv.vhgr_crs)
                  || ' / Entrego ' || COALESCE(ge.label_humano, r.vhgr_crs)
            END                                               AS reserved_group_class_obs,

            rsv.cstm_name                                     AS campaign,
            rsv.cstm_company                                  AS canal_partner,

            r.cstm_kdnr                                       AS cliente_kdnr,
            p.prtn_name                                       AS partner_nombre,
            p.prtn_subsidiary_name                            AS partner_subsidiaria,
            p.prtn_parent_name                                AS partner_grupo,
            p.prtn_country_code                               AS partner_pais,
            CASE WHEN p.prtn_kdnr IS NOT NULL THEN 1 ELSE 0 END AS cliente_es_partner_b2b,

            ch.canal_principal                                AS canal_principal,
            ch.canal_subcanal                                 AS canal_subcanal,
            ch.canal_detalle                                  AS canal_detalle,

            r.rntl_payment_type                               AS forma_pago,
            r.rntl_payment_type_code                          AS forma_pago_codigo,
            rsv.rsrv_prepaid_flg                              AS prepago_flag,
            ROUND(rsv.rsrv_prepaid_value_local::numeric, 0)   AS prepago_cop,

            r.oprt_bed                                        AS operador_handover_codigo,
            r.oprt_bed_checkout                               AS operador_checkout_codigo,

            ROUND(r.rntl_revenue_main_local::numeric, 0)      AS revenue_base_cop,
            ROUND(r.rntl_revenue_secondary_local::numeric, 0) AS revenue_extras_cop,
            ROUND(r.rntl_revenue_local_currency::numeric, 0)  AS revenue_total_cop,
            ROUND(COALESCE(r.rntl_distount_local, 0)::numeric, 0) AS descuento_cop,

            ROUND(r.rntl_revenue_main::numeric, 2)            AS revenue_base_eur,
            ROUND(r.rntl_revenue::numeric, 2)                 AS revenue_total_eur,
            ROUND(COALESCE(r.rntl_discount, 0)::numeric, 2)   AS descuento_eur,

            r.rntl_rental_currency_code                       AS moneda_renta,
            ROUND(r.rntl_revenue_main_rental::numeric, 2)     AS revenue_base_rental,
            ROUND(r.rntl_revenue_rental::numeric, 2)          AS revenue_total_rental,
            ROUND(COALESCE(r.rntl_discount_rental, 0)::numeric, 2) AS descuento_rental,
            CASE WHEN r.rntl_rental_currency_code = 'USD'
                 THEN ROUND(r.rntl_revenue_main_rental::numeric, 2) END AS revenue_base_usd,
            CASE WHEN r.rntl_rental_currency_code = 'USD'
                 THEN ROUND(r.rntl_revenue_rental::numeric, 2) END     AS revenue_total_usd,
            CASE WHEN r.rntl_rental_currency_code = 'USD'
                 THEN ROUND(COALESCE(r.rntl_discount_rental, 0)::numeric, 2) END AS descuento_usd,

            ROUND(r.rntl_exchange_rate_rental::numeric, 4)    AS trm_aplicada_cop_per_renta,
            ROUND(r.rntl_exchange_rate::numeric, 4)           AS trm_aplicada_cop_per_eur,

            ROUND(r.rntl_tax_rental::numeric, 2)              AS iva_total_renta_curr,
            ROUND(r.rntl_tax_main_rental::numeric, 2)         AS iva_base_renta_curr,
            ROUND(r.rntl_tax_secondary_rental::numeric, 2)    AS iva_extras_renta_curr,
            ROUND((r.rntl_tax_rental * r.rntl_exchange_rate_rental)::numeric, 0) AS iva_total_cop,
            CASE WHEN r.rntl_rental_currency_code = 'USD'
                 THEN ROUND(r.rntl_tax_rental::numeric, 2) END         AS iva_total_usd,
            r.rntl_tax_percentage_m                           AS iva_porcentaje,

            ROUND((r.rntl_revenue_main_local * 1.0
                  / NULLIF(r.rntl_rental_days, 0))::numeric, 0) AS tarifa_dia_cop,
            CASE WHEN r.rntl_rental_currency_code = 'USD'
                 THEN ROUND((r.rntl_revenue_main_rental * 1.0
                            / NULLIF(r.rntl_rental_days, 0))::numeric, 2) END AS tarifa_dia_usd,

            ce.codigos                                        AS extras_counter_codigos,
            ce.descripciones                                  AS extras_counter_observaciones,
            ce.categorias                                     AS extras_counter_categorias,
            ROUND(ce.total_cop::numeric, 0)                   AS extras_counter_total_cop,

            re.codigos                                        AS extras_reserva_codigos,
            re.descripciones                                  AS extras_reserva_observaciones,
            re.categorias                                     AS extras_reserva_categorias,
            ROUND(re.total_cop::numeric, 0)                   AS extras_reserva_total_cop

        FROM silver.fact_rentals r
        LEFT JOIN silver.fact_reservations rsv ON rsv.rsrv_resn = r.rsrv_resn
        LEFT JOIN silver.dim_branches bh        ON bh.brnc_code = r.brnc_code_handover
        LEFT JOIN silver.dim_branches br        ON br.brnc_code = r.brnc_code_return
        LEFT JOIN silver.dim_vehicles v         ON v.vhcl_int_num = r.vhcl_int_num
        LEFT JOIN silver.dim_vehicle_models vm  ON vm.vhmd_cdef = v.vhmd_cdef
        LEFT JOIN silver.dim_vehicle_groups_decoded ge ON ge.vhgr_crs = r.vhgr_crs
        LEFT JOIN silver.dim_vehicle_groups_decoded gr ON gr.vhgr_crs = rsv.vhgr_crs
        LEFT JOIN canal_ra ch            ON ch.rntl_mvnr = r.rntl_mvnr
        LEFT JOIN counter_extras ce      ON ce.rntl_mvnr = r.rntl_mvnr
        LEFT JOIN reserva_extras re      ON re.rsrv_resn = r.rsrv_resn
        LEFT JOIN silver.dim_partners p  ON p.prtn_kdnr = r.cstm_kdnr
                                       AND r.cstm_kdnr > 0
    """)
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_rentals_full_sede_fecha ON silver.vw_rentals_full(sede_handover_codigo, fecha_handover_real)")
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_rentals_full_contrato ON silver.vw_rentals_full(numero_contrato)")
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_rentals_full_reserva ON silver.vw_rentals_full(numero_reserva)")
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_rentals_full")
    cols = _scalar(engine, """
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema='silver' AND table_name='vw_rentals_full'
    """)
    log(f"   {n:,} filas, {cols} columnas ({time.time()-started:.1f}s)")


def build_rentals_detail(engine):
    log("\n>> Construyendo vw_rentals_detail")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_rentals_detail CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.vw_rentals_detail CASCADE")
    _exec(engine, """
        CREATE TABLE silver.vw_rentals_detail AS
        WITH global_konr_ra AS (
            SELECT chra_mvnr, MAX(chra_konr) AS max_global
            FROM silver.fact_charges_ra
            GROUP BY chra_mvnr
        ),
        last_konr_ra AS (
            SELECT b.chra_mvnr, b.chra_inty, b.chra_pos, b.max_konr
            FROM (
                SELECT chra_mvnr, chra_inty, chra_pos, MAX(chra_konr) AS max_konr
                FROM silver.fact_charges_ra
                GROUP BY chra_mvnr, chra_inty, chra_pos
            ) b
            JOIN global_konr_ra g ON g.chra_mvnr = b.chra_mvnr
            WHERE b.max_konr = g.max_global
        ),
        global_konr_rs AS (
            SELECT chrs_resn, MAX(chrs_konr) AS max_global
            FROM silver.fact_charges_rs
            GROUP BY chrs_resn
        ),
        last_konr_rs AS (
            SELECT b.chrs_resn, b.chrs_inty, b.chrs_pos, b.max_konr
            FROM (
                SELECT chrs_resn, chrs_inty, chrs_pos, MAX(chrs_konr) AS max_konr
                FROM silver.fact_charges_rs
                GROUP BY chrs_resn, chrs_inty, chrs_pos
            ) b
            JOIN global_konr_rs g ON g.chrs_resn = b.chrs_resn
            WHERE b.max_konr = g.max_global
        ),
        codigos_reservados AS (
            SELECT DISTINCT c.chrs_resn AS rsrv_resn, c.chrs_chco AS chco
            FROM silver.fact_charges_rs c
            INNER JOIN last_konr_rs lk
                   ON lk.chrs_resn = c.chrs_resn
                  AND lk.chrs_inty = c.chrs_inty
                  AND lk.chrs_pos  = c.chrs_pos
                  AND lk.max_konr  = c.chrs_konr
        ),
        cargos_union AS (
            SELECT
                'RENTAL_COUNTER' AS fuente_cargo,
                c.chra_mvnr      AS rntl_mvnr,
                CASE WHEN cr.rsrv_resn IS NOT NULL
                     THEN NULLIF(r.rsrv_resn, 0) ELSE NULL END AS rsrv_resn,
                c.chra_inty      AS inty,
                c.chra_chco      AS code,
                c.chra_pos       AS posicion,
                c.chra_konr      AS correction_num,
                c.chra_unit_num  AS cantidad,
                c.chra_unit_value_local AS unit_cop,
                c.chra_value_local      AS subtotal_cop,
                c.chra_value            AS subtotal_eur,
                c.chra_value_rental     AS subtotal_rental_curr,
                c.rntl_rental_currency_code AS rental_currency,
                c.rntl_exchange_rate_rental AS xr_rental_cop
            FROM silver.fact_charges_ra c
            INNER JOIN last_konr_ra lk
                   ON lk.chra_mvnr = c.chra_mvnr
                  AND lk.chra_inty = c.chra_inty
                  AND lk.chra_pos  = c.chra_pos
                  AND lk.max_konr  = c.chra_konr
            LEFT JOIN silver.fact_rentals r ON r.rntl_mvnr = c.chra_mvnr
            LEFT JOIN codigos_reservados cr
                   ON cr.rsrv_resn = r.rsrv_resn
                  AND r.rsrv_resn > 0
                  AND cr.chco = c.chra_chco

            UNION ALL

            SELECT
                'RESERVA_ONLINE' AS fuente_cargo,
                r.rntl_mvnr      AS rntl_mvnr,
                c.chrs_resn      AS rsrv_resn,
                c.chrs_inty      AS inty,
                c.chrs_chco      AS code,
                c.chrs_pos       AS posicion,
                c.chrs_konr      AS correction_num,
                c.chrs_unit_num  AS cantidad,
                c.chrs_unit_value_local AS unit_cop,
                c.chrs_value_local      AS subtotal_cop,
                c.chrs_value            AS subtotal_eur,
                c.chrs_value_rental     AS subtotal_rental_curr,
                c.rsrv_rental_currency_code AS rental_currency,
                c.rsrv_exchange_rate_rental AS xr_rental_cop
            FROM silver.fact_charges_rs c
            INNER JOIN last_konr_rs lk
                   ON lk.chrs_resn = c.chrs_resn
                  AND lk.chrs_inty = c.chrs_inty
                  AND lk.chrs_pos  = c.chrs_pos
                  AND lk.max_konr  = c.chrs_konr
            INNER JOIN silver.fact_rentals r ON r.rsrv_resn = c.chrs_resn
        )
        SELECT
            u.rntl_mvnr                                       AS numero_contrato,
            rf.numero_reserva                                 AS numero_reserva,
            u.rsrv_resn                                       AS rsrv_resn_cargo,
            CASE
                WHEN rf.numero_reserva IS NULL THEN NULL
                WHEN u.rsrv_resn IS NOT NULL   THEN 1
                ELSE 0
            END                                               AS cargo_coincide_reserva,
            CASE
                WHEN u.fuente_cargo = 'RESERVA_ONLINE'        THEN 'RESERVA'
                WHEN u.rsrv_resn IS NOT NULL                  THEN 'COUNTER_CON_RESERVA'
                ELSE 'COUNTER_AGREGADO'
            END                                               AS origen_cargo,
            u.fuente_cargo,

            rf.categoria_entregada_acriss                     AS acriss_entregado,
            rf.categoria_reservada_acriss                     AS acriss_reservado,

            u.inty                                            AS cargo_inty,
            u.code                                            AS cargo_codigo,
            ct.descripcion                                    AS cargo_descripcion,
            ct.categoria                                      AS cargo_categoria,
            u.posicion                                        AS cargo_posicion,
            u.correction_num                                  AS cargo_correccion,

            u.cantidad                                        AS cantidad,
            ROUND(u.unit_cop::numeric, 0)                     AS unit_cop,
            ROUND(u.subtotal_cop::numeric, 0)                 AS subtotal_cop,
            ROUND(u.subtotal_eur::numeric, 2)                 AS subtotal_eur,
            ROUND(u.subtotal_rental_curr::numeric, 2)         AS subtotal_rental_curr,
            u.rental_currency,
            CASE WHEN u.rental_currency = 'USD'
                 THEN ROUND(u.subtotal_rental_curr::numeric, 2) END    AS subtotal_usd,
            ROUND(u.xr_rental_cop::numeric, 4)                AS trm_aplicada,

            ROUND((u.subtotal_cop * (1 + COALESCE(rf.iva_porcentaje, 19) / 100.0))::numeric, 0)
                AS subtotal_con_iva_cop,
            ROUND((u.subtotal_eur * (1 + COALESCE(rf.iva_porcentaje, 19) / 100.0))::numeric, 2)
                AS subtotal_con_iva_eur,
            ROUND((u.subtotal_rental_curr * (1 + COALESCE(rf.iva_porcentaje, 19) / 100.0))::numeric, 2)
                AS subtotal_con_iva_rental_curr,
            CASE WHEN u.rental_currency = 'USD'
                 THEN ROUND((u.subtotal_rental_curr * (1 + COALESCE(rf.iva_porcentaje, 19) / 100.0))::numeric, 2)
                 END                                          AS subtotal_con_iva_usd,
            COALESCE(rf.iva_porcentaje, 19)                   AS iva_porcentaje,

            rf.fecha_handover_real, rf.fecha_devolucion_real, rf.dias_renta,
            rf.sede_handover, rf.sede_handover_codigo, rf.sede_devolucion,
            rf.placa, rf.vehiculo, rf.vehiculo_marca, rf.vehiculo_modelo, rf.vehiculo_version,
            rf.categoria_entregada, rf.categoria_reservada,
            rf.reserved_group_class, rf.reserved_group_class_obs,
            rf.transmision, rf.combustible, rf.tipo_vehiculo,
            rf.campaign, rf.canal_partner, rf.canal_principal,
            rf.partner_nombre, rf.partner_subsidiaria, rf.cliente_es_partner_b2b,
            rf.forma_pago, rf.prepago_flag, rf.prepago_cop,
            rf.operador_handover_codigo, rf.operador_checkout_codigo,
            rf.estado_reserva, rf.estado_rental,

            rf.revenue_total_cop      AS revenue_total_rental_cop,
            rf.iva_total_cop          AS iva_total_rental_cop,
            rf.revenue_total_usd      AS revenue_total_rental_usd,
            rf.iva_total_usd          AS iva_total_rental_usd,
            rf.descuento_cop          AS descuento_total_rental_cop,
            rf.descuento_usd          AS descuento_total_rental_usd
        FROM cargos_union u
        LEFT JOIN silver.dim_charge_types ct ON ct.chra_chco = u.code
        LEFT JOIN silver.vw_rentals_full rf  ON rf.numero_contrato = u.rntl_mvnr
    """)
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_rentals_detail_contrato ON silver.vw_rentals_detail(numero_contrato)")
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_rentals_detail_sede_fecha ON silver.vw_rentals_detail(sede_handover, fecha_handover_real)")
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_rentals_detail")
    log(f"   {n:,} filas ({time.time()-started:.1f}s)")


def build_rentals_resumen(engine):
    log("\n>> Construyendo vw_rentals_resumen")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_rentals_resumen CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.vw_rentals_resumen CASCADE")
    _exec(engine, """
        CREATE TABLE silver.vw_rentals_resumen AS
        WITH base AS (
            SELECT
                numero_contrato, sede_handover, sede_handover_codigo,
                fecha_handover_real, fecha_devolucion_real, dias_renta,
                placa, vehiculo, vehiculo_marca, vehiculo_modelo, vehiculo_version,
                categoria_entregada, acriss_entregado, acriss_reservado,
                campaign, canal_partner, canal_principal, partner_nombre,
                forma_pago, prepago_flag, operador_handover_codigo,
                rental_currency, trm_aplicada,
                cargo_codigo, cargo_categoria, subtotal_cop, subtotal_usd,
                revenue_total_rental_cop, iva_total_rental_cop, descuento_total_rental_cop,
                revenue_total_rental_usd, iva_total_rental_usd, descuento_total_rental_usd
            FROM silver.vw_rentals_detail
            WHERE fuente_cargo = 'RENTAL_COUNTER'
        )
        SELECT
            numero_contrato,
            MAX(sede_handover) AS sede_handover,
            MAX(sede_handover_codigo) AS sede_handover_codigo,
            MAX(fecha_handover_real) AS fecha_handover_real,
            MAX(fecha_devolucion_real) AS fecha_devolucion_real,
            MAX(dias_renta) AS dias_renta,
            MAX(placa) AS placa, MAX(vehiculo) AS vehiculo,
            MAX(vehiculo_marca) AS vehiculo_marca,
            MAX(vehiculo_modelo) AS vehiculo_modelo,
            MAX(vehiculo_version) AS vehiculo_version,
            MAX(categoria_entregada) AS categoria_entregada,
            MAX(acriss_entregado) AS acriss_entregado,
            MAX(acriss_reservado) AS acriss_reservado,
            MAX(campaign) AS campaign,
            MAX(canal_partner) AS canal_partner,
            MAX(canal_principal) AS canal_principal,
            MAX(partner_nombre) AS partner_nombre,
            MAX(forma_pago) AS forma_pago,
            MAX(prepago_flag) AS reserva_prepagada,
            MAX(operador_handover_codigo) AS operador_handover_codigo,
            MAX(rental_currency) AS rental_currency,
            MAX(trm_aplicada) AS trm_aplicada,

            ROUND(SUM(CASE WHEN cargo_categoria = 'TARIFA' THEN subtotal_cop END)::numeric, 0) AS tarifa_cop,
            ROUND(SUM(CASE WHEN cargo_categoria = 'TARIFA' THEN subtotal_usd END)::numeric, 2) AS tarifa_usd,
            STRING_AGG(
                CASE WHEN cargo_categoria != 'TARIFA' THEN cargo_codigo END, ', '
            ) AS adicionales_codigos,
            ROUND(SUM(CASE WHEN cargo_categoria != 'TARIFA' THEN subtotal_cop END)::numeric, 0) AS adicionales_cop,
            ROUND(SUM(CASE WHEN cargo_categoria != 'TARIFA' THEN subtotal_usd END)::numeric, 2) AS adicionales_usd,

            ROUND(SUM(subtotal_cop)::numeric, 0) AS bruto_cop,
            ROUND(SUM(subtotal_usd)::numeric, 2) AS bruto_usd,
            MAX(descuento_total_rental_cop) AS descuento_cop,
            MAX(descuento_total_rental_usd) AS descuento_usd,
            MAX(revenue_total_rental_cop)   AS neto_cop,
            MAX(revenue_total_rental_usd)   AS neto_usd,
            MAX(iva_total_rental_cop)       AS iva_cop,
            MAX(iva_total_rental_usd)       AS iva_usd,
            ROUND((MAX(revenue_total_rental_cop) + MAX(iva_total_rental_cop))::numeric, 0) AS total_con_iva_cop,
            ROUND((MAX(revenue_total_rental_usd) + MAX(iva_total_rental_usd))::numeric, 2) AS total_con_iva_usd
        FROM base
        GROUP BY numero_contrato
    """)
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_rentals_resumen_contrato ON silver.vw_rentals_resumen(numero_contrato)")
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_rentals_resumen_sede_fecha ON silver.vw_rentals_resumen(sede_handover, fecha_handover_real)")
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_rentals_resumen")
    log(f"   {n:,} filas ({time.time()-started:.1f}s)")


def build_kpi_anual(engine):
    log("\n>> Construyendo vw_kpi_anual")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_kpi_anual CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.vw_kpi_anual CASCADE")
    _exec(engine, """
        CREATE TABLE silver.vw_kpi_anual AS
        WITH anios AS (
            SELECT DISTINCT EXTRACT(YEAR FROM fecha_handover_real)::int AS anio
            FROM silver.vw_rentals_full
            WHERE fecha_handover_real IS NOT NULL
        ),
        veh AS (
            SELECT
                vhcl_int_num,
                vhcl_first_ci_date::date AS in_date,
                CASE
                    WHEN vhcl_grounded_date IS NULL
                      OR vhcl_grounded_date::date = DATE '1899-12-31'
                    THEN NULL
                    ELSE vhcl_grounded_date::date
                END AS out_date
            FROM silver.dim_vehicles
            WHERE vhcl_first_ci_date IS NOT NULL
              AND vhcl_first_ci_date::date != DATE '1899-12-31'
        ),
        flota_anual AS (
            SELECT
                a.anio,
                COUNT(DISTINCT v.vhcl_int_num) AS flota_activa,
                SUM(
                    (LEAST(COALESCE(v.out_date, (a.anio::text || '-12-31')::date),
                           (a.anio::text || '-12-31')::date)
                     - GREATEST(v.in_date, (a.anio::text || '-01-01')::date))
                    + 1
                ) AS dias_disponibles
            FROM anios a
            JOIN veh v
              ON v.in_date <= (a.anio::text || '-12-31')::date
             AND COALESCE(v.out_date, (a.anio::text || '-12-31')::date) >= (a.anio::text || '-01-01')::date
            GROUP BY a.anio
        ),
        rentals_anual AS (
            SELECT
                EXTRACT(YEAR FROM f.fecha_handover_real)::int AS anio,
                COUNT(*) AS rentals,
                SUM(f.dias_renta) AS dias_rentados
            FROM silver.vw_rentals_full f
            WHERE f.fecha_handover_real IS NOT NULL
            GROUP BY EXTRACT(YEAR FROM f.fecha_handover_real)
        ),
        revenue_anual AS (
            SELECT
                EXTRACT(YEAR FROM r.fecha_handover_real)::int AS anio,
                ROUND(SUM(r.tarifa_usd)::numeric, 2)        AS tarifa_usd,
                ROUND(SUM(r.adicionales_usd)::numeric, 2)   AS adicionales_usd,
                ROUND(SUM(r.neto_usd)::numeric, 2)          AS ingreso_total_usd,
                ROUND(SUM(r.descuento_usd)::numeric, 2)     AS descuento_usd
            FROM silver.vw_rentals_resumen r
            WHERE r.rental_currency = 'USD'
              AND r.fecha_handover_real IS NOT NULL
            GROUP BY EXTRACT(YEAR FROM r.fecha_handover_real)
        )
        SELECT
            a.anio,
            COALESCE(f.flota_activa, 0)         AS flota_activa,
            ROUND(COALESCE(f.dias_disponibles, 0)::numeric, 0) AS dias_disponibles,
            COALESCE(r.rentals, 0)              AS rentals,
            COALESCE(r.dias_rentados, 0)        AS dias_rentados,
            ROUND((COALESCE(r.dias_rentados, 0) * 100.0
                  / NULLIF(f.dias_disponibles, 0))::numeric, 2) AS ocupacion_pct,
            COALESCE(rv.tarifa_usd, 0)          AS tarifa_usd,
            COALESCE(rv.adicionales_usd, 0)     AS adicionales_usd,
            COALESCE(rv.descuento_usd, 0)       AS descuento_usd,
            COALESCE(rv.ingreso_total_usd, 0)   AS ingreso_total_usd,
            ROUND((COALESCE(rv.ingreso_total_usd, 0)
                  / NULLIF(r.dias_rentados, 0))::numeric, 2) AS revenue_per_day_usd
        FROM anios a
        LEFT JOIN flota_anual f   ON f.anio = a.anio
        LEFT JOIN rentals_anual r ON r.anio = a.anio
        LEFT JOIN revenue_anual rv ON rv.anio = a.anio
        ORDER BY a.anio
    """)
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_kpi_anual")
    log(f"   {n} anios ({time.time()-started:.1f}s)")


def build_demanda_anual(engine):
    log("\n>> Construyendo vw_demanda_anual")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_demanda_anual CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.vw_demanda_anual CASCADE")
    _exec(engine, """
        CREATE TABLE silver.vw_demanda_anual AS
        WITH base AS (
            SELECT
                EXTRACT(YEAR FROM rsrv_handover_date)::int AS anio,
                rsrv_status_extended AS estado
            FROM silver.fact_reservations
            WHERE rsrv_handover_date IS NOT NULL
              AND rsrv_status_extended IN (
                  'Invoice', 'Cancellation by Customer',
                  'No show', 'Cancellation by Sixt'
              )
        )
        SELECT
            anio,
            SUM(CASE WHEN estado = 'Invoice' THEN 1 ELSE 0 END)                  AS served,
            SUM(CASE WHEN estado = 'Cancellation by Customer' THEN 1 ELSE 0 END) AS cancel_cliente,
            SUM(CASE WHEN estado = 'No show' THEN 1 ELSE 0 END)                  AS noshow_cliente,
            SUM(CASE WHEN estado = 'Cancellation by Sixt' THEN 1 ELSE 0 END)     AS cancel_sixt,
            COUNT(*) AS total_reservas,
            ROUND((SUM(CASE WHEN estado = 'Invoice' THEN 1 ELSE 0 END) * 100.0 / COUNT(*))::numeric, 2) AS served_pct,
            ROUND(((COUNT(*) - SUM(CASE WHEN estado = 'Invoice' THEN 1 ELSE 0 END)) * 100.0 / COUNT(*))::numeric, 2) AS cancel_rate_pct,
            ROUND((SUM(CASE WHEN estado = 'Cancellation by Customer' THEN 1 ELSE 0 END) * 100.0 / COUNT(*))::numeric, 2) AS cancel_cliente_pct,
            ROUND((SUM(CASE WHEN estado = 'No show' THEN 1 ELSE 0 END) * 100.0 / COUNT(*))::numeric, 2) AS noshow_cliente_pct,
            ROUND((SUM(CASE WHEN estado = 'Cancellation by Sixt' THEN 1 ELSE 0 END) * 100.0 / COUNT(*))::numeric, 2) AS cancel_sixt_pct
        FROM base
        GROUP BY anio
        ORDER BY anio
    """)
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_demanda_anual")
    log(f"   {n} anios ({time.time()-started:.1f}s)")


def build_demanda_sede_acriss_anual(engine):
    log("\n>> Construyendo vw_demanda_sede_acriss_anual")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_demanda_sede_acriss_anual CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.vw_demanda_sede_acriss_anual CASCADE")
    _exec(engine, """
        CREATE TABLE silver.vw_demanda_sede_acriss_anual AS
        WITH base AS (
            SELECT
                EXTRACT(YEAR FROM r.rsrv_handover_date)::int AS anio,
                bh.brnc_name AS sede,
                bh.brnc_code AS sede_codigo,
                r.vhgr_crs   AS acriss,
                r.rsrv_status_extended AS estado
            FROM silver.fact_reservations r
            LEFT JOIN silver.dim_branches bh ON bh.brnc_code = r.brnc_code_handover
            WHERE r.rsrv_handover_date IS NOT NULL
              AND r.rsrv_status_extended IN (
                  'Invoice','Cancellation by Customer','No show','Cancellation by Sixt'
              )
              AND r.vhgr_crs IS NOT NULL
              AND bh.brnc_name IS NOT NULL
        )
        SELECT
            anio, sede, sede_codigo, acriss,
            SUM(CASE WHEN estado = 'Invoice' THEN 1 ELSE 0 END)                  AS served,
            SUM(CASE WHEN estado = 'Cancellation by Customer' THEN 1 ELSE 0 END) AS cancel_cliente,
            SUM(CASE WHEN estado = 'No show' THEN 1 ELSE 0 END)                  AS noshow_cliente,
            SUM(CASE WHEN estado = 'Cancellation by Sixt' THEN 1 ELSE 0 END)     AS cancel_sixt,
            COUNT(*) AS total_reservas,
            ROUND((SUM(CASE WHEN estado = 'Invoice' THEN 1 ELSE 0 END) * 100.0 / COUNT(*))::numeric, 2) AS served_pct,
            ROUND(((COUNT(*) - SUM(CASE WHEN estado = 'Invoice' THEN 1 ELSE 0 END)) * 100.0 / COUNT(*))::numeric, 2) AS cancel_rate_pct,
            ROUND((SUM(CASE WHEN estado = 'Cancellation by Customer' THEN 1 ELSE 0 END) * 100.0 / COUNT(*))::numeric, 2) AS cancel_cliente_pct,
            ROUND((SUM(CASE WHEN estado = 'No show' THEN 1 ELSE 0 END) * 100.0 / COUNT(*))::numeric, 2) AS noshow_cliente_pct,
            ROUND((SUM(CASE WHEN estado = 'Cancellation by Sixt' THEN 1 ELSE 0 END) * 100.0 / COUNT(*))::numeric, 2) AS cancel_sixt_pct
        FROM base
        GROUP BY anio, sede, sede_codigo, acriss
        ORDER BY anio, sede, acriss
    """)
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_dem_sede_acriss_anio ON silver.vw_demanda_sede_acriss_anual(anio, sede, acriss)")
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_demanda_sede_acriss_anual")
    log(f"   {n:,} filas ({time.time()-started:.1f}s)")


def build_utilizacion_sede_categoria_mes(engine):
    log("\n>> Construyendo vw_utilizacion_sede_categoria_mes")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_utilizacion_sede_categoria_mes CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.vw_utilizacion_sede_categoria_mes CASCADE")
    _exec(engine, """
        CREATE TABLE silver.vw_utilizacion_sede_categoria_mes AS
        WITH veh AS (
            SELECT
                vhcl_int_num, vhgr_crs AS acriss,
                vhcl_first_ci_date::date AS in_date,
                CASE WHEN vhcl_grounded_date IS NULL
                       OR vhcl_grounded_date::date = DATE '1899-12-31'
                     THEN NULL
                     ELSE vhcl_grounded_date::date END AS out_date
            FROM silver.dim_vehicles
            WHERE vhcl_first_ci_date IS NOT NULL
              AND vhcl_first_ci_date::date != DATE '1899-12-31'
        ),
        disponibles AS (
            SELECT
                TO_CHAR(d.full_date, 'YYYY-MM') AS anio_mes,
                v.acriss,
                COUNT(DISTINCT v.vhcl_int_num) AS vehiculos_distintos,
                COUNT(*) AS dias_disponibles
            FROM silver.dim_dates d
            JOIN veh v
              ON d.full_date >= v.in_date
             AND (v.out_date IS NULL OR d.full_date <= v.out_date)
            WHERE d.full_date >= DATE '2020-01-01'
              AND d.full_date <= CURRENT_DATE
            GROUP BY TO_CHAR(d.full_date, 'YYYY-MM'), v.acriss
        ),
        rentados AS (
            SELECT
                TO_CHAR(fecha_handover_real, 'YYYY-MM') AS anio_mes,
                sede_handover, sede_handover_codigo,
                categoria_entregada_acriss AS acriss,
                COUNT(*) AS rentals,
                SUM(dias_renta) AS dias_rentados
            FROM silver.vw_rentals_full
            WHERE fecha_handover_real IS NOT NULL
              AND categoria_entregada_acriss IS NOT NULL
            GROUP BY TO_CHAR(fecha_handover_real, 'YYYY-MM'),
                     sede_handover, sede_handover_codigo,
                     categoria_entregada_acriss
        )
        SELECT
            r.anio_mes, r.sede_handover, r.sede_handover_codigo, r.acriss,
            r.rentals, r.dias_rentados,
            d.vehiculos_distintos    AS flota_acriss_mes,
            d.dias_disponibles       AS dias_disponibles_acriss_mes,
            ROUND((r.dias_rentados * 100.0 / NULLIF(d.dias_disponibles, 0))::numeric, 2)
                                     AS utilizacion_pct
        FROM rentados r
        LEFT JOIN disponibles d
               ON d.anio_mes = r.anio_mes
              AND d.acriss   = r.acriss
        ORDER BY r.anio_mes, r.sede_handover, r.acriss
    """)
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_util_mes_sede ON silver.vw_utilizacion_sede_categoria_mes(anio_mes, sede_handover)")
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_utilizacion_sede_categoria_mes")
    log(f"   {n:,} filas ({time.time()-started:.1f}s)")


def build_flota_segmento_anual(engine):
    log("\n>> Construyendo vw_flota_segmento_anual")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_flota_segmento_anual CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.vw_flota_segmento_anual CASCADE")
    _exec(engine, """
        CREATE TABLE silver.vw_flota_segmento_anual AS
        WITH rentals_anio AS (
            SELECT
                EXTRACT(YEAR FROM fecha_handover_real)::int AS anio,
                vehiculo_int_num, sede_handover, sede_handover_codigo,
                categoria_entregada_acriss AS acriss,
                COUNT(*) AS rentals
            FROM silver.vw_rentals_full
            WHERE fecha_handover_real IS NOT NULL
              AND vehiculo_int_num IS NOT NULL
              AND categoria_entregada_acriss IS NOT NULL
              AND sede_handover IS NOT NULL
            GROUP BY EXTRACT(YEAR FROM fecha_handover_real),
                     vehiculo_int_num, sede_handover,
                     sede_handover_codigo, categoria_entregada_acriss
        ),
        sede_dominante AS (
            SELECT anio, vehiculo_int_num, sede_handover, sede_handover_codigo, acriss
            FROM (
                SELECT ra.*,
                       ROW_NUMBER() OVER (PARTITION BY anio, vehiculo_int_num
                                          ORDER BY rentals DESC) AS rn
                FROM rentals_anio ra
            ) t
            WHERE rn = 1
        )
        SELECT
            anio, sede_handover AS sede,
            sede_handover_codigo AS sede_codigo,
            acriss,
            COUNT(DISTINCT vehiculo_int_num) AS vehiculos
        FROM sede_dominante
        GROUP BY anio, sede_handover, sede_handover_codigo, acriss
        ORDER BY anio, sede_handover, acriss
    """)
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_flota_segmento_anual")
    log(f"   {n:,} filas ({time.time()-started:.1f}s)")


def build_kpi_sede_categoria_anual(engine):
    log("\n>> Construyendo vw_kpi_sede_categoria_anual")
    started = time.time()
    _exec(engine, "DROP TABLE IF EXISTS silver.vw_kpi_sede_categoria_anual CASCADE")
    _exec(engine, "DROP VIEW IF EXISTS silver.vw_kpi_sede_categoria_anual CASCADE")
    _exec(engine, """
        CREATE TABLE silver.vw_kpi_sede_categoria_anual AS
        WITH rentals_agg AS (
            SELECT
                EXTRACT(YEAR FROM r.fecha_handover_real)::int AS anio,
                r.sede_handover                  AS sede,
                r.sede_handover_codigo           AS sede_codigo,
                r.acriss_entregado               AS acriss,
                COUNT(*)                          AS rentals,
                SUM(r.dias_renta)                 AS dias_rentados,
                ROUND(SUM(r.tarifa_usd)::numeric, 2)       AS tarifa_usd,
                ROUND(SUM(r.adicionales_usd)::numeric, 2)  AS adicionales_usd,
                ROUND(SUM(r.neto_usd)::numeric, 2)         AS ingreso_total_usd
            FROM silver.vw_rentals_resumen r
            WHERE r.rental_currency = 'USD'
              AND r.fecha_handover_real IS NOT NULL
              AND r.sede_handover IS NOT NULL
              AND r.acriss_entregado IS NOT NULL
            GROUP BY EXTRACT(YEAR FROM r.fecha_handover_real),
                     r.sede_handover, r.sede_handover_codigo, r.acriss_entregado
        ),
        flota AS (
            SELECT anio, sede, sede_codigo, acriss, vehiculos AS flota
            FROM silver.vw_flota_segmento_anual
        ),
        canceladas AS (
            SELECT anio, sede, sede_codigo, acriss,
                   cancel_cliente + noshow_cliente + cancel_sixt AS reservas_canceladas
            FROM silver.vw_demanda_sede_acriss_anual
        )
        SELECT
            COALESCE(r.anio, f.anio)                 AS anio,
            COALESCE(r.sede, f.sede)                 AS sede,
            COALESCE(r.sede_codigo, f.sede_codigo)   AS sede_codigo,
            COALESCE(r.acriss, f.acriss)             AS acriss,
            COALESCE(f.flota, 0)                     AS flota,
            COALESCE(r.rentals, 0)                   AS rentals,
            COALESCE(r.dias_rentados, 0)             AS dias_rentados,
            COALESCE(r.tarifa_usd, 0)                AS tarifa_usd,
            COALESCE(r.adicionales_usd, 0)           AS adicionales_usd,
            COALESCE(r.ingreso_total_usd, 0)         AS ingreso_total_usd,
            ROUND((r.tarifa_usd / NULLIF(r.dias_rentados, 0))::numeric, 2) AS tarifa_promedio_dia_usd,
            ROUND((r.ingreso_total_usd / NULLIF(f.flota, 0))::numeric, 2) AS ingreso_por_unidad_usd,
            COALESCE(c.reservas_canceladas, 0)       AS reservas_canceladas
        FROM rentals_agg r
        FULL OUTER JOIN flota f
               ON f.anio = r.anio AND f.sede = r.sede AND f.acriss = r.acriss
        LEFT JOIN canceladas c
               ON c.anio = COALESCE(r.anio, f.anio)
              AND c.sede = COALESCE(r.sede, f.sede)
              AND c.acriss = COALESCE(r.acriss, f.acriss)
        ORDER BY anio, sede, acriss
    """)
    _exec(engine, "CREATE INDEX IF NOT EXISTS idx_kpi_sede_cat_anio ON silver.vw_kpi_sede_categoria_anual(anio, sede, acriss)")
    n = _scalar(engine, "SELECT COUNT(*) FROM silver.vw_kpi_sede_categoria_anual")
    log(f"   {n:,} filas ({time.time()-started:.1f}s)")


# =============================================================================
# main
# =============================================================================

def main():
    log("=" * 70)
    log("  SILVER BUILD -> Supabase Postgres (schema silver)")
    log("=" * 70)

    started = time.time()
    engine = get_engine("silver,bronze")

    # 1. DDLs en orden
    for ddl_file in sorted(DDL_DIR.glob("*.sql")):
        run_ddl(engine, ddl_file)

    # 2. dim_dates
    build_dim_dates(engine)

    # 3. ACRISS + rentals enriquecidos
    build_dim_vehicle_groups_decoded(engine)
    build_rentals_enriched(engine)

    # 4. TRM
    build_dim_trm_diaria(engine)

    # 5. Charges
    build_dim_charge_types(engine)
    build_charges_ra_enriched_view(engine)
    build_charges_rs_enriched_view(engine)

    # 6. Cierre diario
    build_cierre_diario_sede_table(engine)

    # 7-9. Vista 360, detalle, resumen
    build_rentals_full(engine)
    build_rentals_detail(engine)
    build_rentals_resumen(engine)

    # 10. Analiticas anuales
    build_kpi_anual(engine)
    build_demanda_anual(engine)
    build_demanda_sede_acriss_anual(engine)
    build_utilizacion_sede_categoria_mes(engine)
    build_flota_segmento_anual(engine)
    build_kpi_sede_categoria_anual(engine)

    report_counts(engine)

    log("\n" + "=" * 70)
    log(f"  SILVER BUILD COMPLETO en {time.time() - started:.1f}s")
    log("=" * 70)


if __name__ == "__main__":
    main()
