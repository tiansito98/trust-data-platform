# Coding style — Trust Data Platform

> Cómo escribir vistas/funciones/queries nuevas para que se sientan parte del mismo sistema.

## Filosofía

1. **Toda la lógica de negocio vive en `pipelines/silver/build.py`.** El dashboard, notebooks y scripts ad-hoc son consumidores tontos.
2. **Una función por vista en `build.py`.** Patrón: `def build_<nombre>(con): ...`. Se llama desde `main()` en orden de dependencia.
3. **Convención `vw_*`:** todas las vistas se materializan como `CREATE TABLE`. El prefijo `vw_` queda por convención histórica.
4. **Idempotencia.** El rebuild completo de Silver corre en ~15s. Cualquier función debe poder correrse N veces sin acumular estado.
5. **Documentación inline.** Comentar el **por qué** del JOIN o del filtro, no el qué.

## Plantilla para una nueva vista

```python
def build_<nombre_vista>(con):
    """Vista <descripcion corta>: 1 fila por <granularidad>.

    <Que hace y por que existe. Mencionar de qué tablas viene y
    cualquier filtro/regla de negocio no obvia.>

    Granularidad: <PK efectivo>
    """
    log("\n>> Construyendo vw_<nombre_vista>")
    started = time.time()
    try:
        con.execute("DROP TABLE IF EXISTS vw_<nombre_vista>")
    except sqlite3.OperationalError:
        pass
    con.execute("DROP VIEW IF EXISTS vw_<nombre_vista>")

    con.execute("""
        CREATE TABLE vw_<nombre_vista> AS
        WITH ...
        SELECT ...
    """)

    # Indices para los WHEREs comunes del dashboard
    con.execute("CREATE INDEX IF NOT EXISTS idx_<nombre>_<col> ON vw_<nombre_vista>(<col>)")
    con.commit()

    n = con.execute("SELECT COUNT(*) FROM vw_<nombre_vista>").fetchone()[0]
    log(f"   {n:,} filas ({time.time()-started:.1f}s)")
```

**Patrón `try DROP TABLE / DROP VIEW`:** en rebuilds intermedios la vista puede haber existido como `VIEW` o como `TABLE`. Hacer ambos drops cubre los dos casos sin fallar.

## Convenciones SQL

### Nombres de columna (Silver → Dashboard)

Renombrar todos los `chra_chco`/`rntl_mvnr`/`rsrv_resn` a algo en español:

| Bronze (crudo) | Silver (legible) |
|---|---|
| `rntl_mvnr` | `numero_contrato` |
| `rsrv_resn` | `numero_reserva` |
| `chra_chco` / `chrs_chco` | `cargo_codigo` |
| `chra_value_local` | `subtotal_cop` |
| `vhcl_plate` | `placa` |
| `rntl_handover_date` | `fecha_handover_real` |
| `brnc_code` | `sede_codigo` |
| `rntl_revenue_local_currency` | `revenue_total_cop` |

### Monedas paralelas

Cuando hay valores monetarios, **exponer las 3 monedas en columnas paralelas** (no convertir):
- `<algo>_cop` — pesos colombianos (moneda local del franchisee)
- `<algo>_usd` — dólares (poblado solo cuando `rental_currency = 'USD'`, NULL si no)
- `<algo>_eur` — euros (moneda corporativa Sixt)

**Nunca aplicar TRM en silver para convertir.** Si el contrato fue en USD, el USD viene directo de bronze. Si fue en COP, el USD queda NULL. El dashboard decide qué mostrar.

### Filtros estándar

```sql
WHERE c.chra_konr = 0           -- siempre: evita duplicados por correcciones
  AND mndt_code = 409           -- siempre: filtro de mandant Colombia (a nivel bronze ya filtrado, pero defensivo)
```

### CTEs sobre subqueries

Preferir `WITH ... AS (...)` anidados sobre subqueries en `FROM`. Mantiene la query lineal de leer.

### `MAX()` para columnas no agregadas

Cuando un `GROUP BY numero_contrato` necesita arrastrar columnas que son constantes por contrato (fecha, placa, etc.), usar `MAX(col)` en vez de inventar grupos sintéticos. SQLite lo permite y es lo que el proyecto ya usa.

## Convenciones para el dashboard

### Filtros estándar a aplicar siempre

```sql
WHERE fuente_cargo = 'RENTAL_COUNTER'   -- la "verdad" firmada en counter
  AND rental_currency = 'USD'           -- si la vista usa montos USD
```

### Formato visual

- **Pesos colombianos:** `$1.502.654,05` (punto miles, coma decimal — formato europeo).
- **Millones**, no "billones". En español "billón" = 10^12. Usar "mil millones" para 10^9.
- **NO emojis** en ningún lado (código, dashboard, commits, exports).
- **Fechas:** `YYYY-MM-DD` siempre, no formatos locales.

### Read-only desde Streamlit

```python
con = sqlite3.connect('file:data/silver.db?mode=ro', uri=True)
```

`mode=ro` permite que el refresh corra simultáneo sin bloquear el dashboard.

## Convenciones para notebooks

`notebooks/_*.py` son scripts ad-hoc que generan Excels para Trust. Naming: `_<reporte>_<sede>.py`. Salida con sufijo de versión: `<reporte>_<sede>_<periodo>_v<N>.xlsx`. Si el archivo está abierto en Excel, bump el `N` (no overwrite forzado).

## Cómo agregar una columna nueva a una vista existente

1. Editar la función `build_<vista>` en `pipelines/silver/build.py`.
2. Si la columna depende de un nuevo JOIN, agregar el JOIN solo si no existe.
3. Si la columna debe propagarse a vistas que dependen de esta (ej. agregar algo a `vw_rentals_full` que necesita aparecer en `vw_rentals_detail`), editar también la SELECT downstream.
4. Re-correr `python -m pipelines.silver.build` — no hay migrations, el rebuild es la migration.
5. Si la columna se usa en una query source-of-truth, actualizar `docs/source_of_truth.md`.

## Cómo agregar una vista completamente nueva

1. Escribir `build_<nueva>(con)` siguiendo la plantilla de arriba.
2. Agregar la llamada en `main()` después de sus dependencias.
3. Decidir si materializar (`CREATE TABLE`) — default sí — o dejar como `CREATE VIEW`. Materializar conviene cuando el query es pesado o se consulta mucho desde el dashboard.
4. Crear índices para los WHEREs típicos del dashboard.
5. Documentar en [ARCHITECTURE.md](../ARCHITECTURE.md) sección "Vistas (`vw_*`)" y, si es source-of-truth, en [source_of_truth.md](source_of_truth.md).

## Anti-patrones (cosas que NO hacemos)

- **No SQL embebido en el dashboard.** Si lo necesitas, conviértelo en vista.
- **No `pd.read_sql` desde `bronze.db`** en scripts/dashboard. Pasar siempre por silver. (Excepción: scripts de exploración en `notebooks/`.)
- **No aplicar TRM para convertir.** USD/COP/EUR siempre vienen de bronze paralelos.
- **No mockear DBs en tests.** El usuario lo pidió explícitamente — usar `silver.db` real.
- **No commitear archivos generados** (`*.xlsx` en `notebooks/`, `data/*.db`, `*.log`). Ver `.gitignore`.
- **No usar `LIKE '%foo%'`** en columnas grandes cuando hay un código exacto. Buscar el código en `dim_charge_types` y joinear.
- **No `SELECT *`** en producción (vistas, dashboard). Listar columnas explícitamente.
