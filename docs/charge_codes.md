# Códigos de cargo (`chra_chco` / `chrs_chco`) — referencia

> Mapping confirmado por consultor Trust el 2026-05-04 con base en operación Sixt Colombia.
> Implementado en Silver como tabla seed `dim_charge_types` + vistas `vw_charges_ra_enriched` y `vw_charges_rs_enriched`.

---

## Resumen ejecutivo

`fact_charges_ra` (cargos sobre rentals) y `fact_charges_rs` (cargos sobre reservas) usan una columna corta `chra_chco` / `chrs_chco` con un código de 1-2 letras para identificar el tipo de cargo. Sixt **no expone diccionario oficial** en el datashare, así que armamos un seed propio con 22 códigos confirmados + 8 sin info.

Composición de revenue por categoría (datos al 2026-05-04, mandant 409):

| Categoría | Cargos | Total COP | % del revenue |
|---|---:|---:|---:|
| TARIFA | 13,058 | 14.00B | 71.7% |
| CONTEXTO | 14,327 | 2.51B | 12.9% |
| COBERTURA | 6,988 | 1.83B | 9.4% |
| EXTRA | 4,393 | 0.37B | 1.9% |
| OTROS | 1,114 | 0.32B | 1.7% |
| AJUSTE | 1,095 | 0.27B | 1.4% |
| PENALIZACION | 714 | 0.22B | 1.1% |

---

## Mapping completo (30 códigos)

### Confirmados (22)

| Código | Descripción | Categoría |
|---|---|---|
| **T** | Time and mileage (tarifa por tiempo + kilómetros) | TARIFA |
| **Y** | Location fee (recargo por ubicación, ej. aeropuerto) | CONTEXTO |
| **OW** | One-way fee (entrega en sede distinta) | CONTEXTO |
| **OH** | Out of hours (apertura fuera de horario) | CONTEXTO |
| **AE** | Recargo menor de 25 años (young driver fee) | CONTEXTO |
| **DL** | Delivery (entrega a domicilio) | CONTEXTO |
| **CO** | Collection (cobranza/pickup post-rental) | CONTEXTO |
| **CL** | Collection (recogida del vehículo) | CONTEXTO |
| **BF** | Full coverage (cobertura completa del vehículo) | COBERTURA |
| **LD** | Loss Damage Waiver (cobertura por daños) | COBERTURA |
| **SL** | Supplemental Liability (responsabilidad civil extra) | COBERTURA |
| **AD** | Conductor adicional | EXTRA |
| **CS** | Silla para niño (child seat) | EXTRA |
| **BC** | Asistencia en carretera (road assistance) | EXTRA |
| **UP** | Upgrade de categoría | EXTRA |
| **PF** | Prepaid fuel (combustible prepagado) | EXTRA |
| **VA** | Lavada del vehículo | EXTRA |
| **FI** | Fee administrativo (ej. extensión pico y placa Bogotá) | AJUSTE |
| **PP** | Prepaid difference (diferencia de prepago — ajuste cuando reserva prepagada cambia de fecha) | AJUSTE |
| **DC** | Damage Charge (cobro por daño tras devolución) | PENALIZACION |
| **RL** | Late return (penalización entrega tarde) | PENALIZACION |
| **OT** | Otros cargos varios | OTROS |

### No confirmados (8 — pendiente diccionario oficial Sixt)

`D9, X, BS, NV, FC, RU, DV, RF` — frecuencias bajas (< 100 instancias cada uno), categorizados temporalmente como **OTROS** con `confianza = NO_CONFIRMADO` en el seed. Cuando llegue diccionario oficial, actualizar el seed.

### Pendientes de aclaración

- **CO vs CL:** ambos están descritos como "Collection" pero parecen tener matices distintos (cobranza post-rental vs recogida del vehículo). Confirmar con Sixt si son funcionalmente distintos o variantes del mismo evento.

---

## Tablas y vistas en Silver

### `dim_charge_types` (seed, 30 filas)

Tabla materializada en `pipelines/silver/build.py:build_dim_charge_types()`.

| Columna | Tipo | Significado |
|---|---|---|
| `chra_chco` | TEXT PK | Código de cargo (1-2 letras) |
| `descripcion` | TEXT | Descripción humana legible |
| `categoria` | TEXT | TARIFA / CONTEXTO / COBERTURA / EXTRA / AJUSTE / PENALIZACION / OTROS |
| `confianza` | TEXT | CONFIRMADO / NO_CONFIRMADO |
| `notas` | TEXT | Observaciones (ej. variantes pendientes de aclarar) |

### `vw_charges_ra_enriched` (vista sobre `fact_charges_ra`, 41,689 filas)

Joinea cada cargo de rental con su decodificación + montos en 3 monedas:

| Columna | Origen |
|---|---|
| `rental` | `chra_mvnr` |
| `inty` | `chra_inty` (M=main, S=secondary) |
| `code` | `chra_chco` |
| `descripcion`, `categoria`, `confianza_decode` | `dim_charge_types` |
| `posicion`, `cantidad` | `chra_pos`, `chra_unit_num` |
| `unit_cop`, `total_cop` | en COP |
| `unit_eur`, `total_eur` | en EUR (moneda corporativa Sixt) |
| `rental_currency`, `unit_rental`, `total_rental` | en moneda original del rental |
| `total_usd` | NULL si rental_currency != USD; igual a `total_rental` cuando es USD |
| `xr_eur_to_cop`, `xr_rentalcurr_to_cop` | tipos de cambio aplicados |

### `vw_charges_rs_enriched` (vista sobre `fact_charges_rs`, 57,987 filas)

Análoga pero para cargos sobre **reservas** (no rentals). Mismas columnas con prefijo `chrs_*` mapeado igual.

---

## Queries de ejemplo

### Composición de revenue por categoría

```sql
SELECT categoria, COUNT(*) AS cargos,
       SUM(total_cop) AS total_cop,
       ROUND(SUM(total_cop)*100.0 /
             (SELECT SUM(total_cop) FROM vw_charges_ra_enriched), 1) AS pct
FROM vw_charges_ra_enriched
GROUP BY categoria ORDER BY total_cop DESC;
```

### Cargos detallados de un rental específico

```sql
SELECT code, descripcion, categoria, cantidad, total_cop, total_usd
FROM vw_charges_ra_enriched
WHERE rental = 9522794175
ORDER BY total_cop DESC;
```

Resultado para rental NPQ368 (Bogotá El Dorado, 4 días, RFAR):

| code | descripcion | categoria | cantidad | total_cop | total_usd |
|---|---|---|---:|---:|---:|
| T | Time and mileage | TARIFA | 4 | 2,103,501 | 576.84 |
| FI | Fee administrativo (ej. extensión pico y placa Bogotá) | AJUSTE | 1 | 145,864 | 40.00 |

### Cargos extras (no tarifa) de los rentals de una sede

```sql
SELECT b.brnc_name AS sede, ce.categoria, COUNT(*) AS cargos,
       ROUND(SUM(ce.total_cop), 0) AS total_cop
FROM vw_charges_ra_enriched ce
JOIN fact_rentals r ON r.rntl_mvnr = ce.rental
JOIN dim_branches b ON b.brnc_code = r.brnc_code_handover
WHERE ce.categoria != 'TARIFA'
  AND r.rntl_handover_date BETWEEN '2026-04-01' AND '2026-05-04'
GROUP BY b.brnc_name, ce.categoria
ORDER BY b.brnc_name, total_cop DESC;
```

### % de extras sobre tarifa por sede

```sql
WITH agg AS (
  SELECT b.brnc_name AS sede,
         SUM(CASE WHEN ce.categoria = 'TARIFA' THEN ce.total_cop ELSE 0 END) AS tarifa,
         SUM(CASE WHEN ce.categoria != 'TARIFA' THEN ce.total_cop ELSE 0 END) AS extras
  FROM vw_charges_ra_enriched ce
  JOIN fact_rentals r ON r.rntl_mvnr = ce.rental
  JOIN dim_branches b ON b.brnc_code = r.brnc_code_handover
  GROUP BY b.brnc_name
)
SELECT sede, tarifa, extras,
       ROUND(extras * 100.0 / NULLIF(tarifa + extras, 0), 1) AS pct_extras_del_total
FROM agg
ORDER BY pct_extras_del_total DESC;
```

---

## Decisiones tomadas

- **Implementación en Silver:** sí, dos vistas + tabla seed.
- **Dashboard:** **NO se agregó nada** — solo data accesible para queries directas y notebooks.
- **CO vs CL:** se mantienen como entradas separadas en el seed con notas. Confirmar matiz exacto con Sixt.
- **Códigos no confirmados (D9, X, BS, NV, FC, RU, DV, RF):** seed con `confianza = NO_CONFIRMADO`. Cuando llegue respuesta oficial, actualizar el dict en `silver/build.py:build_dim_charge_types()` y rebuild.

## Mensaje pendiente para Florian (si se decide cerrar los gaps)

> Hi Florian, we mapped 22 of ~30 distinct `chra_chco` codes in the franchise charges tables based on Trust CO operational knowledge. Could you confirm:
> 1. The exact difference between **CO** and **CL** (both translate as "collection" but seem to have distinct uses).
> 2. The meaning of the rare codes: **D9, X, BS, NV, FC, RU, DV, RF** (each < 100 instances total).
>
> Also, is there an official Sixt charge type dictionary we can reference for completeness? Thanks.

---

*Última actualización: 2026-05-04 — mapping confirmado, tablas/vistas en Silver activas.*
