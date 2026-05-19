"""
Utilidad unica para resolver credenciales en cualquier contexto.

Resuelve en este orden:
  1. st.secrets[key]  (cuando corremos dentro de Streamlit Cloud / local)
  2. os.environ[key]  (cuando corremos en GitHub Actions / scripts CLI)
  3. valor de .env via python-dotenv (solo si el modulo esta disponible)
  4. default (si se especifica) o raises ValueError

Uso:
    from scripts.get_secret import get_secret
    db_url = get_secret("SUPABASE_DB_URL")
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOTENV_LOADED = False


def _load_dotenv_once() -> None:
    """Carga .env del root del repo una sola vez por proceso. Silent si no existe."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except ImportError:
        pass


def get_secret(key: str, default: Any = ...) -> str:
    """Devuelve el valor del secret. Lanza ValueError si falta y no hay default."""
    try:
        import streamlit as st
        try:
            value = st.secrets[key]
            if value not in (None, ""):
                return str(value)
        except (KeyError, FileNotFoundError, AttributeError):
            pass
    except ImportError:
        pass

    value = os.getenv(key)
    if value not in (None, ""):
        return value

    _load_dotenv_once()
    value = os.getenv(key)
    if value not in (None, ""):
        return value

    if default is not ...:
        return default
    raise ValueError(
        f"Secret '{key}' no encontrado. Configuralo en .env, "
        f"env vars del runner, o .streamlit/secrets.toml."
    )


def has_secret(key: str) -> bool:
    """True si el secret existe con valor no-vacio. Util para features opcionales."""
    try:
        return get_secret(key) not in (None, "")
    except ValueError:
        return False
