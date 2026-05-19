"""
TRUST Dashboard v2 - landing.

Construido sobre las vistas source-of-truth (vw_rentals_resumen / detail /
full) y dim_trm_diaria. Lee silver.db en modo read-only.

Correr:
    streamlit run dashboard_v2/app.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

from components.common import (
    inject_styles, render_header, section, kpi, fmt_int, fmt_money,
    fmt_money_short, load_query,
)
from components.filters import render_sidebar_filters, render_active_filters_banner
from components.auth import require_auth, logout_button

st.set_page_config(
    page_title="TRUST",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Auth gate: si no esta logueado, render form + st.stop() antes de cualquier query.
require_auth()

inject_styles()
render_header("Analitica Comercial")
logout_button()

filtros = render_sidebar_filters(default_days=30)
render_active_filters_banner(filtros)

where_sql, params = filtros.where_clause()

# KPIs principales: rentals, revenue USD, ticket promedio, % adicionales.
kpi_sql = f"""
SELECT COUNT(*)                                                AS rentals,
       COALESCE(SUM(neto_usd), 0)                              AS neto_usd,
       COALESCE(SUM(tarifa_usd), 0)                            AS tarifa_usd,
       COALESCE(SUM(adicionales_usd), 0)                       AS adicionales_usd,
       COALESCE(AVG(neto_usd), 0)                              AS ticket_usd,
       COALESCE(SUM(dias_renta), 0)                            AS dias_renta
FROM vw_rentals_resumen
WHERE {where_sql}
"""
df = load_query(kpi_sql, params)
row = df.iloc[0]
tarifa = float(row["tarifa_usd"])
adicionales = float(row["adicionales_usd"])
pct_adic = (adicionales / (tarifa + adicionales) * 100) if (tarifa + adicionales) else 0

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Rentals", fmt_int(row["rentals"]))
kpi(c2, "Revenue neto", fmt_money(row["neto_usd"], "USD"),
    fmt_money_short(row["neto_usd"], "USD"))
kpi(c3, "Ticket promedio", fmt_money(row["ticket_usd"], "USD"))
kpi(c4, "Mix adicionales", f"{pct_adic:.1f} %",
    f"Tarifa {fmt_money_short(tarifa, 'USD')} + Adic {fmt_money_short(adicionales, 'USD')}")

section("Paginas disponibles")
st.markdown(
    """
- **1. Cierre Diario** - Q1 detalle por contrato (factura) o Q2 resumen una fila por contrato.
  Validado contra contrato 9523073821 (Rionegro, Abril 2026) = $826.95 USD.
- **2. Ingresos** - Tarifa vs adicionales por sede y por categoria de cargo. Top codigos.
- **4. Vehiculos** - Distribucion ACRISS, upgrades/downgrades reservado vs entregado,
  top modelos fisicos.
- **5. Disponibilidad** - Flota actual: on rent / ready to rent por sede y categoria.
- **6. Facturas** - Captura de facturas / recibos (escribe a operational.invoices).

**Filtros**: sede (multiselect, vacio = todas), rango de fechas, moneda USD o COP con
toggle Banrep (oficial) vs Sixt (interna ~1% mas alta).

**Fuente**: silver.db (vistas materializadas reconstruidas cada 6h desde Redshift datashare
de Sixt mandant 409).
    """
)

st.markdown("---")
st.caption(
    "Trust Data Platform v2. Toda la logica de calculo vive en pipelines/silver/build.py. "
    "El dashboard solo filtra y muestra."
)
