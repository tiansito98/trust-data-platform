"""Cambia de una vez la contrasena de todas las cuentas del dashboard.

Uso:
  1. Copia TODO el texto de los secrets de Streamlit Cloud
     (Manage app -> Settings -> Secrets) a  docs/private/secrets_actual.toml
  2. python scripts/rotar_claves.py
        (opcional: --solo sixt_pereira,sixt_bogota   o   --excluir trust_admin)
  3. Pega el contenido de docs/private/secrets_nuevo.toml en los secrets, guarda
     y haz Reboot app.
  4. Reparte las claves de docs/private/claves_nuevas.txt (una por persona,
     por canal privado) y BORRA los tres archivos.

Solo cambia la linea password_hash de cada bloque [users.<usuario>]; el resto
de los secrets (conexiones, roles, sedes, paginas) queda igual, caracter por
caracter. docs/private/ esta en el .gitignore: nada de esto se sube al repo.
"""
from __future__ import annotations

import argparse
import re
import secrets
import sys
import tomllib
from pathlib import Path

import bcrypt

ROOT = Path(__file__).resolve().parent.parent
PRIV = ROOT / "docs" / "private"

# Sin caracteres que se confunden al dictarlos o leerlos (0/O, 1/l/I).
_ALFABETO = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def clave_nueva() -> str:
    """12 caracteres aleatorios en 3 grupos: 'Xk7p-M2qa-9Rtz' (~70 bits)."""
    grupos = ["".join(secrets.choice(_ALFABETO) for _ in range(4)) for _ in range(3)]
    return "-".join(grupos)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entrada", default=str(PRIV / "secrets_actual.toml"))
    ap.add_argument("--salida", default=str(PRIV / "secrets_nuevo.toml"))
    ap.add_argument("--claves", default=str(PRIV / "claves_nuevas.txt"))
    ap.add_argument("--solo", default="", help="usuarios separados por coma (default: todos)")
    ap.add_argument("--excluir", default="", help="usuarios separados por coma a no tocar")
    a = ap.parse_args()

    entrada = Path(a.entrada)
    if not entrada.exists():
        sys.exit(f"No existe {entrada}. Pega ahi el texto completo de los secrets.")
    texto = entrada.read_text(encoding="utf-8")
    try:
        usuarios = tomllib.loads(texto).get("users", {})
    except tomllib.TOMLDecodeError as e:
        sys.exit(f"El archivo no es TOML valido ({e}). Copia los secrets completos otra vez.")
    if not usuarios:
        sys.exit("No encontre bloques [users.<usuario>] en el archivo.")

    solo = {u.strip().lower() for u in a.solo.split(",") if u.strip()}
    excluir = {u.strip().lower() for u in a.excluir.split(",") if u.strip()}
    faltan = (solo | excluir) - set(usuarios)
    if faltan:
        sys.exit(f"Estos usuarios no estan en los secrets: {', '.join(sorted(faltan))}")
    objetivo = [u for u in usuarios if (not solo or u in solo) and u not in excluir]

    # Recorre linea por linea: dentro de [users.X] reemplaza solo password_hash.
    sec_re = re.compile(r'^\s*\[\s*users\.("?)([^"\]]+)\1\s*\]\s*$')
    hash_re = re.compile(r'^(\s*password_hash\s*=\s*)(["\']).*?\2(\s*(#.*)?)$')
    nuevas: dict[str, str] = {}
    actual = None
    salida = []
    for linea in texto.splitlines(keepends=True):
        cuerpo = linea.rstrip("\r\n")
        fin = linea[len(cuerpo):]
        m = sec_re.match(cuerpo)
        if m:
            actual = m.group(2).strip()
        elif cuerpo.lstrip().startswith("["):
            actual = None
        else:
            h = hash_re.match(cuerpo)
            if h and actual in objetivo and actual not in nuevas:
                clave = clave_nueva()
                hashed = bcrypt.hashpw(clave.encode(), bcrypt.gensalt()).decode()
                nuevas[actual] = clave
                cuerpo = f'{h.group(1)}"{hashed}"{h.group(3) or ""}'
        salida.append(cuerpo + fin)

    sin_cambiar = [u for u in objetivo if u not in nuevas]
    if sin_cambiar:
        sys.exit("No encontre la linea password_hash de: " + ", ".join(sin_cambiar)
                 + ". No se escribio nada.")

    nuevo = "".join(salida)
    # Verificacion: el TOML nuevo parsea, cada clave entra con su hash y nada mas cambio.
    cfg = tomllib.loads(nuevo)
    for u, clave in nuevas.items():
        assert bcrypt.checkpw(clave.encode(), cfg["users"][u]["password_hash"].encode()), u
    viejo_sin = {u: {k: v for k, v in d.items() if k != "password_hash"} for u, d in usuarios.items()}
    nuevo_sin = {u: {k: v for k, v in d.items() if k != "password_hash"} for u, d in cfg["users"].items()}
    assert viejo_sin == nuevo_sin, "cambio algo distinto al hash"
    assert {k: v for k, v in cfg.items() if k != "users"} == \
           {k: v for k, v in tomllib.loads(texto).items() if k != "users"}, "cambio otro secret"

    Path(a.salida).write_text(nuevo, encoding="utf-8", newline="")
    ancho = max(len(u) for u in nuevas)
    lineas = [f"{u.ljust(ancho)}   {c}" for u, c in sorted(nuevas.items())]
    Path(a.claves).write_text("\n".join(lineas) + "\n", encoding="utf-8")

    print(f"Listo: {len(nuevas)} cuentas con clave nueva.")
    no_tocadas = sorted(set(usuarios) - set(nuevas))
    if no_tocadas:
        print("Sin cambio: " + ", ".join(no_tocadas))
    print(f"\n1. Pega en los secrets de Streamlit Cloud el contenido de:\n   {a.salida}")
    print("2. Guarda y haz Manage app -> Reboot app.")
    print(f"3. Reparte las claves de:\n   {a.claves}")
    print("4. Borra secrets_actual.toml, secrets_nuevo.toml y claves_nuevas.txt de docs/private/.")


if __name__ == "__main__":
    main()
