# Dashboard — Streamlit con branding Sixt

> Por ahora carpeta placeholder. Cuando Bronze + Silver estén listos, portamos el dashboard de la demo (`c:\Users\Sebastian\Desktop\sixt-edw\trust_demo\dashboard\`) y lo apuntamos a `data/silver.db`.
>
> **Estado al 2026-05-04:** Bronze + Silver poblados. Listo para Fase D (portar dashboard).

---

## Estructura prevista

```
dashboard/
├── app.py                 ← entry point: resumen ejecutivo
├── pages/
│   ├── 1_Cierre_Diario.py
│   ├── 2_Novedades.py
│   ├── 3_Incidentes.py
│   ├── 4_Checklist.py
│   ├── 5_Traslados.py
│   ├── 6_Soporte.py
│   └── 7_Contratos_Soportes.py
├── components/
│   └── common.py          ← utilidades + branding
└── assets/
    └── styles.css         ← naranja Sixt #ff6900 + negro
```

---

## Cómo migrar de la demo a este proyecto

**Importante:** el demo ya usa `sqlite3` (igual que este proyecto). La migración es **mucho más simple** que si tuvieramos que pasar a DuckDB. Solo hay que cambiar el path del `.db` y agregar `read_only` mode.

1. Copiar todos los archivos de `c:\Users\Sebastian\Desktop\sixt-edw\trust_demo\dashboard\` a `dashboard/`.

2. Editar `components/common.py`:

   ```python
   # Antes (demo)
   DB_PATH = Path(__file__).parent.parent.parent / "data" / "trust_demo.db"

   @st.cache_resource
   def get_conn():
       return sqlite3.connect(str(DB_PATH), check_same_thread=False)

   # Después (este proyecto)
   DB_PATH = Path(__file__).parent.parent.parent / "data" / "silver.db"

   @st.cache_resource
   def get_conn():
       # read_only=True via URI mode: no choca con el rebuild de Silver cada 6h
       return sqlite3.connect(
           f"file:{DB_PATH.as_posix()}?mode=ro",
           uri=True,
           check_same_thread=False,
       )
   ```

3. Ajustar las queries de cada página. La mayoría no cambia (mismos nombres en plural). Excepciones específicas:

   **`pages/1_Cierre_Diario.py`:**
   ```python
   # Antes
   "SELECT ... FROM op_cierre_diario_sede WHERE ..."

   # Después: usar la vista derivada
   "SELECT ... FROM vw_cierre_diario_sede WHERE ..."
   ```

   **`pages/2_Novedades.py`, `3_Incidentes.py`, `4_Checklist.py`, `5_Traslados.py`, `6_Soporte.py`, `7_Contratos_Soportes.py`:**
   Estas tablas `op_*` están vacías por diseño hasta que Trust capture. En cada página, al inicio:
   ```python
   n = pd.read_sql_query(f"SELECT COUNT(*) AS n FROM {tabla_op}", conn).iloc[0]["n"]
   if n == 0:
       st.warning(f"📋 Datos operativos pendientes de captura — esta vista se llenará cuando Trust empiece a registrar [{descripcion}] vía formulario, Excel o app.")
       # mostrar skeleton vacío del reporte
   else:
       # comportamiento normal
   ```

   **`pages/X.py` que consultan `dim_customers`/`dim_employees`/`fact_payments`:**
   Estos placeholders están vacíos. Si la página los joinea, va a perder esas filas (LEFT JOIN devuelve NULLs). Mostrar el dato tal cual o el `cstm_kdnr` como número.

4. Probar:

   ```bash
   streamlit run dashboard/app.py
   ```

---

## Naming Silver

Las tablas Silver usan **plural** para compatibilidad 1:1 con el dashboard demo:

| Demo usa | Silver de este proyecto | Match |
|---|---|---|
| `dim_branches` | `dim_branches` | ✅ |
| `dim_vehicles` | `dim_vehicles` | ✅ |
| `dim_vehicle_groups` | `dim_vehicle_groups` | ✅ |
| `dim_dates` | `dim_dates` | ✅ |
| `dim_customers` | `dim_customers` (vacía, placeholder) | ✅ schema |
| `dim_employees` | `dim_employees` (vacía, placeholder) | ✅ schema |
| `fact_reservations` | `fact_reservations` | ✅ |
| `fact_rentals` | `fact_rentals` | ✅ |
| `fact_charges` | `fact_charges_rs` + `fact_charges_ra` | ⚠️ split en dos |
| `fact_payments` | `fact_payments` (vacía, placeholder) | ✅ schema |
| `fact_damages` | `fact_damages` | ✅ (vacía hoy) |
| `op_*` (las 7) | `op_*` (las 7) | ✅ |

**Único mismatch real:** `fact_charges` ahora son dos tablas (`fact_charges_rs` y `fact_charges_ra`) porque tienen estructura distinta. Si el demo agregaba `chrs_resn` y `chra_mvnr`, las páginas hay que ajustarlas para hacer UNION ALL on-the-fly o usar solo una de las dos según el contexto.

---

## Notas técnicas

- **Read-only en SQLite:** `sqlite3.connect("file:silver.db?mode=ro", uri=True)`. Esto es importante porque cada 6h el `silver/build.py` rebuilda dim/fact. WAL permite multiple readers + 1 writer, pero open en read-only nos asegura que el dashboard nunca toma lock de escritura.
- **Cache:** `@st.cache_data(ttl=300)` para queries pesadas. La data cambia cada 6h, 5 min de cache es invisible.
- **Branding Sixt:** naranja `#ff6900` + negro `#000000`. Mantener `assets/styles.css` igual al demo.
- **Vistas derivadas listas:** `vw_cierre_diario_sede`, `vw_reservation_enriched`, `vw_vehicle_current_state`, `vw_ranking_sedes`. Se pueden consultar como tablas normales.
