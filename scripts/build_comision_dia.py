#!/usr/bin/env python3
"""
build_comision_dia.py - construye silver.fact_comision_dia (comisiones prorrateadas
por dia efectivo 24h) y genera la comparativa antes/despues en docs/.

TABLA NUEVA, no toca ninguna existente. Grano: 1 fila por (contrato x dia efectivo).

Regla de prorrateo (validada con el usuario 2026-08-27):
  - Base comisionable por contrato = SUMA de cargos pure-counter, periodo 0, de
    codigos COMISIONABLES, sin no-shows; con IVA 19%; COP a TRM Banrep del dia de
    entrega. (Identico a la base que ya calcula Cargos Granular.)
  - N = dias efectivos 24h = CEIL((devolucion - entrega)/24h), minimo 1.
  - Cada dia lleva base_total / N. Dias = fechas consecutivas desde la entrega
    (entrega + 0..N-1). Filtrar por ventana [desde,hasta] da el prorrateo.

Uso:
  python scripts/build_comision_dia.py           # crea la tabla + comparativa
  python scripts/build_comision_dia.py --no-build # solo re-genera la comparativa
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
load_dotenv()
from pipelines._common import get_engine  # noqa: E402
COMISIONABLES = ["AD", "BF", "LD", "BS", "UP", "CS", "BC", "PF", "SL"]
IVA = 1.19
TASA = 0.05  # 5% sobre base con IVA

_codes = ",".join(f"'{c}'" for c in COMISIONABLES)

# El DDL de silver.fact_comision_dia vive en pipelines/silver/build.py
# (build_comision_dia). Aqui NO se duplica: este script lo invoca. Asi la tabla
# que valida la comparativa es EXACTAMENTE la que construye el pipeline.

# "Antes" = logica actual de la pagina: rentas ENTREGADAS en la ventana, base completa.
OLD_SQL = f"""
SELECT d.operador_handover_codigo AS cod,
       SUM(ROUND(d.counter_cargo_usd::numeric * COALESCE(t.trm_cop_per_usd,0), 0)) * {IVA} AS base_cop
FROM silver.vw_rentals_detail d
LEFT JOIN silver.dim_trm_diaria t ON t.fecha = d.fecha_handover_real::date
WHERE d.cargo_codigo IN ({_codes})
  AND d.counter_cargo_usd > 0.01
  AND COALESCE(d.prepagado_cargo_usd, 0) < 0.01
  AND COALESCE(d.cargo_periodo, 0) = 0
  AND TRIM(COALESCE(d.placa, '')) <> ''
  AND d.fecha_handover_real::date BETWEEN :desde AND :hasta
GROUP BY 1
"""

# "Despues" = prorrateado: dias efectivos que caen en la ventana.
NEW_SQL = """
SELECT operador_handover_codigo AS cod,
       SUM(base_comision_cop_civa_dia) AS base_cop
FROM silver.fact_comision_dia
WHERE fecha BETWEEN :desde AND :hasta
GROUP BY 1
"""

NAMES_SQL = """
SELECT codigo_silver::text AS cod, TRIM(COALESCE(nombres,'') || ' ' || COALESCE(apellidos,'')) AS nombre
FROM operational.op_asesores WHERE codigo_silver IS NOT NULL
"""


def _fmt_cop(v: float) -> str:
    # Formato europeo: punto miles, coma decimales (regla del repo).
    s = f"{v:,.0f}".replace(",", ".")
    return f"${s}"


def _norm(v) -> str:
    # Los codigos vienen como float (7798873.0) o None; normalizar a entero-str.
    if v is None:
        return "(sin codigo)"
    try:
        return str(int(float(v)))
    except (ValueError, TypeError):
        return str(v)


def comparativa(eng, desde: str, hasta: str) -> list[dict]:
    with eng.connect() as c:
        old = {_norm(r[0]): float(r[1] or 0) for r in c.execute(text(OLD_SQL), {"desde": desde, "hasta": hasta})}
        new = {_norm(r[0]): float(r[1] or 0) for r in c.execute(text(NEW_SQL), {"desde": desde, "hasta": hasta})}
        names = {_norm(r[0]): r[1] for r in c.execute(text(NAMES_SQL))}
    rows = []
    for cod in sorted(set(old) | set(new)):
        bo, bn = old.get(cod, 0.0), new.get(cod, 0.0)
        rows.append({
            "cod": cod,
            "nombre": names.get(cod, "-") or "-",
            "base_old": bo, "base_new": bn, "delta_base": bn - bo,
            "com_old": bo * TASA, "com_new": bn * TASA, "delta_com": (bn - bo) * TASA,
        })
    rows.sort(key=lambda r: r["base_new"], reverse=True)
    return rows


def tabla_md(rows: list[dict]) -> str:
    h = ("| Codigo | Nombre | Base ANTES | Base DESPUES | Delta base | "
         "Comision ANTES (5%) | Comision DESPUES (5%) | Delta comision |\n"
         "|---|---|--:|--:|--:|--:|--:|--:|\n")
    body = ""
    for r in rows:
        body += (f"| {r['cod']} | {r['nombre']} | {_fmt_cop(r['base_old'])} | "
                 f"{_fmt_cop(r['base_new'])} | {_fmt_cop(r['delta_base'])} | "
                 f"{_fmt_cop(r['com_old'])} | {_fmt_cop(r['com_new'])} | {_fmt_cop(r['delta_com'])} |\n")
    tot = {k: sum(r[k] for r in rows) for k in ("base_old", "base_new", "delta_base", "com_old", "com_new", "delta_com")}
    body += (f"| **TOTAL** | | **{_fmt_cop(tot['base_old'])}** | **{_fmt_cop(tot['base_new'])}** | "
             f"**{_fmt_cop(tot['delta_base'])}** | **{_fmt_cop(tot['com_old'])}** | "
             f"**{_fmt_cop(tot['com_new'])}** | **{_fmt_cop(tot['delta_com'])}** |\n")
    return h + body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true", help="No recrear la tabla, solo la comparativa.")
    args = ap.parse_args()
    eng = get_engine("silver,bronze")

    if not args.no_build:
        from pipelines.silver.build import build_comision_dia
        build_comision_dia(eng)

    ventanas = [
        ("Julio 2026", "2026-07-01", "2026-07-31"),
        ("Agosto 2026 (parcial, al 27)", "2026-08-01", "2026-08-31"),
    ]
    out = ["# Comparativa comisiones: actual (por entrega) vs prorrateado (dias efectivos)",
           "",
           "**Generado:** " + dt.date.today().isoformat(),
           "",
           "**Que compara:** la BASE COMISIONABLE (con IVA, COP a TRM Banrep del dia de entrega) "
           "por asesor, en dos metodos:",
           "",
           "- **ANTES:** logica actual de Cargos Granular. La renta cuenta COMPLETA en el mes de "
           "ENTREGA. Si filtras julio, ves solo rentas entregadas en julio (enteras).",
           "- **DESPUES:** prorrateado. La renta aporta a cada mes solo sus dias efectivos 24h. "
           "Una renta entregada en junio que corre hasta julio aporta sus dias de julio a julio.",
           "",
           "La comision es el 5% de la base. Atribuida al asesor que ENTREGO (abrio) el contrato.",
           ""]
    for titulo, desde, hasta in ventanas:
        rows = comparativa(eng, desde, hasta)
        out.append(f"## {titulo}")
        out.append("")
        out.append(tabla_md(rows))
        out.append("")

    # docs/private/ (gitignored): trae nombres de asesores + cuanto se le paga a
    # cada uno, y el repo es publico.
    dest = REPO / "docs" / "private" / "comparativa_comisiones_prorrateo.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f">> comparativa escrita en {dest}")


if __name__ == "__main__":
    main()
