# Ocupación — revisión de tu manager (docx) y qué falta

Fuente de verdad: `docs/revisión ocupación trust.docx` (revisión carro por carro de julio 2026).
Análisis y fixes: 2026-09-01.

## Ya corregido y en vivo (gold_carro_dia v6 + fact_comision_dia + gold_cargo_dia)

1. **Hora de gracia (24h → 24h + 1h).** El sistema no cobra día extra si se devuelve
   dentro de la hora siguiente al bloque. Antes 25h = 2 días; ahora 25h = 1 día.
   Fórmula: `CEIL((duración_segundos − 3600) / 86400)`, mínimo 1. Aplicado en las 3
   tablas con regla de 24h. Efecto: **menor** de lo esperado (la mayoría de las
   diferencias NO eran por esto — ver punto 2).
2. **Segmentos administrativos sub-hora.** Cada cambio de vehículo / traslado deja
   segmentos de 0.0–0.7 h (check-in/out sin kilómetros ni revenue) que por el piso
   `GREATEST(...,1)` contaban **1 día de ocupación cada uno**. Ahora se **excluyen**
   de la ocupación, PERO solo si el contrato tiene otro segmento real (la renta vive
   ahí) o si no facturó — así **no se pierde revenue** de rentas cortas legítimas
   (140 contratos, ~44k USD en 2026, cuyo único tramo es sub-hora pero sí facturaron).
   **Revenue total sin cambios (+10 USD en 2026).** Ocupación 2026: 60,2% → 58,7%.
3. **Ubicación del día rentado = sede de su propia renta** (no el timeline global).
   Un traslado espurio durante una renta larga corrompía la ubicación. Caso
   `QIV456`: la renta larga (5-jul→31-ago, Bogotá) aparecía con 21 días en Medellín
   Poblado por un traslado del 11-jul; ahora los 27 días están en Bogotá.
4. **Rentas largas ABIERTAS contaban 0 días (centinela `1899-12-31`).**
   `fact_rental_vehicles` trae `rvnc_return_datm = 1899-12-31` (placeholder de Sixt)
   en rentas aún sin devolver. El `COALESCE(return, NOW())` no lo capturaba → duración
   NEGATIVA → la renta colapsaba a 1 día. Caso `NIZ571` (contrato mar→sep): 0 → 31
   días en julio. Fix: tratar `return < 1900-01-01` como NULL (abierta) → capada a hoy.
   Recupera ~883 días de renta en 2026 (ocupación 58,7% → **62,4%**). Revenue conservado.
   `vw_rentals_full` ya resolvía bien la devolución, así que comisiones no estaban afectadas.

Ocupación julio final: **73,6%** (2.468 días rentados), revenue US$ 201.444.

Validación julio (día rentado por placa, real = número de tu manager):

| placa | real | antes (v4) | ahora (v6) |
|---|--:|--:|--:|
| QIW855 | 12 | 20 | 17 |
| QKP632 | 22 | 27 | 26 |
| LOY343 | 11 | 14 | 12 |
| KOS445 | 21 | 23 | 22 |
| FIW787 | 16 | 19 | 19 |
| QIY151 | 21 | 24 | 23 |
| FIY108 | 20 | 22 | 21 |
| QQY981 | 21 | 25 | 23 |

Baja todo hacia el número real, pero queda un residuo de 1–3 días → punto A.

## Pendiente de DECISIÓN DE NEGOCIO (no adivinar)

**A. Contratos de "cambio de vehículo": ¿cuenta el carro que se cambió?**
El residuo son segmentos **reales, multi-hora, con kilómetros** de un carro que fue
cambiado a mitad de contrato. Ejemplo: `FIW787` en el contrato `9523847246`
(10→12 jul) manejó **465 km** (81.706 → 82.171) y facturó. Tu manager dice que estos
no deberían contar como ocupación de FIW787. Es defendible (el carro tuvo un problema
y lo cambiaron) pero **el carro sí estuvo rentado y rodó**, así que hay que decidir la
regla explícita antes de tocarlo:
- Opción 1: contar (hoy) — el carro estuvo productivo.
- Opción 2: NO contar los tramos del carro **cambiado-fuera** (hser < hser final del
  contrato). Reproduciría casi exacto los números de tu manager.
Implementable en una tarde una vez confirmada la opción.

## Pendiente — bugs de ubicación / completitud (aparte de la regla de 24h)

**B. One-way de cliente: la ubicación OCIOSA no sigue la sede de devolución.**
`NGX853` devolvió el 2-jul en Pereira y de ahí en adelante debía contar disponibilidad
en Pereira; hoy los días ociosos siguen la sede de apertura. El día RENTADO ya quedó
bien (por sede de su renta), pero los días **parados** post-one-way no se reubican.
Requiere separar el timeline ocioso: usar la **sede de retorno** de la última renta.
(Ojo: revertir esto con cuidado — un cambio anterior con sede_devolución metió carros
en la sede equivocada; hay que hacerlo solo para días ociosos, no rentados.)

**C. ~~Contratos largos sin fila / con 0 ocupación~~ — RESUELTO (punto 4 arriba).**
`NIZ571` SÍ tenía su fila en `fact_rental_vehicles`; el problema era el centinela
`1899-12-31` en la devolución (renta abierta), no un segmento faltante. Corregido.
