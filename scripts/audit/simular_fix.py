# -*- coding: utf-8 -*-
"""Simula el estado de cada linea reclamada bajo 3 escenarios:
   A) hoy
   B) solo corrigiendo la inversion entrega/devolucion
   C) inversion + OT/FI comisionables
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
from claims_julio import CLAIMS, ASESORES

OUT = os.path.join(os.path.dirname(__file__), 'out')
TASA = 0.05 * 1.19
COMISIONABLES = ["AD", "BF", "LD", "BS", "UP", "CS", "BC", "PF", "SL"]
EXTRA = ["OT", "FI"]
REMAP = {(9523909872, 'LD'): 9523897935}

det = pd.read_csv(os.path.join(OUT, 'detail.csv'))
jul = pd.read_csv(os.path.join(OUT, 'julio.csv'))
trm = dict(pd.read_csv(os.path.join(OUT, 'trm.csv'))[['fecha', 'trm_cop_per_usd']].values)
for d in (det, jul):
    d['cop_ban'] = d.subtotal_usd * d.fecha_handover_real.map(trm)
pool = pd.concat([det[det.fuente_cargo == 'RENTAL_COUNTER'], jul]).drop_duplicates(
    subset=['numero_contrato', 'cargo_codigo', 'cargo_inty', 'subtotal_usd'])

rows = []
for ases, cto, txt, codes, val in CLAIMS:
    yo = float(ASESORES[ases]['codigo'])
    r = dict(asesor=ases, contrato=cto, adicional=txt, reclamado=val)
    if cto is None:
        r.update(estado='fuera del sistema (bono Google)', A=0, B=0, C=0); rows.append(r); continue
    cto_r = REMAP.get((cto, codes[0] if codes else None), cto)
    g = pool[pool.numero_contrato == cto_r]
    if g.empty:
        r.update(estado='contrato inexistente', A=0, B=0, C=0); rows.append(r); continue

    m = g[g.cargo_codigo.isin(codes)]
    if m.empty:   # buscar por monto (etiquetas mal puestas: UP->FI, UP->OT)
        g2 = g[~g.cargo_codigo.isin(['T', 'Y'])].copy()
        g2['com'] = g2.cop_ban * TASA
        if not g2.empty:
            b = g2.iloc[(g2.com - val).abs().argmin()]
            if abs(b.com - val) / val < 0.02:
                m = g2[g2.cargo_codigo == b.cargo_codigo]
    if m.empty:
        r.update(estado='cargo no existe en el contrato', A=0, B=0, C=0); rows.append(r); continue

    entrego = g.operador_checkout_codigo.iloc[0]
    recibe  = g.operador_handover_codigo.iloc[0]
    pure    = m.prepagado_cargo_cop.fillna(0).sum() == 0
    cods    = set(m.cargo_codigo)
    en_lista     = cods.issubset(set(COMISIONABLES))
    en_lista_ext = cods.issubset(set(COMISIONABLES + EXTRA))
    com = m.cop_ban.sum() * TASA
    cuadra = abs(val - com) / max(com, 1) <= 0.02

    def pago(atrib_ok, lista_ok):
        return round(com) if (atrib_ok and lista_ok and pure) else 0
    r['A'] = pago(recibe == yo, en_lista)
    r['B'] = pago(entrego == yo, en_lista)
    r['C'] = pago(entrego == yo, en_lista_ext)

    motivos = []
    if entrego != yo:   motivos.append('la entrego otro asesor')
    if not cuadra:      motivos.append('monto reclamado no cuadra')
    if not pure:        motivos.append('cargo MIXTO (parte prepagada)')
    if not en_lista_ext: motivos.append('codigo fuera de comisionables')
    elif not en_lista:  motivos.append('codigo OT/FI: solo paga en escenario C')
    r['estado'] = ' + '.join(motivos) if motivos else 'queda resuelto con el swap'
    r['codigos'] = '/'.join(sorted(cods))
    rows.append(r)

df = pd.DataFrame(rows)
df.to_csv(os.path.join(OUT, 'simulacion.csv'), index=False, encoding='utf-8')
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 46)

print('LINEAS RECLAMADAS QUE **NO** QUEDAN RESUELTAS CON SOLO EL SWAP')
print('=' * 118)
pend = df[df.estado != 'queda resuelto con el swap']
print(pend[['asesor', 'contrato', 'adicional', 'reclamado', 'B', 'C', 'estado']].to_string(index=False))
print()
print('RESUMEN POR ASESOR (COP)')
print('=' * 118)
s = df.groupby('asesor').agg(lineas=('reclamado', 'size'), reclamado=('reclamado', 'sum'),
                             hoy=('A', 'sum'), solo_swap=('B', 'sum'), swap_mas_otfi=('C', 'sum'))
s['resueltas_swap'] = df[df.estado == 'queda resuelto con el swap'].groupby('asesor').size()
s = s.reindex(['STEFFANY', 'DANILO', 'NATALIA', 'DAVID'])
print(s.fillna(0).astype(int).to_string())
print()
print(f"TOTAL reclamado: {df.reclamado.sum():,} | hoy: {df.A.sum():,} | "
      f"solo swap: {df.B.sum():,} | swap+OT/FI: {df.C.sum():,}")
