# Arquitectura — Trust Data Platform

> Decisiones de diseño del EDW Medallion. Léelo antes de implementar cambios estructurales.

---

## Principios fundamentales

1. **Local-first.** El volumen de Trust (decenas de miles de filas) cabe holgadamente en una máquina. No hay razón para pagar cloud hasta que el volumen lo justifique.
2. **Open formats.** SQLite + SQL estándar. Migrar a Postgres/Databricks/Snowflake es cambiar la cadena de conexión, no reescribir lógica.
3. **Idempotencia.** Cualquier pipeline puede correrse dos veces sin romper nada. Bronze incremental detecta duplicados con PK; Silver hace rebuild completo de `dim_*`/`fact_*`.
4. **Reproducibilidad.** Borrar `data/bronze.db` + `data/silver.db` y correr `bronze.full_load` + `silver.build` reconstruye el estado completo (excepto `op_*`, que son captura humana).
5. **Auditabilidad.** Cada corrida de Bronze deja log con qué se cargó, cuántas filas, cuánto tardó. Tabla `ctrl_extraction_log` en Bronze.

---

## Stack técnico

| Componente | Tecnología | Por qué |
|---|---|---|
| **Almacenamiento local** | SQLite (stdlib `sqlite3`) | Cero setup, viene con Python, suficiente para volúmenes Trust |
| **Conexión Redshift** | `redshift-connector` + `paramiko<4.0` + `sshtunnel` | Stack validado el 2026-04-30 |
| **Procesamiento** | pandas | DataFrame → `to_sql` para INSERTs masivos |
| **Config** | `pyyaml` + `python-dotenv` | tables.yml + .env |
| **Dashboard** | Streamlit + Plotly | Local, sin licencias |
| **Concurrencia readers/writers** | PRAGMA `journal_mode=WAL` | Permite que el dashboard lea mientras refresh escribe |

> **Nota histórica:** la decisión inicial (#1 del HANDOFF) era usar DuckDB. Se cambió a SQLite el 2026-05-04 por simplicidad operativa y compatibilidad directa con el dashboard demo que ya usaba `sqlite3`. Para los volúmenes actuales (~28K reservas, ~15K rentals, ~100K charges, ~20 tablas) SQLite es ampliamente suficiente.

---

## La arquitectura Medallion

### Bronze — la copia cruda

**Ubicación:** `data/bronze.db` (SQLite)
**Naming:** `<schema_origen>_<tabla_origen>` — ej. `rent_shop_rs_fct_reservations`
**Mutación:** append-only (incremental con DELETE-INSERT por PK) o replace (full load).
**Filtro siempre aplicado:** `WHERE mndt_code = 409`.

#### Reglas de Bronze

- **Espejo del origen.** Mismos nombres de columna que Redshift. Cero transformaciones de negocio.
- **Solo metadata adicional:** `_loaded_at` (timestamp del load), `_source_table` (tabla original).
- **Cero deduplicación, cero filtros adicionales, cero JOINs.** Lo que Sixt manda es lo que queda.
- Si Sixt actualiza un registro, el incremental hace DELETE+INSERT por PK y refleja la versión nueva.

#### Tabla de control

```sql
CREATE TABLE ctrl_extraction_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_datm        TIMESTAMP,
    table_name      TEXT,
    mode            TEXT,         -- FULL / INCREMENTAL_WATERMARK
    rows_loaded     INTEGER,
    watermark_to    TEXT,         -- max watermark de la corrida
    duration_sec    REAL,
    status          TEXT,         -- SUCCESS / EMPTY / FAILED
    error_detail    TEXT
);
```

---

### Silver — el modelo gobernado

**Ubicación:** `data/silver.db` (SQLite)
**Mutación:** rebuild completo de `dim_*` y `fact_*` cada corrida (DROP + CREATE AS SELECT desde Bronze attached). `op_*` con `CREATE TABLE IF NOT EXISTS` (nunca se borran).
**Refresco:** después de Bronze, ejecutar `pipelines/silver/build.py`.

#### Estructura de Silver — 4 grupos

##### 1. Dimensiones (`dim_*`) — naming PLURAL

| Tabla | Origen Bronze | Notas |
|---|---|---|
| `dim_branches` | `common_shop_br_dim_branches` | 6 sedes |
| `dim_mandants` | `common_shop_mn_dim_mandants` | 1 fila (409) |
| `dim_partners` | `customer_shop_pa_dim_partners_franchise` | 902 KDNRs B2B |
| `dim_agencies` | `customer_shop_pa_dim_agencies_franchise` | 651 |
| `dim_vehicle_groups` | `fleet_shop_ve_dim_vehicle_groups_franchise` | 13 ACRISS |
| `dim_vehicle_models` | `fleet_shop_ve_dim_vehicle_models` | 72,493 (global) |
| `dim_vehicles` | `fleet_shop_ve_dim_vehicles` | 183 master |
| `dim_vehicles_current` | `fleet_shop_ve_fct_vehicles_current` | 106 snapshot del estado |
| `dim_vehicles_history` | `fleet_shop_ve_fct_vehicles_current_incl_history` | 183 con historia (SCD2 viene de Sixt) |
| `dim_rate_plans` | `rent_shop_rt_dim_rates_franchise` | 1,434 con SCD2 implícito por `rate_gdat` |
| `dim_channels_rs` | `rent_shop_rs_dim_scd_channels_franchise` | 27,946 (1/reserva) |
| `dim_channels_ra` | `rent_shop_ra_dim_scd_channels_franchise` | 14,872 (1/rental) |
| `dim_dates` | (generada en build.py) | 4,018 días 2020-2030 + festivos CO básicos |
| `dim_customers` | **placeholder vacío** | Sixt no comparte B2C |
| `dim_employees` | **placeholder vacío** | Trust interno |

**SCD2 — decisión del 2026-05-04:** NO versionamos local. La historia que importa ya viene de Sixt en `dim_vehicles_history` (col `_loaded_at` por fila) y `dim_rate_plans` (col `rate_gdat`). Versionar nuestro lado agregaría complejidad sin valor.

##### 2. Hechos derivados de Sixt (`fact_*`)

| Tabla | Origen Bronze | Granularidad | Filas |
|---|---|---|---|
| `fact_reservations` | `rs_fct_reservations` | 1 fila por reserva | 27,946 |
| `fact_rentals` | `ra_fct_rentals_vwt_franchise` | 1 fila por contrato (RA) | 14,465 |
| `fact_rental_vehicles` | `ra_fct_rental_vehicles_franchise` | 1 fila por vehículo asignado a un rental | 15,218 |
| `fact_charges_rs` | `ch_fct_rs_charges_franchise` | 1 fila por cargo sobre reserva | 57,987 |
| `fact_charges_ra` | `ch_fct_ra_charges_franchise` | 1 fila por cargo sobre rental | 41,689 |
| `fact_damages` | `dm_fct_damages` | 1 fila por daño | 0 (datashare vacío) |
| `fact_damage_details` | `dm_fct_damage_details_franchise` | 1 fila por detalle | 0 |
| `fact_damage_cases` | `dm_dim_damage_cases_franchise` | 1 fila por case ID | 0 |
| `fact_payments` | **placeholder vacío** | — | 0 (Sixt no comparte payments individuales) |

##### 3. Tablas operativas Trust — Tramo 2 (`op_*`)

Schema-only, nunca tocadas por el rebuild. Trust las llena por su lado.

| Tabla | Para qué | Estado |
|---|---|---|
| `op_cierre_diario_sede` | Cierre operativo nocturno por sede | Vacía. **`vw_cierre_diario_sede` deriva esto de Tramo 1** — no necesita captura. |
| `op_novedades_vehiculo` | Fallas, documentos vencidos, limpieza, GPS | Vacía. Captura humana requerida. |
| `op_incidentes` | Accidentes, robos, vandalismo | Vacía. Captura humana requerida. |
| `op_checklist_apertura_cierre` | Score de apertura/cierre de sede | Vacía. Captura humana requerida. |
| `op_traslado_vehiculos` | Transferencias inter-sede con motivo y costo | Vacía. Captura humana requerida. |
| `op_solicitudes_soporte` | Tickets internos con SLA | Vacía. Captura humana requerida. |
| `op_contratos_soportes_faltantes` | Contratos con docs pendientes | Vacía. Captura humana requerida. |

##### 4. Vistas (`vw_*`)

| Vista | Granularidad | Para qué | Filas (aprox.) |
|---|---|---|---|
| `vw_rentals_full` | 1 / rental | Vista 360 del rental — sede, vehículo (incl. marca+modelo), categoría ACRISS, canales, totales en COP/USD/EUR, descuento, IVA, extras agregados. Base para detail/resumen. | ~14K |
| `vw_rentals_detail` | 1 / cargo | Detalle por cargo (counter + reserva) con contexto del rental, flag `cargo_coincide_reserva`, descuento e IVA del rental repetidos por fila. Source-of-truth para tablas item-por-item. | ~70K |
| `vw_rentals_resumen` | 1 / rental | Resumen comercial: tarifa + adicionales concatenados (`'SL, Y, BF'`) + bruto + descuento + neto + IVA + total. Source-of-truth para tabla principal del dashboard v2. | ~14K |
| `vw_cierre_diario_sede` | 1 / sede × día | KPIs de cierre derivados de Tramo 1. | ~10K |
| `vw_charges_ra_enriched` | 1 / cargo counter | Cargos del counter con decode (`T → Time and mileage`) + montos en COP/EUR/moneda original. | ~41K |
| `vw_charges_rs_enriched` | 1 / cargo reserva | Cargos de la reserva online enriquecidos. | ~58K |
| `vw_reservation_enriched` | 1 / reserva | Reserva + sede handover + sede return + grupo de vehículo. | ~28K |
| `vw_vehicle_current_state` | 1 / vehículo | Snapshot del estado actual de vehículo + sede + grupo. | 106 |
| `vw_ranking_sedes` | 1 / sede | Ranking ejecutivo por sede. | 6 |

**Las vistas se construyen en este orden** (cada una depende de las anteriores):

1. `dim_vehicle_groups_decoded` ← ACRISS decoder
2. `vw_rentals_enriched` ← rentals con 3 monedas
3. `dim_charge_types` ← seed de codigos
4. `vw_charges_ra_enriched`, `vw_charges_rs_enriched`
5. `vw_cierre_diario_sede` ← tabla materializada con cálculo histórico
6. `vw_rentals_full` ← vista 360 (depende de canales + extras)
7. `vw_rentals_detail` ← depende de `vw_rentals_full`
8. `vw_rentals_resumen` ← depende de `vw_rentals_detail`

Source-of-truth queries (Q1, Q2) usados por el dashboard v2 documentados en [docs/source_of_truth.md](docs/source_of_truth.md).

---

### Gold — agregaciones para reportes (futuro)

**Ubicación:** `data/gold.db` (SQLite, no creado todavía)
**Mutación:** rebuild completo cada corrida.
**Decisión pendiente:** si `vw_*` en Silver crecen mucho, mover a `gold.db` con tablas materializadas.

---

## Flujo de datos end-to-end

```
[REDSHIFT SIXT]
    │
    │  SSH tunnel (paramiko + sshtunnel)
    │  filtro: WHERE mndt_code = 409
    ▼
[pipelines/bronze/full_load.py]      ← una vez (full)
[pipelines/bronze/incremental.py]    ← cada 6h vía Task Scheduler (incremental_watermark + DELETE-INSERT)
    │
    │  pandas DataFrame por tabla, paginado en 50K filas
    │  df.to_sql(target, sqlite_conn, if_exists=...)
    │
    ▼
[data/bronze.db] (SQLite)
    │
    │  pipelines/silver/build.py
    │  - ATTACH bronze.db
    │  - DROP+CREATE de dim_* y fact_* desde bronze
    │  - CREATE IF NOT EXISTS de op_* (preserva data capturada)
    │  - dim_dates generada por código
    │  - vw_* DROP+CREATE
    │  - DETACH bronze
    │
    ▼
[data/silver.db] (SQLite)
    │
    │  Streamlit lee silver.db (read_only=True via URI mode)
    │
    ▼
[http://localhost:8501]
```

---

## Cadencia de refresh

| Capa | Frecuencia | Trigger | Tiempo típico |
|---|---|---|---|
| Bronze | Cada 6 horas | Task Scheduler ejecuta `scripts/refresh.bat` | 1-15 min (incremental: solo diffs) |
| Silver | Después de cada Bronze | Mismo script invoca `silver.build` | 4-10 s (rebuild de ~30 tablas chicas/medianas) |
| Gold | (cuando exista) | Después de Silver | TBD |

**Total tiempo por corrida estimado:** 5-15 minutos en estado estable.

**Concurrencia:** dashboard usa `read_only=True`. Bronze writer + Silver writer no chocan porque `silver.build` solo ATTACHa Bronze (no escribe ahí). PRAGMA WAL permite multiple readers + 1 writer.

---

## Estrategia de incremental refresh (Bronze)

Cada tabla en `tables.yml` declara su `mode`:

### Tablas con `mode: full`
Tablas chicas o snapshot: `br_dim_branches`, `mn_dim_mandants`, `pa_dim_agencies_franchise`, `ve_dim_vehicle_groups_franchise`, `ve_dim_vehicle_models`, `ve_fct_vehicles_current`, `ve_fct_vehicles_current_incl_history`, `rs_dim_scd_channels_franchise`, `ra_dim_scd_channels_franchise`.

```sql
DROP TABLE IF EXISTS bronze.<tabla>;
-- df.to_sql(target, conn, if_exists='replace')
```

### Tablas con `mode: incremental_watermark`
Tablas grandes con timestamp de update confiable. Watermarks reales (validados):

- `pa_dim_partners_franchise`: `sys_upd_datm`
- `ve_dim_vehicles`: `sys_upd_datm`
- `rs_fct_reservations`: `sys_upd_datm`
- `ra_fct_rentals_vwt_franchise`: `sys_upd_datm`
- `ra_fct_rental_vehicles_franchise`: `sys_upd_datm`
- `ch_fct_rs_charges_franchise`: `sys_upd_datm`
- `ch_fct_ra_charges_franchise`: `sys_upd_datm`
- `rt_dim_rates_franchise`: `rate_gdat`
- `dm_fct_damages`: `damg_date`
- `dm_fct_damage_details_franchise`: `ddet_last_timestamp`
- `dm_dim_damage_cases_franchise`: `sys_upd_datm`

```sql
SELECT * FROM redshift.<tabla>
WHERE mndt_code = 409
  AND <watermark_col> > '<last_watermark_de_ctrl_extraction_log>';

-- Para upsert: staging table SQLite + DELETE WHERE PK IN (SELECT PK FROM stg) + INSERT
```

---

## Manejo de errores

- **Bronze:** cada tabla en su propia transacción. Si falla, log en `ctrl_extraction_log` con `status=FAILED` y la siguiente tabla intenta. El watermark NO se guarda si falla, así la próxima corrida retoma desde el último exitoso.
- **Silver:** transacción única por archivo DDL. El `_strip_sql_comments` evita errores de parsing.
- **Reintento exponencial** para fallos de red SSH (no implementado todavía; agregar si hace falta).
- **Logs:** `logs/full_load_<ts>.log`, `logs/incremental_<ts>.log`, `logs/silver_build_<ts>.log`.

---

## Migración futura — qué cambia y qué no

Cuando el volumen requiera Postgres / Databricks:

| Componente | Cambia | No cambia |
|---|---|---|
| `open_local()` en `_common.py` | ✅ swap `sqlite3.connect` por `psycopg2`/`pyodbc` | |
| `df.to_sql(...)` → `COPY FROM` o equiv | ✅ | |
| `ATTACH DATABASE` → schema separado | ✅ | |
| `AUTOINCREMENT` → `SERIAL` / `IDENTITY` | ✅ | |
| **DDL de Silver** | | ✅ Casi idéntico (SQL estándar) |
| **Queries del dashboard** | | ✅ SQL estándar |
| **Lógica de incremental DELETE-INSERT** | | ✅ Misma |

Estimado de esfuerzo de migración: **3-5 días** una vez que se decida el destino.

---

## Decisiones que NO se debaten más (cerradas)

1. ❌ NO usar Power BI / Power Apps / Microsoft Fabric — descartados por costo y lock-in.
2. ❌ NO usar SharePoint Lists como base maestra.
3. ❌ NO conectarse a COBRA directo — el único camino es Redshift Data Exchange.
4. ✅ **SQLite** para todas las capas locales (override de la decisión #1 original que era DuckDB; ver HANDOFF.md).
5. ✅ Streamlit para el dashboard.
6. ✅ Python con `redshift-connector` + `paramiko<4.0` + `sshtunnel`.
7. ✅ **Naming PLURAL** en Silver (`dim_branches`, `fact_reservations`) para compatibilidad con dashboard demo.
8. ✅ **Silver rebuild completo** de `dim_*`/`fact_*` cada corrida; **`op_*` preservadas**.
9. ✅ **`vw_cierre_diario_sede` derivada de Tramo 1**, no captura manual.
10. ✅ Mismo branding Sixt (naranja `#ff6900`, negro).

---

## Diagrama de archivos clave

```
pipelines/
├── _common.py                    ← UNA SOLA fuente de verdad para conexiones
│                                    open_redshift(), open_local(layer, read_only=...)
├── bronze/
│   ├── full_load.py              ← carga inicial completa
│   ├── incremental.py            ← refresh por watermark (cada 6h)
│   ├── inspect.py                ← validación post-load
│   ├── explore.py                ← genera docs/data_dictionary.md
│   └── explore_remote.py         ← introspecciona Redshift sin bajar (usa SVV_REDSHIFT_COLUMNS)
├── silver/
│   ├── build.py                  ← orquesta DDL + dim_dates + report_counts
│   ├── tramo2_seed.py            ← stub (no se usa por decisión del 2026-05-04)
│   └── ddl/
│       ├── 01_dim.sql            ← CREATE TABLE dim_*
│       ├── 02_fact.sql           ← CREATE TABLE fact_*
│       ├── 03_tramo2.sql         ← CREATE TABLE IF NOT EXISTS op_*
│       └── 04_views.sql          ← CREATE VIEW vw_*
└── (gold/ - futuro)

config/
├── tables.yml                    ← tablas + watermarks REALES validados
└── watermarks.yml                ← (deprecated, info en tables.yml)

data/                              ← gitignored
├── bronze.db
├── silver.db
└── gold.db                       ← (futuro)

docs/
├── remote_schema.md              ← columnas Redshift via SVV_REDSHIFT_COLUMNS
├── data_dictionary.md            ← Bronze local con cardinalidad/% nulls/samples
├── inferred_watermarks.yml       ← informativo, NO usar programáticamente
├── bronze_tables.md              ← inventario manual
├── silver_dimensional.md         ← detalle del modelo Silver
└── runbooks.md                   ← troubleshooting

dashboard/                         ← (a portar en Fase D)
├── app.py
├── pages/
├── components/common.py
└── assets/styles.css
```

---

*Última revisión: 2026-05-04 — stack SQLite confirmado, Silver poblado.*
