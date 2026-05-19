# Gold — Capa de Reportes

> Por implementar. Vistas materializadas para reportes ejecutivos y operativos.
>
> Se construye una vez Silver esté completo y validado.

---

## Reportes planificados

| Tabla | Para qué |
|---|---|
| `rpt_daily_occupancy` | Ocupación real por sede × categoría × día |
| `rpt_revenue_by_branch` | Revenue diario/mensual por sede |
| `rpt_reservations_risk` | Reservas próximas sin vehículo asignado |
| `rpt_pending_transfers` | Cola de rebalanceo entre sedes |
| `rpt_sla_breach` | Tickets de soporte con SLA incumplido |
| `rpt_vehicle_tco` | TCO acumulado por vehículo (acquisition + maintenance + incidents) |
| `opt_rebalancing` | Recomendaciones de rebalanceo (futuro: con ML) |

Todos parten de Silver y agregan/consolidan.
