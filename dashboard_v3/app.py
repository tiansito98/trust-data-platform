"""Dashboard v3 - Vision Historica Trust Colombia (2021-2026).

Lanzar:
    streamlit run dashboard_v3/app.py --server.port 8503

Estructura:
    pages/1_KPIs_Anuales.py    - flota, ocupacion, RPD, ingresos por anio
    pages/2_Demanda.py         - % served, cancel rate desagregado
    pages/3_Capacidad_Flota.py - utilizacion mensual + evolucion por segmento ACRISS
"""
import streamlit as st
from components.common import inject_styles, render_header

st.set_page_config(
    page_title="Trust v3 - Vision Historica",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_styles()
render_header("Vision Historica")

st.markdown(
    """
    Dashboard analitico **agnostico a sedes** (consolidado nacional) que cubre
    el rango 2021-2026. Pensado para entender la evolucion del negocio en el
    tiempo: flota, ocupacion, ingresos, demanda y mix de categorias.

    Todos los montos en **USD** (sin TRM), sin IVA salvo donde se indique.

    Paginas (sidebar):
    - **KPIs Anuales**: flota activa, ocupacion, revenue per day, ingresos por
      tarifa vs adicionales, ingreso total.
    - **Demanda**: % served, cancel rate desagregado por cliente / no-show /
      Sixt.
    - **Capacidad y Flota**: utilizacion mensual por sede y categoria ACRISS,
      evolucion del mix de flota por anio.
    """
)

st.divider()

with st.expander("Diccionario ACRISS (codigo de 4 letras)"):
    st.markdown(
        """
        **Posicion 1 - Categoria de tamaño:**
        `M` Mini · `E` Economy · `C` Compact · `I` Intermediate · `S` Standard ·
        `F` Fullsize · `P` Premium · `L` Luxury · `X` Special

        **Posicion 2 - Tipo de carroceria:**
        `B` 2 puertas · `C` 2/4 puertas · `D` 4/5 puertas · `W` Wagon · `V` Van ·
        `S` Sport · `T` Convertible · `F` SUV · `J` Open Air · `X` Special ·
        `P` Pickup regular · `Q` Pickup extended · `Z` Special offer

        **Posicion 3 - Transmision y traccion:**
        `M` Manual + 2WD · `N` Manual + 4WD · `C` Manual + AWD · `A` Auto + 2WD ·
        `B` Auto + 4WD · `D` Auto + AWD

        **Posicion 4 - Combustible y aire acondicionado:**
        `R` Gasolina + AC · `N` Gasolina + sin AC · `D` Diesel + AC ·
        `Q` Diesel + sin AC · `H` Hibrido + AC · `I` Electrico-hibrido + AC ·
        `C` Electrico + AC · `L` LPG-Compressed gas + AC · `E` Electrico distancia ·
        `S` Etanol + AC · `A` Hibrido enchufable + AC · `M` Multifuel + AC

        Ejemplos comunes en Sixt Colombia:
        - `EDMR` Economy, 4/5 puertas, manual, gasolina + AC (Chevrolet Joy)
        - `IDAR` Intermediate, 4/5 puertas, auto, gasolina + AC (Chevrolet Onix Premier)
        - `SDAR` Standard, 4/5 puertas, auto, gasolina + AC
        - `IDAH` Intermediate, 4/5 puertas, auto, hibrido + AC
        - `SFAR` Standard SUV, auto, gasolina + AC (Chevrolet Captiva)
        """
    )
