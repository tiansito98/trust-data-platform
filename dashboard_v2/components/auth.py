"""
Auth simple para el dashboard v2.

Credenciales: hardcodeadas en secrets (DASHBOARD_USER / DASHBOARD_PASS). UN
solo usuario autorizado. NO Supabase Auth, NO role system, NO cookies — la
sesion vive solo en st.session_state mientras la tab este abierta.

Cada pagina del dashboard debe llamar require_auth() al inicio. Si el usuario
no esta logueado, render el form + st.stop().
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from scripts.get_secret import get_secret  # noqa: E402


def _is_authenticated() -> bool:
    return bool(st.session_state.get("authenticated", False))


def require_auth() -> None:
    """
    Si no esta logueado, render form + st.stop(). Si esta logueado, pasa.
    Llamar al tope de cada pagina, antes de cualquier query a la DB.
    """
    if _is_authenticated():
        return

    st.title("Trust Data Platform")
    st.caption("Acceso restringido. Ingresa tus credenciales.")

    with st.form("login_form", clear_on_submit=False):
        user = st.text_input("Usuario", key="login_user")
        pwd = st.text_input("Contrasenia", type="password", key="login_pwd")
        submitted = st.form_submit_button("Entrar")

    if submitted:
        expected_user = get_secret("DASHBOARD_USER", default="")
        expected_pwd = get_secret("DASHBOARD_PASS", default="")
        if not expected_user or not expected_pwd:
            st.error("Auth no configurado. Setea DASHBOARD_USER y "
                     "DASHBOARD_PASS en secrets/.env.")
            st.stop()
        if user == expected_user and pwd == expected_pwd:
            st.session_state["authenticated"] = True
            st.session_state["dashboard_user"] = user
            st.rerun()
        else:
            st.error("Usuario o contrasenia incorrectos.")
    st.stop()


def logout_button(location: st.sidebar = None) -> None:
    """Boton de logout (opcional). Llamarlo desde la sidebar o donde quieras."""
    target = location if location is not None else st.sidebar
    if target.button("Cerrar sesion", key="btn_logout"):
        for k in ("authenticated", "dashboard_user", "login_user", "login_pwd"):
            st.session_state.pop(k, None)
        st.rerun()
