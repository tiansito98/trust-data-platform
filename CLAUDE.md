# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Permissions

You have full autonomy to execute commands in this repo. The project settings (`.claude/settings.json`) pre-approve all common tools so you will NOT be prompted for permission. Just do it.

**What you can do freely (no permission prompts):**
- **Git:** `git add`, `git commit`, `git push origin main`, `git status`, `git diff`, `git log` — commit and push directly to `main`. No PR workflow. Single developer repo.
- **Python:** `python`, `python -m pipelines.*`, `python scripts/run_pipeline.py`, `pip install`
- **Streamlit:** `streamlit run dashboard_v2/app.py`
- **File operations:** Read, Write, Edit, Glob, Grep — all pre-approved
- **Shell:** `ls`, `cat`, `head`, `tail`, `grep`, `find`, `wc`, `rm`, `mv`, `mkdir`, `echo`

**Conventions:**
- Always include `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` in commit messages.
- Never commit `.env`, `users.yml`, `*.pem`, or any file matched by `.gitignore`.
- When a task is done, commit + push without asking "should I commit?" — just do it.
- If you need to run `silver.build` or the pipeline, tell the user it'll take ~13 min and run it.

## Stack

**Supabase Postgres** (Pro plan, Micro compute) + **Medallion architecture** (Bronze → Silver → Gold) + **Streamlit** (dashboard, hosted on Streamlit Community Cloud). Source: Sixt Redshift Data Exchange (mandant 409) via SSH tunnel + `redshift-connector`. Orchestration: plain Python + psycopg2/SQLAlchemy (no dbt). Repo is public on GitHub.

### Connection pooler routing (CRITICAL)

Supabase exposes two poolers — use the right one for the workload or you'll cause `ECHECKOUTTIMEOUT` errors:

- **Pipeline / silver builds → Session pooler (port `5432`)** — long-running transactions, persistent settings (`statement_timeout`, `search_path`)
- **Streamlit dashboard → Transaction pooler (port `6543`)** — many short queries, connections returned to pool after each transaction

Both Streamlit secrets and `.env` should use port `6543` for the dashboard, `5432` for the pipeline. If you ever see `ECHECKOUTTIMEOUT after 15000ms in Session mode` on the dashboard, the secret is pointing at port 5432 (wrong pooler).

## How to run

```powershell
# Full pipeline: bronze incremental + TRM + silver rebuild (~16 min total)
python scripts/run_pipeline.py

# Or step by step:
python -m pipelines.bronze.incremental       # ~3 min (only new/changed rows)
python -m pipelines.bronze.external_trm      # ~5 sec (TRM oficial Banrep)
python -m pipelines.silver.build             # ~13 min (full rebuild of silver)

# Full bronze reset (rare — only if watermarks are corrupt):
python scripts/run_pipeline.py --full

# Dashboard locally:
streamlit run dashboard_v2/app.py
```

Production dashboard: hosted on Streamlit Community Cloud, auto-deploys from `main` on push. Data lives in Supabase — no local files needed in prod.

## Architecture

```
Sixt Redshift ──SSH tunnel──> pipelines/bronze/ ──> Supabase bronze schema
                                                         │
datos.gov.co (TRM) ──HTTP──> pipelines/bronze/           │
                              external_trm.py ──>        │
                                                         ▼
                              pipelines/silver/build.py ──> Supabase silver schema
                                                                │
                              dashboard_v2/ (Streamlit) ◄───────┘
                                    │
                              operational.invoices (form writes)
```

### Schemas in Supabase

- **bronze**: raw mirror of Sixt Redshift datashare. Same column names. ~20 tables. `ctrl_extraction_log` tracks watermarks.
- **silver**: governed model. `dim_*`, `fact_*`, `vw_*` (materialized as TABLEs, not VIEWs). All business logic lives here via `pipelines/silver/build.py`.
- **operational**: data Trust captures (invoice form). `operational.invoices` written by dashboard Facturas page.

### Secrets resolution

`scripts/get_secret.py` provides `get_secret(key)` that checks (in order):
1. `st.secrets[key]` (Streamlit Cloud)
2. `os.environ[key]` (GitHub Actions / system env vars)
3. `.env` file via python-dotenv (local dev)

### Connection handling (Supabase pooler quirks)

Supabase's Session pooler ignores `-c options` in the libpq connection string. All search_path and statement_timeout settings must be applied via explicit SQL:
- Dashboard: `SET search_path TO silver, operational, public` runs inline before every `load_query()` call.
- Silver build: `SET LOCAL statement_timeout = 0` runs inside every `_exec()` transaction.
- TRM Hoy queries use `(NOW() AT TIME ZONE 'America/Bogota')::date` — Supabase runs UTC, Colombia is UTC-5.

## Key files

| File | Purpose |
|---|---|
| `pipelines/_common.py` | All connections (Redshift SSH tunnel + Supabase SQLAlchemy engine). Central `get_engine(schema)`. |
| `pipelines/silver/build.py` | **All silver business logic.** One function per materialized view. ~1500 lines. `main()` calls them in dependency order. |
| `pipelines/silver/ddl/*.sql` | DDL for dim/fact tables (01_dim, 02_fact, 03_tramo2 operational, 04_views). Run by `build.py` first. |
| `dashboard_v2/components/common.py` | Dashboard helpers: `load_query()`, `execute_write()`, `apply_trm()`, `get_trm_hoy()`, formatters. |
| `dashboard_v2/components/auth.py` | Multi-user auth with role-based page + branch restrictions. Reads from `st.secrets["users"]` (prod) or `config/users.yml` (dev). |
| `dashboard_v2/components/filters.py` | Sidebar filters (sede, dates, moneda, ACRISS, canal). Branch-locks for `sede` role users. |
| `dashboard_v2/config/users.yml` | User credentials with bcrypt hashes. **Gitignored.** Template: `users.yml.example`. |
| `scripts/setup_postgres.sql` | One-time Supabase bootstrap (schemas, `ctrl_extraction_log`, `operational.invoices`). |
| `scripts/run_pipeline.py` | Top-level orchestrator. Handles SSH key materialization from env vars for GitHub Actions. |
| `.github/workflows/refresh.yml` | Cron 3x daily (06/12/18 COT). Self-hosted runner. Not yet activated. |

## Silver views (source-of-truth)

| View | Granularity | Purpose |
|---|---|---|
| `vw_rentals_full` | 1 row / rental | 360-degree rental view. 80+ columns. Base for everything. |
| `vw_rentals_detail` | 1 row / charge | Per-charge with rental context. Includes `prepagado_cargo_usd` / `counter_cargo_usd` per-charge split and `bucket_pago` / `canal_cobro_tarifa`. |
| `vw_rentals_resumen` | 1 row / rental | Commercial summary: tarifa + adicionales + totals. Includes `prepagado_usd` / `counter_usd` (net after discounts). |
| `dim_trm_diaria` | 1 row / calendar day | Official Banrep TRM COP/USD. Expanded from bronze `external_trm_diaria`. |
| `vw_cierre_diario_sede` | 1 row / branch × day | Daily operational KPIs (handovers, returns, revenue, occupancy). |
| `vw_kpi_anual` | 1 row / year | Annual KPIs. Dashboard v3. |
| `vw_demanda_anual` | 1 row / year | Demand: served % + cancel rate by cause. Dashboard v3. |
| `vw_utilizacion_sede_categoria_mes` | 1 row / month × branch × ACRISS | Monthly utilization. Dashboard v3. |
| `vw_flota_segmento_anual` | 1 row / year × branch × ACRISS | Fleet mix evolution. Dashboard v3. |
| `vw_disponibilidad_vehiculo_dia` | 1 row / vehicle × day | Vehicle availability grid. Current month +/- 1 month. Manual > rental > reservation > default. |
| `vw_charges_ra_enriched` | 1 row / charge (VIEW) | Counter charges with code decode + 3 currencies. |
| `vw_charges_rs_enriched` | 1 row / charge (VIEW) | Reservation charges with code decode. |

Static seeds (skip rebuild if already populated):
- `dim_dates` — calendar 2020-2030, skips if row count matches expected.
- `dim_charge_types` — 30 charge code mappings, skips if already ≥ 30.

## Authentication & authorization

Multi-user system with two roles:
- **admin**: sees all pages, all branches. User: `trust_admin`.
- **sede**: sees only Cierre Diario + Facturas. Locked to their branch. Branch selector disabled.

Credentials stored as bcrypt hashes in `dashboard_v2/config/users.yml` (local dev, gitignored) and `st.secrets["users"]` (Streamlit Cloud). Auth module: `dashboard_v2/components/auth.py`.

Every page calls `require_auth()` + `require_page("X_PageName")` at the top.

## Prepay/counter charge split (critical business logic)

For each `fact_charges_ra` row (counter contract), LEFT JOIN to `fact_charges_rs` (reservation) by `(rsrv_resn, inty, chco)` — **NOT by pos** (positions shift when counter inserts charges in the middle). The rs value = prepagado, the delta (ra - rs) = counter.

This unified rule covers:
- **Wholesalers** (CarTrawler): M-inty charges match rs → prepagado; S-inty charges have no rs → counter.
- **Sixt Prepago direct** (Priceline): ALL charges are M-inty, but rs only has a subset → per-charge split, with MIXTO labels for partial matches.

Implemented in `build_rentals_detail` (CTE `prepay_lookup`). Aggregated in `build_rentals_resumen` as `prepagado_usd` / `counter_usd` (net of discounts: `SUM(prepagado_cargo) - descuento_main`).

## Konr rule (charge versioning)

Sixt corrects contracts by inserting a new "wave" of charges with `konr+1` and **omitting** positions that no longer apply. The valid position set is: `(inty, pos)` whose `MAX(konr)` equals the `MAX(konr)` global of the contract. Implemented in `vw_charges_ra_enriched`, `vw_charges_rs_enriched`, `vw_rentals_detail`, and `vw_rentals_full`.

## Operating safely — Supabase IO budget awareness

**On Pro plan with Micro compute**, the database has a finite daily IO budget:

| Metric | Value |
|---|---|
| Baseline IO bandwidth | 87 Mbps (always available) |
| Burst IO bandwidth | 2,085 Mbps (24x baseline) |
| Daily burst budget | **30 minutes total per day** |
| Reset | Rolling 24-hour window (mostly refilled by next morning) |

When the burst budget is exhausted, the DB falls back to baseline 87 Mbps. The dashboard still works (~98% cache hit rate means tiny disk reads), but heavy operations slow dramatically.

### What burns the budget (in order)

1. **Silver build** (DROP+CREATE 30+ tables) — ~5-10 min of burst per run = ~15-30% of daily budget
2. **Bronze incremental** with large changes — ~2-5 min of burst per run = ~7-15%
3. **Ad-hoc heavy queries** (multi-CTE scans, no LIMIT, large GROUP BY) — varies, can be massive
4. **Failed pipeline + retry combo** — doubles IO consumption for same data
5. **Dashboard usage** — negligible (mostly cached)

### Pipeline safety rules

- **Run pipelines on a schedule** (06:00 + 20:00 COT recommended for 2/day, or 06/13/20 for 3/day)
- **Avoid manual runs during business hours** (08:00-18:00 COT) unless necessary
- **If pipeline runs > 20 minutes, kill it and restart** — Supabase pooler/network blips can leave it stuck; the watermark system makes restarts cheap
- **Never retry a failed pipeline immediately** — investigate first, otherwise you double the IO cost
- **Don't combine pipeline + heavy ad-hoc analysis on the same day** — that's how budget gets depleted

### Ad-hoc query safety rules

When the user asks for diagnostic/exploration queries, default to lightweight patterns:

- Always include `LIMIT` while iterating (e.g., `LIMIT 100`)
- Always add date filters when scanning fact tables: `WHERE fecha BETWEEN '2026-03-01' AND '2026-03-31'`
- Run `EXPLAIN ANALYZE` first if a query looks expensive
- If the user will re-run a query weekly/monthly, **save it as a silver view** instead of running it ad-hoc
- After a heavy debugging session (>5 multi-CTE queries), pause before running more — IO budget is shared
- A "few lines of SQL" can do massive work — text length ≠ execution cost

### How to check IO health

**Supabase UI (authoritative):**
- Project Settings → Compute and Disk → see "Disk IO consumed per day" chart
- Bars at <50% = healthy, >75% = use ad-hoc queries sparingly, 100% = budget depleted (baseline only until reset)

**Postgres SQL:**
```sql
-- Cache hit ratio (>95% = excellent, low disk IO)
SELECT ROUND(100.0 * sum(heap_blks_hit) /
       NULLIF(sum(heap_blks_hit) + sum(heap_blks_read), 0), 2) AS cache_hit_pct
FROM pg_statio_user_tables WHERE schemaname = 'silver';

-- Currently running heavy queries
SELECT pid, now() - query_start AS duration, LEFT(query, 100)
FROM pg_stat_activity WHERE state != 'idle' AND now() - query_start > interval '5 seconds';

-- Top historic disk-readers (since last stats reset)
SELECT LEFT(query, 100), calls, shared_blks_read
FROM pg_stat_statements WHERE shared_blks_read > 0
ORDER BY shared_blks_read DESC LIMIT 10;
```

### When IO budget is depleted

1. Dashboard still works fine (cache hit rate ~98%)
2. **Do not run more pipelines** until budget refills
3. **Do not run heavy ad-hoc queries** — they'll queue and crawl
4. Light queries (single-row lookups, indexed filters, TRM update) are safe
5. Budget refills overnight — fully reset by next morning typically

### Incident reference: 2026-06-05

- Failed 11-hour pipeline run + successful retry + silver rebuild + COBRA debugging queries combined = 100% budget depletion
- Cascade: project marked "unhealthy" → Supabase restarted instance → statement timeouts → dashboard timed out
- Resolution: upgraded to Pro + Micro compute, switched dashboard to Transaction pooler (6543), ran ANALYZE on silver tables
- Lesson: **the pipeline alone can deplete daily budget on Micro tier when it fails and retries**. Add a 20-minute timeout watchdog.

## Hard rules

1. **No DuckDB.** Stack is Supabase Postgres (was SQLite locally, migrated 2026-05-19).
2. **Bronze is raw mirror.** Same column names as Redshift. Zero business logic.
3. **All business logic lives in `pipelines/silver/build.py`.** Never write SQL transforms in the dashboard.
4. **No emojis in code or dashboard.**
5. **Pesos colombianos:** European format (`$1.502.654,05` — dot thousands, comma decimal). "mil millones" NOT "billones".
6. **COP conversion: always Banrep TRM** from `dim_trm_diaria`. The Sixt internal TRM is NOT used.
7. **Convención `vw_*`:** all views materialized as `CREATE TABLE`. Pattern: `DROP TABLE IF EXISTS ... CASCADE; DROP VIEW IF EXISTS ... CASCADE;` before creating.
8. **Idempotence:** any pipeline runs twice without breaking anything.
9. **Dummy vehicle filter:** `vehiculo_int_num = 99999999` is a Sixt administrative placeholder. Filter it out from vehicle analytics with `TRIM(vehiculo) != ''`.
10. **No-show / cancelación filter:** contratos con `TRIM(placa) = ''` (asesor 7777777 sistémico) o `total_con_iva_usd = 0` son no-shows y cancelaciones. NO se cuentan como ingreso en Cierre Diario ni Cargos Granular. Filtro: `TRIM(COALESCE(placa,'')) <> '' AND COALESCE(total_con_iva_usd,0) > 0`.
11. **Standardized date range filter:** todas las páginas del dashboard usan `render_sidebar_filters()` de `components/filters.py`. NO crear datepickers propios en páginas nuevas — usar el sidebar unificado para consistencia.
12. **operational.op_asesores:** tabla maestra manual de asesores (nombre + codigo_silver + codigo_hr). Se mantiene con INSERT/UPDATE manuales. El pipeline NO la toca. Requerida para mostrar nombres en Cargos Granular via LEFT JOIN por `codigo_silver = operador_handover_codigo`.

## Sixt data model — key columns

- `mndt_code = 409` → mandant Colombia. Always filtered.
- `rntl_mvnr` → contract number (PK of `fact_rentals`).
- `rsrv_resn` → reservation number (PK of `fact_reservations`). `rsrv_resn = 0` → walk-in (no online reservation).
- `chra_inty` → charge type: `'M'` = main (tercero/prepaid bucket), `'S'` = secondary (counter bucket).
- `chra_konr` → charge correction version. See "Konr rule" above.
- `rntl_agency1_type` → `'Wholesaler'` for OTA-booked rentals.
- `rsrv_prepaid_flg` → only `1` when Sixt central charged the client directly (sixt.com.co). Wholesaler prepayments show as `0`.
- `canal_cobro_tarifa` → derived: `SIXT_PREPAGO` / `WHOLESALER` / `COUNTER`. Covers both prepay scenarios.
- ACRISS → 4-letter category code. Decoded in `dim_vehicle_groups_decoded`.
- Bug: column is `rntl_distount_local` (typo in datashare, NOT `discount`).

## Dashboard pages

| Page | File | Access | Description |
|---|---|---|---|
| Landing | `app.py` | all | Summary KPIs (rentals, revenue, ticket, mix adicionales) |
| Cierre Diario | `1_Cierre_Diario.py` | all | Q2 resumen (1 row/contract) + Q1 detalle (per-charge factura with prepago/counter split, MIXTO labels, header table with Canal/Tercero) |
| Ingresos | `2_Ingresos.py` | admin | Tarifa vs adicionales by sede. RPD KPI. COP via Banrep per-row recalc. |
| Vehiculos | `4_Vehiculos.py` | admin | ACRISS distribution, upgrades/downgrades, top models (dummy vehicles filtered) |
| Disponibilidad | `5_Disponibilidad.py` | admin | Fleet snapshot (on-rent / ready-to-rent by sede and category) |
| Facturas | `6_Facturas.py` | all | Invoice capture form (writes to `operational.invoices`). Fields: sede (locked for sede users), fecha, contrato, factura, recibo, monto counter + prepagado (IVA 19% extracted by backend). Sede-role users have their branch locked. |
| Disponibilidad Flota | `7_Disponibilidad_Flota.py` | all | Monthly vehicle availability grid (vehicle x day). Combines auto data (rentals/reservations from Sixt) with manual entries (taller, PYP, transito, etc.). Staff can register/delete manual states. Writes to `operational.op_disponibilidad_manual`. |

## Disponibilidad Flota (operational.op_disponibilidad_manual)

### Color convention (manager-defined)
- **Green** (#c8e6c9): Rentado — vehicle generating revenue (good)
- **Blue** (#bbdefb): Reservado — future reservation
- **Red** (#ffcdd2): Taller — in maintenance (bad, out of service)
- **Light green** (#e8f5e9): Disponible — ready to rent
- **Yellow** (#fff9c4): PYP — pico y placa restriction
- **Gray** (#e0e0e0): Transito — between branches
- **Cyan** (#b2ebf2): Lavado — being washed
- **Dark** (#424242): Bloqueado — docs/fines/legal

### ACRISS display order
Fixed order matching real operations: EDMR, SDMR, CDMR, IDAH, SDAR, CFAR, IFAR, SFAR, RFAR. Note: SDMR and CDMR are the same category (CDMR is used in Pereira).

### Per-sede exceptions
- **Pereira** (`PEREIRA AIRPORT MATECANA INTL`): IDAR and SDAR are filtered out from both the grid and the vehicle selector.

### Schema (operational.op_disponibilidad_manual)
Key columns: `id` (PK), `vhcl_int_num`, `placa`, `fecha` (date), `estado`, `nota`, `asesor_codigo`, `sede_codigo`, `created_by`, `created_at`. Unique constraint on `(vhcl_int_num, fecha)` — UPSERT on conflict.

### Silver view: vw_disponibilidad_vehiculo_dia
Materialized by `build_disponibilidad_vehiculo_dia()`. 1 row per (vehicle x day), covering current month +/- 1 month. Priority: manual > rental > reservation > default (disponible). Reservations join loosely by ACRISS + sede (not specific vehicle) since open reservations don't have a vehicle assigned.

## Facturas workflow (operational.invoices)

Facturas have a lifecycle: **abierta (draft) → finalizada (cerrada)**. Each factura belongs to a sede and is only visible/editable by users of that sede (admin sees all).

### Create → Edit → Finalize → Validate flow

1. **Asesor creates factura** (draft): types contrato, monto counter + prepagado, numero factura/recibo. Backend computes `monto_total = counter + prepagado`, `monto_base = total / 1.19`, `iva = total - base`, `prepaid = prepagado > 0`. Status: `finalizada = FALSE`.

2. **Asesor edits** (while rental is open): clicks "Editar" on an open factura → form pre-fills → edits montos/recibos → "Guardar cambios" (UPDATE). Can edit as many times as needed.

3. **Vehicle returned → asesor finalizes**: clicks "Finalizar" → sets `finalizada = TRUE`, `finalizada_at = NOW()`, `finalizada_por = username`.

4. **Validation runs automatically**: for every finalized factura, the page compares `monto_total` (what asesor typed) vs `total_con_iva_usd * TRM_Banrep(handover_date)` (what silver computed from Sixt charges). Tolerance: $500 COP for rounding.
   - **Green**: amounts match within tolerance → all good.
   - **Red alarm**: difference > $500 COP → shows discrepancy + "Reabrir" button.
   - **Yellow (pendiente)**: contract not yet in silver (pipeline hasn't pulled it from Redshift yet) → no false alarm, just informational. Validation kicks in automatically after the next pipeline refresh.

5. **Reabrir**: if mismatch detected, asesor clicks "Reabrir" → reverts to draft (`finalizada = FALSE`) → asesor edits → re-finalizes → validation re-runs.

### Per-sede isolation

All factura queries filter by `sede_nombre = :user_sede` for sede-role users. A sede user **cannot** see, edit, finalize, or reopen another sede's facturas. The filtering is at the SQL level, not just UI-level.

### Schema (operational.invoices)

Key columns: `invoice_id` (PK), `rntl_mvnr` (contract), `sede_nombre`, `fecha_emision`, `numero_factura` (DIAN), `numero_recibo` (datafono), `monto_total` (counter + prepagado, IVA included), `monto_counter`, `monto_prepagado`, `monto_base` (backend-computed: total/1.19), `iva` (backend-computed), `prepaid` (boolean: prepagado > 0), `finalizada` (boolean), `finalizada_at`, `finalizada_por`, `capturado_por`, `capturado_at`.

## COBRA report reconciliation (manager's monthly batchfile)

COBRA produces a monthly Excel with 4 buckets per sede. Silver's per-charge totals reconcile to COBRA within ~0.1% when bucketed correctly.

### Bucket mapping (silver `cargo_codigo` → COBRA column)

| COBRA column | Silver codes | Notes |
|---|---|---|
| **VENTAS** | `T` | Tarifa core |
| **COBERTURAS** | `BF` + `LD` + `SL` | Full cover + LDW + liability |
| **ADICIONALES** | everything else except `Y` (`OT`, `OW`, `DC`, `FI`, `AD`, `AE`, `CL`, `OH`, `CS`, `RL`, `DL`, `BC`, `PP`, `BS`, `VA`, `RU`, etc.) | All other counter charges |
| **TAX** | `Y` (location/airport surcharge) | **NOT Colombian IVA**. Despite the column name, this is the airport concession fee. Real IVA is computed separately. |

### Contract-set difference (by design, not a bug)

COBRA and silver use different date fields for "month X" filtering:

- **COBRA**: contracts CLOSED/RETURNED in month X, with long-term leases pro-rated monthly (~1/12 of annual value per month).
- **Silver `vw_rentals_resumen`**: contracts where `fecha_handover_real::date BETWEEN ...`, with each rental's FULL value attributed to its handover month.

Validated March 2026: 288 contracts overlap (~80%), 71 silver-only (March handover → April return), 68 COBRA-only (handed over earlier, returned/billed in March). Silver $119,137.64 vs COBRA $119,271 = **99.89% agreement**.

### Konr rule (validated, do not weaken)

Sixt does **full restatement** on konr corrections: every konr+1 wave republishes ALL valid positions. The silver rule (`MAX(konr) per (mvnr, inty, pos) == MAX(konr) global per mvnr`) is correct and loses zero revenue. Verified March 2026: 0 rows flagged as "dropped — partial-restatement candidate", $0 dropped.

## Useful commands for one-off debugging

```python
# Run a single silver builder function
python -c "from pipelines.silver.build import build_rentals_resumen; from pipelines._common import get_engine; build_rentals_resumen(get_engine('silver,bronze'))"

# Check silver column exists
# In Supabase SQL Editor:
SELECT column_name FROM information_schema.columns WHERE table_schema='silver' AND table_name='vw_rentals_resumen' AND column_name = 'prepagado_usd';

# Validate a specific contract
SELECT numero_contrato, prepagado_usd, counter_usd, ROUND((prepagado_usd + counter_usd) * 1.19, 2) AS total_con_iva FROM silver.vw_rentals_resumen WHERE numero_contrato = 9523011485;
```

## Reference docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — design decisions, end-to-end flow
- [docs/source_of_truth.md](docs/source_of_truth.md) — queries for dashboard v2
- [docs/coding_style.md](docs/coding_style.md) — how to write a new silver view
- [docs/charge_codes.md](docs/charge_codes.md) — dictionary of T, BF, SL, etc.
- [docs/runbooks.md](docs/runbooks.md) — SSH/Redshift troubleshooting
