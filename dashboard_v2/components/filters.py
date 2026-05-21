"""Filtros transversales reusables del v2.

Sidebar uniforme entre paginas. Persistencia entre paginas via session_state
(misma key default 'v2_*'). Devuelve un dict con todo lo necesario para que
las paginas armen el WHERE.
"""
import datetime as dt
from dataclasses import dataclass

import streamlit as st

from .common import (
    get_sedes, get_fecha_range, get_acriss_options, get_canal_options,
    render_trm_today_sidebar,
)


@dataclass
class FilterState:
    """Estado consolidado de filtros para una pagina."""
    sedes_codigos: list      # lista de codigos seleccionados (vacia = todas)
    sedes_nombres: list      # nombres para mostrar en headers/banners
    fecha_desde: dt.date
    fecha_hasta: dt.date
    moneda: str              # 'USD' o 'COP'
    trm_source: str = "Banrep"  # SIEMPRE Banrep — la TRM Sixt ya no se ofrece
    acriss: list = None      # categorias ACRISS (vacia = todas)
    canal: list = None       # canales (vacia = todos)

    def __post_init__(self):
        if self.acriss is None:
            self.acriss = []
        if self.canal is None:
            self.canal = []

    @property
    def sede_label(self) -> str:
        if not self.sedes_codigos:
            return "Todas las sedes"
        if len(self.sedes_codigos) == 1:
            return self.sedes_nombres[0]
        return f"{len(self.sedes_codigos)} sedes"

    @property
    def moneda_label(self) -> str:
        if self.moneda == "USD":
            return "USD"
        return "COP (Banrep)"

    @property
    def revenue_col_usd(self) -> str:
        return "neto_usd"

    @property
    def revenue_col_cop(self) -> str:
        # Siempre recalculamos COP a partir de USD x TRM Banrep para que el
        # numero coincida con lo oficial del Banco de la Republica.
        return "neto_cop"

    def where_clause(self, table_alias: str = "") -> tuple:
        """Devuelve (where_sql, params) para query parametrizada.

        Incluye filtros estandar: rental_currency='USD', fecha range,
        sedes (si hay), acriss (si hay), canal (si hay).
        """
        prefix = f"{table_alias}." if table_alias else ""
        parts = [
            f"{prefix}rental_currency = 'USD'",
            f"DATE({prefix}fecha_handover_real) BETWEEN ? AND ?",
        ]
        params = [self.fecha_desde.isoformat(), self.fecha_hasta.isoformat()]
        if self.sedes_codigos:
            placeholders = ",".join("?" * len(self.sedes_codigos))
            parts.append(f"{prefix}sede_handover_codigo IN ({placeholders})")
            params.extend(self.sedes_codigos)
        if self.acriss:
            placeholders = ",".join("?" * len(self.acriss))
            parts.append(f"{prefix}acriss_entregado IN ({placeholders})")
            params.extend(self.acriss)
        if self.canal:
            placeholders = ",".join("?" * len(self.canal))
            parts.append(f"{prefix}canal_principal IN ({placeholders})")
            params.extend(self.canal)
        return " AND ".join(parts), tuple(params)


def render_sidebar_filters(default_days: int = 30,
                           show_acriss: bool = False,
                           show_canal: bool = False) -> FilterState:
    """Pinta los filtros en st.sidebar y devuelve un FilterState."""
    sedes_df = get_sedes()
    d_min, d_max = get_fecha_range()

    nombres = sedes_df["nombre"].tolist()

    # Pre-seed session_state ONCE para que la persistencia entre paginas funcione
    # bien. En Streamlit, pasar `default=` + `key=` a un widget puede causar que
    # el `default` gane sobre lo guardado en session_state al navegar entre
    # paginas; solo usar `key=` (con session_state pre-seedeado) es el patron
    # confiable.
    today = dt.date.today()
    default_hasta = min(today, d_max)
    default_desde = max(d_min, default_hasta - dt.timedelta(days=2))
    if "v2_sedes" not in st.session_state:
        st.session_state["v2_sedes"] = []
    if "v2_fechas" not in st.session_state:
        st.session_state["v2_fechas"] = (default_desde, default_hasta)
    if "v2_moneda" not in st.session_state:
        st.session_state["v2_moneda"] = "USD"
    if "v2_acriss" not in st.session_state:
        st.session_state["v2_acriss"] = []
    if "v2_canal" not in st.session_state:
        st.session_state["v2_canal"] = []

    # TRM Hoy banner — visible al tope del sidebar en TODAS las paginas.
    render_trm_today_sidebar()

    with st.sidebar:
        st.markdown("## Filtros")

        # Sede multiselect — solo key=, sin default= (anti-pattern).
        sedes_sel = st.multiselect(
            "Sedes",
            options=nombres,
            key="v2_sedes",
            help="Vacio = todas las sedes. Tu seleccion se mantiene entre paginas.",
        )

        # Fechas. Default ya pre-seedeado a (hoy - 2 .. hoy) arriba; aqui solo
        # se renderiza el widget que persiste via session_state["v2_fechas"].
        rango = st.date_input(
            "Rango de fechas",
            key="v2_fechas",
            min_value=d_min,
            max_value=d_max,
        )
        if isinstance(rango, tuple) and len(rango) == 2:
            fecha_desde, fecha_hasta = rango
        elif isinstance(rango, dt.date):
            # Streamlit devuelve un solo date cuando aun no se cierra el rango
            fecha_desde = fecha_hasta = rango
        else:
            fecha_desde, fecha_hasta = default_desde, default_hasta

        # Caption inline para feedback visual del rango seleccionado.
        if fecha_desde == fecha_hasta:
            st.caption(f"Mostrando: **{fecha_desde.isoformat()}** (1 dia)")
        else:
            dias = (fecha_hasta - fecha_desde).days + 1
            st.caption(
                f"Mostrando: **{fecha_desde.isoformat()}** &rarr; "
                f"**{fecha_hasta.isoformat()}** ({dias} dias)"
            )

        # Moneda. TRM siempre Banrep (oficial datos.gov.co).
        # La opcion 'Sixt TRM' se retiro: usar siempre la TRM oficial para
        # que los reportes en COP coincidan con cifras del Banco de la Republica.
        moneda = st.radio(
            "Moneda",
            options=["USD", "COP"],
            horizontal=True,
            key="v2_moneda",
        )
        trm_source = "Banrep"
        if moneda == "COP":
            st.caption("COP recalculado con TRM Banrep oficial (datos.gov.co).")

        # Opcionales: ACRISS y canal. Mismo patron — solo key=, sin default=.
        acriss_sel = []
        if show_acriss:
            acriss_sel = st.multiselect(
                "Categoria ACRISS",
                options=get_acriss_options(),
                key="v2_acriss",
            )

        canal_sel = []
        if show_canal:
            canal_sel = st.multiselect(
                "Canal principal",
                options=get_canal_options(),
                key="v2_canal",
            )

    codigos = sedes_df[sedes_df["nombre"].isin(sedes_sel)]["codigo"].astype(int).tolist()
    return FilterState(
        sedes_codigos=codigos,
        sedes_nombres=sedes_sel,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        moneda=moneda,
        trm_source=trm_source,
        acriss=acriss_sel,
        canal=canal_sel,
    )


def render_active_filters_banner(state: FilterState):
    """Banner compacto con filtros activos al tope de la pagina."""
    dias = (state.fecha_hasta - state.fecha_desde).days + 1
    parts = [
        f"<strong>Sede:</strong> {state.sede_label}",
        f"<strong>Rango:</strong> {state.fecha_desde.isoformat()} &rarr; "
        f"{state.fecha_hasta.isoformat()} &nbsp;({dias} dias)",
        f"<strong>Moneda:</strong> {state.moneda_label}",
    ]
    if state.acriss:
        parts.append(f"<strong>ACRISS:</strong> {', '.join(state.acriss)}")
    if state.canal:
        parts.append(f"<strong>Canal:</strong> {', '.join(state.canal)}")
    html = " &nbsp;|&nbsp; ".join(parts)
    st.markdown(
        f"""
        <div style="background:#fff3e0;border-left:4px solid #ff6900;
                    padding:8px 14px;margin:4px 0 16px 0;font-size:0.95rem;
                    color:#333;border-radius:2px;
                    box-shadow:0 2px 6px rgba(0,0,0,0.06);">
            {html}
        </div>
        """,
        unsafe_allow_html=True,
    )
