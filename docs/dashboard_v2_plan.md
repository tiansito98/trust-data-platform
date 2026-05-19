# Dashboard v2 — Plan de construcción

> Objetivo: **construir un dashboard Streamlit NUEVO** basado en las vistas source-of-truth (`vw_rentals_full`, `vw_rentals_detail`, `vw_rentals_resumen`, `dim_trm_diaria`). El dashboard actual (`dashboard/`) queda intacto. Acordado con la gerente el 2026-05-13.

## Dónde construirlo

- Crear carpeta nueva `dashboard_v2/` paralela a `dashboard/`.
- Layout sugerido:
  ```
  dashboard_v2/
  ├── app.py                    # entrypoint
  ├── pages/
  │   ├── 1_Cierre_Diario.py    # objetivo 1
  │   ├── 2_Ingresos.py         # objetivos 2 + 5
  │   └── 3_Asesores.py         # objetivo 3
  ├── components/
  │   ├── common.py             # COPIAR base de dashboard/components/common.py
  │   └── filters.py            # nuevo: filtros transversales reusables
  └── assets/                   # COPIAR styles.css de dashboard/assets/
  ```
- Lanzarlo con `streamlit run dashboard_v2/app.py` (puerto distinto al v1 si quieres correr ambos).

## Reusable del v1 que vale la pena copiar (no importar)

De `dashboard/components/common.py`:
- `get_conn()` con `@st.cache_resource` — conexión read-only a `silver.db` vía URI `mode=ro`.
- `load_query()` con `@st.cache_data(ttl=300)`.
- Paleta: `SIXT_ORANGE = "#ff6900"`, fondo blanco.
- `PLOTLY_LAYOUT` estandarizado.

**Copiar, no importar**, para que el v2 pueda evolucionar sin riesgo de romper el v1.

---

## Objetivos del v2 (5 entregables)

### 1. Cierres diarios para todas las sedes

Dos vistas en una misma página, con switch entre ellas:

**(a) Detalle por contrato** — usa Q1 de [docs/source_of_truth.md](source_of_truth.md). Una "factura" por contrato con sus N cargos + 5 filas de totales (SUBTOTAL BRUTO → DESCUENTO → SUBTOTAL NETO → IVA 19% → TOTAL CON IVA).

**(b) Resumen 1 fila por contrato** — usa Q2 directo desde `vw_rentals_resumen`. Columnas: contrato, fecha, placa, vehículo, categoría, tarifa, adicionales (CSV), descuento, neto, IVA, total.

Filtros mínimos: sede, rango de fechas, moneda (USD/COP toggle).

### 2. Ingresos por reservas vs adicionales

Tabla y/o gráfica con:
- Tarifa total (suma de `tarifa_usd` / `tarifa_cop`)
- Adicionales por categoría (CONTEXTO, COBERTURA, EXTRA, AJUSTE, PENALIZACION, OTROS — ver [charge_codes.md](charge_codes.md))
- % adicionales sobre tarifa por sede
- Top códigos de adicionales

Pendiente del usuario: definir qué adicionales específicos quiere ver con prioridad. Por ahora, mostrar todas las categorías.

### 3. Revenue por código de asesor

Hoy `vw_rentals_full.operador_handover_codigo` trae el código `oprt_bed_handover` (ej. `THZA`). El nombre del asesor **no está en el datashare**. Hay un mapping manual pendiente (ver memoria `project_forma_pago_pendiente.md` para contexto histórico — los top 20 códigos cubren ~97% de rentals).

Lo que sí podemos mostrar ya:
- Revenue por `operador_handover_codigo`
- Conteo de rentals por código
- Ticket promedio por código
- Mix tarifa/adicionales por código

Si el usuario eventualmente crea el CSV de mapping `codigo → nombre`, agregar como `dim_employees_seed` en silver.

### 4. Filtros transversales

Componente reusable (sticky en topo, fue revertido por bug de scroll en v1 — replantear sin `position: sticky`):
- **Sede** (multiselect, default: todas)
- **Fecha desde / hasta** (default: últimos 30 días)
- **Moneda** (USD / COP)
- **Categoría ACRISS** (multiselect, opcional)
- **Canal** (multiselect, opcional)

Implementación: leer sedes de `SELECT DISTINCT sede_handover FROM vw_rentals_full`; rango max de fechas de `MAX/MIN(fecha_handover_real)`.

### 5. Resumen de categorías de carros entregados

Distribución por categoría ACRISS (4-letter code) o por `categoria_entregada` (label humano):
- Rentals por categoría (counts)
- Revenue por categoría
- Días de renta promedio
- Comparación entregado vs reservado (detectar upgrades/downgrades comparando `acriss_reservado` vs `acriss_entregado`)
- Top vehículos físicos (por `vehiculo` = marca+modelo)

---

## Queries source-of-truth a usar

Vienen ya documentados en [docs/source_of_truth.md](source_of_truth.md). El dashboard NO debe escribir SQL nuevo de cálculo; solo `WHERE` y `ORDER BY`. Si una agregación que necesitas NO está en silver, agrégala como columna a `vw_rentals_resumen` o crea una nueva vista (ver [coding_style.md](coding_style.md)).

### Casos típicos

**Listar contratos de una sede en rango:**
```sql
SELECT * FROM vw_rentals_resumen
WHERE sede_handover = :sede
  AND DATE(fecha_handover_real) BETWEEN :desde AND :hasta
  AND rental_currency = 'USD'
ORDER BY fecha_handover_real DESC, numero_contrato;
```

**Detalle de un contrato (cargos):**
```sql
SELECT cargo_codigo, cargo_descripcion, cargo_categoria,
       cantidad, subtotal_usd,
       CASE WHEN cargo_coincide_reserva = 1 THEN 'RESERVA' ELSE 'COUNTER' END AS origen
FROM vw_rentals_detail
WHERE numero_contrato = :contrato
  AND fuente_cargo = 'RENTAL_COUNTER';
```

**Revenue por código de asesor (ej. Rionegro abril):**
```sql
SELECT operador_handover_codigo,
       COUNT(*) AS rentals,
       ROUND(SUM(neto_usd), 2) AS revenue_neto_usd,
       ROUND(AVG(neto_usd), 2) AS ticket_promedio_usd,
       ROUND(SUM(tarifa_usd), 2) AS tarifa_usd,
       ROUND(SUM(adicionales_usd), 2) AS adicionales_usd
FROM vw_rentals_resumen
WHERE sede_handover = :sede
  AND DATE(fecha_handover_real) BETWEEN :desde AND :hasta
  AND rental_currency = 'USD'
GROUP BY operador_handover_codigo
ORDER BY revenue_neto_usd DESC;
```

**Revenue por categoría de cargo:**
```sql
SELECT cargo_categoria,
       COUNT(*) AS cargos,
       ROUND(SUM(subtotal_usd), 2) AS suma_usd,
       COUNT(DISTINCT numero_contrato) AS contratos
FROM vw_rentals_detail
WHERE sede_handover = :sede
  AND DATE(fecha_handover_real) BETWEEN :desde AND :hasta
  AND fuente_cargo = 'RENTAL_COUNTER'
  AND rental_currency = 'USD'
GROUP BY cargo_categoria
ORDER BY suma_usd DESC;
```

**Mix tarifa vs adicionales por sede:**
```sql
SELECT sede_handover,
       ROUND(SUM(tarifa_usd), 0) AS tarifa,
       ROUND(SUM(adicionales_usd), 0) AS adicionales,
       ROUND(SUM(adicionales_usd) * 100.0 / NULLIF(SUM(tarifa_usd) + SUM(adicionales_usd), 0), 1) AS pct_adicionales
FROM vw_rentals_resumen
WHERE DATE(fecha_handover_real) BETWEEN :desde AND :hasta
  AND rental_currency = 'USD'
GROUP BY sede_handover
ORDER BY tarifa DESC;
```

**Distribución de categorías entregadas:**
```sql
SELECT acriss_entregado, categoria_entregada,
       COUNT(*) AS rentals,
       ROUND(SUM(neto_usd), 0) AS revenue,
       ROUND(AVG(neto_usd), 0) AS ticket_promedio,
       SUM(CASE WHEN acriss_entregado != acriss_reservado THEN 1 ELSE 0 END) AS upgrades_o_downgrades
FROM vw_rentals_resumen
WHERE DATE(fecha_handover_real) BETWEEN :desde AND :hasta
  AND rental_currency = 'USD'
  AND acriss_reservado IS NOT NULL
GROUP BY acriss_entregado, categoria_entregada
ORDER BY rentals DESC;
```

---

## Lo que NO debe hacer el dashboard

- **NO** aplicar TRM para convertir USD↔COP. Las columnas ya vienen en monedas paralelas.
- **NO** filtrar fuera de los WHEREs estándar (`fuente_cargo`, `rental_currency`, fechas).
- **NO** materializar cálculos en código Python que ya están en vistas (descuento, IVA, neto).
- **NO** consultar `data/bronze.db` directamente. Solo silver.
- **NO** usar emojis. Por instrucción explícita del usuario.
- **NO** mostrar revenue 0 (1,076 cortesías + 170 prepagos no-counter) en gráficas de revenue principal. Filtrar con `rental_payment_type` o `prepago_flag` si se exponen, o por `bruto_usd > 0`.

## TRM real Banrep (importante)

Existe `dim_trm_diaria` en silver con la TRM oficial COP/USD por día calendario (datos.gov.co dataset `32sa-8pi3`, mismo número certificado por Banrep). Cubre desde 2024-01-03 hasta ayer/hoy.

Columnas: `fecha` (PK), `trm_cop_per_usd`, `vigenciadesde`, `dia_publicacion` (1 = Banrep publicó nuevo ese día, 0 = heredada de fin de semana/festivo).

**Para mostrar revenue COP real (no la TRM que metió Sixt):**

```sql
SELECT r.numero_contrato, r.vehiculo, r.fecha_handover_real,
       r.neto_usd,
       t.trm_cop_per_usd                                       AS trm_banrep,
       ROUND(r.neto_usd * t.trm_cop_per_usd, 0)                AS neto_cop_real,
       r.neto_cop                                              AS neto_cop_sixt,
       ROUND(r.neto_usd * t.trm_cop_per_usd - r.neto_cop, 0)   AS diferencia_cop
FROM vw_rentals_resumen r
LEFT JOIN dim_trm_diaria t
       ON t.fecha = DATE(r.fecha_handover_real)
WHERE r.rental_currency = 'USD'
  AND r.sede_handover = :sede
  AND DATE(r.fecha_handover_real) BETWEEN :desde AND :hasta;
```

Validado: contrato `9523073821` (Rionegro, handover 2026-04-28). TRM Banrep ese día = $3,593.17. Revenue COP real = $2,496,966 vs $2,520,941 que reporta Sixt (Sixt usa TRM ~$34 más alta, diferencia ~1%).

**Filosofía:** en el dashboard, ofrecer un toggle "TRM Banrep (oficial)" vs "TRM Sixt (interna)" cuando se muestran montos COP. Por defecto mostrar Banrep.

## Columnas útiles disponibles (no obvias)

- `reserva_prepagada` (en `vw_rentals_resumen` y vía `prepago_flag` en `vw_rentals_full`/`detail`) — booleano `1`/`0`/`NULL`:
  - `1` = la reserva venía prepagada (cobrada online vía OTA, voucher corporativo, etc.)
  - `0` = había reserva pero NO prepagada — se cobra en counter
  - `NULL` = walk-in (sin reserva online)
- `forma_pago` — string descriptivo del medio (`'Visa Card'`, `'Sixt Corporate Card'`, `'Free of charge'`, etc.).
- `acriss_entregado` vs `acriss_reservado` — para detectar upgrades/downgrades.
- `cargo_coincide_reserva` (en `vw_rentals_detail`) — 1 si el cargo venía en la reserva, 0 si se agregó en counter, NULL si walk-in.

## Lo que está fuera de scope para el v2

- Forma de pago discriminada en mayor granularidad (ej. separar OTA prepagada vs corporativa prepagada) — solo si Trust lo necesita. Hoy `reserva_prepagada` + `forma_pago` cubren la mayoría de casos. Ver `project_forma_pago_pendiente.md` en memoria si surge.
- Mapping `oprt_bed → nombre asesor` — Trust debe proveer CSV.
- Cleaning de duplicados antiguos en `fact_charges_ra` (190 filas de 2022-2023). No afecta 2024+.
- Gold layer (agregaciones pre-computadas). Solo si silver se vuelve lento.

---

## Tabla de validación (antes de mostrar al usuario)

Antes de demostrar la página, validar contra los siguientes contratos conocidos:

| Contrato | Sede | Mes | USD esperado |
|---|---|---|---:|
| 9523073821 | Rionegro | Abril 2026 | Total $826.95 (tarifa 475.20 + adic 253.33 - desc 33.61 + IVA 132.03) |
| 9523076149 | Rionegro | Abril 2026 | (cualquier total, verificar que listed bien los 4 huérfanos COUNTER: OW, RL, DL, OT) |

Si los números no cuadran ahí, no cuadran en ningún lado.
