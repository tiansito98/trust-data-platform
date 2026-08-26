# -*- coding: utf-8 -*-
"""Tabla final: por cargo reclamado, es counter? es suyo? que dice el sistema?"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
from pertenencia import LINEAS, TASA, OUT
from claims_julio import ASESORES

NOM = {int(v['codigo']): v['nombre'] for v in ASESORES.values()}
NOM.update({7784272: 'Valeria Quintero', 7785764: 'Daniel Tabares',
            7787702: 'Eliana Cuervo', 7797448: 'Samantha Castillo',
            7798120: 'Juan D. Osorio', 7790373: 'Javier Rondon'})
def nm(c):
    if pd.isna(c): return '-'
    c = int(c)
    return NOM.get(c, str(c))

ra  = pd.read_csv(os.path.join(OUT, 'ra_dedup.csv'))
ctx = pd.read_csv(os.path.join(OUT, 'ctx.csv')).set_index('contrato')

rows = []
for ases, escrito, real, cod, val in LINEAS:
    yo = int(ASESORES[ases]['codigo'])
    r = dict(asesor=ases, contrato=escrito, cargo=cod, reclamado=val)
    if real is None:
        r.update(es_counter='-', entrego='-', acredita_hoy='-',
                 valor_sistema=None, veredicto='CONTRATO NO EXISTE')
        rows.append(r); continue

    c = ctx.loc[real]
    g = ra[(ra.contrato == real) & (ra.codigo == cod)]
    if g.empty:
        r.update(es_counter='-', entrego=nm(c.entrego), acredita_hoy=nm(c.acredita_hoy),
                 valor_sistema=None, veredicto='CARGO NO EXISTE EN EL CONTRATO')
        rows.append(r); continue

    usd    = g.valor_usd.sum()
    en_rsv = g.valor_en_reserva_usd.fillna(0).sum()
    walkin = int(c.reserva) == 0
    if walkin:
        counter = 'Si (walk-in)'
    elif en_rsv <= 0:
        counter = 'Si'
    elif abs(en_rsv - usd) < 0.01:
        counter = 'NO - venia en la reserva'
    else:
        counter = f'Parcial (reserva {en_rsv:.0f} de {usd:.0f} USD)'

    vendido_counter_usd = usd - max(en_rsv, 0)
    r['es_counter']    = counter
    r['entrego']       = nm(c.entrego)
    r['acredita_hoy']  = nm(c.acredita_hoy)
    r['unidades']      = int(g.unidades.sum())
    r['valor_usd']     = round(usd, 2)
    r['valor_sistema'] = round(vendido_counter_usd * c.trm * TASA)

    suyo = int(c.entrego) == yo
    if not counter.startswith('Si') and vendido_counter_usd <= 0:
        r['veredicto'] = 'NO ES COUNTER - lo trajo la reserva'
    elif not suyo:
        r['veredicto'] = f'NO ES SUYO - lo entrego {nm(c.entrego)}'
    elif val is not None and abs(val - r['valor_sistema']) / max(r['valor_sistema'], 1) > 0.02:
        r['veredicto'] = 'SUYO, pero el monto no cuadra'
    else:
        r['veredicto'] = 'SUYO Y ES COUNTER'
    rows.append(r)

df = pd.DataFrame(rows)
df.to_csv(os.path.join(OUT, 'tabla_pertenencia.csv'), index=False, encoding='utf-8')
pd.set_option('display.width', 260); pd.set_option('display.max_colwidth', 34)
cols = ['contrato', 'cargo', 'unidades', 'valor_usd', 'es_counter', 'reclamado',
        'valor_sistema', 'entrego', 'acredita_hoy', 'veredicto']
for a in ['STEFFANY', 'DANILO', 'NATALIA', 'DAVID']:
    print('=' * 150); print(a); print('=' * 150)
    print(df[df.asesor == a][cols].to_string(index=False))
    print()
print('VEREDICTOS:'); print(df.veredicto.value_counts().to_string())
