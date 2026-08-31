# Backlog — grano segmento y bugs colaterales

Estado al **2026-08-30**. Contexto: la investigación del "hueco de ocupación por
placa" (caso LHL609 / contrato `9523555919`) reveló que el grano real del vehículo
es el **segmento** (`contrato × rvnc_hser`), no el contrato. Ver hard rule 16 en
CLAUDE.md y la memoria `reference_datashare_completitud`.

## Ya hecho (en vivo)

- **PASO 1 — Bronze pierde filas.** PK de `ra_fct_rental_vehicles` ahora incluye
  `rvnc_hser`. Full reload histórico (`scripts/reload_rental_vehicles.py`), 38 filas
  recuperadas. Commit `1883312`.
- **PASO 2 — `gold_carro_dia` v4 por segmento.** Días rentados y revenue se
  atribuyen a la placa real de cada tramo. Comparativa en
  `scripts/gold_v4_compare.py`. Impacto 2026: revenue estable (+0,05 %), ocupación
  57,8 % → 59,8 %, doble-reservas fantasma 859 → 150 placa-días. Commit `ebe00c1`.

---

## Pendiente 1 — `vw_rentals_full/resumen/detail` usan la placa del header

**Prioridad:** media. **Riesgo:** bajo (cosmético/lectura), no mueve revenue.

- **Síntoma.** Estas tres vistas son 1 fila por contrato y muestran **una sola
  placa** (la del header = primer carro). Un contrato que cambió de vehículo se lee
  como si hubiera sido ese carro todo el tiempo. Caso visible: contrato
  `9523555919` sale con placa `NLR239` (Chevrolet Joy = EDMR) pero
  `acriss_entregado = SDAR` en la misma fila — incoherente.
- **Causa raíz.** Toman `vhcl_int_num` del header `ra_fct_rentals_vwt`, no el
  timeline de `fact_rental_vehicles`.
- **Alcance.** Contratos con cambio de carro: 150 en 2024, 230 en 2025, 233 en 2026
  (4–7 % del total).
- **Fix propuesto.** No cambiar el grano (siguen 1 fila/contrato). Agregar columnas
  derivadas de `fact_rental_vehicles`: `placa_inicial` / `placa_final`, o una lista
  `placas_contrato`. Opcional: exponer una vista silver a grano `(contrato, hser)`
  con placa + fechas + sede + odómetro (hoy no existe nada a ese grano; la usaría
  también gold).
- **Cómo validar.** Para `9523555919` deben verse 4 placas
  (NLR239, LHL609, LHL602, LHL609); `placa_inicial=NLR239`, `placa_final=LHL609`.

---

## Pendiente 2 — Split prepago/counter roto en contratos multi-período (`mser`)

**Prioridad:** media-alta. **Riesgo:** medio (afecta buckets prepago/counter, NO revenue total).

- **Síntoma.** En contratos multi-período, el cargo de la reserva se cuenta **una
  vez por período**, inflando el prepagado. Puede dar counter **negativo**. Caso
  `9523555919`: prepagado 1.491,00 USD > bruto 1.277,91 USD → counter = −213,09 USD.
- **Causa raíz.** El `prepay_lookup` de `build_rentals_detail` une por
  `(rsrv_resn, inty, chco)` **sin `cargo_periodo` (`chra_mser`)**. Es el mismo punto
  ciego de `mser` ya documentado para la regla konr (ver "Limitación conocida:
  konr x mser" en CLAUDE.md).
- **Alcance medido (Redshift).** 8 contratos en 2025 (−296.727 USD de counter) y
  6 en 2026 (−132.172 USD). **No afecta revenue total**; sí los buckets
  prepago/counter de Cierre Diario y Cargos Granular.
- **Fix propuesto.** Agregar `chra_mser` al join del `prepay_lookup` (bajar el grano
  del lookup a `(rsrv_resn, inty, chco, mser)`), para que cada período matchee su
  propia reserva. Revalidar contra COBRA los buckets afectados.
- **Cómo validar.** Ningún contrato debe quedar con `counter_usd < 0` por este
  motivo; `9523555919` counter debe ser ≈ (bruto − prepagado real del período 0).
  Correr la query de detección de "período × corrección" del bloque konr de CLAUDE.md.

---

## Pendiente 3 — `vw_disponibilidad_vehiculo_dia` duplicada

**Prioridad:** media. **Riesgo:** medio (la grilla de Disponibilidad Flota puede pintar mal).

- **Síntoma.** Debería ser 1 fila por `(vehículo, día)` y trae ~**3,2×**. En la
  semana 1–7 jul 2026 hay 2.444 filas para 770 pares únicos. Para `NLR239` el 3-jul
  hay 16 filas.
- **Causa raíz (probable).** Join que se abre — reservas que casan por ACRISS+sede
  (no por vehículo específico) y/o el mismo timeline de contrato-vs-segmento. A
  confirmar en `build_disponibilidad_vehiculo_dia()`.
- **Fix propuesto.** Deduplicar al grano `(vhcl_int_num, fecha)` con la prioridad ya
  definida (manual > rental > reservation > default) usando `DISTINCT ON` o una
  ventana `ROW_NUMBER()`. Revisar si el join de reservas debe ser LATERAL/agregado.
- **Cómo validar.** `COUNT(*) = COUNT(DISTINCT (vhcl_int_num, fecha))` en cualquier
  ventana; `NLR239` el 3-jul = 1 fila.

---

## Nota de orden y de IO

- El Pendiente 2 y (si toca gold) el 1 implican **rebuild de silver (~13 min,
  15–30 % del burst diario)**. No combinar con análisis ad-hoc pesado el mismo día.
- **NO tocar la regla konr:** está validada y no pierde revenue. El problema de estos
  pendientes es otro grano (`hser` / `mser`), no konr.
- Discrepancias fuente-vs-realidad detectadas de paso (para eventual escalamiento a
  Sixt/Florian, no son bugs nuestros): `NPQ347` y `LHL609` con días que la operación
  vio pero el datashare reparte distinto.
