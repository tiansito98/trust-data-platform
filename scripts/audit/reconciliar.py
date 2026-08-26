# -*- coding: utf-8 -*-
"""
Auditoria de comisiones por adicionales - julio 2026.

Valida los reclamos de Jeimmy Fajardo (STEFFANY), Danilo Gutierrez, Natalia
Quintero y David Bonilla contra silver/bronze.

Regla de comision (segun 8_Cargos_Granular.py): 5% sobre el counter CON IVA,
equivalente a 5.95% del valor del cargo sin IVA, en COP a TRM Banrep del
dia de entrega.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
from claims_julio import CLAIMS, ASESORES, SISTEMA_OK, TOTALES_DECLARADOS

OUT = os.path.join(os.path.dirname(__file__), 'out')
TASA = 0.05 * 1.19          # 5% sobre valor con IVA = 5.95% sobre valor sin IVA
TOL_REL = 0.02              # 2% de tolerancia (redondeo TRM)

det = pd.read_csv(os.path.join(OUT, 'detail.csv'))
jul = pd.read_csv(os.path.join(OUT, 'julio.csv'))
trm = dict(pd.read_csv(os.path.join(OUT, 'trm.csv'))[['fecha', 'trm_cop_per_usd']].values)

# Correcciones de numero de contrato detectadas durante el analisis
REMAP = {
    (9523909872, 'LD'): 9523897935,   # LD 12.200 pertenece a 9523897935
}

cnt = det[det.fuente_cargo == 'RENTAL_COUNTER'].copy()
cnt['trm_ban'] = cnt.fecha_handover_real.map(trm)
cnt['cop_ban'] = cnt.subtotal_usd * cnt.trm_ban
jul['trm_ban'] = jul.fecha_handover_real.map(trm)
jul['cop_ban'] = jul.subtotal_usd * jul.trm_ban

pool = pd.concat([cnt, jul]).drop_duplicates(
    subset=['numero_contrato', 'cargo_codigo', 'cargo_inty', 'subtotal_usd'])

rows = []
for ases, cto, txt, codes, val in CLAIMS:
    cod_key = codes[0] if codes else None
    cto_real = REMAP.get((cto, cod_key), cto)
    yo = float(ASESORES[ases]['codigo'])
    r = dict(asesor=ases, contrato=cto, contrato_real=cto_real, adicional=txt,
             reclamado=val)
    if cto is None:
        r.update(veredicto='FUERA DE SISTEMA', nota='No es un contrato (bono Google)')
        rows.append(r); continue
    g = pool[pool.numero_contrato == cto_real]
    if g.empty:
        r.update(veredicto='CONTRATO INEXISTENTE',
                 nota='No existe en Redshift ni bronze')
        rows.append(r); continue

    r['entrego']  = g.operador_checkout_codigo.iloc[0]    # oprt_bed_checkout = ENTREGA
    r['recibio']  = g.operador_handover_codigo.iloc[0]    # oprt_bed          = DEVOLUCION
    r['acredita_sistema_hoy'] = r['recibio']
    m = g[g.cargo_codigo.isin(codes)]
    if m.empty:
        # buscar el cargo cuyo 5.95% se acerque al valor reclamado
        g2 = g[~g.cargo_codigo.isin(['T', 'Y'])].copy()
        g2['com'] = g2.cop_ban * TASA
        if not g2.empty:
            best = g2.iloc[(g2.com - val).abs().argmin()]
            if abs(best.com - val) / val < TOL_REL:
                m = g2[g2.cargo_codigo == best.cargo_codigo]
                r['codigo_real'] = best.cargo_codigo
    if m.empty:
        r.update(veredicto='CARGO NO EXISTE',
                 nota='codigos en contrato: ' + '/'.join(sorted(set(g.cargo_codigo))))
        rows.append(r); continue

    esperado = m.cop_ban.sum() * TASA
    r['valor_cargo_cop'] = round(m.cop_ban.sum())
    r['comision_esperada'] = round(esperado)
    r['dif'] = round(val - esperado)
    r['prepagado'] = m.prepagado_cargo_cop.sum() > 0
    if abs(val - esperado) / max(esperado, 1) <= TOL_REL:
        r['veredicto'] = 'OK' if r['entrego'] == yo else 'OK (monto) / OTRO ASESOR ENTREGO'
    else:
        r['veredicto'] = 'MONTO NO CUADRA'
    if r.get('codigo_real'):
        r['nota'] = f"reclamo dice {txt}, en sistema es {r['codigo_real']}"
    if cto_real != cto:
        r['nota'] = f"numero de contrato corregido: {cto} -> {cto_real}"
    rows.append(r)

rep = pd.DataFrame(rows)
rep.to_csv(os.path.join(OUT, 'veredictos.csv'), index=False, encoding='utf-8')

pd.set_option('display.width', 260); pd.set_option('display.max_columns', 40)
cols = ['contrato', 'contrato_real', 'adicional', 'reclamado', 'valor_cargo_cop',
        'comision_esperada', 'dif', 'entrego', 'acredita_sistema_hoy', 'veredicto', 'nota']
for a in ['STEFFANY', 'DANILO', 'NATALIA', 'DAVID']:
    sub = rep[rep.asesor == a]
    print('=' * 130)
    print(f"{a}  ({ASESORES[a]['nombre']}, codigo {ASESORES[a]['codigo']})   "
          f"total declarado: {TOTALES_DECLARADOS[a]:,}")
    print('=' * 130)
    print(sub[[c for c in cols if c in sub.columns]].to_string(index=False))
    ok = sub[sub.veredicto.astype(str).str.startswith('OK')]
    print(f"  -> lineas soportadas por el sistema: {len(ok)}/{len(sub)} | "
          f"comision soportada: {ok.comision_esperada.sum():,.0f} COP")
    print()
