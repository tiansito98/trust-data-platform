# Source-of-truth queries — Dashboard v2

> Queries acordados con la gerente el 2026-05-13 como referencia oficial para mostrar contratos, items y totales. **Toda la lógica vive en `vw_rentals_detail` y `vw_rentals_resumen`** (silver). El dashboard solo aplica filtros y ordena.

## Por qué este enfoque

1. **Una sola fuente de verdad.** Las reglas de negocio (qué cargo viene de la reserva vs counter, cómo se calcula el bruto, dónde se aplica el descuento, qué es "adicional") viven en `pipelines/silver/build.py`. Si la regla cambia, se cambia en un solo lugar.
2. **Dashboard tonto.** El frontend (Streamlit, futuras apps) solo lee vistas y aplica `WHERE` por sede/fecha/moneda. Cero lógica de cálculo en el dashboard.
3. **TRM sin sorpresas.** El usuario decidió usar **solo valores USD nativos** (sin aplicar TRM por nosotros) cuando el contrato fue facturado en USD. Los valores USD vienen directos de bronze (`rntl_revenue_rental`, `rntl_tax_rental`, `rntl_discount_rental`) sin multiplicaciones. Para rentals en COP ya hay columnas paralelas `_cop`.
4. **USD vs COP en paralelo.** Cada vista expone ambas monedas. El dashboard decide cuál mostrar según preferencia del usuario; nunca debe convertir entre ellas con TRM.

## Reglas que las vistas implementan

### 1. Distinguir cargos de la reserva vs cargos agregados en counter

Cada cargo del counter (`fact_charges_ra`) se compara contra los cargos que existieron en la reserva online (`fact_charges_rs`). Si el código (`T`, `BF`, `Y`, etc.) existía en la reserva, se considera que **vino de la reserva**; si no, fue **agregado al firmar en counter**.

En `vw_rentals_detail`:
- `cargo_coincide_reserva` = `1` (vino de reserva), `0` (agregado en counter), `NULL` (rental sin reserva online).
- `rsrv_resn_cargo` = poblado solo cuando `cargo_coincide_reserva = 1`.
- `numero_reserva` = la del rental padre, siempre poblada si hubo reserva.
- `origen_cargo` = `RESERVA` / `COUNTER_CON_RESERVA` / `COUNTER_AGREGADO`.

En los queries del dashboard, lo simplificamos a:
```sql
CASE WHEN cargo_coincide_reserva = 1 THEN 'RESERVA' ELSE 'COUNTER' END AS fuente_cargo
```

### 2. Tarifa vs adicionales

Usando `dim_charge_types.categoria`:
- **TARIFA** = código `T` (Time and mileage)
- **Adicionales** = todo lo demás (CONTEXTO, COBERTURA, EXTRA, AJUSTE, PENALIZACION, OTROS)

### 3. Descuentos

`vw_rentals_full.descuento_cop` viene de `rntl_distount_local` (typo del datashare). El `revenue_total_cop` **ya viene neto** (con descuento restado). En el detalle del Excel mostramos el descuento como línea separada:

```
Subtotal bruto (suma de cargos)
- Descuento
= Subtotal neto (= revenue_total_cop)
+ IVA 19% (= iva_total_cop)
= Total con IVA
```

### 4. Filtros estándar

- `fuente_cargo = 'RENTAL_COUNTER'` → siempre filtrar a counter (la "verdad" firmada). Los `RESERVA_ONLINE` están solo para análisis de overrides.
- `chra_konr = 0` → siempre. Versiones de corrección > 0 duplicarían filas.
- `rental_currency = 'USD'` → cuando se quieren montos USD nativos.

---

## Query 1 — Detalle con totales por contrato (varias filas por contrato)

**Caso de uso:** vista "factura" estilo Excel. Cada contrato muestra sus N cargos seguidos de 5 filas de totales (SUBTOTAL BRUTO → DESCUENTO → SUBTOTAL NETO → IVA 19% → TOTAL CON IVA).

**Fuentes:** `vw_rentals_detail` (líneas de detalle) + `vw_rentals_resumen` (totales). Ambas vistas en silver.

**No es una vista** porque el `UNION ALL` de 6 niveles haría 6× scan al materializar. El dashboard lo arma como "footer rows".

```sql
WITH detalle AS (
    SELECT
        'DETALLE' AS tipo_fila, 1 AS orden_seccion,
        numero_contrato,
        fecha_handover_real, fecha_devolucion_real, dias_renta,
        placa, vehiculo, categoria_entregada, acriss_entregado, acriss_reservado,
        campaign, canal_partner, forma_pago, prepago_flag AS reserva_prepagada,
        operador_handover_codigo,
        CASE WHEN cargo_coincide_reserva = 1 THEN 'RESERVA' ELSE 'COUNTER' END
            AS fuente_cargo,
        cargo_inty, cargo_codigo, cargo_descripcion, cargo_categoria,
        cantidad, subtotal_usd,
        ROW_NUMBER() OVER (PARTITION BY numero_contrato
                           ORDER BY cargo_inty, cargo_posicion) AS orden_intra
    FROM vw_rentals_detail
    WHERE sede_handover = :sede
      AND DATE(fecha_handover_real) BETWEEN :fecha_desde AND :fecha_hasta
      AND fuente_cargo = 'RENTAL_COUNTER'
      AND rental_currency = 'USD'
),
tot AS (
    SELECT numero_contrato, fecha_handover_real, fecha_devolucion_real, dias_renta,
           placa, vehiculo, categoria_entregada, acriss_entregado, acriss_reservado,
           campaign, canal_partner, forma_pago, reserva_prepagada,
           operador_handover_codigo,
           bruto_usd, descuento_usd, neto_usd, iva_usd, total_con_iva_usd
    FROM vw_rentals_resumen
    WHERE sede_handover = :sede
      AND DATE(fecha_handover_real) BETWEEN :fecha_desde AND :fecha_hasta
      AND rental_currency = 'USD'
),
sub_bruto AS (
    SELECT 'SUBTOTAL BRUTO', 2,
        numero_contrato, fecha_handover_real, fecha_devolucion_real, dias_renta,
        placa, vehiculo, categoria_entregada, acriss_entregado, acriss_reservado,
        campaign, canal_partner, forma_pago, reserva_prepagada, operador_handover_codigo,
        NULL, NULL, NULL, '--- Subtotal bruto ---', NULL, NULL, bruto_usd, 9996
    FROM tot
),
descuento AS (
    SELECT 'DESCUENTO', 3,
        numero_contrato, fecha_handover_real, fecha_devolucion_real, dias_renta,
        placa, vehiculo, categoria_entregada, acriss_entregado, acriss_reservado,
        campaign, canal_partner, forma_pago, reserva_prepagada, operador_handover_codigo,
        NULL, NULL, NULL, '--- Descuento ---', NULL, NULL, -descuento_usd, 9997
    FROM tot
),
sub_neto AS (
    SELECT 'SUBTOTAL NETO', 4,
        numero_contrato, fecha_handover_real, fecha_devolucion_real, dias_renta,
        placa, vehiculo, categoria_entregada, acriss_entregado, acriss_reservado,
        campaign, canal_partner, forma_pago, reserva_prepagada, operador_handover_codigo,
        NULL, NULL, NULL, '--- Subtotal neto ---', NULL, NULL, neto_usd, 9998
    FROM tot
),
linea_iva AS (
    SELECT 'IVA 19%', 5,
        numero_contrato, fecha_handover_real, fecha_devolucion_real, dias_renta,
        placa, vehiculo, categoria_entregada, acriss_entregado, acriss_reservado,
        campaign, canal_partner, forma_pago, reserva_prepagada, operador_handover_codigo,
        NULL, NULL, NULL, '--- IVA 19% ---', NULL, NULL, iva_usd, 9999
    FROM tot
),
total_con_iva AS (
    SELECT 'TOTAL CON IVA', 6,
        numero_contrato, fecha_handover_real, fecha_devolucion_real, dias_renta,
        placa, vehiculo, categoria_entregada, acriss_entregado, acriss_reservado,
        campaign, canal_partner, forma_pago, reserva_prepagada, operador_handover_codigo,
        NULL, NULL, NULL, '*** TOTAL CON IVA ***', NULL, NULL, total_con_iva_usd, 10000
    FROM tot
)
SELECT
    tipo_fila, numero_contrato,
    fecha_handover_real, fecha_devolucion_real, dias_renta,
    placa, vehiculo, categoria_entregada, acriss_entregado, acriss_reservado,
    campaign, canal_partner, forma_pago, reserva_prepagada, operador_handover_codigo,
    fuente_cargo, cargo_inty, cargo_codigo, cargo_descripcion, cargo_categoria,
    cantidad,
    ROUND(subtotal_usd, 2) AS subtotal_usd
FROM (
    SELECT * FROM detalle
    UNION ALL SELECT * FROM sub_bruto
    UNION ALL SELECT * FROM descuento
    UNION ALL SELECT * FROM sub_neto
    UNION ALL SELECT * FROM linea_iva
    UNION ALL SELECT * FROM total_con_iva
)
ORDER BY fecha_handover_real DESC, numero_contrato, orden_seccion, orden_intra;
```

**Validado contra contrato `9523073821`** (CHEVROLET CAPTIVA, Rionegro, abril 2026): 5 líneas DETALLE + 5 líneas de totales que cierran a `$826.95 USD` total con IVA. Coincide con `revenue_total_cop` + `iva_total_cop` de bronze.

## Query 2 — Resumen (1 fila por contrato)

**Caso de uso:** tabla principal del dashboard. Una fila por contrato con tarifa, lista de adicionales separados por coma, descuento, neto, IVA y total.

**Fuente:** `vw_rentals_resumen` (vista materializada). Lectura directa, sin transformaciones.

```sql
SELECT
    numero_contrato,
    fecha_handover_real, fecha_devolucion_real, dias_renta,
    placa, vehiculo, categoria_entregada, acriss_entregado, acriss_reservado,
    campaign, canal_partner, forma_pago, reserva_prepagada,
    operador_handover_codigo,
    tarifa_usd,
    adicionales_codigos,
    adicionales_usd,
    bruto_usd,
    descuento_usd,
    neto_usd,
    iva_usd,
    total_con_iva_usd
FROM vw_rentals_resumen
WHERE sede_handover = :sede
  AND DATE(fecha_handover_real) BETWEEN :fecha_desde AND :fecha_hasta
  AND rental_currency = 'USD'
ORDER BY fecha_handover_real DESC, numero_contrato;
```

`adicionales_codigos` viene como string `'SL, Y, BF, AD'` (CSV). En el dashboard se puede splitear para chips/tags. Versión COP disponible en `_cop`.

## Sedes disponibles

Para parametrizar el WHERE de sede:
- `MEDELLIN AP JOSE MARIA CORDOVA` (Rionegro)
- `BOGOTA AP EL DORADO`
- `CARTAGENA AP RAFAEL NUNEZ`
- `CALI AP ALFONSO BONILLA ARAGON`
- `BARRANQUILLA AP ERNESTO CORTISSOZ`
- `SANTA MARTA AP SIMON BOLIVAR`

Sus códigos también están disponibles en `sede_handover_codigo` (más estables).

## Vehículo entregado vs reservado

- `vehiculo` (en `vw_rentals_full` y propagado a detail/resumen) = marca + modelo del vehículo físico entregado (ej. "CHEVROLET CAPTIVA"). Viene del JOIN `fact_rentals.vhcl_int_num → dim_vehicles → dim_vehicle_models`.
- No existe un "vehículo reservado" como modelo específico — en Sixt las reservas online se hacen por **categoría ACRISS**, no por modelo.
- Para detectar upgrades/downgrades: comparar `acriss_reservado` vs `acriss_entregado`.

## Próximas extensiones acordadas

- **Forma de pago discriminada** (pago en destino vs prepago vs mayorista). Ver memoria `project_forma_pago_pendiente.md`. Probablemente derivable de `rntl_payment_*` / `prepago_flag` / `dim_rate_plans`.
- **Estadística descriptiva** (avg ticket, ticket por categoría ACRISS, frecuencia de adicionales, top combos). El dashboard v2 arranca con eso.
