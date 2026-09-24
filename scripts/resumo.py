#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resumo da execucao exibido na aba Actions do GitHub."""
import json, os, sys

ARQ = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "dados", "status", "index.json")
LUZ = {"green": "Verde — ofertas atualizadas pela FONTE_SITE",
       "yellow": "Amarelo — ofertas confirmadas / mantidas",
       "red": "Vermelho — validacao manual necessaria"}

print("### Coleta de ofertas via FONTE_SITE\n")
try:
    s = json.load(open(ARQ, encoding="utf-8"))
except Exception as e:
    print("Nenhum arquivo de status gerado (%s)." % e)
    sys.exit(0)

c = s.get("counts", {})
print("| Indicador | Valor |")
print("|---|---|")
print("| Semaforo | %s |" % LUZ.get(s.get("overall"), "-"))
print("| Atualizadas (verde) | %d |" % c.get("green", 0))
print("| Mantidas (amarelo) | %d |" % c.get("yellow", 0))
print("| A validar (vermelho) | %d |" % c.get("red", 0))
print("| Alertas | %d |" % s.get("alertCount", 0))
print("| Cobertura | %s |" % s.get("coverage", "-"))
print("| Referencia | %s |" % s.get("updated", "-"))
alertas = s.get("alerts", [])
if alertas:
    print("\n**Fontes que exigem validacao manual**\n")
    for a in alertas[:15]:
        print("- %s" % a.get("msg", ""))
