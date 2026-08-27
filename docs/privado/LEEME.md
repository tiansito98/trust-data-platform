# docs/privado — no se sube a GitHub

**El repo es publico.** Todo lo que pongas en esta carpeta se queda en tu maquina:
`.gitignore` ignora el contenido completo y solo versiona este archivo, para que la
carpeta exista al clonar y la regla quede a la vista.

## Que va aqui

- Datos de personas identificadas: nombres de empleados, comisiones o sueldos,
  evaluaciones, cualquier cosa de RRHH.
- Exports con cifras internas que no queremos publicas (ingresos por sede,
  reconciliaciones con COBRA, metas comerciales).
- Documentos de Sixt cubiertos por el acuerdo del datashare.
- Datos de clientes: nombres, documentos, medios de pago.

## Que NO va aqui

Documentacion tecnica normal — arquitectura, diccionarios de datos, runbooks,
estilo de codigo. Eso vive en `docs/` y se versiona como siempre.

## Como usarla

Guarda el archivo aqui y listo, no hay que hacer nada mas. Para comprobar que git
lo esta ignorando:

```powershell
git check-ignore -v docs/privado/tu_archivo.xlsx
```

Si imprime la regla que lo bloquea, esta bien. Si no imprime nada, git lo va a
subir: revisa el `.gitignore` antes de commitear.

## Antecedente

El 26-ago-2026 se subieron a `main` dos Excel de la auditoria de comisiones con
nombres de asesores y su compensacion individual. Estuvieron publicos ~19 horas.
Se retiraron el 27-ago, pero siguen en el historial de git: sacar un archivo del
arbol no lo borra de los commits anteriores. De ahi esta carpeta.

**Si algo sensible llega a subirse, avisar de inmediato:** limpiarlo de verdad
exige reescribir el historial (`git filter-repo`) y forzar el push, y eso hay que
coordinarlo con el runner de DigitalOcean, que pushea a diario.
