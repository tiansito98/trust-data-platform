# -*- coding: utf-8 -*-
"""
Genera docs/auditoria_comisiones_julio_REVISADO.xlsx

Toma el Excel original de los asesores (asesor / # contrato / adicional / valor /
sistema) y le agrega la revision: si el adicional se vendio realmente en el
counter, a quien le corresponde y cuanto seria la comision una vez corregidos
los errores del sistema.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd

OUT = os.path.join(os.path.dirname(__file__), 'out')

TASA = 0.05 * 1.19          # 5% sobre el cargo con IVA
COMISIONABLES = {"AD", "BF", "LD", "BS", "UP", "CS", "BC", "PF", "SL"}
OTFI = {"OT", "FI"}

ra  = pd.read_csv(os.path.join(OUT, 'x_ra.csv'))
ctx = pd.read_csv(os.path.join(OUT, 'x_ctx.csv')).set_index('contrato')
_as = pd.read_csv(os.path.join(OUT, 'x_ases.csv'))
NOM = {int(r.codigo_silver): (str(r.nombres) + " " + str(r.apellidos)) for r in _as.itertuples()}

ASESOR_COD = {"STEFFANY": 7793224, "DANILO": 7791677,
              "NATALIA": 7792174, "DAVID": 7795534}

def nm(c):
    if c is None or pd.isna(c):
        return "-"
    return NOM.get(int(c), str(int(c)))

# --- filas EXACTAS del Excel original ---
ORIG = [
    ("STEFFANY", 9523774314, "BF",           8954),
    ("STEFFANY", 9523781208, "LD X 28 DIAS", 123845),
    ("STEFFANY", 9523898459, "BF X 26 DIAS", 121860),
    ("STEFFANY", 9523845472, "SL",           4130),
    ("STEFFANY", 9523910889, "LD",           4852),
    ("STEFFANY", 9523923550, "SILLA BEBE",   9583),
    ("STEFFANY", 9523929866, "SL",           2717),
    ("STEFFANY", None,       "GOOGLE / X",   100000),
    ("DANILO",   9524024893, "BF",           8023),
    ("DANILO",   9523986328, "BF AD",        61727),
    ("DANILO",   9523875927, "BF",           12183),
    ("DANILO",   9523877379, "UP",           3515),
    ("DANILO",   9523826906, "BF",           21019),
    ("DANILO",   9523826011, "UP",           3969),
    ("DANILO",   9523771679, "OT AD",        9029),
    ("NATALIA",  9523826011, "OT",           3969),
    ("NATALIA",  9523849946, "BF",           59512),
    ("NATALIA",  9523854552, "AD",           4870),
    ("NATALIA",  9523853782, "SL",           2706),
    ("NATALIA",  9523886016, "BF",           28429),
    ("NATALIA",  9523895564, "BF",           11709),
    ("NATALIA",  9523963080, "SL",           13588),
    ("NATALIA",  9523985817, "OT",           5342),
    ("NATALIA",  9523986588, "SL",           4006),
    ("NATALIA",  9524046682, "SL",           1335),
    ("DAVID",    9523813233, "AD OT",        14430),
    ("DAVID",    9524049080, "SL BC",        2280),
    ("DAVID",    9523848159, "SL BC",        9500),
    ("DAVID",    9523909872, "LD",           12200),
    ("DAVID",    9523909872, "OT",           3900),
    ("DAVID",    9523962548, "BF OT",        13664),
]

CODIGOS = {
    "BF": ["BF"], "LD X 28 DIAS": ["LD"], "BF X 26 DIAS": ["BF"], "SL": ["SL"],
    "LD": ["LD"], "SILLA BEBE": ["CS"], "BF AD": ["BF", "AD"], "OT AD": ["OT", "AD"],
    "OT": ["OT"], "AD": ["AD"], "AD OT": ["AD", "OT"], "SL BC": ["SL", "BC"],
    "BF OT": ["BF", "OT"], "GOOGLE / X": [],
}
UP_REAL = {9523877379: ["FI"], 9523826011: ["OT"]}   # "UP" mal etiquetado
REMAP   = {(9523909872, "LD"): 9523897935}           # numero de contrato equivocado

COLS = ["ASESOR", "# CONTRATO", "ADICIONAL", "VALOR",
        "CONTRATO VERIFICADO", "CODIGO EN SISTEMA", "DIAS", "VALOR CARGO USD",
        "SE VENDIO EN COUNTER", "VALOR COUNTER COP", "COMISION QUE CORRESPONDE",
        "DIFERENCIA", "QUIEN ENTREGO", "LE PAGA HOY EL SISTEMA",
        "LE CORRESPONDE", "RESULTADO", "QUE PASO"]


def build():
    filas = []
    for ases, cto, adic, val in ORIG:
        cod_ases = ASESOR_COD[ases]
        f = {c: "-" for c in COLS}
        f.update({"ASESOR": ases, "# CONTRATO": cto if cto else "GOOGLE",
                  "ADICIONAL": adic, "VALOR": val})
        codes = UP_REAL.get(cto) if adic == "UP" else CODIGOS.get(adic, [])
        cto_r = REMAP.get((cto, adic), cto)

        if cto is None:
            f.update({"RESULTADO": "FUERA DEL SISTEMA", "LE CORRESPONDE": "-",
                      "QUE PASO": "El bono de resenas de Google no es un cargo de Sixt: "
                                  "no aparece en el sistema y hay que liquidarlo aparte."})
            filas.append(f); continue

        if cto_r not in ctx.index:
            f.update({"CONTRATO VERIFICADO": "NO EXISTE",
                      "COMISION QUE CORRESPONDE": 0, "DIFERENCIA": -val,
                      "LE CORRESPONDE": "NO", "RESULTADO": "CONTRATO NO EXISTE",
                      "QUE PASO": "Este numero de contrato no existe en Sixt. El mas "
                                  "parecido es 9523788459 (BF de 28 dias, entregado por "
                                  "Steffany), cuya comision seria 84.062. Falta que la "
                                  "asesora confirme el numero real."})
            filas.append(f); continue

        c = ctx.loc[cto_r]
        g = ra[(ra.contrato == cto_r) & (ra.codigo.isin(codes))]
        if g.empty:
            f.update({"CONTRATO VERIFICADO": cto_r, "CODIGO EN SISTEMA": "NO EXISTE",
                      "COMISION QUE CORRESPONDE": 0, "DIFERENCIA": -val,
                      "QUIEN ENTREGO": nm(c.entrego),
                      "LE PAGA HOY EL SISTEMA": nm(c.acredita_hoy),
                      "LE CORRESPONDE": "NO", "RESULTADO": "EL CARGO NO EXISTE",
                      "QUE PASO": "El contrato existe pero no tiene ese cargo."})
            filas.append(f); continue

        usd    = g.usd.sum()
        en_rsv = g.usd_en_reserva.sum()
        walkin = int(c.reserva) == 0
        counter_usd = max(usd - en_rsv, 0)
        if walkin:
            vendido = "SI - walk-in (cliente llego sin reserva)"
        elif en_rsv <= 0:
            vendido = "SI - no venia en la reserva"
        elif counter_usd <= 0.01:
            vendido = "NO - venia incluido en la reserva"
        else:
            vendido = "PARCIAL - " + format(en_rsv, ",.0f") + " USD venian de la reserva"

        counter_cop = counter_usd * c.trm
        cods = sorted(set(g.codigo))
        es_otfi = bool(set(cods) & OTFI)
        comisiona = set(cods).issubset(COMISIONABLES)
        suyo = int(c.entrego) == cod_ases
        comision = counter_cop * TASA if (suyo and counter_usd > 0) else 0

        notas = []
        if cto_r != cto:
            notas.append("El numero correcto del contrato es " + str(cto_r) + ", no " +
                         str(cto) + ". El cargo y el valor si son correctos.")
        if adic == "UP":
            notas.append("Lo anoto como 'UP' pero en el sistema el codigo es " +
                         "/".join(cods) + ".")
        if counter_usd <= 0.01:
            notas.append("Este adicional venia incluido en la reserva del cliente: no se "
                         "vendio en el counter, por lo tanto no genera comision de counter.")
        if not suyo:
            notas.append("Segun Sixt, quien entrego el vehiculo fue " + nm(c.entrego) + ".")
        elif int(c.acredita_hoy) != cod_ases:
            notas.append("Lo vendio el asesor, pero hoy el sistema le paga la comision a " +
                         nm(c.acredita_hoy) + ", que fue quien recibio el carro en la "
                         "devolucion. Al corregir el error, la comision vuelve a quien entrego.")
        else:
            notas.append("Lo vendio el asesor y el sistema ya se lo reconoce correctamente.")
        if suyo and counter_usd > 0 and abs(val - comision) / max(comision, 1) > 0.02:
            if val < comision:
                notas.append("Reclamo " + format(val, ",.0f") + " pero le corresponden " +
                             format(comision, ",.0f") + ": liquido menos dias de los que "
                             "tiene el contrato. La diferencia esta a favor del asesor.")
            else:
                notas.append("Reclamo " + format(val, ",.0f") + " pero el sistema solo "
                             "respalda " + format(comision, ",.0f") + ". Falta aclarar con "
                             "el asesor como calculo ese valor.")
        if es_otfi and not comisiona:
            notas.append("OJO: los codigos OT y FI hoy no estan en la lista de "
                         "comisionables. Falta definir si comisionan o no.")

        if counter_usd <= 0.01:
            res = "NO ES COUNTER"
        elif not suyo:
            res = "NO LE CORRESPONDE"
        elif es_otfi and not comisiona:
            res = "SUYO - FALTA DEFINIR OT/FI"
        elif abs(val - comision) / max(comision, 1) > 0.02:
            res = "SUYO - REVISAR MONTO"
        else:
            res = "CORRECTO"

        f.update({
            "CONTRATO VERIFICADO": cto_r,
            "CODIGO EN SISTEMA": "/".join(cods),
            "DIAS": int(g.unidades.sum()),
            "VALOR CARGO USD": round(usd, 2),
            "SE VENDIO EN COUNTER": vendido,
            "VALOR COUNTER COP": round(counter_cop),
            "COMISION QUE CORRESPONDE": round(comision),
            "DIFERENCIA": round(comision - val),
            "QUIEN ENTREGO": nm(c.entrego),
            "LE PAGA HOY EL SISTEMA": nm(c.acredita_hoy),
            "LE CORRESPONDE": "SI" if (suyo and counter_usd > 0) else "NO",
            "RESULTADO": res,
            "QUE PASO": " ".join(notas),
        })
        filas.append(f)
    return pd.DataFrame(filas)[COLS]


if __name__ == "__main__":
    rev = build()
    rev.to_csv(os.path.join(OUT, 'revision_final.csv'), index=False, encoding='utf-8')
    pd.set_option('display.width', 220)
    print(rev[["ASESOR", "# CONTRATO", "ADICIONAL", "VALOR",
               "COMISION QUE CORRESPONDE", "DIFERENCIA", "RESULTADO"]].to_string(index=False))
    print()
    print(rev.RESULTADO.value_counts().to_string())
