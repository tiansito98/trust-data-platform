# Captura pendiente — qué falta para que las páginas operativas tengan data

> Este documento describe qué falta capturar para llenar las 6 páginas del dashboard que hoy aparecen vacías.
> El cierre diario (página 1) NO necesita captura — ya se deriva de Tramo 1 vía `vw_cierre_diario_sede`.

---

## Por qué hay 6 páginas vacías

Sixt comparte vía Redshift Data Exchange los datos de **Tramo 1** (reservas, rentals, charges, vehículos, sedes). Esos llegan a Bronze automáticamente cada 6h y reconstruyen `dim_*` y `fact_*` en Silver.

**Tramo 2** son eventos físicos / juicios operativos que Sixt **no captura** porque su sistema central (COBRA) termina en el contrato. Trust los necesita para operar pero hay que registrarlos por su lado:

- novedades físicas del vehículo (falla, GPS, documento vencido, limpieza),
- incidentes (accidente, robo, vandalismo),
- checklists internos de apertura/cierre,
- traslados inter-sede con motivo y costo,
- tickets de soporte / escalamiento entre áreas,
- contratos con soportes faltantes (licencia, foto, SOAT, etc.).

Hasta que Trust empiece a registrar esto, las 6 tablas `op_*` están vacías y las páginas correspondientes muestran KPIs en cero, gráficos vacíos y dataframes sin filas.

---

## Página por página: qué necesita

### Página 2 — Novedades de Vehículos
**Tabla:** `op_novedades_vehiculo`
**Granularidad:** 1 fila por novedad reportada.
**Quién captura:** operador de sede / mecánico / supervisor.
**Cuándo:** al detectar la novedad.

Columnas a capturar:

| Columna | Tipo | Ejemplo / valores |
|---|---|---|
| `nove_date` | DATE | Fecha del evento |
| `nove_datm` | TIMESTAMP | Timestamp exacto |
| `brnc_code` | INTEGER | Sede donde se detectó (FK a `dim_branches`) |
| `vhcl_int_num` | INTEGER | Vehículo (FK a `dim_vehicles`) |
| `vhcl_plate` | TEXT | Placa para legibilidad rápida |
| `nove_type` | TEXT | DOCUMENTO_VENCIDO / FALLA_MECANICA / LLANTA / BATERIA / LIMPIEZA / GPS / OTRO |
| `nove_severity` | TEXT | BAJA / MEDIA / ALTA / CRITICA |
| `nove_description` | TEXT | Descripción libre |
| `nove_reported_by` | INTEGER | Empleado que reportó (FK `dim_employees` cuando se llene) |
| `nove_status` | TEXT | ABIERTA / EN_GESTION / RESUELTA / ESCALADA |
| `nove_resolved_datm` | TIMESTAMP | Cuándo se cerró |
| `nove_resolution_notes` | TEXT | Cómo se resolvió |

**Mecanismo sugerido:** formulario Streamlit interno (página `8_Capturar_Novedad.py`) o app móvil para personal de sede. Por ahora bulk import de Excel también es viable.

---

### Página 3 — Incidentes
**Tabla:** `op_incidentes`
**Granularidad:** 1 fila por incidente.
**Quién captura:** supervisor de sede al ocurrir el evento, o central de operaciones al recibir reporte.

Columnas: `inci_date`, `inci_datm`, `brnc_code`, `vhcl_int_num`, `rntl_mvnr` (FK a rental real, opcional), `cstm_kdnr`, `inci_type` (ACCIDENTE/ROBO/VANDALISMO/ABANDONO/DEVOLUCION_TARDIA/DOCUMENTO_FALSO), `inci_severity`, `inci_description`, `inci_third_party_flg`, `inci_police_flg`, `inci_insurance_flg`, `inci_estimated_cost`, `inci_status` (ABIERTO/EN_PROCESO/CON_ASEGURADORA/CERRADO), `inci_reported_by`, `inci_assigned_to`.

**Fuente parcial:** algunos casos podrían provenir de `fact_damages` cuando Sixt habilite el datashare de daños (hoy 0 filas). Pero la mayoría seguirán siendo captura humana porque incluyen contexto que Sixt no registra (descripción, asignado a, póliza).

---

### Página 4 — Checklist Apertura/Cierre
**Tabla:** `op_checklist_apertura_cierre`
**Granularidad:** 1 fila por sede × día × turno (apertura o cierre).
**Quién captura:** operador de turno cada apertura/cierre.

Columnas: `chkl_date`, `chkl_dtid`, `brnc_code`, `chkl_type` (APERTURA/CIERRE), `chkl_datm`, `chkl_submitted_by`, 7 flags 0/1 (`chkl_caja_ok`, `chkl_oficina_limpia`, `chkl_inventario_vehiculos_ok`, `chkl_documentos_organizados`, `chkl_sistema_operativo_ok`, `chkl_seguridad_ok`, `chkl_combustible_disponible`), `chkl_caja_monto`, `chkl_observations`, `chkl_score` (suma de flags 0-7), `chkl_status`.

**No tiene equivalente en Sixt.** Es un proceso interno Trust. Sin data acá no hay forma de medir disciplina operativa de las sedes.

**Mecanismo sugerido:** formulario rápido (smartphone) que el operador completa al abrir y al cerrar. 7 toggles y un campo de observaciones.

---

### Página 5 — Traslados Inter-Sede
**Tabla:** `op_traslado_vehiculos`
**Granularidad:** 1 fila por traslado.

Columnas clave: `tras_request_date`, `vhcl_int_num`, `vhcl_plate`, `brnc_code_origin`, `brnc_code_destination`, `tras_reason` (REBALANCEO/ONE_WAY_RETURN/MANTENIMIENTO/DEMANDA/OTRO), `tras_priority`, `tras_requested_by`, `tras_assigned_to`, `tras_executed_datm`, `tras_arrival_datm`, `tras_distance_km`, `tras_duration_hours`, `tras_cost`, `tras_status` (SOLICITADO/APROBADO/EN_TRANSITO/COMPLETADO/CANCELADO).

**Fuente parcial derivable:** el cambio de sede del vehículo se ve en `dim_vehicles_current` (columnas `brnc_code` actual vs `brnc_code_handover_rarent` original). Pero el motivo, el conductor, el costo y la duración no son derivables — los registra Trust.

**Mecanismo sugerido:** flujo de aprobación: solicitud → aprobación → confirmación de salida → confirmación de llegada. Podría integrarse con el formulario de novedades cuando el motivo es mantenimiento.

---

### Página 6 — Solicitudes de Soporte / Escalamiento
**Tabla:** `op_solicitudes_soporte`
**Granularidad:** 1 fila por ticket.

Columnas: `sopt_request_date`, `brnc_code` (sede que pide), `sopt_category` (SISTEMA/OPERATIVO/FINANCIERO/LEGAL/CLIENTE/TECNOLOGIA), `sopt_priority` (BAJA/MEDIA/ALTA/URGENTE), `sopt_subject`, `sopt_description`, `sopt_requested_by`, `sopt_assigned_to`, `sopt_status` (ABIERTO/EN_PROCESO/RESUELTO/ESCALADO/CERRADO), `sopt_resolved_datm`, `sopt_sla_hours` (default 24), `sopt_sla_breach_flg` (1 si vencido sin resolver), `sopt_resolution_notes`.

**No tiene equivalente en Sixt.** Es ticketing interno entre áreas.

**Mecanismo sugerido:** formulario Streamlit con auto-cálculo del `sopt_sla_breach_flg` (job programado que marca tickets sin cerrar después de N horas). O integrar con un sistema de tickets externo (Jira, Zendesk, ClickUp) e importar.

---

### Página 7 — Contratos con Soportes Faltantes
**Tabla:** `op_contratos_soportes_faltantes`
**Granularidad:** 1 fila por (rental, soporte faltante).

Columnas: `cosf_date`, `rntl_mvnr` (FK al rental real), `rsrv_resn` (FK a reserva), `cstm_kdnr`, `brnc_code`, `cosf_missing_type` (LICENCIA/CEDULA/TARJETA_CREDITO/FIRMA/FOTO_VEHICULO_CHECKOUT/FOTO_VEHICULO_RETURN/SOAT/SEGURO), `cosf_missing_count`, `cosf_severity`, `cosf_age_hours`, `cosf_age_days`, `cosf_status` (PENDIENTE/EN_PROCESO/SUBSANADO/ESCALADO), `cosf_responsible`, `cosf_resolved_datm`.

**Fuente parcial derivable:** algunos casos podrían generarse automáticamente con queries sobre `fact_rentals` (rentals sin foto de check-out, sin licencia adjunta — si esa info se llegara a almacenar en algún sistema de Trust). Por ahora no es derivable porque Sixt no comparte esos archivos adjuntos.

**Mecanismo sugerido:**
1. Al cierre del día, job que detecta rentals con campos vacíos de doc y abre filas en `op_contratos_soportes_faltantes` automáticamente.
2. El operador de sede actualiza `cosf_status='SUBSANADO'` cuando consigue el documento.
3. Job diario incrementa `cosf_age_hours/days` y marca como `ESCALADO` si superan umbral.

---

## Tabla resumen: prioridad y costo de captura

| Página | Captura difícil? | Cuánto valor agrega? | Prioridad sugerida |
|---|---|---|---|
| 4 — Checklist apertura/cierre | Bajo (7 toggles + obs) | Alto (mide disciplina operativa diaria) | **Alta** — primero |
| 2 — Novedades vehículo | Bajo (form simple) | Alto (sin esto no hay seguimiento de mantenimiento) | **Alta** |
| 5 — Traslados | Medio (flujo multi-paso) | Medio (logística) | **Media** |
| 3 — Incidentes | Medio (datos de seguros) | Alto pero baja frecuencia | **Media** |
| 6 — Soporte interno | Medio (tickets) | Medio | **Media** |
| 7 — Contratos faltantes | Bajo si se automatiza | Alto (cumplimiento legal) | **Alta** — automatizable |

---

## Camino sugerido para activar Tramo 2

Tres caminos no excluyentes:

1. **Captura manual rápida** — agregar páginas Streamlit `8_Capturar_*.py` con formularios simples que hacen `INSERT INTO op_*` directo en `silver.db`. Para cumplir con read-only del dashboard principal, abrir conexión separada en write mode con WAL.
2. **Bulk import de Excel** — un script `pipelines/silver/import_op.py --csv data.csv --table op_novedades_vehiculo` que lee CSV y hace INSERT bulk. Útil para histórico inicial.
3. **App móvil** — flujo nativo para operador de sede (futuro, requiere desarrollo aparte).

**Importante:** las tablas `op_*` están protegidas por `CREATE TABLE IF NOT EXISTS` en `silver/build.py`, así que un rebuild de Silver NO borra lo que Trust capture. Backupear `silver.db` con frecuencia una vez que empiece la captura.

---

## Lo que NO falta capturar (resuelto)

- **Cierre diario de sede** (`op_cierre_diario_sede`): tabla vacía pero no se necesita captura. La vista `vw_cierre_diario_sede` deriva los KPIs (rentals, returns, revenue, ocupación) automáticamente de Tramo 1. La página 1 ya consume esa vista.
- **Daños** (`fact_damages`, `fact_damage_details`, `fact_damage_cases`): vacías globalmente en el datashare al 2026-05-04. Cuando Florian habilite acceso, se llenarán solas en el próximo refresh sin captura humana.

---

*Última actualización: 2026-05-04 — al cerrar Fase D del dashboard.*
