# Runbooks — Procedimientos Operativos y Troubleshooting

> Qué hacer cuando algo falla. Mantener actualizado con cada incidente real.

---

## Connection issues (Redshift / SSH)

### Síntoma: `AttributeError: module 'paramiko' has no attribute 'DSSKey'`

**Causa:** Paramiko 4.0 (lanzado abril 2026) eliminó DSSKey por deprecación de DSA en OpenSSH 2025. La librería `sshtunnel` todavía lo importa.

**Fix:**
```powershell
pip install "paramiko<4.0" --upgrade
python -c "import paramiko; print(paramiko.__version__)"   # debe ser 3.5.x
```

---

### Síntoma: `WARNING: UNPROTECTED PRIVATE KEY FILE`

**Causa:** Permisos de la SSH key son demasiado abiertos.

**Fix:**
```powershell
icacls "$env:USERPROFILE\.ssh\sixt_key.pem" --% /inheritance:r
icacls "$env:USERPROFILE\.ssh\sixt_key.pem" --% /grant:r "%USERNAME%:R"
icacls "$env:USERPROFILE\.ssh\sixt_key.pem"   # debe mostrar solo tu user con (R)
```

---

### Síntoma: `Connection refused` o `Connection timeout` al SSH

**Causa probable 1:** Tu IP rotó (Tigo Colombia rota cada 5-7 días).

**Verificar:**
```powershell
Invoke-RestMethod -Uri "https://api.ipify.org"
```

Si difiere de la última IP que mandaste a Florian, escribirle:

> Hi Florian, my IP rotated from `OLD_IP/32` to `NEW_IP/32`. Could you please update the allowlist on your end? Thanks.

**Causa probable 2:** Bastion temporalmente caído. Reintentar en 5 min.

---

### Síntoma: `password authentication failed for user "<redshift-user>"`

**Causa:** Password mal copiada en `.env` (espacios al inicio/final, caracteres rotos).

**Fix:**
1. Volver a abrir el link de Sven (si todavía está activo) o pedir uno nuevo.
2. Re-copiar password con cuidado, sin espacios.
3. Re-popular `SIXT_REDSHIFT_PASSWORD` en `.env`.

---

### Síntoma: `database "prod_database" does not exist`

**Causa:** Nombre de DB equivocado en `.env`.

**Fix:** Confirmar valor con Florian. A 2026-05-04 era `prod_database`.

---

### Síntoma: `permission denied for relation X`

**Fix:** escribirle a Florian pidiendo grant SELECT sobre `<schema>.<table>`.

---

### Síntoma: explore_remote dice "0 cols" para todas las tablas

**Causa:** `information_schema.columns` viene **vacío** en consumer Redshift para tablas que llegan vía datashare.

**Fix:** ya está aplicado en `pipelines/bronze/explore_remote.py` (usa `SVV_REDSHIFT_COLUMNS`). Si vuelve a aparecer, confirmar que la query está apuntando a esa vista.

---

## Pipeline issues (Bronze)

### Bronze full_load se queda colgado en una tabla

**Causa probable:** una tabla muy grande está siendo paginada en bloques que no caben en memoria.

**Fix:** reducir `BRONZE_PAGE_SIZE` en `.env` de `50000` a `10000`.

---

### Bronze incremental trae 0 filas siempre aunque hay cambios

**Causa probable:** la columna watermark configurada en `tables.yml` no es la correcta.

**Diagnóstico:**

```python
import sys; sys.path.insert(0, '.')
from pipelines._common import open_redshift, query_redshift

with open_redshift() as conn:
    df = query_redshift(conn, """
        SELECT column_name, data_type FROM SVV_REDSHIFT_COLUMNS
        WHERE schema_name = 'rent_shop' AND table_name = 'rs_fct_reservations'
          AND (column_name LIKE '%datm%' OR column_name LIKE '%date%' OR column_name LIKE '%upd%')
        ORDER BY ordinal_position
    """)
    print(df)
```

Identificar la columna que efectivamente cambia con cada update y actualizar `watermark_col` en `config/tables.yml`.

---

### Validar que `tables.yml` apunta a columnas reales

```python
import yaml
import sys; sys.path.insert(0, '.')
from pipelines._common import open_redshift, query_redshift

with open('config/tables.yml', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

with open_redshift() as conn:
    for t in cfg['tables']:
        schema, name = t['source'].split('.', 1)
        df = query_redshift(conn,
            f"SELECT column_name FROM SVV_REDSHIFT_COLUMNS WHERE schema_name='{schema}' AND table_name='{name}'")
        cols = set(df['column_name'])
        problems = [c for c in t.get('pk',[]) if c not in cols]
        wm = t.get('watermark_col')
        if wm and wm not in cols: problems.append(f'wm:{wm}')
        if problems: print(f'  FAIL {t["source"]}: {problems}')
        else: print(f'  OK   {t["source"]}')
```

---

## Pipeline issues (Silver)

### `Silver build` falla en algún DDL con "no such column"

**Causa probable:** una columna referenciada en el DDL no existe en Bronze (los nombres de Sixt cambian, o quedó un placeholder).

**Fix:**
```bash
sqlite3 data/bronze.db "PRAGMA table_info('rent_shop_rs_fct_reservations');" | head -30
```
Y ajustar el DDL en `pipelines/silver/ddl/0X_*.sql`.

---

### `Silver build` se queja de "syntax error near 'X'" donde X es una palabra del comentario

**Causa:** un comentario con `;` literal o un `--` que no inicia línea (comentario inline) confunde al splitter.

**Fix:** asegurar que los comentarios `--` ocupen toda la línea (no después de SQL en la misma línea). El splitter en `silver/build.py:_strip_sql_comments` solo descarta líneas que empiezan con `--`.

---

### `database is locked` en SQLite

**Causa:** otra conexión de escritura abierta. Con `journal_mode=WAL` (ya activado) esto es raro pero puede pasar si el dashboard se quedó con write lock.

**Fix temporal:** parar Streamlit (Ctrl+C en la terminal del dashboard) y reintentar.

**Fix permanente:** usar siempre `read_only=True` desde el dashboard:
```python
con = sqlite3.connect("file:data/silver.db?mode=ro", uri=True)
```
Esto ya está implementado en `pipelines._common.open_local(layer, read_only=True)`.

---

### El rebuild de Silver borró la data de `op_*` que Trust había capturado

**Esto NO debería pasar.** El DDL usa `CREATE TABLE IF NOT EXISTS` para `op_*`. Si pasa:

1. Verificar `pipelines/silver/ddl/03_tramo2.sql` — todos los `CREATE TABLE` deben ser `CREATE TABLE IF NOT EXISTS` (sin `DROP TABLE` antes).
2. Restaurar de backup más reciente (`backups/silver_<TS>.db`).
3. Reportar como bug.

---

## Pipeline issues (Vistas)

### `vw_ranking_sedes` muestra ocupación >100%

**Causa:** JOIN entre `fact_rentals` y `dim_vehicles_current` infla filas. Cada rental se multiplica por la cantidad de vehículos en la sede, y SUM(CASE) over `vhcl_on_rent_flg` se sobrecuenta.

**Fix:** ya está aplicado en `04_views.sql` — la vista usa CTEs separadas (`rentals_per_branch`, `revenue_per_branch`, `fleet_per_branch`) y joinea por sede al final. Si vuelve a verse >100%, revisar que no se haya re-introducido el patrón JOIN-en-una-sola-query.

---

## Dashboard issues (cuando exista en Fase D)

### Streamlit dice "Address already in use" en puerto 8501

**Fix:**
```powershell
streamlit run dashboard\app.py --server.port 8502
```

---

### Dashboard muestra data vacía

**Causa probable:**
1. Silver no está construido → correr `python -m pipelines.silver.build`.
2. Las páginas `op_*` tienen 0 filas porque Trust no capturó aún → mostrar banner "datos pendientes de captura" en lugar de fail.

---

## Backups y recovery

### Hacer backup de los .db locales

```powershell
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
mkdir backups -Force
Copy-Item data\bronze.db "backups\bronze_$ts.db"
Copy-Item data\silver.db "backups\silver_$ts.db"
```

### Backup específico de captura Tramo 2 (op_*)

Las `op_*` son la única data que NO se puede regenerar desde Bronze. **Backupear silver.db con frecuencia** una vez que Trust empiece a llenarlas.

```powershell
sqlite3 data\silver.db ".dump op_cierre_diario_sede op_novedades_vehiculo op_incidentes op_checklist_apertura_cierre op_traslado_vehiculos op_solicitudes_soporte op_contratos_soportes_faltantes" > "backups\op_$ts.sql"
```

### Recuperar de un backup

```powershell
Copy-Item backups\bronze_<TIMESTAMP>.db data\bronze.db
# o solo restaurar Tramo 2:
sqlite3 data\silver.db < backups\op_<TIMESTAMP>.sql
```

---

## Inspección rápida con sqlite3 CLI

```bash
# Listar tablas
sqlite3 data/silver.db ".tables"

# Schema de una tabla
sqlite3 data/silver.db ".schema dim_branches"

# Ranking sedes
sqlite3 data/silver.db "SELECT brnc_name, rentals_total, revenue_total, ROUND(occupancy_pct,1) FROM vw_ranking_sedes ORDER BY revenue_total DESC"

# Tablas con counts
sqlite3 data/silver.db "SELECT name, (SELECT COUNT(*) FROM \"X\") FROM sqlite_master WHERE type='table'"
# ↑ no funciona directo; usar python -m pipelines.bronze.inspect
```

---

## Cuándo escalar a Florian

Escribir a Florian solo en estos casos:

1. **IP whitelist** — si tu IP rotó.
2. **Permission denied** — si necesitas grants sobre una tabla nueva.
3. **Schema cambió** — si una tabla deja de existir o cambia columnas.
4. **Cluster fuera de servicio** — si llevas 30+ min con `connection refused` y otros sistemas tampoco responden.
5. **Daños no aparecen** — si quieres que habiliten `damage_shop` en el datashare (hoy 0 filas globalmente).

**No escalar por:**
- Errores de tu código local (paramiko, DDL, parser SQL).
- Errores de DBeaver / configuración local.
- Cuestiones de naming convention que puedes investigar con `SVV_REDSHIFT_COLUMNS`.

---

## Checklist mensual de mantenimiento

- [ ] Revisar logs de `logs/refresh_*.log` por failures recurrentes.
- [ ] Revisar `ctrl_extraction_log` en bronze.db por tablas con `status='FAILED'`.
- [ ] Confirmar que la SSH key sigue protegida (`icacls`).
- [ ] Revisar tamaño de los `.db` (alerta si bronze > 5 GB).
- [ ] Backup del `.env` en password manager.
- [ ] Verificar que la IP no rotó y sigue en allowlist de Florian.
- [ ] Backup de `silver.db` si Trust está capturando Tramo 2.
- [ ] Revisar si `damage_shop_*` empezó a tener data (Sixt podría habilitarlo).
