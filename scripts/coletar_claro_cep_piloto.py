#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piloto seguro de consulta territorial Claro por CEP.

Le fontes.json, seleciona cinco cidades piloto, abre o portal oficial de
cobertura da Claro, preenche o CEP, marca endereco sem numero quando possivel,
submete a consulta e grava evidencias em dados/piloto-claro-cep.json.

Este script NAO altera dados/ofertas.json nem dados/status/index.json.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
FONTES = RAIZ / "fontes.json"
SAIDA = RAIZ / "dados" / "piloto-claro-cep.json"
EVIDENCIAS = RAIZ / "evidencias-claro-cep"

URL_COBERTURA = "https://planos.claro.com.br/cobertura"
TIMEOUT = 60000
ESPERA_APOS_CONSULTA = 10000

CIDADES_PADRAO = [
    "ADAMANTINA",
    "CAMPINAS",
    "RIBEIRAO PRETO",
    "SAO JOSE DOS CAMPOS",
    "SOROCABA",
]


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sem_acento(valor):
    texto = str(valor or "")
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip().upper()


def normalizar_cep(valor):
    texto = re.sub(r"\D", "", str(valor or ""))
    if not texto:
        return None
    texto = texto.zfill(8)
    return texto if re.fullmatch(r"\d{8}", texto) else None


def formatar_cep(valor):
    cep = normalizar_cep(valor)
    return "%s-%s" % (cep[:5], cep[5:]) if cep else None


def carregar_alvos(cidades):
    with FONTES.open(encoding="utf-8") as f:
        cfg = json.load(f)

    desejadas = {sem_acento(c) for c in cidades}
    encontrados = {}

    for fonte in cfg.get("fontes", []):
        if sem_acento(fonte.get("op")) != "CLARO":
            continue
        for alvo in fonte.get("cidades", []):
            nome = sem_acento(alvo.get("c"))
            if nome in desejadas:
                item = dict(alvo)
                item["op"] = "Claro"
                item["src"] = fonte.get("url")
                item["cep"] = normalizar_cep(item.get("cep"))
                encontrados[nome] = item

    ausentes = sorted(desejadas - set(encontrados))
    if ausentes:
        raise RuntimeError("Cidades nao encontradas no fontes.json: %s" % ", ".join(ausentes))

    return [encontrados[sem_acento(c)] for c in cidades]


def primeiro_visivel(candidatos):
    for loc in candidatos:
        try:
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return None


def preencher_cep(page, cep_formatado):
    campo = primeiro_visivel([
        page.get_by_label(re.compile(r"cep", re.I)),
        page.get_by_placeholder(re.compile(r"cep", re.I)),
        page.get_by_role("textbox", name=re.compile(r"cep", re.I)),
        page.locator("input[name*='cep' i]"),
        page.locator("input[id*='cep' i]"),
        page.locator("input[autocomplete='postal-code']"),
    ])
    if campo is None:
        return False, "Campo de CEP nao localizado"
    campo.fill(cep_formatado)
    return True, None


def marcar_sem_numero(page):
    candidatos = [
        page.get_by_label(re.compile(r"nao possui numero|sem numero", re.I)),
        page.get_by_text(re.compile(r"meu endereco nao possui numero", re.I)),
        page.locator("input[type='checkbox'][name*='numero' i]"),
        page.locator("input[type='checkbox'][id*='numero' i]"),
    ]
    alvo = primeiro_visivel(candidatos)
    if alvo is None:
        return False
    try:
        if alvo.get_attribute("type") == "checkbox":
            alvo.check()
        else:
            alvo.click()
        return True
    except Exception:
        return False


def preencher_numero_fallback(page):
    campo = primeiro_visivel([
        page.get_by_label(re.compile(r"numero", re.I)),
        page.get_by_placeholder(re.compile(r"numero", re.I)),
        page.locator("input[name*='numero' i]"),
        page.locator("input[id*='numero' i]"),
    ])
    if campo is None:
        return False
    try:
        campo.fill("1")
        return True
    except Exception:
        return False


def submeter(page):
    botao = primeiro_visivel([
        page.get_by_role("button", name=re.compile(r"consultar disponibilidade", re.I)),
        page.get_by_role("button", name=re.compile(r"consultar|continuar|buscar|confirmar|ver ofertas", re.I)),
        page.locator("button[type='submit']"),
        page.locator("input[type='submit']"),
    ])
    if botao is None:
        return False, "Botao de consulta nao localizado"
    botao.click()
    return True, None


def texto_compativel(texto, alvo):
    pagina = sem_acento(texto)
    cidade = sem_acento(alvo.get("c"))
    uf = sem_acento(alvo.get("uf"))
    cidade_ok = cidade in pagina
    uf_ok = bool(re.search(r"(^|[\s/\-])%s([\s/\-]|$)" % re.escape(uf), pagina))
    return cidade_ok and uf_ok


RE_PRECO = re.compile(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+)(?:[,.]([0-9]{2}))?")
RE_MEGA = re.compile(r"([0-9]{2,5})\s*(?:MEGA|MB|MBPS)\b", re.I)
RE_GIGA = re.compile(r"([0-9](?:[,.][0-9])?)\s*(?:GIGA|GB|GBPS)\b", re.I)


def pares_oferta(texto):
    precos = []
    for m in RE_PRECO.finditer(texto):
        try:
            valor = float(m.group(1).replace(".", "") + "." + (m.group(2) or "00"))
        except ValueError:
            continue
        if 19 <= valor <= 1500:
            precos.append((valor, m.start()))

    velocidades = []
    for m in RE_MEGA.finditer(texto):
        valor = int(m.group(1))
        if 50 <= valor <= 10000:
            velocidades.append((valor, m.start()))
    for m in RE_GIGA.finditer(texto):
        valor = int(round(float(m.group(1).replace(",", ".")) * 1000))
        if 500 <= valor <= 10000:
            velocidades.append((valor, m.start()))

    pares = []
    for preco, pp in precos:
        if not velocidades:
            break
        vel, pv = min(velocidades, key=lambda x: abs(x[1] - pp))
        distancia = abs(pv - pp)
        if distancia <= 500:
            pares.append({"price": round(preco, 2), "speed": vel, "distance": distancia})

    unicos = []
    vistos = set()
    for p in sorted(pares, key=lambda x: (x["speed"], x["price"])):
        chave = (p["speed"], p["price"])
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(p)
    return unicos


def consultar(page, alvo):
    cep = normalizar_cep(alvo.get("cep"))
    base = {
        "ib": str(alvo.get("ib") or ""),
        "c": alvo.get("c"),
        "uf": alvo.get("uf"),
        "op": "Claro",
        "cep": cep,
        "cepConsultado": cep,
        "src": URL_COBERTURA,
        "collectedAt": agora(),
        "collectionMethod": "playwright_cep_piloto",
        "locationConfirmed": False,
        "status": "a validar",
        "confidence": "baixa",
    }

    if not cep:
        base["reason"] = "CEP ausente ou invalido"
        return base

    slug = "%s-%s" % (sem_acento(alvo.get("c")).lower().replace(" ", "-"), cep)
    screenshot = EVIDENCIAS / (slug + ".png")
    html_path = EVIDENCIAS / (slug + ".html")

    try:
        resposta = page.goto(URL_COBERTURA, wait_until="domcontentloaded", timeout=TIMEOUT)
        page.wait_for_timeout(3000)
        ok, erro = preencher_cep(page, formatar_cep(cep))
        if not ok:
            base["reason"] = erro
            page.screenshot(path=str(screenshot), full_page=True)
            return base

        if not marcar_sem_numero(page):
            preencher_numero_fallback(page)

        ok, erro = submeter(page)
        if not ok:
            base["reason"] = erro
            page.screenshot(path=str(screenshot), full_page=True)
            return base

        page.wait_for_timeout(ESPERA_APOS_CONSULTA)
        texto = page.locator("body").inner_text()
        html = page.content()
        html_path.write_text(html, encoding="utf-8")
        page.screenshot(path=str(screenshot), full_page=True)

        base["httpStatus"] = resposta.status if resposta else None
        base["locationConfirmed"] = texto_compativel(texto, alvo)
        base["locationTextFound"] = base["locationConfirmed"]
        base["offersFound"] = pares_oferta(texto)
        base["evidenceScreenshot"] = str(screenshot.relative_to(RAIZ))
        base["evidenceHtml"] = str(html_path.relative_to(RAIZ))

        if not base["locationConfirmed"]:
            base["reason"] = "Cidade/UF nao confirmadas no conteudo retornado"
            return base
        if not base["offersFound"]:
            base["reason"] = "Nenhuma oferta com preco e velocidade localizada apos o CEP"
            return base

        base["status"] = "validada_piloto"
        base["confidence"] = "alta"
        return base

    except PlaywrightTimeoutError as e:
        base["reason"] = "Timeout Playwright: %s" % str(e)[:160]
    except Exception as e:
        base["reason"] = "%s: %s" % (type(e).__name__, str(e)[:160])

    try:
        page.screenshot(path=str(screenshot), full_page=True)
        base["evidenceScreenshot"] = str(screenshot.relative_to(RAIZ))
    except Exception:
        pass
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cidades", nargs="*", default=CIDADES_PADRAO)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    alvos = carregar_alvos(args.cidades)
    resultados = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, args=["--disable-dev-shm-usage", "--no-sandbox"])
        for alvo in alvos:
            context = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo", viewport={"width": 1366, "height": 900})
            page = context.new_page()
            page.set_default_timeout(TIMEOUT)
            resultado = consultar(page, alvo)
            resultados.append(resultado)
            print("[piloto] %-24s CEP %s | confirmado=%s | ofertas=%d | %s" % (
                alvo.get("c"), alvo.get("cep"), resultado.get("locationConfirmed"),
                len(resultado.get("offersFound", [])), resultado.get("reason", resultado.get("status"))))
            context.close()
        browser.close()

    payload = {
        "meta": {"generated": agora(), "mode": "piloto_claro_cep", "cities": len(resultados), "productionFilesChanged": False},
        "summary": {
            "locationConfirmed": sum(1 for r in resultados if r.get("locationConfirmed")),
            "withOffers": sum(1 for r in resultados if r.get("offersFound")),
            "pending": sum(1 for r in resultados if r.get("status") == "a validar"),
        },
        "results": resultados,
    }
    SAIDA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[piloto] resultado salvo em %s" % SAIDA)
    print("[piloto] resumo: %s" % payload["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
