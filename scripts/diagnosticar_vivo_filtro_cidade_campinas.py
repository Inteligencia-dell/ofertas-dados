#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostica o filtro publico de cidade da home Vivo para Campinas/SP.

Nao acessa checkout, nao fornece dados pessoais e nao conclui contratacao.
Preserva cookies/localStorage da selecao para verificar paginas oficiais de ofertas.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "dados" / "diagnostico-vivo-filtro-cidade-campinas.json"
EVIDENCIAS = RAIZ / "evidencias-vivo-filtro-cidade-campinas"
HOME = "https://vivo.com.br/para-voce"
PAGINAS = [
    "https://vivo.com.br/para-voce/produtos-e-servicos/melhores-ofertas",
    "https://vivo.com.br/para-voce/produtos-e-servicos/para-casa/internet",
    "https://internet.vivo.com.br/ofertas/fibra-e-pos/",
]
TIMEOUT = 60000


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def primeiro_visivel(candidatos):
    for loc in candidatos:
        try:
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return None


def aceitar_cookies(page):
    botao = primeiro_visivel([
        page.get_by_role("button", name=re.compile(r"aceitar|concordar|continuar|entendi", re.I)),
        page.get_by_text(re.compile(r"aceitar todos", re.I), exact=False),
    ])
    if botao:
        try:
            botao.click(timeout=5000)
            page.wait_for_timeout(1000)
        except Exception:
            pass


def abrir_filtro(page):
    if localizar_campo(page) is not None:
        return True
    alvo = primeiro_visivel([
        page.get_by_text(re.compile(r"Ofertas para", re.I), exact=False),
        page.get_by_role("button", name=re.compile(r"Ofertas para|cidade|localiza", re.I)),
        page.locator("[aria-label*='ofertas para' i]"),
        page.locator("[aria-label*='cidade' i]"),
    ])
    if alvo:
        try:
            alvo.click(timeout=10000)
            page.wait_for_timeout(1800)
        except Exception:
            pass
    return localizar_campo(page) is not None


def localizar_campo(page):
    return primeiro_visivel([
        page.get_by_placeholder(re.compile(r"nome da sua cidade", re.I)),
        page.get_by_label(re.compile(r"insira sua localiza", re.I)),
        page.locator("input[placeholder*='cidade' i]"),
        page.locator("input[aria-label*='cidade' i]"),
        page.locator("input[type='search']"),
    ])


def localizar_opcao(page):
    padrao = re.compile(r"Campinas\s*(?:/|\(|-|,)\s*SP\s*\)?", re.I)
    return primeiro_visivel([
        page.get_by_role("option", name=padrao),
        page.get_by_role("button", name=padrao),
        page.get_by_role("link", name=padrao),
        page.locator("[role='option']").filter(has_text=re.compile(r"Campinas", re.I)),
        page.locator("li").filter(has_text=padrao),
        page.get_by_text(padrao, exact=False),
    ])


def selecionar_campinas(page):
    if not abrir_filtro(page):
        return False, "Filtro aberto, mas campo de cidade nao localizado"
    campo = localizar_campo(page)
    if campo is None:
        return False, "Campo de cidade nao localizado"
    try:
        campo.click()
        campo.fill("Campinas")
    except Exception:
        campo.click()
        campo.press("Control+A")
        campo.press_sequentially("Campinas", delay=120)
    page.wait_for_timeout(3500)
    opcao = localizar_opcao(page)
    if opcao:
        opcao.click()
        page.wait_for_timeout(1500)
    confirmar = primeiro_visivel([
        page.get_by_role("button", name=re.compile(r"^Confirmar$", re.I)),
        page.get_by_text(re.compile(r"^Confirmar$", re.I), exact=True),
    ])
    if confirmar:
        confirmar.click()
        page.wait_for_timeout(7000)
    texto = page.locator("body").inner_text()
    confirmado = bool(re.search(r"Ofertas para\s+Campinas\s*\(SP\)", texto, re.I))
    return confirmado, None if confirmado else "Cabecalho nao confirmou Ofertas para Campinas (SP)"


def snapshot_storage(page):
    try:
        storage = page.evaluate("""() => ({
          localStorage: Object.fromEntries(Object.entries(localStorage)),
          sessionStorage: Object.fromEntries(Object.entries(sessionStorage))
        })""")
    except Exception:
        storage = {"localStorage": {}, "sessionStorage": {}}
    return storage


def analisar_pagina(page, url, indice):
    nome = "%02d-pagina" % indice
    html = EVIDENCIAS / (nome + ".html")
    png = EVIDENCIAS / (nome + ".png")
    item = {"url": url, "httpStatus": None, "finalUrl": None}
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        page.wait_for_timeout(7000)
        item["httpStatus"] = response.status if response else None
        item["finalUrl"] = page.url
        texto = page.locator("body").inner_text()
        item["campinasVisible"] = bool(re.search(r"Campinas\s*(?:/|\(|-|,)\s*SP", texto, re.I))
        item["locationHeaderVisible"] = bool(re.search(r"Ofertas para\s+Campinas", texto, re.I))
        item["fiberMentioned"] = bool(re.search(r"Vivo Fibra|Internet Fibra", texto, re.I))
        item["vivoTotalMentioned"] = bool(re.search(r"Vivo Total|Fibra\s*\+\s*P[oó]s", texto, re.I))
        html.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(png), full_page=True)
    except Exception as erro:
        item["error"] = "%s: %s" % (type(erro).__name__, str(erro)[:180])
    item["evidenceHtml"] = str(html.relative_to(RAIZ)) if html.exists() else None
    item["evidenceScreenshot"] = str(png.relative_to(RAIZ)) if png.exists() else None
    return item


def main():
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    resultado = {
        "operator": "Vivo",
        "city": "CAMPINAS",
        "uf": "SP",
        "generated": agora(),
        "home": HOME,
        "locationConfirmed": False,
        "productionFilesChanged": False,
        "personalDataSubmitted": False,
        "pagesChecked": [],
    }
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
            context = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo", viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.set_default_timeout(TIMEOUT)
            response = page.goto(HOME, wait_until="domcontentloaded", timeout=TIMEOUT)
            page.wait_for_timeout(6000)
            resultado["homeHttpStatus"] = response.status if response else None
            aceitar_cookies(page)
            ok, erro = selecionar_campinas(page)
            resultado["locationConfirmed"] = ok
            if erro:
                resultado["reason"] = erro
            resultado["cookiesAfterSelection"] = [
                {"name": c.get("name"), "domain": c.get("domain"), "path": c.get("path")}
                for c in context.cookies()
            ]
            resultado["storageAfterSelection"] = snapshot_storage(page)
            home_html = EVIDENCIAS / "00-home-campinas.html"
            home_png = EVIDENCIAS / "00-home-campinas.png"
            home_html.write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(home_png), full_page=True)

            if ok:
                for indice, url in enumerate(PAGINAS, 1):
                    resultado["pagesChecked"].append(analisar_pagina(page, url, indice))
            browser.close()
    except PlaywrightTimeoutError as erro:
        resultado["reason"] = "Timeout Playwright: %s" % str(erro)[:180]
    except Exception as erro:
        resultado["reason"] = "%s: %s" % (type(erro).__name__, str(erro)[:180])

    resultado["summary"] = {
        "locationConfirmed": resultado.get("locationConfirmed", False),
        "pagesChecked": len(resultado.get("pagesChecked", [])),
        "pagesKeepingCampinas": sum(1 for x in resultado.get("pagesChecked", []) if x.get("campinasVisible") or x.get("locationHeaderVisible")),
        "pagesWithFiber": sum(1 for x in resultado.get("pagesChecked", []) if x.get("fiberMentioned")),
        "pagesWithFiberMobile": sum(1 for x in resultado.get("pagesChecked", []) if x.get("vivoTotalMentioned")),
    }
    SAIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
