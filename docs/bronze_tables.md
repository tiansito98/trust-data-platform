# Bronze — Inventario de Tablas

> Inventario de las ~20 tablas que Bronze ingiere desde el Redshift Data Exchange de Sixt.
>
> Estado a **2026-04-30** después de la primera conexión exitosa.

---

## Schemas confirmados

| Schema | Para qué |
|---|---|
| `common_shop` | Datos compartidos: sedes, mandantes |
| `customer_shop` | Partners (clientes corporativos), agencias |
| `damage_shop` | Daños y casos asociados |
| `fleet_shop` | Vehículos y categorías (incluye SCD2 history) |
| `rent_shop` | Reservas, rentals, charges, channels, rates |

---

## Tablas — vista completa

### `common_shop`

| Tabla | Filas Trust CO | Notas |
|---|---|---|
| `br_dim_branches` | 6 | **Interesante: 6 sedes, no 5.** Investigar. |
| `mn_dim_mandants` | 1 | Solo `409` (RLS funciona) |

### `customer_shop`

| Tabla | Filas Trust CO | Notas |
|---|---|---|
| `pa_dim_partners_franchise` | TBD | KDNRs corporativos |
| `pa_dim_agencies_franchise` | TBD | Agencias |

### `fleet_shop`

| Tabla | Filas Trust CO | Notas |
|---|---|---|
| `ve_dim_vehicle_groups_franchise` | TBD | Categorías ACRISS |
| `ve_dim_vehicle_models` | TBD | Modelos físicos |
| `ve_dim_vehicles` | TBD | Master de vehículos |
| `ve_fct_vehicles_current` | 106 | Snapshot del estado actual |
| `ve_fct_vehicles_current_incl_history` | TBD | **SCD2 — fuente de verdad histórica** |

### `rent_shop`

| Tabla | Filas Trust CO | Notas |
|---|---|---|
| `rs_fct_reservations` | **27,946** | Reservas |
| `rs_dim_scd_channels_franchise` | TBD | Canales SCD asociados a reservas |
| `ra_fct_rentals_vwt_franchise` | TBD | Rentals (RAs) |
| `ra_fct_rental_vehicles_franchise` | TBD | Historia de vehículos por rental |
| `ra_dim_scd_channels_franchise` | TBD | Canales SCD asociados a rentals |
| `ch_fct_rs_charges_franchise` | TBD | Charges sobre reservas |
| `ch_fct_ra_charges_franchise` | TBD | Charges sobre rentals |
| `rt_dim_rates_franchise` | TBD | Tarifas con histórico |

### `damage_shop`

| Tabla | Filas Trust CO | Notas |
|---|---|---|
| `dm_fct_damages` | 0 | **0 filas inicialmente.** Confirmar si es la tabla correcta o si hay versión `_franchise`. |
| `dm_fct_damage_details_franchise` | TBD | Detalles por daño (multi-position) |
| `dm_dim_damage_cases_franchise` | TBD | Damage case IDs |

---

## Convención de naming en Bronze local

Las tablas se renombran con `_` reemplazando el `.` del schema original:

```
rent_shop.rs_fct_reservations  →  rent_shop_rs_fct_reservations
fleet_shop.ve_dim_vehicles     →  fleet_shop_ve_dim_vehicles
```

DuckDB no soporta nested schemas como Redshift, por eso el flatten.

---

## Columnas adicionales agregadas en Bronze

A cada tabla se le agregan al cargar:

| Columna | Tipo | Para qué |
|---|---|---|
| `_loaded_at` | TIMESTAMP | Momento del load, útil para debug y auditoría |
| `_source_table` | VARCHAR | Tabla origen (ej. `rent_shop.rs_fct_reservations`) |

---

## Tareas pendientes de exploración

### 1. Investigar la sede #6

```sql
SELECT brnc_code, brnc_name, brnc_main_type, brnc_city, brnc_active_flg
FROM common_shop_br_dim_branches
ORDER BY brnc_code;
```

Trust dijo que opera en 5 ciudades (Bogotá, Medellín, Bucaramanga, Pereira, Rionegro). La 6ta puede ser:
- Sede dual (downtown + airport en una misma ciudad).
- Sede deshabilitada que sigue en el master.
- Sede en proceso de apertura.

### 2. Confirmar estructura SCD2 en `ve_fct_vehicles_current_incl_history`

```sql
DESCRIBE bronze.fleet_shop_ve_fct_vehicles_current_incl_history;
```

Verificar si las columnas SCD2 son:
- `_valid_from` / `_valid_to` (formato Sixt)
- O `valid_from` / `valid_to` (sin underscore)
- O alguna otra convención

Eso afecta directamente el DDL de `silver/ddl/01_dim.sql`.

### 3. Confirmar si `dm_fct_damages` realmente tiene 0 filas para Trust CO

```sql
SELECT mndt_code, COUNT(*) AS n
FROM bronze.damage_shop_dm_fct_damages
GROUP BY mndt_code
ORDER BY mndt_code;
```

Si efectivamente tiene 0, podría ser que Trust use otra tabla (¿`_franchise`?) o que históricamente no se hayan subido daños desde Colombia.

### 4. Identificar columnas watermark reales

Para cada tabla en `config/tables.yml` con `mode: incremental_watermark`, validar que la columna `watermark_col` efectivamente existe y cambia con cada update:

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = '<SCHEMA>'
  AND table_name = '<TABLE>'
  AND data_type IN ('timestamp', 'timestamp without time zone', 'timestamp with time zone', 'date')
ORDER BY column_name;
```

---

## Sample queries de validación

### Conteo total por mandant en cada tabla principal

```sql
-- Tablas principales de Trust CO con sus volúmenes
SELECT
    'rs_fct_reservations'              AS tabla,
    COUNT(*)                           AS filas
FROM bronze.rent_shop_rs_fct_reservations
WHERE mndt_code = 409
UNION ALL
SELECT 'ra_fct_rentals_vwt_franchise', COUNT(*)
FROM bronze.rent_shop_ra_fct_rentals_vwt_franchise
WHERE mndt_code = 409
UNION ALL
SELECT 've_fct_vehicles_current', COUNT(*)
FROM bronze.fleet_shop_ve_fct_vehicles_current
WHERE mndt_code = 409
UNION ALL
SELECT 'br_dim_branches', COUNT(*)
FROM bronze.common_shop_br_dim_branches
WHERE mndt_code = 409;
```

### Rango de fechas disponible

```sql
SELECT
    MIN(rsrv_date)  AS first_reservation,
    MAX(rsrv_date)  AS last_reservation,
    COUNT(*)        AS total_reservations
FROM bronze.rent_shop_rs_fct_reservations
WHERE mndt_code = 409;
```

### Health check de la última extracción

```sql
SELECT
    table_name,
    MAX(run_datm)       AS last_run,
    SUM(rows_loaded)    AS total_rows_ever,
    MAX(status)         AS last_status
FROM ctrl_extraction_log
GROUP BY table_name
ORDER BY last_run DESC;
```

---

*Actualizar este documento después del primer full load real con los conteos definitivos.*
