# Handoff — Contexto Para Sesión Nueva de Claude

> **Lee esto primero si retomas el proyecto sin contexto previo.**
> Este documento contiene el estado actual, las decisiones tomadas, y los próximos pasos.

---

## El proyecto en 3 frases

1. Trust Colombia (franquicia de Sixt) está construyendo su propia plataforma de datos.
2. Sixt corporativo abrió acceso vía **Redshift Data Exchange** (validado el 2026-04-30) que da acceso a reservas, rentals, vehículos, daños, sedes, etc. filtrados al mandant 409 (Colombia).
3. Trust ingiere esa data localmente con arquitectura **Medallion** (Bronze → Silver → Gold) en **SQLite** y la sirve a un dashboard Streamlit.

---

## Estado actual (2026-05-04)

### ✅ Bronze poblado con data real

Archivo: `data/bronze.db` (105.81 MB, 21 tablas).

Counts confirmados (mandant 409):
- `rent_shop_rs_fct_reservations`: **27,946** filas (180 cols)
- `rent_shop_ra_fct_rentals_vwt_franchise`: **14,465** (174 cols)
- `rent_shop_ra_fct_rental_vehicles_franchise`: **15,218**
- `rent_shop_ch_fct_rs_charges_franchise`: **57,987**
- `rent_shop_ch_fct_ra_charges_franchise`: **41,689**
- `rent_shop_rs_dim_scd_channels_franchise`: **27,946**
- `rent_shop_ra_dim_scd_channels_franchise`: **14,872**
- `rent_shop_rt_dim_rates_franchise`: **1,434**
- `customer_shop_pa_dim_partners_franchise`: **902**
- `customer_shop_pa_dim_agencies_franchise`: **651**
- `fleet_shop_ve_dim_vehicle_models`: **72,493** (global, sin filtro mandant)
- `fleet_shop_ve_dim_vehicles`: **183**
- `fleet_shop_ve_fct_vehicles_current`: **106** (vehículos activos)
- `fleet_shop_ve_fct_vehicles_current_incl_history`: **183** (con historia)
- `fleet_shop_ve_dim_vehicle_groups_franchise`: **13** (ACRISS codes)
- `common_shop_br_dim_branches`: **6** sedes
- `common_shop_mn_dim_mandants`: **1**
- `damage_shop_dm_*`: **0** filas las tres tablas — Sixt no comparte daños en el datashare aún (no es un filtro nuestro: la fuente está vacía globalmente).

Full load tomó 297s. `ctrl_extraction_log` registra cada corrida.

### ✅ Silver poblado con derivación + placeholders

Archivo: `data/silver.db` (~112 MB).

**31 tablas + 4 vistas:**

| Familia | Tablas | Estado |
|---|---|---|
| `dim_*` (espejo Bronze) | 11 tablas | Pobladas |
| `dim_customers`, `dim_employees`, `fact_payments` | 3 placeholders | Vacíos (Sixt no comparte / Trust no captura aún) |
| `dim_dates` | 1 | 4,018 filas (2020-2030 con festivos CO básicos) |
| `fact_*` Tramo 1 | 6 tablas | Pobladas |
| `fact_damages*` | 3 tablas | Vacías (datashare no comparte) |
| `op_*` Tramo 2 | 7 tablas | **Vacías por diseño** — Trust las llena por su lado |
| `vw_*` | 4 vistas | Pobladas: `vw_cierre_diario_sede` (6,982), `vw_reservation_enriched` (27,946), `vw_vehicle_current_state` (106), `vw_ranking_sedes` (6) |

**Importante:** `vw_cierre_diario_sede` **reemplaza** la captura manual del demo: deriva los KPIs de cierre diario directamente desde `fact_rentals + fact_charges_ra + dim_vehicles_current`. La tabla `op_cierre_diario_sede` queda vacía pero el schema sigue ahí por compat con el dashboard.

Build tomó 4.2s.

Sanity check del ranking ejecutivo (`vw_ranking_sedes`):

| Sede | Rentals | Revenue (COP) | Vehículos | Ocupación |
|---|---:|---:|---:|---:|
| BOGOTA EL DORADO INTL AIRPORT | 3,449 | 6,356,724,934 | 33 | 69.7% |
| MEDELLIN AP JOSE MARIA CORDOVA | 4,684 | 5,876,529,654 | 27 | 59.3% |
| PEREIRA AIRPORT MATECANA INTL | 3,225 | 4,439,778,955 | 19 | 21.1% |
| MEDELLIN CITY EL POBLADO | 2,316 | 1,943,820,820 | 13 | 53.8% |
| BUCARAMANGA AIRPORT | 790 | 908,514,259 | 12 | 33.3% |
| COLOMBIA ZKST | 1 | 0 | 2 | 0% |

### ✅ Conexión Redshift — VALIDADA

- **SSH tunnel:** `<sixt-bastion-host>:22` con user `<ssh-user>` y key OpenSSH (path en `.env` local).
- **Cluster Redshift:** `<sixt-redshift-cluster>.redshift.amazonaws.com:5439`.
- **Database:** `<redshift-db>` (valor real en `.env`).
- **User:** `<redshift-user>` (RLS aplicado server-side, solo ve mandant 409).
- **Password:** vive en `.env` local.
- **Stack que funcionó:** Python + `paramiko<4.0` + `sshtunnel` + `redshift-connector` + `sslmode=require`.

**Quirk descubierto:** `information_schema.columns` viene **vacío** en consumer Redshift para tablas datashare. Hay que usar `SVV_REDSHIFT_COLUMNS` (vista de catálogo). `pipelines/bronze/explore_remote.py` ya está parchado.

### ✅ Documentación clave generada

- `docs/remote_schema.md` (85 KB) — todas las columnas de las 20 tablas Redshift.
- `docs/data_dictionary.md` (140 KB, 1,506 líneas) — Bronze local con cardinalidad, % nulls, samples, candidatos PK/watermark.
- `docs/inferred_watermarks.yml` (84 líneas) — informativo. **No usar programáticamente** (heurística da falsos positivos en tablas chicas).

---

## Lo que FALTA hacer (próximos pasos en orden)

### 🔜 Próximo paso 1 — Fase D: portar dashboard

**Objetivo:** llevar el dashboard de `c:\Users\Sebastian\Desktop\sixt-edw\trust_demo\dashboard\` a este proyecto y apuntarlo a `data/silver.db`.

Pasos:
1. Copiar `dashboard/app.py`, `pages/`, `components/common.py`, `assets/styles.css` desde el demo.
2. `components/common.py` ya usa `sqlite3` — se queda casi idéntico. Solo cambiar `DB_PATH` a `silver.db`. Importante: usar `read_only=True` con URI mode (`sqlite3.connect("file:silver.db?mode=ro", uri=True)`) para no chocar con el rebuild.
3. Las queries de la mayoría de páginas funcionan tal cual (mismos nombres de tabla en plural). Excepciones:
   - **`1_Cierre_Diario.py`**: cambiar `SELECT FROM op_cierre_diario_sede` → `SELECT FROM vw_cierre_diario_sede` (es derivada de Tramo 1, no captura manual).
   - **`3_Incidentes.py`, `2_Novedades.py`, etc.**: como `op_*` están vacías, agregar banner "Datos operativos pendientes de captura — esta vista se llenará cuando Trust empiece a registrar via formulario/app/Excel".
   - **`fact_payments`** está vacía: si alguna página lo consulta, banner similar.
4. Lanzar: `streamlit run dashboard/app.py`.

### 🔜 Próximo paso 2 — Refresh incremental + Task Scheduler

**Objetivo:** que cada 6h corra `bronze.incremental` + `silver.build`.

`pipelines/bronze/incremental.py` ya está. Crear `scripts/refresh.bat` que ejecute:
```bat
python -m pipelines.bronze.incremental
python -m pipelines.silver.build
```

Programar con Windows Task Scheduler cada 6h.

### 🔜 Próximo paso 3 — Captura Tramo 2

**Objetivo:** llenar las 6 tablas `op_*` que requieren captura humana (la séptima, `op_cierre_diario_sede`, ya tiene `vw_cierre_diario_sede` derivada).

Caminos posibles (no decidido):
- Forms Streamlit dentro del mismo dashboard (`8_Capturar_Cierre.py`, etc.).
- Importer Excel/CSV bulk.
- App móvil para personal de sede.

### 🔜 Próximo paso 4 — Gold layer

Vistas materializadas para reportes ejecutivos. Hoy las "vistas" están en Silver (`vw_*`). Si crecen mucho, mover a `data/gold.db` con rebuild propio.

### 🔜 Próximo paso 5 — Damages cuando Sixt los habilite

Las 3 tablas `damage_shop_dm_*` están vacías. Si Florian habilita acceso, el pipeline las cargará automáticamente sin cambios (ya están en `tables.yml`).

---

## Decisiones de diseño tomadas (no debatir, solo seguirlas)

1. **SQLite local en lugar de DuckDB.**
   - **Cambio del 2026-05-04** que sobreescribe la decisión #1 original ("DuckDB para todo").
   - **Razón:** SQLite viene en stdlib de Python, cero setup, alineado con dashboard demo que ya usaba `sqlite3.connect`. Para los volúmenes de Trust (decenas de miles de filas) la diferencia performance es invisible.
   - Migración futura cuando volumen crezca: SQLite → Postgres → Databricks. Cero re-trabajo en queries (mismo SQL estándar).

2. **Tres archivos `.db` separados** (`bronze.db`, `silver.db`, `gold.db` cuando exista).
   - **Razón:** aislamiento. Si Silver se rompe, Bronze sigue intacto y rebuilds son baratos.
   - **Bronze ↔ Silver vía `ATTACH DATABASE`** durante el build.

3. **Bronze es append-only o replace por tabla** (no upsert).
   - **Razón:** Bronze debe ser una réplica fiel de la fuente, sin lógica.

4. **Silver: rebuild completo de `dim_*` y `fact_*`** desde Bronze cada corrida (DROP + CREATE AS SELECT).
   - **Decisión del 2026-05-04** (Opción A vs B).
   - **Razón:** simple, idempotente, cero drift. Historia SCD2 que importa ya viene de Sixt (`ve_fct_vehicles_current_incl_history`, `rt_dim_rates_franchise` con `rate_gdat`). NO versionamos local.
   - **Excepción:** `op_*` usan `CREATE TABLE IF NOT EXISTS`, **nunca se borran en rebuild**.

5. **`vw_cierre_diario_sede` deriva el cierre diario** de Tramo 1.
   - **Decisión del 2026-05-04.**
   - **Razón:** `fact_rentals + fact_charges_ra + dim_vehicles_current` ya tienen los KPIs (rentals_count, returns_count, revenue_total, vehicles_in_branch, occupancy). Calcular es mejor que pedirle al operador de sede que lo capture manualmente cada noche.
   - Las otras 6 op_* sí necesitan captura humana porque registran eventos físicos / juicios operativos que Sixt no captura (novedades, incidentes, checklists, traslados, soporte, soportes faltantes).

6. **Tramo 2 vive en Silver** con prefijo `op_*`, no en una capa separada.

7. **Naming Silver: PLURAL** (`dim_branches`, `fact_reservations`).
   - **Decisión del 2026-05-04.** Override de ARCHITECTURE.md original que decía singular.
   - **Razón:** compatibilidad 1:1 con queries del dashboard demo, evita rewrites masivos en Fase D.

8. **Branding Sixt en el dashboard** — naranja `#ff6900` + negro `#000000`.

9. **Idioma del código:** comentarios en español, identificadores en inglés.

---

## Convenciones de código

- **Tablas Bronze:** `<schema>_<tabla>` (ej. `rent_shop_rs_fct_reservations`). SQLite no tiene schemas multi-nivel.
- **Tablas Silver:** prefijos plurales `dim_*`, `fact_*`, `op_*`. Vistas `vw_*`.
- **Columnas:** mantener nombres originales de Sixt en Bronze y Silver. NO renombrar.
- **Conexión:** **SIEMPRE** `pipelines._common.open_local(layer, read_only=...)`. Nunca `sqlite3.connect` directo en pipelines.
- **Read-only en dashboard:** `read_only=True` en `open_local` para no chocar con el refresh.

---

## Cómo continuar el trabajo en una sesión nueva de Claude

1. **Leer este HANDOFF.md primero.**
2. **Leer ARCHITECTURE.md** para entender decisiones de diseño.
3. **Verificar estado actual:**
   ```bash
   python -m pipelines.bronze.inspect            # estado Bronze
   sqlite3 data/silver.db "SELECT name FROM sqlite_master WHERE type='table'"
   ```
4. **Identificar el próximo paso pendiente** de la sección "Lo que FALTA hacer".
5. **Trabajar incrementalmente** — no rehacer lo ya hecho.

---

## Archivos clave

| Archivo | Para qué |
|---|---|
| `HANDOFF.md` | Este archivo — estado del proyecto |
| `ARCHITECTURE.md` | Decisiones de diseño + diagramas |
| `pipelines/_common.py` | `open_local(layer)` + `open_redshift()` |
| `pipelines/bronze/full_load.py` | Carga histórica desde Redshift |
| `pipelines/bronze/incremental.py` | Refresh por watermark |
| `pipelines/silver/build.py` | Rebuild Silver desde Bronze |
| `pipelines/silver/ddl/` | DDL del modelo Silver (01_dim, 02_fact, 03_tramo2, 04_views) |
| `config/tables.yml` | Lista validada de tablas Bronze + watermarks reales |
| `docs/data_dictionary.md` | Data dictionary local (PRAGMA + cardinalidad) |
| `docs/remote_schema.md` | Schema Redshift via SVV_REDSHIFT_COLUMNS |
| `.env` | Credenciales (no committeable) |

---

## Cosas que NO hacer

- ❌ NO instalar DuckDB. Stack es SQLite (stdlib).
- ❌ NO conectarse a producción de Sixt para queries operativas — Sixt explícitamente dijo "this solution is not built for operational queries". Solo ingestión batch.
- ❌ NO exponer la SSH key ni el `.env` a git/cloud/correos.
- ❌ NO borrar las `op_*` en un rebuild. El `silver/build.py` ya respeta esto con `CREATE TABLE IF NOT EXISTS`.
- ❌ NO sembrar Tramo 2 con data dummy (`tramo2_seed.py --demo`). Decisión del usuario el 2026-05-04: sin dummy, esperamos captura real.
- ❌ NO agregar Power Apps / Power Automate / Microsoft Fabric.
- ❌ NO mover la lógica a un cloud provider hasta que el volumen lo justifique (>5 GB o queries lentas con SQLite).

---

## Glosario rápido (para sesión nueva)

| Término | Significado |
|---|---|
| **Trust** | Franquicia colombiana de Sixt (el cliente) |
| **Sixt** | Empresa global, tiene Redshift Data Exchange |
| **Mandant** | Tenant en jerga Sixt; `409` = Colombia |
| **COBRA** | Sistema operativo central de Sixt (no accesible directamente, su data llega vía Redshift Data Exchange) |
| **Tramo 1** | Pre-rental + rental: reservas, asignación, checkout, charges. **Lo cubre Sixt vía COBRA → Redshift.** Hoy en `fact_*`. |
| **Tramo 2** | Operación física propia: novedades de vehículo, incidentes, checklists, traslados, soporte, soportes faltantes. **Trust lo captura propio.** Hoy en `op_*` (vacías). |
| **Florian Merkel** | Sixt corporate IT lead, contacto técnico |
| **Sven** | Quien envía credenciales de Sixt vía link de un solo uso |
| **Medallion** | Patrón Bronze (raw) → Silver (modelado) → Gold (analítica) |
| **SVV_REDSHIFT_COLUMNS** | Vista de catálogo Redshift que SÍ muestra columnas de datashares (information_schema NO funciona) |

---

*Última actualización: 2026-05-04 — Fase A+B+C cerradas. Bronze + Silver poblados con data real. Próxima sesión: Fase D dashboard.*
