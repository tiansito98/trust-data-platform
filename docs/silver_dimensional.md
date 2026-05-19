# Silver — Modelo Dimensional

> Documentación del modelo Silver tal como existe HOY en `data/silver.db`.
> Última actualización: 2026-05-04 después del primer build exitoso.

---

## Filosofía

Silver es la **capa gobernada** donde la data tiene sentido para el negocio. Cuatro principios:

1. **Espejo enriquecido, no transformación radical.** Bronze es la fuente; Silver normaliza, indexa y agrega contexto via JOINs/vistas.
2. **Modelo dimensional Kimball.** `dim_*` = entidades, `fact_*` = eventos.
3. **Tramo 1 (Sixt) y Tramo 2 (Trust) conviven.** Tablas `op_*` (Trust) en el mismo schema que `dim_*` y `fact_*` (Sixt).
4. **Derivar antes que pedir captura.** Cuando un reporte se puede calcular de Tramo 1 (ej. cierre diario), una vista lo deriva. Captura humana solo para eventos físicos / juicios operativos que Sixt no captura.

---

## Naming PLURAL (decisión 2026-05-04)

Las tablas usan plural (`dim_branches`, `fact_reservations`) — override del original singular en ARCHITECTURE.md, para compatibilidad 1:1 con el dashboard demo.

---

## Las 4 familias en Silver

### `dim_*` — Dimensiones (15 tablas)

| Tabla | Origen Bronze | Filas | Notas |
|---|---|---:|---|
| `dim_branches` | `common_shop_br_dim_branches` | 6 | Sedes Trust CO |
| `dim_mandants` | `common_shop_mn_dim_mandants` | 1 | Solo 409 |
| `dim_partners` | `customer_shop_pa_dim_partners_franchise` | 902 | KDNRs B2B |
| `dim_agencies` | `customer_shop_pa_dim_agencies_franchise` | 651 | |
| `dim_vehicle_groups` | `fleet_shop_ve_dim_vehicle_groups_franchise` | 13 | ACRISS codes |
| `dim_vehicle_models` | `fleet_shop_ve_dim_vehicle_models` | 72,493 | Global, sin filtro mandant |
| `dim_vehicles` | `fleet_shop_ve_dim_vehicles` | 183 | Master |
| `dim_vehicles_current` | `fleet_shop_ve_fct_vehicles_current` | 106 | Snapshot del estado actual |
| `dim_vehicles_history` | `fleet_shop_ve_fct_vehicles_current_incl_history` | 183 | Historia (SCD2 viene de Sixt) |
| `dim_rate_plans` | `rent_shop_rt_dim_rates_franchise` | 1,434 | SCD2 implícito por `rate_gdat` |
| `dim_channels_rs` | `rent_shop_rs_dim_scd_channels_franchise` | 27,946 | 1 fila / reserva (cols rsrv_scd_level0/1/2) |
| `dim_channels_ra` | `rent_shop_ra_dim_scd_channels_franchise` | 14,872 | 1 fila / rental (cols rntl_scd_level0/1/2) |
| `dim_dates` | (generada en `build.py`) | 4,018 | 2020-2030 + festivos CO básicos |
| `dim_customers` | **placeholder vacío** | 0 | Sixt no comparte B2C — schema para que JOINs no rompan |
| `dim_employees` | **placeholder vacío** | 0 | Trust interno — futuro si se llena |

**Importante sobre `dim_channels_*`:** las dos tablas tienen estructura distinta (cols `rsrv_*` vs `rntl_*`), no se unifican en una sola `dim_channels`.

---

### `fact_*` — Hechos del Tramo 1 (9 tablas)

| Tabla | Origen Bronze | Granularidad | Filas |
|---|---|---|---:|
| `fact_reservations` | `rent_shop_rs_fct_reservations` | 1 / reserva | 27,946 |
| `fact_rentals` | `rent_shop_ra_fct_rentals_vwt_franchise` | 1 / contrato (RA) | 14,465 |
| `fact_rental_vehicles` | `rent_shop_ra_fct_rental_vehicles_franchise` | 1 / vehículo asignado a rental (incl. upgrades) | 15,218 |
| `fact_charges_rs` | `rent_shop_ch_fct_rs_charges_franchise` | 1 / cargo sobre reserva | 57,987 |
| `fact_charges_ra` | `rent_shop_ch_fct_ra_charges_franchise` | 1 / cargo sobre rental | 41,689 |
| `fact_damages` | `damage_shop_dm_fct_damages` | 1 / daño cabecera | 0 |
| `fact_damage_details` | `damage_shop_dm_fct_damage_details_franchise` | 1 / posición de daño | 0 |
| `fact_damage_cases` | `damage_shop_dm_dim_damage_cases_franchise` | 1 / case ID aseguradora | 0 |
| `fact_payments` | **placeholder vacío** | — | 0 |

**Por qué charges no se unifican:** `fact_charges_rs` tiene `chrs_resn` (FK a reserva) y `fact_charges_ra` tiene `chra_mvnr` (FK a rental). Estructuras de columnas distintas. Si una query necesita ambas, hace UNION ALL on-the-fly.

**Por qué damages están vacías:** `damage_shop.*` está vacío globalmente en el datashare al 2026-05-04 — no es un filtro nuestro, es que Sixt no comparte daños aún. Si Florian habilita acceso, el pipeline las cargará automáticamente.

**`fact_payments` placeholder:** Sixt comparte charges (cargos imponibles) pero no payments individuales (transacciones monetarias con método CARD/CASH/TRANSFER). El demo lo simulaba; en producción real vendría del POS de Trust.

---

### `op_*` — Operativas Tramo 2 (7 tablas)

Schema-only. **`silver/build.py` usa `CREATE TABLE IF NOT EXISTS` y NUNCA borra estas tablas en rebuild.** Trust las llena por su lado: forms, Excel, app móvil, lo que decida.

| Tabla | Para qué | Captura |
|---|---|---|
| `op_cierre_diario_sede` | Cierre operativo nocturno | **NO REQUIERE captura** — usar `vw_cierre_diario_sede` (derivada) |
| `op_novedades_vehiculo` | Documentos vencidos, fallas, llantas, batería, GPS, limpieza | Captura humana (operador de sede) |
| `op_incidentes` | Accidentes, robos, vandalismo, abandono | Captura humana |
| `op_checklist_apertura_cierre` | Score 0-7 de apertura/cierre con 7 ítems | Captura humana |
| `op_traslado_vehiculos` | Transferencias inter-sede con motivo, costo, conductor | Captura humana |
| `op_solicitudes_soporte` | Tickets internos con SLA | Captura humana |
| `op_contratos_soportes_faltantes` | Contratos con docs pendientes (licencia, foto, SOAT, etc.) | Captura humana o derivable parcialmente con queries |

---

### `vw_*` — Vistas derivadas (4 vistas)

| Vista | Para qué | Filas |
|---|---|---:|
| **`vw_cierre_diario_sede`** | KPIs de cierre derivados de Tramo 1 (rentals, returns, revenue, ocupación). **Reemplaza `op_cierre_diario_sede`.** | 6,982 |
| `vw_reservation_enriched` | Reserva + sede handover + sede return + grupo de vehículo | 27,946 |
| `vw_vehicle_current_state` | Snapshot estado actual con sede + grupo (joinea `dim_vehicles` para obtener `vhgr_crs`, que `dim_vehicles_current` no trae) | 106 |
| `vw_ranking_sedes` | Ranking ejecutivo por sede (rentals, revenue, vehículos, ocupación). Usa CTEs separadas para evitar inflación de filas en el JOIN. | 6 |

---

## Estrategia de derivación: Tramo 1 vs captura Tramo 2

| Reporte demo | Derivable de Tramo 1? | Cómo |
|---|---|---|
| Cierre Diario de Sede | ✅ SÍ | `vw_cierre_diario_sede` |
| Resumen Ejecutivo / Ranking | ✅ SÍ | `vw_ranking_sedes`, `vw_reservation_enriched` |
| Mix de flota | ✅ SÍ | JOIN `dim_vehicles_current` × `dim_vehicle_groups` |
| Reservas en riesgo | ✅ SÍ | Query sobre `fact_reservations` con handover futuro y sin vehículo asignado |
| Ocupación / utilización | ✅ SÍ | `vw_vehicle_current_state` + agregaciones |
| Daños | ⚠️ Cuando llegue data | `fact_damages` (vacía hoy) |
| Tarifas / cambios de precio | ✅ SÍ | `dim_rate_plans` con SCD2 implícito en `rate_gdat` |
| **Novedades de vehículo** | ❌ NO | Captura humana en `op_novedades_vehiculo` |
| **Incidentes** | ⚠️ Parcial | Sixt registra solo si hay daño cobrable; el resto va a `op_incidentes` |
| **Checklist apertura/cierre** | ❌ NO | Proceso interno Trust → `op_checklist_apertura_cierre` |
| **Traslados inter-sede** | ⚠️ Parcial | El cambio de sede del vehículo se ve en `dim_vehicles_current` pero no el motivo/costo/conductor → `op_traslado_vehiculos` |
| **Solicitudes de soporte** | ❌ NO | Tickets internos → `op_solicitudes_soporte` |
| **Soportes faltantes** | ⚠️ Parcial | Algunos derivables con queries (rentals sin licencia capturada) pero el juicio "está faltando X" lo marca un humano → `op_contratos_soportes_faltantes` |

---

## Estrategia de refresh

### `dim_*` y `fact_*` — REBUILD COMPLETO

```sql
DROP TABLE IF EXISTS dim_branches;
CREATE TABLE dim_branches AS SELECT * FROM bronze.common_shop_br_dim_branches;
CREATE INDEX IF NOT EXISTS idx_dim_branches_code ON dim_branches(brnc_code);
```

Ventaja: simple, idempotente, cero drift.
Costo: 4-10s para todo Silver.

### `op_*` — PRESERVAR

```sql
CREATE TABLE IF NOT EXISTS op_cierre_diario_sede ( ... );
```

Si la tabla ya existe, no se toca. Lo que Trust capturó queda intacto.

### `vw_*` — REBUILD

```sql
DROP VIEW IF EXISTS vw_cierre_diario_sede;
CREATE VIEW vw_cierre_diario_sede AS ...;
```

Las vistas son lógicas, no cuestan I/O; rebuild trivial.

---

## SCD2 — qué tenemos, qué no

**Lo que SÍ aprovechamos:**
- `dim_vehicles_history` (de `ve_fct_vehicles_current_incl_history`): trae filas históricas por vehículo. La granularidad es por update interno de Sixt; cada fila tiene `_loaded_at` (cuándo lo metimos en Bronze) y la dim no fue versionada por nosotros.
- `dim_rate_plans` (de `rt_dim_rates_franchise`): tiene `rate_gdat` (effective date) y `rate_vdat`. La PK efectiva es `(rate_prl, rate_gdat)` → es SCD2 implícito en la fuente.

**Lo que NO hacemos (decisión 2026-05-04):**
- NO versionamos local con `_valid_from/_valid_to/_is_current/_hash`. Si en el futuro Trust necesita auditoría de "cuándo cambió X en mi sistema", se puede agregar después. Por ahora, `_loaded_at` en cada fila Bronze es suficiente para audit.

### Cómo hacer point-in-time joins con SCD2 que SÍ tenemos

```sql
-- Tarifa que aplicaba a una reserva en el momento que se hizo
SELECT
    r.rsrv_resn,
    r.rsrv_date,
    rp.rate_type,
    rp.rate_designation,
    rp.rate_gdat
FROM fact_reservations r
JOIN dim_rate_plans rp
  ON rp.rate_prl = r.rate_prl   -- ojo: confirmar nombre de la columna en fact_reservations
 AND r.rsrv_date >= rp.rate_gdat
 AND r.rsrv_date <  COALESCE(rp.rate_next_gdat, '9999-12-31');
```

---

## Estructura de archivos DDL

```
pipelines/silver/ddl/
├── 01_dim.sql       ← CREATE TABLE dim_* (incluye placeholders + dim_dates schema vacío)
├── 02_fact.sql      ← CREATE TABLE fact_* (incluye placeholders fact_payments)
├── 03_tramo2.sql    ← CREATE TABLE IF NOT EXISTS op_*
└── 04_views.sql     ← DROP VIEW + CREATE VIEW vw_*
```

`dim_dates` se popula programáticamente en `silver/build.py` porque SQLite no tiene `generate_series`. Festivos CO hardcodeados en el código (6 fijos: Año Nuevo, Trabajo, Independencia, Boyacá, Inmaculada, Navidad).

---

## Performance

- **Indexes** automáticos en `*.brnc_code`, `*.rsrv_resn`, `*.rntl_mvnr`, `*.vhcl_int_num`, `*.vhgr_crs` (declarados en cada DDL).
- **PRAGMA `journal_mode = WAL`** en `_common.open_local()` permite que el dashboard lea mientras refresh escribe.
- **Para queries pesadas en el dashboard:** usar `@st.cache_data(ttl=300)` en Streamlit.
- **Tamaño actual `silver.db`:** ~112 MB. SQLite maneja sin problema hasta varios GB.

---

## Tareas pendientes para evolucionar Silver

1. **`fact_charges` UNION view** (no tabla): si el dashboard quiere ver charges de RS+RA juntos, crear `vw_charges_all` con UNION ALL + columna `charge_source`.
2. **`vw_partner_current`**: si se materializa SCD2 en `dim_partners`, agregar vista para "partner como está hoy".
3. **`dim_employees` y `dim_customers`**: si Trust empieza a llenarlas, decidir flujo de captura.
4. **Reservas en riesgo**: agregar `vw_reservations_at_risk` para reportes ejecutivos.
5. **Festivos CO completos**: hoy hardcodeo solo los 6 fijos. Los movibles (Pascua, Asunción, etc.) requieren cálculo o tabla de seed.

---

*Mantener este documento actualizado conforme se evolucione el modelo Silver.*
