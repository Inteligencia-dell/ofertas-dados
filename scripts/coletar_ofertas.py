#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coletor de Ofertas — RSI | Estrategia Comercial & Go to Market
================================================================================
Atualiza as ofertas consultando EXCLUSIVAMENTE as URLs da coluna FONTE_SITE
da aba COMPARATIVO_OFERTAS, cadastradas em fontes.json.

Semaforo (identico ao painel da aba 5 do dashboard):
    VERDE    oferta atualizada  - a FONTE_SITE comprovou mudanca
    AMARELO  oferta mantida     - a FONTE_SITE confirmou o valor vigente
    VERMELHO validacao manual   - a FONTE_SITE nao permitiu extrair a oferta

Principio inegociavel: nenhum dado e alterado sem evidencia na FONTE_SITE.
Em qualquer falha, o registro anterior e preservado integralmente.

Saidas:
    dados/ofertas.json       -> publicado em <base>/ofertas.json
    dados/status/index.json  -> publicado em <base>/status/

Dependencias: apenas a biblioteca padrao do Python 3.
"""

import argparse
import datetime as dt
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html import unescape

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQ_FONTES = os.path.join(RAIZ, "fontes.json")
DIR_DADOS = os.path.join(RAIZ, "dados")
ARQ_OFERTAS = os.path.join(DIR_DADOS, "ofertas.json")
DIR_STATUS = os.path.join(DIR_DADOS, "status")
ARQ_STATUS = os.path.join(DIR_STATUS, "index.json")

TIMEOUT = 25
TENTATIVAS = 3
PAUSA = 2.0
PARALELO = 6
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

PRECO_MIN, PRECO_MAX = 19.0, 1500.0
VEL_MIN, VEL_MAX = 50, 10000
TOL_PRECO = 0.009
PENAL_POSTERIOR = 3.0
DIST_MAX = 400


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def log(msg):
    print("[coletor] " + msg, flush=True)


# ----------------------------------------------------------------- rede

def baixar(url):
    """Baixa a FONTE_SITE com repeticao e backoff. Retorna (html, erro)."""
    ultimo = None
    for n in range(1, TENTATIVAS + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9",
                "Accept-Encoding": "gzip",
                "Cache-Control": "no-cache",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                bruto = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    bruto = gzip.decompress(bruto)
                return bruto.decode("utf-8", errors="ignore"), None
        except urllib.error.HTTPError as e:
            ultimo = "HTTP %s" % e.code
            if e.code in (404, 410):
                break
        except Exception as e:
            ultimo = "%s: %s" % (type(e).__name__, str(e)[:80])
        if n < TENTATIVAS:
            time.sleep(PAUSA * n)
    return None, ultimo


def limpar(html):
    h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    h = re.sub(r"(?s)<!--.*?-->", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", unescape(h)).strip()


# -------------------------------------------------------------- extracao

RE_PRECO = re.compile(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+)(?:[,.]([0-9]{2}))?")
RE_MEGA = re.compile(r"([0-9]{2,5})\s*(?:mega|mb|mbps)\b", re.I)
RE_GIGA = re.compile(r"([0-9](?:[,.][0-9])?)\s*(?:giga|gb|gbps)\b(?!\s*de\s)", re.I)


def extrair_precos(txt):
    out = []
    for m in RE_PRECO.finditer(txt):
        try:
            v = float(m.group(1).replace(".", "") + "." + (m.group(2) or "00"))
        except ValueError:
            continue
        if PRECO_MIN <= v <= PRECO_MAX:
            out.append((v, m.start()))
    return out


def extrair_velocidades(txt):
    out = []
    for m in RE_MEGA.finditer(txt):
        try:
            v = int(m.group(1))
        except ValueError:
            continue
        if VEL_MIN <= v <= VEL_MAX:
            out.append((v, m.start()))
    for m in RE_GIGA.finditer(txt):
        try:
            v = int(round(float(m.group(1).replace(",", ".")) * 1000))
        except ValueError:
            continue
        if 500 <= v <= VEL_MAX:
            out.append((v, m.start()))
    return out


def parear(txt):
    """Casa cada preco com a velocidade do mesmo bloco de oferta.

    Peso direcional: velocidade ANTES do preco tem prioridade, pois e o padrao
    dos cartoes comerciais ("600 Mega ... por R$ 99,90").
    """
    precos, vels = extrair_precos(txt), extrair_velocidades(txt)
    if not precos or not vels:
        return []
    pares = []
    for p, pos in precos:
        melhor = None
        for v, vp in vels:
            bruta = abs(pos - vp)
            peso = bruta if vp <= pos else bruta * PENAL_POSTERIOR
            if melhor is None or peso < melhor[2]:
                melhor = (v, bruta, peso)
        if melhor and melhor[1] <= DIST_MAX:
            pares.append({"price": p, "speed": melhor[0], "dist": melhor[1]})
    pares.sort(key=lambda x: (x["price"] / max(1, x["speed"]), x["dist"]))
    return pares


def escolher(pares, baseline):
    """Escolhe o par mais aderente ao baseline; sem baseline, melhor R$/Mbps."""
    if not pares:
        return None
    alvo = (baseline or {}).get("velocidade_mb")
    if alvo:
        mesma = [p for p in pares if p["speed"] == alvo]
        if mesma:
            return mesma[0]
        prox = sorted(pares, key=lambda p: abs(p["speed"] - alvo))
        if prox and abs(prox[0]["speed"] - alvo) <= max(100, alvo * 0.2):
            return prox[0]
    return pares[0]


# ---------------------------------------------------------------- IO

def ler_json(caminho, padrao):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao


def gravar_json(caminho, obj):
    """Gravacao atomica: escreve .tmp e so entao substitui."""
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


# ------------------------------------------------------------ validacao

OBRIG = ("ib", "c", "op", "price", "speed", "src")


def validar_payload(p):
    """Replica a validacao LIVE.validateOffer do dashboard."""
    erros = []
    if not isinstance(p, dict) or not isinstance(p.get("offers"), list):
        return ["payload sem array offers"]
    if not p["offers"]:
        return ["payload sem nenhuma oferta"]
    for i, o in enumerate(p["offers"], 1):
        falt = [k for k in OBRIG if o.get(k) in (None, "", [])]
        if falt:
            erros.append("oferta %d: campos ausentes (%s)" % (i, ", ".join(falt)))
            continue
        if not isinstance(o["price"], (int, float)) or o["price"] <= 0:
            erros.append("oferta %d: preco invalido" % i)
        if not isinstance(o["speed"], (int, float)) or o["speed"] <= 0:
            erros.append("oferta %d: velocidade invalida" % i)
        if not re.match(r"^https?://", str(o["src"])):
            erros.append("oferta %d: FONTE_SITE invalida" % i)
    return erros


# ---------------------------------------------------------- orquestracao

def processar_fonte(fonte):
    """Baixa uma FONTE_SITE e devolve os pares extraidos (1 requisicao/URL)."""
    html, erro = baixar(fonte["url"])
    pares = parear(limpar(html)) if html else []
    return {"url": fonte["url"], "op": fonte["op"], "isp": fonte.get("isp"),
            "erro": erro if erro else (None if pares else "pagina sem preco/velocidade extraiveis"),
            "pares": pares}


def coletar(cfg, anteriores):
    ant = {}
    for o in anteriores:
        ant["%s|%s" % (o.get("ib"), o.get("op"))] = o

    fontes = cfg["fontes"]
    log("consultando %d FONTE_SITE distintas..." % len(fontes))
    with ThreadPoolExecutor(max_workers=PARALELO) as ex:
        resultados = list(ex.map(processar_fonte, fontes))

    ofertas, alertas = [], []
    verde = amarelo = vermelho = 0

    for fonte, res in zip(fontes, resultados):
        rot = fonte["op"] + (" / " + fonte["isp"] if fonte.get("isp") else "")
        if res["erro"]:
            log("  %-26s %s" % (rot[:26], res["erro"]))

        for alvo in fonte["cidades"]:
            chave = "%s|%s" % (alvo["ib"], fonte["op"])
            prev = ant.get(chave, {})
            bl = alvo.get("baseline", {}) or {}

            base = {
                "ib": str(alvo["ib"]),
                "c": str(alvo["c"]).upper(),
                "op": fonte["op"],
                "src": fonte["url"],
                "collectedAt": agora(),
            }
            if fonte.get("isp"):
                base["isp"] = fonte["isp"]
            if alvo.get("terr"):
                base["terr"] = alvo["terr"]

            # --- VERMELHO: a FONTE_SITE nao comprovou nada ------------------
            if res["erro"]:
                vermelho += 1
                alertas.append({"op": fonte["op"], "c": base["c"],
                                "msg": "FONTE_SITE nao validou a oferta (%s)" % res["erro"]})
                preco_ant = prev.get("price") or bl.get("preco_mensal")
                vel_ant = prev.get("speed") or bl.get("velocidade_mb")
                if preco_ant and vel_ant:
                    base.update(price=preco_ant, speed=vel_ant,
                                name=prev.get("name") or bl.get("nome"),
                                gb=prev.get("gb") or bl.get("franquia_movel_gb"),
                                benefits=prev.get("benefits") or bl.get("beneficios"),
                                status="a validar", confidence="baixa",
                                collectedAt=prev.get("collectedAt", base["collectedAt"]))
                    ofertas.append(base)
                continue

            escolhido = escolher(res["pares"], bl)
            if not escolhido:
                vermelho += 1
                alertas.append({"op": fonte["op"], "c": base["c"],
                                "msg": "FONTE_SITE sem oferta compativel com o registro atual"})
                preco_ant = prev.get("price") or bl.get("preco_mensal")
                vel_ant = prev.get("speed") or bl.get("velocidade_mb")
                if preco_ant and vel_ant:
                    base.update(price=preco_ant, speed=vel_ant,
                                name=prev.get("name") or bl.get("nome"),
                                status="a validar", confidence="baixa")
                    ofertas.append(base)
                continue

            preco_novo = round(escolhido["price"], 2)
            vel_nova = int(escolhido["speed"])
            preco_ref = prev.get("price") if prev.get("price") else bl.get("preco_mensal")
            vel_ref = prev.get("speed") if prev.get("speed") else bl.get("velocidade_mb")

            mudou = (preco_ref is None or vel_ref is None
                     or abs(float(preco_ref) - preco_novo) > TOL_PRECO
                     or int(vel_ref) != vel_nova)

            base.update(
                price=preco_novo,
                speed=vel_nova,
                name="%d Mega" % vel_nova,
                gb=bl.get("franquia_movel_gb"),
                benefits=bl.get("beneficios"),
                status="atualizada" if mudou else "mantida",
                confidence="alta" if escolhido["dist"] <= 120 else "media",
            )
            if mudou:
                base["previous"] = {"price": preco_ref, "speed": vel_ref}
                verde += 1
            else:
                amarelo += 1
            ofertas.append(base)

    # ofertas sem FONTE_SITE na aba — sempre vermelhas
    for s in cfg.get("sem_fonte", []):
        vermelho += 1
        alertas.append({"op": s.get("op"), "c": s.get("c"),
                        "msg": "sem FONTE_SITE cadastrada na COMPARATIVO_OFERTAS"})

    return ofertas, alertas, {"green": verde, "yellow": amarelo, "red": vermelho}


def main():
    ap = argparse.ArgumentParser(description="Coletor de ofertas via FONTE_SITE")
    ap.add_argument("--dry-run", action="store_true",
                    help="executa sem gravar (validacao em PR)")
    ap.add_argument("--ambiente", default=os.environ.get("AMBIENTE", "producao"))
    ap.add_argument("--operadora", default=None,
                    help="limita a uma operadora (ex.: Claro)")
    args = ap.parse_args()

    cfg = ler_json(ARQ_FONTES, None)
    if not cfg or not cfg.get("fontes"):
        log("ERRO: fontes.json ausente ou vazio.")
        return 2

    if args.operadora:
        cfg = dict(cfg)
        cfg["fontes"] = [f for f in cfg["fontes"] if f["op"] == args.operadora]
        cfg["sem_fonte"] = [s for s in cfg.get("sem_fonte", [])
                            if s.get("op") == args.operadora]
        log("filtro de operadora: %s (%d fonte(s))" % (args.operadora, len(cfg["fontes"])))

    ant = ler_json(ARQ_OFERTAS, {}).get("offers", [])
    ofertas, alertas, cont = coletar(cfg, ant)

    total = cont["green"] + cont["yellow"] + cont["red"]
    cobertura = "%d de %d pontos cidade-operadora" % (len(ofertas), total)
    payload = {
        "meta": {
            "updated": agora(),
            "environment": args.ambiente,
            "coverage": cobertura,
            "generator": "coletar_ofertas.py",
            "source": "COMPARATIVO_OFERTAS / coluna FONTE_SITE",
        },
        "offers": ofertas,
    }

    erros = validar_payload(payload)
    if erros:
        log("PAYLOAD REPROVADO — arquivo anterior preservado:")
        for e in erros[:10]:
            log("   - " + e)
        return 1

    geral = ("red" if cont["red"] and not cont["green"]
             else ("yellow" if cont["red"] or cont["yellow"] else "green"))
    status = {
        "overall": geral,
        "updated": payload["meta"]["updated"],
        "freshness": {"ageHours": 0, "reference": payload["meta"]["updated"]},
        "counts": cont,
        "alertCount": len(alertas),
        "alerts": [{"msg": "%s · %s: %s" % (a["op"], a["c"], a["msg"])}
                   for a in alertas[:25]],
        "environment": args.ambiente,
        "coverage": cobertura,
    }

    if args.dry_run:
        log("dry-run aprovado: %d ofertas | %s" % (len(ofertas), cont))
        return 0

    gravar_json(ARQ_OFERTAS, payload)
    gravar_json(ARQ_STATUS, status)
    log("gravado: %d ofertas | verde %d · amarelo %d · vermelho %d"
        % (len(ofertas), cont["green"], cont["yellow"], cont["red"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
