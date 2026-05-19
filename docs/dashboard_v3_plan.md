# Dashboard v3 - Vision Historica

> Construido 2026-05-13. Analiza el negocio agregado (todas las sedes) en
> ventana 2021-2026. Convive con `dashboard/` (v1) y `dashboard_v2/` (v2 en
> construccion). Puerto 8503.

## Como lanzar

```powershell
streamlit run dashboard_v3/app.py --server.port 8503
```

## Estructura

```
dashboard_v3/
├── app.py                        # landing + diccionario ACRISS
├── pages/
│   ├── 1_KPIs_Anuales.py         # flota, ocupacion, RPD, ingresos
│   ├── 2_Demanda.py              # % served, cancel rate desagregado
│   └── 3_Capacidad_Flota.py      # utilizacion mes x sede x ACRISS, flota
├── components/
│   └── common.py                 # COPIA adaptada de dashboard/components
└── assets/
    └── styles.css                # COPIA de dashboard/assets
```

## Vistas silver que alimentan el v3

Todas son **tablas materializadas** en `data/silver.db`, reconstruidas en
cada `silver/build.py`.

### `vw_kpi_anual` (6 filas, una por anio 2021-2026)

| Columna | Significado |
|---|---|
| `anio` | YYYY |
| `flota_activa` | Vehiculos distintos in-fleet en algun dia del anio |
| `dias_disponibles` | Suma por vehiculo de los dias del anio en que estuvo in-fleet |
| `rentals` | Cantidad de rentals con handover en el anio |
| `dias_rentados` | Suma de `dias_renta` |
| `ocupacion_pct` | `dias_rentados / dias_disponibles * 100` |
| `tarifa_usd` | Suma del cargo `T` (Time and mileage), sin IVA |
| `adicionales_usd` | Suma de los cargos counter distintos de `T`, sin IVA |
| `descuento_usd` | Suma de descuentos aplicados |
| `ingreso_total_usd` | `neto_usd` agregado = tarifa + adicionales - descuento |
| `revenue_per_day_usd` | `ingreso_total_usd / dias_rentados` |

### `vw_demanda_anual` (una fila por anio)

| Columna | Significado |
|---|---|
| `anio` | Asignado por `rsrv_handover_date` |
| `served` | Estado `Invoice` |
| `cancel_cliente` | Estado `Cancellation by Customer` |
| `noshow_cliente` | Estado `No show` |
| `cancel_sixt` | Estado `Cancellation by Sixt` |
| `total_reservas` | Suma de las cuatro categorias terminadas (excluye Open / Offer) |
| `served_pct`, `cancel_rate_pct`, ... | Porcentajes derivados |

### `vw_utilizacion_sede_categoria_mes`

Granularidad: 1 fila por (`anio_mes`, `sede_handover`, `acriss_entregado`).

| Columna | Significado |
|---|---|
| `anio_mes` | YYYY-MM (de `fecha_handover_real`) |
| `sede_handover`, `sede_handover_codigo` | Sede donde se entrego |
| `acriss` | Categoria ACRISS de 4 letras entregada |
| `rentals`, `dias_rentados` | Operacional del mes |
| `flota_acriss_mes` | Vehiculos distintos de ese ACRISS in-fleet ese mes |
| `dias_disponibles_acriss_mes` | Dias-vehiculo del ACRISS en el mes (agnostico a sede) |
| `utilizacion_pct` | `dias_rentados / dias_disponibles_acriss_mes * 100` |

> **Limitacion**: el denominador es agnostico a sede porque Sixt no expone
> la sede home del vehiculo por mes. El ratio puede inflarse si una sede
> concentra la flota efectiva de un ACRISS.

### `vw_flota_segmento_anual` (155 filas)

| Columna | Significado |
|---|---|
| `anio`, `sede`, `sede_codigo`, `acriss` | Llave |
| `vehiculos` | Vehiculos distintos cuya **sede dominante** (mas handovers ese anio) fue esta sede |

Cada (carro, anio) se cuenta una sola vez, en la sede donde tuvo mas
handovers ese anio.

## Diccionario ACRISS (4 letras)

Ver `dashboard_v3/app.py` (landing) - tambien expandido en el sidebar del v3.

| Pos | Significado | Codigos comunes en Sixt Colombia |
|---|---|---|
| 1 | Tamaño | M Mini, E Economy, C Compact, I Intermediate, S Standard, F Fullsize, P Premium, L Luxury |
| 2 | Carroceria | C 2/4 puertas, D 4/5 puertas, W Wagon, V Van, F SUV, P/Q Pickup |
| 3 | Transmision + traccion | M Manual 2WD, A Auto 2WD, B Auto 4WD, D Auto AWD |
| 4 | Combustible + AC | R Gasolina+AC, N Gasolina sin AC, D Diesel+AC, H Hibrido+AC, C Electrico+AC |

Combinaciones tipicas:
- `EDMR` Chevrolet Joy (Economy, manual)
- `IDAR` Chevrolet Onix Premier (Intermediate auto)
- `SDAR` Standard auto
- `IDAH` Intermediate hibrido (Onix hibrido)
- `SFAR` SUV gasolina (Chevrolet Captiva)

## Decisiones de diseno

1. **Anchor temporal: handover_date.** Reservas, rentals y revenue se asignan
   al anio en que se debio/se entrego el vehiculo. Alinea todo bajo el mismo
   eje operativo.
2. **Solo USD nativo.** Los KPIs no aplican TRM (los rentals en COP quedan
   excluidos del revenue para mantener una sola moneda).
3. **Flota activa = COUNT DISTINCT carros con `in_date <= fin_anio AND
   (out_date IS NULL OR out_date >= inicio_anio)`**. Lo definio el usuario:
   contar todos los carros que pasaron in-fleet durante el anio, sin importar
   sede.
4. **Ingreso "sin IVA" = `neto_usd`** (= tarifa + adicionales - descuento; no
   incluye IVA).
5. **% served excluye reservas `Open`/`Offer`** del denominador (no
   terminadas, no se puede saber si serviran).

## Limitaciones conocidas

- 2021 es el primer anio con data significativa de rentals (817). Anios
  anteriores estan en `vw_demanda_anual` (reservas creadas mas temprano) pero
  no en `vw_kpi_anual` ni operacional.
- Utilizacion por sede-ACRISS-mes infla cuando una sede concentra la flota
  efectiva de un ACRISS (denominador agnostico a sede).
- "Sede dominante" del carro en `vw_flota_segmento_anual` puede ocultar
  carros que rotan mucho entre sedes.

## Validacion rapida

Numeros de cuadre 2025 (anio completo mas reciente):
- Flota activa: 101
- Ocupacion: 63.39%
- Revenue/day: USD 74.39
- Ingreso total (sin IVA): USD 1,596,423.92
- % served: 49.96%

Si estos numeros cambian sin un commit explicito en `silver/build.py`, hay
un problema de data freshness (correr `.\scripts\refresh.bat`).
