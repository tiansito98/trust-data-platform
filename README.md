# Trust Data Platform — EDW Medallion para Sixt Colombia

> **Plataforma de datos propia de Trust Colombia** que ingiere data del Redshift Data Exchange de Sixt corporativo, la modela en arquitectura Medallion (Bronze → Silver → Gold), y la sirve a un dashboard operativo.
>
> **Stack:** Python + SQLite + Streamlit · 100% local · sin licencias.

---

## Estado actual (2026-05-04)

✅ Conexión validada al Redshift Data Exchange de Sixt (eu-west-1)
✅ Bronze poblado: 21 tablas, 105.81 MB, 27,946 reservas + 14,465 rentals + 106 vehiculos activos + 6 sedes
✅ Silver poblado: 31 tablas + 4 vistas (~112 MB) — `vw_cierre_diario_sede` derivada de Tramo 1 reemplaza captura manual
✅ Documentación: `docs/data_dictionary.md` (1,506 líneas), `docs/remote_schema.md`
🔜 Próximo: portar dashboard del demo y apuntarlo a `data/silver.db` (Fase D)

---

## Arquitectura en una imagen

```
┌─────────────────────────────────────────────────────────────────────┐
│  REDSHIFT DATA EXCHANGE (Sixt corporativo, eu-west-1)               │
│  - rent_shop.rs_fct_reservations                                    │
│  - rent_shop.ra_fct_rentals_vwt_franchise                           │
│  - fleet_shop.ve_fct_vehicles_current_incl_history (SCD2)           │
│  - damage_shop.dm_fct_damages                                       │
│  - common_shop.br_dim_branches                                      │
│  - ... (~20 tablas)                                                 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ SSH tunnel + redshift-connector
                               │ filtro: mndt_code = 409
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  BRONZE (data/bronze.db) — SQLite                                   │
│  Copia raw de Redshift, schema espejo, append-only / DELETE-INSERT. │
│  Pipeline: pipelines/bronze/full_load.py + incremental.py           │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ transformaciones SQL via ATTACH bronze
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SILVER (data/silver.db) — SQLite                                   │
│  Modelo dimensional + tablas operativas Tramo 2 + vistas derivadas: │
│  - dim_*: branches, vehicles, partners, rate_plans, channels...    │
│  - fact_*: reservations, rentals, charges, damages                  │
│  - op_*: cierre, novedades, incidentes, checklist, traslados,       │
│          soporte, contratos_faltantes (Tramo 2 — captura humana)    │
│  - vw_*: cierre_diario_sede (derivada), reservation_enriched,       │
│          vehicle_current_state, ranking_sedes                       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ agregaciones + KPIs
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  GOLD (data/gold.db) — SQLite (futuro)                              │
│  Vistas materializadas para dashboards y reportes ejecutivos        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ pandas + plotly
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  DASHBOARD — Streamlit                                              │
│  http://localhost:8501                                              │
│  - 7 reportes operativos (cierre, novedades, incidentes, etc.)      │
│  - KPIs ejecutivos                                                  │
│  - Branding Sixt (naranja #ff6900 + negro)                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Estructura del proyecto

```
trust_data_platform/
├── README.md                  ← este archivo (overview)
├── ARCHITECTURE.md            ← arquitectura detallada Medallion
├── HANDOFF.md                 ← contexto para próxima sesión Claude
├── SETUP.md                   ← guía paso a paso de setup
├── .env.example               ← plantilla credenciales
├── .gitignore
├── requirements.txt
│
├── config/
│   ├── tables.yml             ← configuración de tablas Bronze
│   └── watermarks.yml         ← columnas watermark para incremental
│
├── pipelines/
│   ├── _common.py             ← SSH tunnel + conexiones (compartido)
│   ├── bronze/
│   │   ├── full_load.py       ← carga histórica completa de Redshift
│   │   ├── incremental.py     ← refresh por watermark (programado)
│   │   └── inspect.py         ← validación de Bronze
│   ├── silver/
│   │   ├── build.py           ← Bronze → Silver transformations
│   │   ├── tramo2_seed.py     ← seed inicial de tablas operativas
│   │   └── ddl/
│   │       ├── 01_dim.sql     ← dimensiones (espejo Bronze + placeholders)
│   │       ├── 02_fact.sql    ← hechos Tramo 1 derivados de Sixt
│   │       ├── 03_tramo2.sql  ← tablas operativas propias de Trust (op_*)
│   │       └── 04_views.sql   ← vistas derivadas (vw_cierre_diario_sede, etc.)
│   └── gold/
│       └── (próximamente)
│
├── dashboard/
│   ├── app.py                 ← entry Streamlit (resumen ejecutivo)
│   ├── pages/                 ← 7 reportes operativos
│   ├── components/common.py   ← utilidades + branding
│   └── assets/styles.css      ← CSS Sixt (naranja + negro)
│
├── data/                      ← gitignored, se crean los .db acá
│   ├── bronze.db
│   ├── silver.db
│   └── gold.db
│
├── logs/                      ← gitignored, logs de cada corrida
│
├── scripts/
│   ├── setup.bat              ← instala dependencias, una vez
│   ├── refresh.bat            ← Task Scheduler programa esto cada 6h
│   └── dashboard.bat          ← lanza Streamlit local
│
└── docs/
    ├── bronze_tables.md       ← inventario de tablas Bronze + sample data
    ├── silver_dimensional.md  ← documentación del modelo Silver
    └── runbooks.md            ← qué hacer cuando algo falla
```

---

## Quick start

```bash
# 1. Instalar dependencias (una sola vez)
cd C:\Users\Sebastian\Desktop\trust_data_platform
scripts\setup.bat

# 2. Configurar credenciales
copy .env.example .env
# Editar .env y llenar SIXT_REDSHIFT_PASSWORD con tu password

# 3. Test conexión
python -m pipelines.bronze.inspect --test-connection

# 4. (RECOMENDADO) Explorar schema remoto antes del full load
python -m pipelines.bronze.explore_remote
# Genera docs/remote_schema.md con columnas y candidatos a watermark

# 5. Full load inicial
python -m pipelines.bronze.full_load

# 6. Generar data dictionary completo (cardinalidad, nulls, categoricas)
python -m pipelines.bronze.explore
# Genera docs/data_dictionary.md

# 7. Construir Silver
python -m pipelines.silver.build

# 8. Lanzar dashboard
scripts\dashboard.bat
```

### Scripts de exploración (clave para entender la data)

| Comando | Para qué |
|---|---|
| `python -m pipelines.bronze.explore_remote` | Inspecciona Redshift de Sixt SIN bajar data — usa SVV_REDSHIFT_COLUMNS (no information_schema) para soportar datashares |
| `python -m pipelines.bronze.explore` | Genera data dictionary completo desde Bronze local — clave para construir Silver |
| `python -m pipelines.bronze.inspect` | Estado actual de Bronze: conteos, log de extracciones, samples |
| `sqlite3 data/silver.db ".tables"` | Listar tablas/views en Silver |
| `sqlite3 data/silver.db "SELECT * FROM vw_ranking_sedes"` | Ranking ejecutivo |

Más detalles en [SETUP.md](SETUP.md).

---

## Documentación

| Documento | Para qué |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Diseño Medallion, decisiones técnicas, modelo Silver detallado |
| [HANDOFF.md](HANDOFF.md) | **Contexto para retomar el proyecto en una sesión nueva de Claude** |
| [SETUP.md](SETUP.md) | Setup paso a paso (instalación, credenciales, primer load) |
| [docs/bronze_tables.md](docs/bronze_tables.md) | Inventario completo de tablas Bronze con sample data |
| [docs/silver_dimensional.md](docs/silver_dimensional.md) | Modelo dimensional Silver — DIM/FACT/OP |
| [docs/runbooks.md](docs/runbooks.md) | Troubleshooting + procedimientos operativos |

---

## Costos

| Componente | Costo |
|---|---|
| Redshift Data Exchange (acceso a data Sixt) | $0 (incluido en franquicia) |
| Almacenamiento local (SQLite) | $0 |
| Compute Python local | $0 |
| Streamlit local | $0 |
| **Total año 1** | **$0 USD** |

Migración futura a cloud cuando el volumen lo justifique:
- Postgres managed (Neon/Supabase): ~$50-200 USD/mes
- Databricks Lakehouse: ~$200-500 USD/mes para volumen Trust

---

## Contacto técnico

- Trust Colombia mandant: `409`
- Operator email: en `.env` local (`TRUST_OPRT_EMAIL`)
- Sixt corporate IT lead: contacto privado
