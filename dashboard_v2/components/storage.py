"""
Cliente minimo de Supabase Storage via REST (sin supabase-py).

La autenticacion del dashboard es propia (bcrypt), NO Supabase Auth, asi que el
RLS de Storage basado en auth.uid() no aplica: todo pasa por el backend con la
llave de servicio y el permiso (quien ve que) se aplica en el codigo de la
pagina, igual que en operational.invoices. La llave NUNCA llega al navegador:
para abrir un archivo se entrega una URL FIRMADA de pocos minutos.

Secrets necesarios (Streamlit secrets / env / .env, ver scripts/get_secret.py):
  SUPABASE_URL               https://<ref>.supabase.co
  SUPABASE_SERVICE_ROLE_KEY  llave service_role (JWT eyJ...) o secret key (sb_secret_...)

OJO: los backups / PITR de Supabase cubren Postgres, NO los objetos de Storage.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.get_secret import get_secret  # noqa: E402

API_VERSION = 2   # subir si cambia lo que usan documentos/expedientes (ver CLAUDE.md, gotcha de deploy)
BUCKET = "documentos"
TIMEOUT = 60


class StorageError(RuntimeError):
    pass


def _cfg() -> tuple[str, str]:
    url = (get_secret("SUPABASE_URL", default="") or "").rstrip("/")
    key = get_secret("SUPABASE_SERVICE_ROLE_KEY", default="") or ""
    if not url or not key:
        raise StorageError("Faltan SUPABASE_URL y/o SUPABASE_SERVICE_ROLE_KEY en los secrets.")
    return url, key


def configurado() -> bool:
    try:
        _cfg()
        return True
    except Exception:
        return False


def _headers(extra: dict | None = None) -> dict:
    _, key = _cfg()
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    if extra:
        h.update(extra)
    return h


def _obj(path: str) -> str:
    return quote(path, safe="/")


def _check(r: requests.Response, accion: str) -> requests.Response:
    if r.status_code >= 300:
        raise StorageError(f"Storage {accion}: HTTP {r.status_code} {r.text[:300]}")
    return r


def ensure_bucket(bucket: str = BUCKET, limite_mb: int = 50) -> None:
    """Crea el bucket PRIVADO si no existe (idempotente)."""
    url, _ = _cfg()
    r = requests.get(f"{url}/storage/v1/bucket/{bucket}", headers=_headers(), timeout=TIMEOUT)
    if r.status_code == 200:
        return
    r = requests.post(
        f"{url}/storage/v1/bucket", headers=_headers({"Content-Type": "application/json"}),
        json={"id": bucket, "name": bucket, "public": False,
              "file_size_limit": limite_mb * 1024 * 1024},
        timeout=TIMEOUT,
    )
    if r.status_code >= 300 and "already exists" not in r.text.lower():
        _check(r, "crear bucket")


def upload(path: str, data: bytes, mime: str, bucket: str = BUCKET, upsert: bool = False) -> None:
    url, _ = _cfg()
    r = requests.post(
        f"{url}/storage/v1/object/{bucket}/{_obj(path)}",
        headers=_headers({"Content-Type": mime or "application/octet-stream",
                          "x-upsert": "true" if upsert else "false",
                          "cache-control": "3600"}),
        data=data, timeout=TIMEOUT,
    )
    _check(r, "subir")


def download(path: str, bucket: str = BUCKET) -> bytes:
    url, _ = _cfg()
    r = requests.get(f"{url}/storage/v1/object/{bucket}/{_obj(path)}",
                     headers=_headers(), timeout=TIMEOUT)
    return _check(r, "descargar").content


def signed_url(path: str, segundos: int = 300, bucket: str = BUCKET,
               descargar_como: str | None = None) -> str:
    """URL temporal para abrir el archivo en el navegador sin exponer la llave."""
    url, _ = _cfg()
    r = requests.post(
        f"{url}/storage/v1/object/sign/{bucket}/{_obj(path)}",
        headers=_headers({"Content-Type": "application/json"}),
        json={"expiresIn": int(segundos)}, timeout=TIMEOUT,
    )
    rel = _check(r, "firmar URL").json().get("signedURL") or r.json().get("signedUrl")
    if not rel:
        raise StorageError(f"Storage firmar URL: respuesta sin signedURL ({r.text[:200]})")
    full = f"{url}/storage/v1{rel}" if rel.startswith("/") else rel
    if descargar_como:
        full += ("&" if "?" in full else "?") + "download=" + quote(descargar_como)
    return full


def move(origen: str, destino: str, bucket: str = BUCKET) -> None:
    """Mueve (renombra) un objeto dentro del bucket."""
    url, _ = _cfg()
    r = requests.post(f"{url}/storage/v1/object/move",
                      headers=_headers({"Content-Type": "application/json"}),
                      json={"bucketId": bucket, "sourceKey": origen, "destinationKey": destino},
                      timeout=TIMEOUT)
    _check(r, "mover")


def project_ref() -> str:
    """'pelpz...' de https://pelpz....supabase.co (para armar enlaces al panel de Supabase)."""
    url, _ = _cfg()
    return url.split("//", 1)[-1].split(".", 1)[0]


def delete(paths: list[str], bucket: str = BUCKET) -> None:
    url, _ = _cfg()
    r = requests.delete(f"{url}/storage/v1/object/{bucket}",
                        headers=_headers({"Content-Type": "application/json"}),
                        json={"prefixes": list(paths)}, timeout=TIMEOUT)
    _check(r, "borrar")
