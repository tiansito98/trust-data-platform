# Setup — Paso a Paso

> Guía completa para tener el proyecto corriendo desde cero.

---

## Pre-requisitos

- **Windows 10/11** con PowerShell.
- **Python 3.10 o superior** ([python.org](https://www.python.org/downloads/) → marcar "Add Python to PATH").
- **Acceso al Redshift Data Exchange de Sixt** ya configurado:
  - SSH private key en `C:\Users\Sebastian\.ssh\sixt_redshift.pem`.
  - User + password Redshift de Sven.
  - Tu IP whitelisted del lado de Sixt.

---

## 1. Verificar Python

```powershell
python --version
# Debe mostrar Python 3.10.x o superior
```

Si dice "command not found", reinstalá Python marcando "Add to PATH".

---

## 2. Instalar dependencias

```powershell
cd C:\Users\Sebastian\Desktop\trust_data_platform
.\scripts\setup.bat
```

O manualmente:

```powershell
pip install -r requirements.txt
pip install "paramiko<4.0" --upgrade  # IMPORTANTE: paramiko 4.0 tiene bug con sshtunnel
```

---

## 3. Configurar credenciales

```powershell
copy .env.example .env
notepad .env
```

Llenar todos los campos. Los datos correctos a fecha 2026-04-30:

```env
SIXT_SSH_HOST=bastion_redshift.datashop.sixt.com
SIXT_SSH_PORT=22
SIXT_SSH_USER=redshift-user
SIXT_SSH_KEY_PATH=C:/Users/Sebastian/.ssh/sixt_redshift.pem
SIXT_SSH_KEY_PASSPHRASE=

SIXT_REDSHIFT_HOST=sds-prod-redshift-consumption-cluster.ctictghdoqz4.eu-west-1.redshift.amazonaws.com
SIXT_REDSHIFT_PORT=5439
SIXT_REDSHIFT_DB=prod_database
SIXT_REDSHIFT_USER=franchise_co_409_user
SIXT_REDSHIFT_PASSWORD=<TU_PASSWORD>

TRUST_MNDT_CODE=409
TRUST_OPRT_EMAIL=co1025@franchise.sixt.com

LOCAL_PORT=8990
```

---

## 4. Verificar la SSH key tiene permisos correctos

```powershell
icacls "$env:USERPROFILE\.ssh\sixt_redshift.pem"
```

Debe mostrar **solo** tu usuario con `(R)`. Si ves `BUILTIN\Users` o similar, corregir:

```powershell
icacls "$env:USERPROFILE\.ssh\sixt_redshift.pem" --% /inheritance:r
icacls "$env:USERPROFILE\.ssh\sixt_redshift.pem" --% /grant:r "%USERNAME%:R"
```

---

## 5. Test de conexión

```powershell
python -m pipelines.bronze.inspect --test-connection
```

Debe mostrar:
```
[1] OK tunnel abierto en localhost:8990
[2] OK Redshift conectado
[3] user=franchise_co_409_user db=prod_database
    Tablas accesibles: 20
```

Si falla, ver `docs/runbooks.md` sección "Connection issues".

---

## 6. Full load inicial

```powershell
python -m pipelines.bronze.full_load
```

**Tiempo esperado:** 30 minutos a 2 horas dependiendo de volumen.

**Output esperado:** archivo `data/bronze.db` de ~50-200 MB.

**Logs:** `logs/full_load_<timestamp>.log`.

Verificar después:

```powershell
python -m pipelines.bronze.inspect
```

Debe listar todas las tablas con sus conteos de filas.

---

## 7. Construir Silver

```powershell
python -m pipelines.silver.build
```

**Tiempo esperado:** 1-5 minutos.

**Output:** `data/silver.db` con DIM/FACT/OP poblados.

---

## 8. Construir Gold (cuando esté implementado)

```powershell
python -m pipelines.gold.build
```

---

## 9. Lanzar dashboard

```powershell
.\scripts\dashboard.bat
```

O manualmente:

```powershell
streamlit run dashboard\app.py
```

Se abre solo en `http://localhost:8501`.

---

## 10. Programar refresh automático (Windows Task Scheduler)

1. Abrir **Task Scheduler** (Programador de tareas).
2. **Create Basic Task** → nombre: `Trust Redshift Refresh`.
3. **Trigger:** Daily, repeat every 6 hours.
4. **Action:** Start a program.
   - Program: `C:\Users\Sebastian\Desktop\trust_data_platform\scripts\refresh.bat`
   - Start in: `C:\Users\Sebastian\Desktop\trust_data_platform\`
5. Save.

El script `refresh.bat` corre incremental Bronze + Silver build automáticamente.

---

## Troubleshooting frecuente

| Síntoma | Causa | Solución |
|---|---|---|
| `ImportError: paramiko has no attribute DSSKey` | Paramiko 4.0 incompatible | `pip install "paramiko<4.0" --upgrade` |
| `WARNING: UNPROTECTED PRIVATE KEY` | Permisos de la key abiertos | Comando `icacls` del paso 4 |
| `Connection refused` al test | Tu IP rotó | Verificar `Invoke-RestMethod -Uri "https://api.ipify.org"` y avisar a Florian si cambió |
| `password authentication failed` | Password mal copiada | Re-copiar de las credenciales y re-popular `.env` |
| `database "prod_database" does not exist` | DB equivocada | Confirmar valor en `.env` |
| Streamlit dice "address already in use" | Puerto 8501 ocupado | `streamlit run dashboard\app.py --server.port 8502` |

---

## Verificación final

Después del setup completo, deberías tener:

```
trust_data_platform/
├── .env                       ← creado por vos, lleno
├── data/
│   ├── bronze.db              ← ~50-200 MB
│   ├── silver.db              ← ~30-100 MB
│   └── gold.db                ← ~5-30 MB
└── logs/
    └── full_load_*.log        ← logs del primer load
```

Y `streamlit run dashboard\app.py` debería mostrar reportes con data real.

---

## Próximos pasos

Una vez todo funcione:
1. Validar la data en cada capa (`pipelines/bronze/inspect.py` + queries en DBeaver).
2. Ajustar watermarks reales en `config/watermarks.yml` después de explorar.
3. Llenar tablas Tramo 2 (`op_*`) con data operativa real cuando Trust empiece a usar formularios.
4. Iterar el dashboard según feedback del gerente.
