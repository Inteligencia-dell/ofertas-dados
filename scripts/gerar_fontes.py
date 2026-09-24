#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador de fontes.json a partir da aba COMPARATIVO_OFERTAS
================================================================================
Le a coluna FONTE_SITE (campo `src`) e produz o cadastro oficial de fontes
que a automacao usa em todas as atualizacoes via web.

Cada entrada contem:
  op      - OPERADORA
  url     - FONTE_SITE (fonte oficial, exatamente como cadastrada)
  isp     - nome do provedor local, quando aplicavel
  cidades - lista de { ib (CODIGO_IBGE), c (CIDADE), uf, terr, baseline }

O baseline permite identificar MUDANCA: uma oferta so fica verde quando o
valor extraido da FONTE_SITE difere do registro vigente.
"""
import io, json, re, sys
from collections import OrderedDict

ENTRADA = "/mnt/user-data/uploads/Estratégia Comercial & Go to Market _ V.18.09.html"
SAIDA = "/home/claude/pub/fontes.json"


def carregar_seed(caminho):
    html = io.open(caminho, encoding="utf-8").read()
    m = re.search(r"const SEED=(\{.*?\});\s*</script>", html, re.S)
    if not m:
        raise SystemExit("SEED nao localizado no HTML.")
    return json.loads(m.group(1))


def nome_isp(oferta):
    if oferta.get("op") != "ISP LOCAL":
        return None
    nome = str(oferta.get("name") or "")
    if " - " in nome:
        return nome.split(" - ")[0].strip()
    return nome.split("-")[0].strip() or None


def main():
    seed = carregar_seed(ENTRADA)
    ofertas = seed["offers"]
    cidades = {c["ib"]: c for c in seed["cities"]}

    grupos, sem_fonte = OrderedDict(), []

    for o in ofertas:
        url = o.get("src")
        if not url:
            sem_fonte.append({
                "op": o.get("op"), "c": o.get("c"), "ib": o.get("ib"),
                "name": o.get("name"),
                "motivo": "FONTE_SITE ausente na COMPARATIVO_OFERTAS",
            })
            continue

        chave = (o["op"], url)
        g = grupos.setdefault(chave, {
            "op": o["op"], "url": url, "isp": nome_isp(o), "cidades": [],
        })
        if g["isp"] is None:
            g["isp"] = nome_isp(o)

        ref = cidades.get(o["ib"], {})
        g["cidades"].append({
            "ib": str(o["ib"]), "c": o["c"],
            "uf": ref.get("uf", "SP"), "terr": o.get("terr"),
            "baseline": {
                "nome": o.get("name"),
                "velocidade_mb": o.get("speed") or None,
                "franquia_movel_gb": o.get("gb") or None,
                "preco_mensal": o.get("price") or None,
                "preco_promocional": o.get("promo") or None,
                "meses_promocao": o.get("promoM") or None,
                "beneficios": o.get("benefits") or None,
                "tecnologia": o.get("tec") or None,
                "tipo": o.get("tipo") or None,
            },
        })

    fontes = sorted(grupos.values(),
                    key=lambda g: (0 if g["op"] != "ISP LOCAL" else 1,
                                   -len(g["cidades"]), g["op"]))
    for g in fontes:
        g["cidades"].sort(key=lambda x: x["c"])

    payload = OrderedDict()
    payload["observacao"] = (
        "Cadastro gerado da coluna FONTE_SITE da aba COMPARATIVO_OFERTAS. "
        "Fontes oficiais para toda atualizacao automatica via web. "
        "O coletor so altera um registro quando a fonte comprova mudanca.")
    payload["origem"] = "COMPARATIVO_OFERTAS (dashboard V.18.09)"
    payload["totais"] = {
        "ofertas_na_aba": len(ofertas),
        "ofertas_com_fonte": len(ofertas) - len(sem_fonte),
        "ofertas_sem_fonte": len(sem_fonte),
        "fontes_distintas": len(fontes),
        "operadoras": len({g["op"] for g in fontes}),
        "cidades": len(cidades),
    }
    payload["sem_fonte"] = sem_fonte
    payload["fontes"] = fontes

    io.open(SAIDA, "w", encoding="utf-8").write(
        json.dumps(payload, ensure_ascii=False, indent=1))

    print("fontes.json gerado")
    for k, v in payload["totais"].items():
        print("  %-20s %s" % (k.replace("_", " "), v))
    print("\n  principais fontes:")
    for g in fontes[:8]:
        rot = g["op"] + (" / " + g["isp"] if g["isp"] else "")
        print("    %-22s %3d cidade(s)  %s" % (rot[:22], len(g["cidades"]), g["url"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
