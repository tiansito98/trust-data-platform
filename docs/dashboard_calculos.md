# Cómo se calcula cada KPI y gráfica del dashboard

> Referencia para entender qué muestra cada sección del dashboard, de dónde sale el dato, cómo se computa y qué caveats tiene.
> Cubre dos pestañas: **Resumen Ejecutivo** (app.py) y **Cierre Diario de Sede** (pages/1_Cierre_Diario.py).
>
> Última actualización: 2026-05-04.

---

## Fuentes de datos

Todas las métricas salen de `data/silver.db` (SQLite local). Las tablas y vistas relevantes:

| Objeto Silver | Granularidad | Fuente Bronze |
|---|---|---|
| `vw_cierre_diario_sede` (tabla materializada) | 1 fila por sede × día con actividad | Cálculo histórico desde `fact_rentals`, `fact_charges_ra`, `fact_reservations`, `dim_vehicles_current` |
| `fact_reservations` | 1 fila por reserva | `rs_fct_reservations` (Sixt) |
| `fact_rentals` | 1 fila por contrato firmado | `ra_fct_rentals_vwt_franchise` (Sixt) |
| `fact_charges_ra` | 1 fila por cargo sobre rental | `ch_fct_ra_charges_franchise` (Sixt) |
| `dim_branches` | 1 fila por sede (6 sedes) | `br_dim_branches` |
| `dim_vehicles_current` | 1 fila por vehículo activo (106) | `ve_fct_vehicles_current` |
| `dim_vehicles` | 1 fila por vehículo master (183) | `ve_dim_vehicles` |
| `dim_vehicle_groups` | 1 fila por categoría ACRISS (13) | `ve_dim_vehicle_groups_franchise` |
| `vw_vehicle_current_state` | snapshot enriquecido con sede + grupo | view derivada |

---

# Pestaña 1 — Resumen Ejecutivo (app.py)

Filtros en el sidebar: **Sede** (todas / una específica) + **Rango de fechas**. Ambos persistentes entre páginas.

## 1. KPIs principales (4 cifras)

### Revenue del periodo
```sql
SUM(cier_revenue_total) FROM vw_cierre_diario_sede
WHERE cier_date BETWEEN ? AND ? [AND brnc_code = ?]
```
Suma de `chra_value_local` (cargos en moneda local) de todos los rentals que arrancaron en el rango filtrado, dentro de la sede filtrada. Se muestra el número exacto formato Colombia (`$ 6.356.724.934`) más una versión legible (`6.357 millones`).

### Rentals (entregas)
```sql
SUM(cier_rentals_count) FROM vw_cierre_diario_sede
WHERE cier_date BETWEEN ? AND ? [AND brnc_code = ?]
```
Cantidad de contratos cuyo `rntl_handover_date` cayó dentro del rango, partiendo de la sede filtrada.

### Devoluciones
```sql
SUM(cier_returns_count) FROM vw_cierre_diario_sede
```
Cantidad de contratos cuyo `rntl_return_date` cayó en el rango y fueron devueltos a la sede filtrada.

### Ocupación promedio
```sql
AVG(cier_vehicles_rented * 1.0 / NULLIF(cier_vehicles_in_branch, 0))
```
Promedio diario de "vehículos asignados a la sede que estaban en rental abierto ese día" / "flota total de la sede". Calculado por overlap real (`handover_date ≤ día ≤ return_date`).

**Caveat:** el denominador (flota) usa el snapshot actual de `dim_vehicles_current`. Si Trust amplió flota durante el periodo, la ocupación pasada queda sub-estimada.

## 2. KPIs de pendientes (4 cifras)

Estos vienen de tablas `op_*` que requieren captura humana de Trust. **Hoy las 6 tablas op_* están vacías**, por lo que estos KPIs muestran cero.

### Incidentes abiertos
```sql
COUNT(*) FROM op_incidentes
WHERE inci_status NOT IN ('CERRADO') AND inci_date BETWEEN ? AND ? [AND brnc_code = ?]
```

### Soportes faltantes
```sql
COUNT(*) FROM op_contratos_soportes_faltantes
WHERE cosf_status NOT IN ('SUBSANADO') [AND brnc_code = ?]
```

### Novedades abiertas
```sql
COUNT(*) FROM op_novedades_vehiculo
WHERE nove_status NOT IN ('RESUELTA') AND nove_date BETWEEN ? AND ?
```

### SLA incumplido
```sql
COUNT(*) FROM op_solicitudes_soporte
WHERE sopt_sla_breach_flg = 1 AND sopt_request_date BETWEEN ? AND ?
```

**Estado actual:** los 4 KPIs muestran 0 hasta que Trust empiece a capturar Tramo 2 (forms / Excel / app móvil). Detalle del esquema requerido en `docs/captura_pendiente.md`.

## 3. Tendencia operativa diaria

### Cuando "Todas las sedes" está activo

Dos charts con **hue por sede** (cada sede su color, leyenda interactiva con click para aislar):

**Rentals por sede** — línea por sede × día:
```sql
SELECT cier_date, brnc_name, SUM(cier_rentals_count) AS rentals
FROM vw_cierre_diario_sede c JOIN dim_branches b ON b.brnc_code = c.brnc_code
WHERE cier_date BETWEEN ? AND ?
GROUP BY cier_date, brnc_name
```

**Revenue diario apilado por sede** — barras stacked por día.

### Cuando una sede específica está activa

**Rentals vs Devoluciones** — 2 líneas (rentals naranja, devoluciones negro punteado).
**Revenue diario** — barras naranja simples.

## 4. Ranking de sedes

**Solo aparece cuando el filtro de sede es "Todas las sedes".**

Tabla con: Sede, Ciudad, Rentals, Revenue, Ocupación, Días con actividad. Ordenado descendente por revenue.

```sql
SELECT b.brnc_name, b.brnc_city,
       SUM(c.cier_rentals_count), SUM(c.cier_revenue_total),
       AVG(c.cier_vehicles_rented * 1.0 / NULLIF(c.cier_vehicles_in_branch, 0)) * 100,
       COUNT(c.cier_date)
FROM dim_branches b
LEFT JOIN vw_cierre_diario_sede c
  ON c.brnc_code = b.brnc_code AND c.cier_date BETWEEN ? AND ?
GROUP BY b.brnc_name, b.brnc_city
ORDER BY 4 DESC
```

Más 2 charts: revenue por sede (barras naranja) y ocupación promedio por sede (barras negras).

## 5. Mix de flota por categoría

Snapshot del estado actual (no histórico). Joinea `dim_vehicles_current` con `dim_vehicles` con `dim_vehicle_groups`.

```sql
SELECT vhgr_category_level2 AS categoria, vhgr_category_level1 AS tipo, COUNT(*)
FROM vw_vehicle_current_state
WHERE [brnc_code = ?]
GROUP BY vhgr_category_level2, vhgr_category_level1
```

Dos charts:
- **Sunburst** — composición jerárquica categoría → tipo.
- **Bar horizontal** — vehículos por categoría.

**Caveat:** esta sección no varía con el filtro de fechas (es snapshot HOY).

---

# Pestaña 2 — Cierre Diario de Sede (pages/1_Cierre_Diario.py)

Mismos filtros que app.py.

## 1. Resumen del periodo (8 KPIs)

Una fila operativa principal y otra fila de métricas derivadas.

### Fila 1
- **Rentals (entregas)** — `SUM(cier_rentals_count)`. Contratos que arrancaron en el rango.
- **Devoluciones** — `SUM(cier_returns_count)`. Contratos que terminaron en el rango.
- **Revenue total** — `SUM(cier_revenue_total)`. COP del periodo.
- **Ticket promedio / rental** — `revenue / rentals`. Ingresos promedio por contrato.

### Fila 2
- **Días con actividad** — `COUNT(DISTINCT cier_date)`. Cantidad de días distintos del rango con algún registro.
- **Sedes activas** — `COUNT(DISTINCT brnc_code)`. Cantidad de sedes (de 6) con actividad en el rango.
- **Devoluciones / rentals** — ratio. ≈1.0 = sede equilibrada; >1 = recibe más de lo que entrega; <1 = al revés.
- **Rentals / día (promedio)** — `rentals / días con actividad`. Volumen diario típico.

## 2. Demanda y conversión

Mide qué pasó con TODAS las reservas, no solo las que se concretaron en rental.

### KPIs (8 cifras)

```sql
SELECT COUNT(*) AS total,
  SUM(CASE WHEN rsrv_status='Processed' AND rsrv_status_extended='Invoice' THEN 1 ELSE 0 END) AS procesadas,
  SUM(CASE WHEN rsrv_status='Cancelled' AND rsrv_status_extended='Cancellation by Customer' THEN 1 ELSE 0 END) AS canc_cliente,
  SUM(CASE WHEN rsrv_status='Cancelled' AND rsrv_status_extended='Cancellation by Sixt' THEN 1 ELSE 0 END) AS canc_sixt,
  SUM(CASE WHEN rsrv_noshow_flg = 1 THEN 1 ELSE 0 END) AS no_show,
  SUM(CASE WHEN rsrv_status='Open' THEN 1 ELSE 0 END) AS open_,
  SUM(CASE WHEN rsrv_status='Offer' THEN 1 ELSE 0 END) AS offer_
FROM fact_reservations
WHERE rsrv_handover_date BETWEEN ? AND ? [AND brnc_code_handover = ?]
```

Cada KPI muestra el conteo + el % sobre el total.

**Demanda perdida** = `canc_cliente + canc_sixt + no_show`. Reservas que no terminaron en rental por causas controlables (cancelaciones) o no controlables (no-show).

### Chart — Stacked bar diario por estado

Barras apiladas por día con 4 segmentos: Procesadas (naranja), No-show (gris), Canceladas cliente (rojo), Canceladas Sixt (negro). Click en la leyenda aísla cada estado.

**Lectura típica:** si el revenue es bajo en un periodo, este chart te dice si fue por baja demanda o por alta cancelación / no-show.

## 3. Ocupación histórica diaria

### Cómo se calcula

Para cada día X y sede S del rango filtrado:

- **Numerador** = vehículos asignados a la sede HOY que tenían un rental abierto ese día (overlap `handover_date ≤ X ≤ return_date`).
- **Denominador** = flota actual de la sede (snapshot `dim_vehicles_current`).
- **Ocupación %** = numerador / denominador × 100.

Lo precalcula la tabla materializada `vw_cierre_diario_sede` (campos `cier_vehicles_rented`, `cier_vehicles_in_branch`).

### KPIs (4 cifras)

- **Flota promedio** — `AVG(SUM(cier_vehicles_in_branch) por día)`. Es prácticamente constante porque la flota usa el snapshot actual.
- **Rentados (max)** — pico máximo de vehículos en renta simultáneos.
- **Rentados (promedio)** — vehículos en renta en un día típico.
- **Ocupación promedio** — promedio diario del % ocupación.

### Chart — Línea de ocupación %

Una línea naranja con el % ocupación cada día del periodo.

### Caveats documentados en la página

- El denominador usa el snapshot HOY, no la flota histórica real. Si un vehículo se incorporó después o ya se defleeteó, el cálculo no lo ajusta. Para los volúmenes Trust (~106 vehículos) la aproximación es razonable.
- Para flota histórica exacta haría falta usar `dim_vehicles_history` con SCD2 — ejercicio futuro.

## 3b. Carros disponibles por sede × día

Esta sección descompone la flota en 4 categorías para entender capacidad disponible.

### Cómo se calcula

Las columnas materializadas en `vw_cierre_diario_sede`:
- **`cier_vehicles_in_branch`** = flota actual de la sede (constante por sede).
- **`cier_vehicles_rented`** = vehículos en rental abierto ese día (overlap).
- **`cier_reservations_pending`** = reservas con `rsrv_status='Open'` cuyo handover prevista ≤ día ≤ return prevista, en la sede de handover.
- **`cier_vehicles_available`** (físicos) = `MAX(0, flota − rentados)`.
- **`cier_vehicles_available_net`** = `MAX(0, flota − rentados − reservas_pendientes)`.

### KPIs (3 cifras)

- **Disponibles físicos promedio** — flota − rentados.
- **Reservas pendientes promedio** — reservas Open con handover en el día.
- **Disponibles netos promedio** — descontando rentals + reservas pendientes.

### Chart — Cuando "Todas las sedes"

Dos visualizaciones:
1. **Línea de disponibles netos por sede** — una línea por sede a lo largo del rango. Click en leyenda para aislar.
2. **Heatmap sede × fecha de disponibles netos** — rojo = saturada, naranja = libre.

### Chart — Cuando una sede específica

Una sola visualización con 5 líneas:
- Flota total (gris claro punteado)
- Rentados (negro punteado)
- Reservas pendientes (gris medio dashdot)
- Disponibles físicos (gris medio sólido)
- Disponibles netos (naranja Sixt grueso)

### Caveat sobre reservas Open

Algunas reservas Open viejas (de 2018-2024) son fantasmas del sistema (nunca se cerraron). Inflan ligeramente las reservas pendientes para días pasados. Si se quiere precisión mayor, se puede limitar el cap de antigüedad — ejercicio pendiente.

## 4. Renta por día por categoría de vehículo

Discrimina la tarifa promedio por categoría ACRISS (Standard / Intermediate / Compact / Economy).

### Cómo se calcula

```sql
SELECT vg.vhgr_category_level2 AS categoria,
       COUNT(r.rntl_mvnr) AS rentals,
       SUM(r.rntl_rental_days) AS dias_total,
       SUM(r.rntl_revenue_main_local) AS rev_base,
       SUM(r.rntl_revenue_secondary_local) AS rev_extras,
       SUM(r.rntl_revenue_local_currency) AS rev_total,
       SUM(r.rntl_revenue_main_local) * 1.0 / NULLIF(SUM(r.rntl_rental_days), 0) AS price_per_day
FROM fact_rentals r
LEFT JOIN dim_vehicle_groups vg ON vg.vhgr_crs = r.vhgr_crs
WHERE r.rntl_handover_date BETWEEN ? AND ? [AND brnc_code_handover = ?]
GROUP BY categoria
HAVING SUM(r.rntl_rental_days) > 0
```

`rntl_rental_days` viene pre-calculado en Bronze (no se computa con `julianday`).

### Charts (2 al lado)

- **Tarifa promedio por día** — bar chart x = categoría, y = `price_per_day`. Cada barra muestra el COP exacto encima.
- **Revenue total por categoría** — bar chart x = categoría, y = `rev_total`.

### Tabla

Categoría / Rentals / Días rental / Revenue base / Revenue extras / Revenue total / Tarifa/día.

## 5. Composición de ingresos: tarifa base vs extras

Discrimina el revenue total entre **tarifa base** (la renta del vehículo) y **extras** (cobros adicionales: combustible, cobertura, conductor extra, etc.).

### Cómo se calcula

```sql
SELECT DATE(rntl_handover_date) AS fecha,
       SUM(rntl_revenue_main_local) AS "Tarifa base",
       SUM(rntl_revenue_secondary_local) AS "Extras"
FROM fact_rentals
WHERE rntl_handover_date BETWEEN ? AND ? [AND brnc_code_handover = ?]
GROUP BY fecha
```

### KPIs (3 cifras)

- **Tarifa base** — `SUM(rntl_revenue_main_local)`.
- **Extras** — `SUM(rntl_revenue_secondary_local)`.
- **% extras del total** — `extras / (base + extras) × 100`.

### Chart — Stacked bar diario

Barras apiladas por día con 2 colores: Tarifa base (naranja) + Extras (negro).

### Caveat

`rntl_additional_revenue_local` está NULL para todos los rentals — no se usa. Para detalle granular (combustible, cobertura, etc.) habría que agrupar `fact_charges_ra.chra_chco` con un diccionario de códigos que Sixt no provee directamente; queda pendiente.

## 6. Flota actual por sede y categoría

**Snapshot del estado actual.** No varía con el filtro de fechas.

### Cómo se calcula

```sql
SELECT b.brnc_name, vg.vhgr_category_level2, COUNT(*) AS total,
       SUM(CASE WHEN vc.vhcl_on_rent_flg = 1 THEN 1 ELSE 0 END) AS rentados,
       SUM(CASE WHEN vc.vhcl_ready_to_rent_flg = 1 AND vc.vhcl_on_rent_flg = 0 THEN 1 ELSE 0 END) AS disponibles,
       SUM(CASE WHEN vc.vhcl_ready_to_rent_flg = 0 AND vc.vhcl_on_rent_flg = 0 THEN 1 ELSE 0 END) AS otros
FROM dim_vehicles_current vc
LEFT JOIN dim_branches b ON b.brnc_code = vc.brnc_code
LEFT JOIN dim_vehicles v ON v.vhcl_int_num = vc.vhcl_int_num
LEFT JOIN dim_vehicle_groups vg ON vg.vhgr_crs = v.vhgr_crs
WHERE [brnc_code = ?]
GROUP BY sede, categoria
```

`dim_vehicles_current` no trae `vhgr_crs`, hay que pasar por `dim_vehicles` para obtener el grupo del vehículo.

### Charts (2 al lado)

- **Heatmap "Disponibles por sede y categoría"** — filas = sedes, columnas = Compact/Economy/Intermediate/Standard, valor = disponibles ahora. Naranja = mucha disponibilidad.
- **Estado de la flota por sede** — stacked bar (Rentados / Disponibles / Otros).

### Tabla

Sede / Categoría / Total / Rentados / Disponibles / Otros.

## 7. Tendencia diaria del periodo

Mismo patrón que la sección 3 de Resumen Ejecutivo, pero local a la página de cierre diario.

- "Todas las sedes": **rentals con hue por sede** + **revenue stacked por sede**.
- Una sede: **rentals vs devoluciones** + **revenue diario simple**.

## 8. Detalle: sede × día

Tabla con drill-down completo, ordenada por fecha desc.

```sql
SELECT cier_date, brnc_name, cier_rentals_count, cier_returns_count,
       cier_revenue_total, cier_vehicles_in_branch, cier_vehicles_rented, cier_vehicles_available
FROM vw_cierre_diario_sede c JOIN dim_branches b ON b.brnc_code = c.brnc_code
WHERE c.cier_date BETWEEN ? AND ? [AND c.brnc_code = ?]
ORDER BY c.cier_date DESC, b.brnc_name
LIMIT 1000
```

Sirve para auditoría — cuando un chart muestra un pico raro un día específico, en esta tabla está el número exacto. Streamlit permite copiar/exportar como CSV.

---

# Pestaña 3 — BSC (Balanced Scorecard, pages/8_BSC.py)

Vista ejecutiva con 7 KPIs derivables de la matriz BSC del comité operativo. Los 3 KPIs no derivables (Forecast Error, RPD vs recomendado, GOPPAC) están listados al final como pendientes de fuente externa.

## Selector de período propio

Esta página tiene su **propio selector de período** (no usa el rango global). Presets: Último día / Última semana / Último mes / Últimos 3 meses / Últimos 12 meses / Personalizado. Para cada preset el rango se calcula como `(hoy - N días, hoy)`.

El header muestra siempre: sede + rango calculado + N días + preset elegido.

## Perspectiva: Demanda

Mide qué tan bien convertimos la demanda en revenue.

### Demanda total (reservas)

```sql
SELECT COUNT(*) FROM fact_reservations
WHERE rsrv_handover_date BETWEEN ? AND ? [AND brnc_code_handover = ?]
```

Cantidad bruta de reservas con handover en el rango. Sin semáforo (es informativo).

### Served % (aprox)

**Fórmula:** `Procesadas / Total reservas`.

```sql
100.0 * SUM(CASE WHEN rsrv_status='Processed' AND rsrv_status_extended='Invoice' THEN 1 ELSE 0 END)
     / COUNT(*)
```

| Semáforo | Umbral |
|---|---|
| Verde | ≥ 95% |
| Amarillo | ≥ 92% y < 95% |
| Rojo | < 92% |

**Ejemplo (último mes 2026-04-04 → 2026-05-04):** total 442 reservas, procesadas 246 → **Served % = 55.7%** (rojo).

**Caveat marcado "(aprox)":** la fórmula BSC ideal usa "demanda calificada" como denominador (filtrando spam, clientes bloqueados, etc.). Sixt no expone esa distinción, así que aquí se aproxima con TOTAL.

### Lost % (aprox)

**Fórmula:** `(Cancelaciones por Sixt + No-show) / Total reservas`. Mide demanda perdida **controlable del lado de la oferta** (Trust pudo evitarla con mejor flota/operación).

```sql
100.0 * SUM(CASE
    WHEN rsrv_status_extended='Cancellation by Sixt' OR rsrv_noshow_flg=1 THEN 1
    ELSE 0
END) / COUNT(*)
```

| Semáforo | Umbral |
|---|---|
| Verde | ≤ 3% |
| Amarillo | > 3% y ≤ 5% |
| Rojo | > 5% |

**Ejemplo:** canc Sixt 12 + no-show 34 = 46. `46 / 442 = 10.4%` (rojo).

**Caveat:** las cancelaciones por cliente NO entran acá porque el cliente cambió de opinión, no es controlable. Se reportan en Cancel Rate. Tampoco entran las solicitudes rechazadas pre-reserva ("no había carro disponible") porque Sixt no captura eso.

### Cancel Rate

**Fórmula:** `Total canceladas / Reservas confirmadas`. Distinta base que las anteriores.

```sql
100.0 * SUM(CASE WHEN rsrv_cancelled_flg = 1 THEN 1 ELSE 0 END)
     / SUM(CASE WHEN rsrv_status IN ('Processed','Cancelled') OR rsrv_noshow_flg=1 THEN 1 ELSE 0 END)
```

- Numerador: TODAS las canceladas (cliente + Sixt).
- Denominador: solo "confirmadas" = Procesadas + Canceladas + No-show. **Excluye Open + Offer.**

| Semáforo | Umbral |
|---|---|
| Verde | ≤ 4% |
| Amarillo | > 4% y ≤ 6% |
| Rojo | > 6% |

**Ejemplo:** canceladas (157) / confirmadas (426) = **36.9%** (rojo, muy lejos de la meta).

### Por qué Served % + Lost % + Cancel Rate ≠ 100%

Los 3 KPIs **usan denominadores distintos** y se solapan parcialmente. **No están diseñados para sumar 100%.**

- Served % y Lost % comparten denominador (Total reservas) pero numeradores distintos y no exhaustivos (faltan Open + Offer + Canc cliente).
- Cancel Rate tiene **otra base** (solo confirmadas) y **double-cuenta** las "Canc Sixt" que ya están en Lost %.

**Si querés ver una descomposición que sume 100%** sobre el TOTAL: Procesadas % + Canc Cliente % + Canc Sixt % + No-show % + Open % + Offer %. Esos sí parten todas las reservas en buckets disjuntos. Está reportada por separado en la sección 2 de Cierre Diario.

## Perspectiva: Capacidad

Mide qué tan bien usamos la flota.

### Utilización

**Fórmula BSC correcta:** `días-auto-rentados / días-auto-disponibles` agregado sobre todo el periodo.

```sql
WITH daily AS (
    SELECT cier_date,
           SUM(cier_vehicles_in_branch) AS flota,
           SUM(cier_vehicles_rented) AS rentados
    FROM vw_cierre_diario_sede
    WHERE cier_date BETWEEN ? AND ? [AND brnc_code = ?]
    GROUP BY cier_date
)
SELECT 100.0 * SUM(rentados) / SUM(flota) AS util_pct FROM daily
```

La unidad es **vehículo-día**: si un día Bogotá tiene 33 vehículos en flota y 20 rentados, contribuye 33 al denominador y 20 al numerador. Sumado sobre todos los días del periodo.

| Semáforo | Banda |
|---|---|
| Verde | 80% – 88% (banda óptima) |
| Amarillo | 70% – 80% (sub) o 88% – 92% (sobrecargo) |
| Rojo | < 70% o > 92% |

**Por qué la banda tiene techo (no es "más alto = mejor"):** > 92% indica saturación constante → demanda perdida por falta de flota. La meta es estar cerca de 85% sostenido.

**Ejemplo:** último mes, util_pct ≈ 51.2% → **rojo** (capacidad ociosa).

### Equivalencia con "% por carro"

`SUM(rentados-día) / SUM(flota-día)` es matemáticamente idéntico a:

> "para cada vehículo individual, contar días que estuvo rentado / días posibles, sumar numeradores y denominadores, dividir."

Demostración con 3 vehículos en 4 días:
- Vehículo A: rentado 4/4 días.
- Vehículo B: rentado 2/4 días.
- Vehículo C: rentado 0/4 días.

Suma agregada: rentado 6, posible 12 → **50%**. Es lo mismo si lo calculás por vehículo y promediás ponderado.

**Nota sobre Cierre Diario:** la sección "Ocupación histórica diaria" usa `AVG(rentados/flota)` por día (promedio simple de %s diarios), que es una aproximación distinta. Los números coinciden cuando filtrás una sola sede pero divergen ligeramente con "todas las sedes" porque AVG no pondera por tamaño de flota. Para análisis ejecutivo usar siempre BSC.

### Días en over-demand (norm. mes)

Días donde la operación quedó **saturada total** = `disponibles_netos = 0` (flota ocupada por rentals + reservas Open con handover ese día).

```sql
WITH daily AS (
    SELECT cier_date,
           SUM(cier_vehicles_available_net) AS disp_net
    FROM vw_cierre_diario_sede
    WHERE cier_date BETWEEN ? AND ? [AND brnc_code = ?]
    GROUP BY cier_date
)
SELECT SUM(CASE WHEN disp_net = 0 THEN 1 ELSE 0 END) AS dias_over_demand FROM daily
```

**Normalización a 30 días:** `dias_over_demand × 30 / N_días_del_periodo`. Hace comparable contra los umbrales mensuales de la matriz BSC, sin importar si filtraste 7 días o 90.

| Semáforo (días/mes) | Umbral |
|---|---|
| Verde | ≤ 4 |
| Amarillo | 5 – 7 |
| Rojo | > 7 |

**Ejemplo:** último mes, 0 días over-demand global → verde.

**Caveat:** "demanda > capacidad" puro requiere registrar lost-sales pre-reserva ("cliente llamó, no había carro"), que Sixt no captura. Aquí aproximamos con `disponibles_netos = 0`, que detecta saturación pero no demanda rechazada.

### Días en sub-utilización (norm. mes)

Días donde la utilización global cayó por debajo del 70% (umbral asumido por la matriz BSC).

```sql
WITH daily AS (
    SELECT cier_date,
           SUM(cier_vehicles_in_branch) AS flota,
           SUM(cier_vehicles_rented) AS rentados
    FROM vw_cierre_diario_sede
    WHERE cier_date BETWEEN ? AND ? [AND brnc_code = ?]
    GROUP BY cier_date
)
SELECT SUM(CASE WHEN flota > 0 AND rentados * 1.0 / flota < 0.70 THEN 1 ELSE 0 END) AS dias_sub_util
FROM daily
```

Por cada día del rango: agregar todas las sedes, calcular `rentados / flota`, si < 70% marcar como sub-utilizado, contar.

**Normalización a 30 días:** igual que over-demand.

| Semáforo (días/mes) | Umbral |
|---|---|
| Verde | ≤ 6 |
| Amarillo | 7 – 10 |
| Rojo | > 10 |

**Ejemplo:** último mes, 30 de 31 días bajo 70% (utilización promedio 51%) → ~29 días/mes normalizado → **rojo**.

**Para qué sirve:** detectar capacidad ociosa estructural. Combinado con días over-demand:

| Sub-util alto | Over-demand alto | Lectura |
|---|---|---|
| Sí | No | Flota sobrada — bajar flota o subir demanda |
| Sí | Sí | Flota mal balanceada — rebalancear sede/categoría |
| No | No | Operación calibrada |
| No | Sí | Estacionalidad fuerte / pricing dinámico necesario |

**Caveats:**
- El umbral 70% está **hardcodeado**. Si Trust opera con turnover más alto, el óptimo podría ser 80%.
- Agregar todas las sedes puede ocultar sub-utilización por sede individual: una con 90% y otra con 30% promedian al 60% global. Para análisis fino conviene filtrar sede por sede.
- Denominador no descuenta "fuera de servicio" (Sixt no comparte mantenimiento), por lo que la utilización está sub-estimada y `días sub-utilización` está **sobreestimado**.

## Perspectiva: Valor

Mide rentabilidad por unidad de capacidad.

### Revenue del periodo

`SUM(cier_revenue_total) FROM vw_cierre_diario_sede`. Informativo, sin semáforo.

### Ticket promedio

`revenue / total rentals`. Informativo. COP por contrato.

### Yield (Revenue / auto / día)

**Fórmula:** `Revenue total / días-auto-disponibles`.

```sql
SUM(cier_revenue_total) / SUM(cier_vehicles_in_branch)
FROM vw_cierre_diario_sede
WHERE cier_date BETWEEN ? AND ? [AND brnc_code = ?]
```

**Sin semáforo absoluto.** La matriz BSC pide "crecimiento ≥ inflación + 2pp YoY", que se compara contra el año anterior (siguiente KPI).

**Lectura:** mezcla precio × utilización. Yield bajo puede ser por tarifas bajas (problema pricing) o por flota ociosa (problema demanda) o ambos.

### Yield YoY

**Fórmula:** `(Yield actual / Yield mismo periodo año anterior) - 1`.

Compara contra el rango `(fi - 365 días, ff - 365 días)`. Detecta crecimiento real ajustando estacionalidad.

| Semáforo | Umbral |
|---|---|
| Verde | ≥ 0% (creciendo) |
| Amarillo | ≥ -5% y < 0% (estable / leve caída) |
| Rojo | < -5% |

**Caveat:** la matriz BSC pide específicamente "≥ inflación + 2pp", que no está parametrizada en UI. Asumimos 0% como umbral verde simple. Para Trust en CO con inflación ~5-7% anual, el 0% real es "estancamiento" — ajustar el umbral en UI sería refinamiento futuro.

## KPIs pendientes de fuente externa

Tabla informativa al final que documenta los 3 KPIs que **no se pueden calcular** con la data actual:

| KPI | Falta | Captura propuesta |
|---|---|---|
| Forecast Error % | El forecast comercial-operativo de Trust no está en Silver | Tabla `op_forecast_demanda` con forecast por mes/sede/categoría, vía Excel import o forms |
| RPD real vs recomendado | La tarifa recomendada del pricing engine | Tabla `op_tarifa_recomendada` con tarifa por sede/categoría/día, exportada del pricing engine |
| GOPPAC | El P&L operativo (costos por sede) | Tabla `op_pnl_sede` con GOP mensual por sede, exportada del ERP/contabilidad |

Cuando esas tablas existan, los KPIs se calculan con joins simples sobre `fact_rentals` y `vw_cierre_diario_sede`.

## Tendencia mensual

Cuando el período cubre ≥ 2 meses, dos charts:
- **Utilización mensual (%)** — línea con bandas de fondo (verde 80-88%, amarillo 70-80% y 88-92%) para visualizar contra umbrales BSC.
- **Yield mensual** — barras con COP/auto/día por mes.

## Lectura ejecutiva con tu data actual (último mes)

| KPI | Valor | Color |
|---|---:|---|
| Demanda total | 442 reservas | — |
| Served % | 51.7% | Rojo |
| Lost % | 10.4% | Rojo |
| Cancel Rate | 36.9% | Rojo |
| Utilización | 51.2% | Rojo |
| Días over-demand (norm) | 0 | Verde |
| Días sub-utilización (norm) | ~29 | Rojo |
| Yield YoY | depende del año previo | — |

**Diagnóstico:** demanda decente (442/mes), pero baja conversión (37% canceladas) y flota muy ociosa (51% utilización, casi todos los días bajo 70%). Cero saturación → la flota **no es el cuello de botella**, lo es la **conversión**. El leverage está en reducir cancelaciones cliente y no-show — no en bajar flota.

---

# Glosario de columnas y conceptos

## Columnas Silver clave

| Columna | Significado | Tabla |
|---|---|---|
| `brnc_code` | Código numérico de sede | `dim_branches`, `vw_cierre_diario_sede`, fact_* |
| `cier_date` | Fecha del cierre derivado | `vw_cierre_diario_sede` |
| `cier_rentals_count` | Rentals cuyo `handover_date = cier_date` y `brnc_code_handover = brnc_code` | `vw_cierre_diario_sede` |
| `cier_returns_count` | Rentals cuyo `return_date = cier_date` y `brnc_code_return = brnc_code` | `vw_cierre_diario_sede` |
| `cier_revenue_total` | SUM(`chra_value_local`) de rentals que arrancaron ese día desde esa sede | `vw_cierre_diario_sede` |
| `cier_vehicles_in_branch` | Flota actual asignada a la sede (snapshot) | `vw_cierre_diario_sede` |
| `cier_vehicles_rented` | Vehículos asignados a la sede HOY que estaban en rental abierto ese día | `vw_cierre_diario_sede` |
| `cier_reservations_pending` | Reservas Open con handover prevista ≤ día ≤ return prevista, en la sede | `vw_cierre_diario_sede` |
| `cier_vehicles_available` | flota − rentados (físicos) | `vw_cierre_diario_sede` |
| `cier_vehicles_available_net` | flota − rentados − reservas_pendientes | `vw_cierre_diario_sede` |
| `rntl_rental_days` | Duración del rental en días (Bronze, no calculado) | `fact_rentals` |
| `rntl_revenue_main_local` | Tarifa base del rental en moneda local (COP) | `fact_rentals` |
| `rntl_revenue_secondary_local` | Cobros adicionales del rental en COP | `fact_rentals` |
| `rntl_revenue_local_currency` | Revenue total del rental en COP | `fact_rentals` |
| `rsrv_status` | Open / Processed / Cancelled / Offer | `fact_reservations` |
| `rsrv_status_extended` | Detalle del status (Invoice / Cancellation by Customer / Cancellation by Sixt / No show / Open / Offer) | `fact_reservations` |
| `rsrv_cancelled_flg` | 1 si la reserva se canceló | `fact_reservations` |
| `rsrv_noshow_flg` | 1 si el cliente no apareció | `fact_reservations` |
| `vhcl_on_rent_flg` | 1 si el vehículo está en rental ahora | `dim_vehicles_current` |
| `vhcl_ready_to_rent_flg` | 1 si el vehículo está listo para rentarse | `dim_vehicles_current` |
| `vhgr_category_level1` / `level2` | Categoría ACRISS de vehículo (Standard / Compact / etc.) | `dim_vehicle_groups` |

## Definiciones clave

- **Rental abierto / overlap:** un rental que cubre un día X tiene `handover_date ≤ X ≤ return_date` (o `return_date IS NULL`). Esto es el cálculo histórico real, no snapshot.
- **Demanda total:** todas las reservas creadas (`fact_reservations`), independientemente de su status. Trust hoy tiene 27,946 reservas en mandant 409.
- **Demanda perdida:** canceladas (cliente o Sixt) + no-show. Reservas que no se concretaron en rental.
- **Reserva Open:** reserva que aún no se procesó (no hay rental) ni se canceló ni fue no-show. 388 reservas hoy en este estado, varias de ellas viejas (fantasmas del sistema).
- **Categoría ACRISS:** código estándar de la industria de rental (ECAR, IFAR, SDAR, etc.). En `dim_vehicle_groups.vhgr_crs`. La categoría humana legible está en `vhgr_category_level2` (Standard / Compact / etc.).

## Refresh

- **Bronze incremental:** cada 6 horas vía Task Scheduler ejecutando `pipelines/bronze/incremental.py`. Usa watermark `sys_upd_datm` por tabla.
- **Silver build:** después de Bronze, ejecuta `pipelines/silver/build.py`. Reconstruye `dim_*`, `fact_*`, `vw_*` y la tabla materializada `vw_cierre_diario_sede`. Las `op_*` (captura humana) NO se tocan en rebuild.
- **Dashboard:** lee `data/silver.db` en modo read-only via URI (`?mode=ro`), con cache TTL de 5 minutos en queries. No bloquea ni es bloqueado por el refresh.
