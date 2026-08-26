# -*- coding: utf-8 -*-
"""Reclamos de los asesores (Excel docs/auditoria_comisiones_por_adicionales_julio.xlsx)."""

ASESORES = {
    "STEFFANY": {"codigo": "7793224", "nombre": "Jeimmy Fajardo"},
    "DANILO":   {"codigo": "7791677", "nombre": "Danilo Gutierrez"},
    "NATALIA":  {"codigo": "7792174", "nombre": "Natalia Quintero"},
    "DAVID":    {"codigo": "7795534", "nombre": "David Bonilla"},
}

# (asesor, contrato, texto_adicional, codigos_normalizados, valor_cop)
CLAIMS = [
    ("STEFFANY", 9523774314, "BF",            ["BF"],       8954),
    ("STEFFANY", 9523781208, "LD X 28 DIAS",  ["LD"],     123845),
    ("STEFFANY", 9523898459, "BF X 26 DIAS",  ["BF"],     121860),
    ("STEFFANY", 9523845472, "SL",            ["SL"],       4130),
    ("STEFFANY", 9523910889, "LD",            ["LD"],       4852),
    ("STEFFANY", 9523923550, "SILLA BEBE",    ["BS","CS"],  9583),
    ("STEFFANY", 9523929866, "SL",            ["SL"],       2717),
    ("STEFFANY", None,       "GOOGLE / X",    [],         100000),

    ("DANILO",   9524024893, "BF",            ["BF"],       8023),
    ("DANILO",   9523986328, "BF AD",         ["BF","AD"], 61727),
    ("DANILO",   9523875927, "BF",            ["BF"],      12183),
    ("DANILO",   9523877379, "UP",            ["UP"],       3515),
    ("DANILO",   9523826906, "BF",            ["BF"],      21019),
    ("DANILO",   9523826011, "UP",            ["UP"],       3969),
    ("DANILO",   9523771679, "OT AD",         ["OT","AD"],  9029),

    ("NATALIA",  9523826011, "OT",            ["OT"],       3969),
    ("NATALIA",  9523849946, "BF",            ["BF"],      59512),
    ("NATALIA",  9523854552, "AD",            ["AD"],       4870),
    ("NATALIA",  9523853782, "SL",            ["SL"],       2706),
    ("NATALIA",  9523886016, "BF",            ["BF"],      28429),
    ("NATALIA",  9523895564, "BF",            ["BF"],      11709),
    ("NATALIA",  9523963080, "SL",            ["SL"],      13588),
    ("NATALIA",  9523985817, "OT",            ["OT"],       5342),
    ("NATALIA",  9523986588, "SL",            ["SL"],       4006),
    ("NATALIA",  9524046682, "SL",            ["SL"],       1335),

    ("DAVID",    9523813233, "AD OT",         ["AD","OT"], 14430),
    ("DAVID",    9524049080, "SL BC",         ["SL","BC"],  2280),
    ("DAVID",    9523848159, "SL BC",         ["SL","BC"],  9500),
    ("DAVID",    9523909872, "LD",            ["LD"],      12200),
    ("DAVID",    9523909872, "OT",            ["OT"],       3900),
    ("DAVID",    9523962548, "BF OT",         ["BF","OT"], 13664),
]

# Columna "SISTEMA": contratos que, segun el asesor, el sistema si le capturo bien.
SISTEMA_OK = {
    "STEFFANY": [9523771679, 9523826906, 9523848159, 9523895564,
                 9523897935, 9523962548, 9523963080],
    "DANILO":   [9523774314, 9523854552, 9523875927, 9524024893],
    "NATALIA":  [9523813233, 9523845472, 9523853782, 9523888501,
                 9524049080, 9524060490],
    "DAVID":    [],
}

TOTALES_DECLARADOS = {"STEFFANY": 375941, "DANILO": 119469,
                      "NATALIA": 135466, "DAVID": 55974}

def todos_los_contratos():
    s = {c for _, c, _, _, _ in CLAIMS if c}
    for v in SISTEMA_OK.values():
        s.update(v)
    return sorted(s)
