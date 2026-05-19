# Trust Data Platform — Guía rápida

> Léeme antes de tocar código. Apuntadores a documentación detallada al final.

## Stack en una línea

SQLite (no DuckDB) + Medallion (Bronze → Silver → Gold) + Streamlit. Origen: Redshift Sixt (mandant 409) vía SSH tunnel + `redshift-connector`.

## Cómo correr el refresh

```powershell
# Bronze incremental + TRM Banrep + Silver rebuild en un solo paso:
.\scripts\refresh.bat

# O manual, paso a paso:
python -m pipelines.bronze.incremental       # ~2-3 min
python -m pipelines.bronze.external_trm      # ~1 s — TRM oficial datos.gov.co
python -m pipelines.silver.build             # ~15 s
```

`scripts/refresh.bat` está pensado para Task Scheduler cada 6 horas. Cuando migremos a la nube, el equivalente serían tres jobs encadenados. Si llevamos N días sin correr, el incremental de TRM recupera todas las TRMs faltantes en una sola llamada.

## Cómo correr el dashboard

```powershell
.\scripts\dashboard.bat
# o
streamlit run dashboard/app.py
```

## Layout del repo

```
trust_data_platform/
├── config/
│   ├── tables.yml          ← qué tabla Redshift bajar y en qué modo
│   └── .env                ← credenciales SSH/Redshift (NO commitear)
├── pipelines/
│   ├── bronze/
│   │   ├── full_load.py        ← reset completo desde Redshift
│   │   ├── incremental.py      ← cada 6h, DELETE+INSERT por PK con watermark
│   │   └── explore_remote.py   ← introspección de datashare (SVV_REDSHIFT_COLUMNS)
│   ├── silver/
│   │   ├── ddl/*.sql           ← DDL declarativo para dim_*, fact_*, op_*
│   │   └── build.py            ← rebuild completo. Toda la lógica de view aquí.
│   └── gold/                   ← (vacío, futuro)
├── data/
│   ├── bronze.db               ← espejo crudo, ~70 MB
│   └── silver.db               ← modelo gobernado, ~50 MB
├── dashboard/
│   ├── app.py                  ← Streamlit entrypoint
│   ├── pages/                  ← 1 archivo por página
│   └── components/             ← reusables (filtros, banner sticky)
├── notebooks/                  ← scripts ad-hoc / exports a Excel
└── docs/
    ├── architecture.md         ← decisiones de diseño (LEER)
    ├── source_of_truth.md      ← queries source-of-truth para el dashboard v2
    ├── coding_style.md         ← convenciones para escribir nuevas vistas
    ├── charge_codes.md         ← mapping de codigos de cargo (T, BF, SL, ...)
    └── runbooks.md             ← troubleshooting
```

## Vistas source-of-truth (silver)

| Vista | Granularidad | Para qué |
|---|---|---|
| `vw_rentals_full` | 1 fila / rental | Vista 360 del rental — todo en una fila. Base para el resto. |
| `vw_rentals_detail` | 1 fila / cargo | Detalle por cargo con contexto del rental. Para mostrar items por contrato. |
| `vw_rentals_resumen` | 1 fila / rental | Resumen comercial: tarifa + adicionales concatenados + neto + IVA + total. |
| `dim_trm_diaria` | 1 fila / día calendario | TRM oficial Banrep (vía datos.gov.co). Para calcular revenue COP real. |
| `vw_kpi_anual` | 1 fila / año | KPIs anuales: flota, ocupación, RPD, ingresos. Dashboard v3. |
| `vw_demanda_anual` | 1 fila / año | % served + cancel rate desagregado por causa. Dashboard v3. |
| `vw_utilizacion_sede_categoria_mes` | 1 fila / mes × sede × ACRISS | Utilización mensual por categoría. Dashboard v3. |
| `vw_flota_segmento_anual` | 1 fila / año × sede × ACRISS | Evolución del mix de flota. Dashboard v3. |
| `vw_cierre_diario_sede` | 1 fila / sede × día | KPIs operativos diarios. |
| `vw_charges_ra_enriched` | 1 fila / cargo | Cargos del counter con decode de codigo + 3 monedas. |
| `vw_charges_rs_enriched` | 1 fila / cargo | Cargos de la reserva online. |

Estas vistas son **tablas materializadas** (prefijo `vw_` por convención histórica). Se reconstruyen cada `silver/build.py`.

## Reglas de oro

1. **No DuckDB.** El stack es SQLite. Lo confirmó el usuario el 2026-05-04.
2. **Bronze es espejo crudo.** Mismos nombres de columna que Redshift. Cero lógica de negocio.
3. **Toda la lógica vive en `pipelines/silver/build.py`.** Una función por vista, todas se llaman desde `main()`.
4. **No mockear DBs en tests** (lección aprendida). Usar `silver.db` real.
5. **No emojis en código ni dashboard.** El usuario lo pidió explícitamente.
6. **Pesos colombianos:** formato europeo (`$1.502.654,05` — punto miles, coma decimal). Y "mil millones" NO "billones".
7. **Convención `vw_*`:** todas las vistas se materializan como `CREATE TABLE`. Patrón `try DROP TABLE / DROP VIEW IF EXISTS` antes de crear (porque puede existir como cualquiera de los dos tipos en rebuilds intermedios).
8. **Idempotencia:** cualquier pipeline corre dos veces sin romper nada.

## Modelo Sixt — claves importantes

- `mndt_code = 409` → mandant Colombia. Se filtra siempre.
- `rntl_mvnr` → numero de contrato (PK de `fact_rentals`)
- `rsrv_resn` → numero de reserva (PK de `fact_reservations`)
- `chra_konr` → version del cargo. **Posicion vigente = `(inty, pos)` cuyo `MAX(konr)` iguala al `MAX(konr)` global del contrato.** Cuando Sixt corrige un contrato inserta una "wave" nueva de filas con konr+1 y **omite** las posiciones que dejaron de aplicar; tomar solo `MAX(konr)` por pos sin chequear el global deja huerfanas a esas posiciones obsoletas (ej. contrato 9522967577 tenia Y pos 4 konr 0 que quedo obsoleta cuando T/AD/Y3 se corrigieron a konr 1). La regla esta implementada en `vw_charges_ra_enriched` y `vw_rentals_detail`. Histórico: hasta 2026-05-13 usabamos `konr = 0` (ocultaba 261 cargos); 2026-05-13 paso a `MAX(konr) por pos` (corrigio caso OT pero dejaba huerfanas); misma fecha refinado a la regla actual (MAX_pos = MAX_global, cuadra 99.97%).
- ACRISS → 4-letter category code (ej. `IDAR` = Intermediate Door Auto Refrigerated). Decodificado en `dim_vehicle_groups_decoded`.
- Bug datashare: la columna se llama `rntl_distount_local` (con typo, NO `discount`).

## Pendientes conocidos

Ver `~/.claude/projects/c--Users-Sebastian-Desktop-trust-data-platform/memory/` para memoria de Claude.

Más detalle en:
- [ARCHITECTURE.md](ARCHITECTURE.md) — decisiones de diseño, flujo end-to-end, estrategia de refresh
- [docs/dashboard_v2_plan.md](docs/dashboard_v2_plan.md) — **plan del dashboard v2 con los 5 objetivos y queries**
- [docs/dashboard_v3_plan.md](docs/dashboard_v3_plan.md) — **dashboard v3 (visión histórica, puerto 8503)**
- [docs/source_of_truth.md](docs/source_of_truth.md) — queries finales para el dashboard v2
- [docs/coding_style.md](docs/coding_style.md) — cómo escribir una vista nueva
- [docs/charge_codes.md](docs/charge_codes.md) — diccionario de codigos `T`, `BF`, `SL`, etc.
- [docs/runbooks.md](docs/runbooks.md) — troubleshooting SSH/Redshift
