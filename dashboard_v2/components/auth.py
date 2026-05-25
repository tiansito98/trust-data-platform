"""
Auth multi-usuario con roles y restriccion por sede.

Credenciales almacenadas en dashboard_v2/config/users.yml con password
hasheados (bcrypt). Cada usuario tiene un rol (admin / sede) y una lista
de sedes visibles.

Funciones clave que cada pagina debe llamar:
  require_auth()  -> bloquea si no esta logueado (muestra login form).
  require_page(page_key) -> bloquea si el usuario no tiene acceso a esa pagina.
  get_user_branches() -> devuelve la lista de sedes del usuario, o ["*"].
  is_admin() -> True si el usuario es admin.
  logout_button() -> boton en sidebar para cerrar sesion.
"""
from __future__ import annotations

from pathlib import Path

import bcrypt
import streamlit as st
import yaml


_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_USERS_FILE = _CONFIG_DIR / "users.yml"


@st.cache_data(ttl=3600)
def _load_users() -> dict:
    """Carga usuarios. Fuente primaria: st.secrets["users"] (Streamlit Cloud).
    Fallback: config/users.yml local (desarrollo). Cacheado 1 hora."""
    # 1. Streamlit Cloud secrets (TOML nested bajo [users.xxx])
    try:
        if hasattr(st, "secrets") and "users" in st.secrets:
            secrets_users = st.secrets["users"]
            return {
                username: {
                    "password_hash": str(u["password_hash"]),
                    "role": str(u.get("role", "sede")),
                    "branches": list(u.get("branches", [])),
                    "pages": list(u.get("pages", [])),
                }
                for username, u in secrets_users.items()
            }
    except Exception:
        pass
    # 2. Fallback: YAML local (gitignored, para desarrollo).
    if _USERS_FILE.exists():
        with open(_USERS_FILE, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cfg.get("users", {})
    return {}


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _is_authenticated() -> bool:
    return bool(st.session_state.get("authenticated", False))


def get_current_user() -> dict | None:
    """Devuelve el dict del usuario logueado, o None si no esta logueado."""
    if not _is_authenticated():
        return None
    return st.session_state.get("user_info")


def is_admin() -> bool:
    user = get_current_user()
    return user is not None and user.get("role") == "admin"


def get_user_branches() -> list[str]:
    """Devuelve la lista de sedes del usuario. ["*"] para admin (= todas)."""
    user = get_current_user()
    if user is None:
        return []
    return user.get("branches", [])


def get_user_pages() -> list[str]:
    """Devuelve la lista de pages permitidas. ["*"] para admin (= todas)."""
    user = get_current_user()
    if user is None:
        return []
    return user.get("pages", [])


def require_auth() -> None:
    """Si no esta logueado, muestra form de login y hace st.stop()."""
    if _is_authenticated():
        return

    st.title("Trust Data Platform")
    st.caption("Acceso restringido. Ingresa tus credenciales.")

    users = _load_users()
    if not users:
        st.error("No se encontro el archivo de usuarios (config/users.yml).")
        st.stop()

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Usuario", key="login_user")
        password = st.text_input("Contrasena", type="password", key="login_pwd")
        submitted = st.form_submit_button("Entrar")

    if submitted:
        user_cfg = users.get(username)
        if user_cfg is None:
            st.error("Usuario o contrasena incorrectos.")
            st.stop()
        if not _verify_password(password, user_cfg.get("password_hash", "")):
            st.error("Usuario o contrasena incorrectos.")
            st.stop()

        st.session_state["authenticated"] = True
        st.session_state["dashboard_user"] = username
        st.session_state["user_info"] = {
            "username": username,
            "role": user_cfg.get("role", "sede"),
            "branches": user_cfg.get("branches", []),
            "pages": user_cfg.get("pages", []),
        }
        st.rerun()

    st.stop()


def require_page(page_key: str) -> None:
    """Bloquea la pagina si el usuario no tiene acceso.

    page_key debe ser el prefijo del nombre de archivo de la pagina.
    Ej: "1_Cierre_Diario", "6_Facturas", "2_Ingresos".
    Para admin (pages=["*"]) siempre pasa.
    """
    allowed = get_user_pages()
    if "*" in allowed:
        return
    if page_key not in allowed:
        st.warning("Acceso restringido. Tu usuario no tiene permiso para "
                   "ver esta pagina.")
        st.stop()


def logout_button(location=None) -> None:
    """Boton de logout. Llamar desde sidebar o donde convenga."""
    target = location if location is not None else st.sidebar
    user = get_current_user()
    if user:
        target.caption(f"Usuario: **{user['username']}** ({user['role']})")
    if target.button("Cerrar sesion", key="btn_logout"):
        for k in list(st.session_state.keys()):
            if k.startswith(("authenticated", "dashboard_user", "user_info",
                             "login_user", "login_pwd", "v2_")):
                st.session_state.pop(k, None)
        st.rerun()
