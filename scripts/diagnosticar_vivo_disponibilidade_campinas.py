#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostica a jornada territorial das ofertas Vivo sem contratar.

Limites de seguranca:
- nao preenche CPF, nome, telefone, e-mail ou outros dados pessoais;
- nao conclui pedidos;
- nao tenta contornar HTTP 403, CAPTCHA ou controles de acesso;
- gera apenas JSON, HTML e PNG para auditoria.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "dados" / "diagnostico-vivo-disponibilidade-campinas.json"
EVIDENCIAS = RAIZ / "evidencias-vivo-disponibilidade-campinas"
LANDING = "https://internet.vivo.com.br/ofertas/fibra-e-pos/"
TIMEOUT = 60000

CAMPOS_TERRITORIAIS = {
    "cep": re.compile(r"\bcep\b|codigo postal|c[oó]digo postal", re.I),
    "numero": re.compile(r"n[uú]mero|numero da residencia|n[uú]mero do im[oó]vel", re.I),
    "cidade": re.compile(r"cidade|munic[ií]pio", re.I),
    "uf": re.compile(r"\buf\b|estado", re.I),
    "bairro": re.compile(r"bairro", re.I),
    "logradouro": re.compile(r"endere[cç]o|logradouro|rua|avenida", re.I),
}

CAMPOS_PESSOAIS = {
    "cpf": re.compile(r"\bcpf\b", re.I),
    "nome": re.compile(r"nome completo|seu nome", re.I),
    "telefone": re.compile(r"telefone|celular|whatsapp", re.I),
    "email": re.compile(r"e-?mail", re.I),
    "nascimento": re.compile(r"nascimento|data de nascimento", re.I),
}


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def slug(valor):
    return re.sub(r"[^a-z0-9]+", "-", str(valor).lower()).strip("-")


def texto_elemento(loc):
    partes = []
    for getter in [
        lambda: loc.get_attribute("placeholder"),
        lambda: loc.get_attribute("aria-label"),
        lambda: loc.get_attribute("name"),
        lambda: loc.get_attribute("id"),
        lambda: loc.get_attribute("title"),
        lambda: loc.get_attribute("type"),
    ]:
        try:
            valor = getter()
            if valor:
                partes.append(valor)
        except Exception:
            pass
    try:
        partes.append(loc.inner_text())
    except Exception:
        pass
    return " ".join(partes)


def detectar_campos(page):
    resultado = {
        "territorial": {chave: False for chave in CAMPOS_TERRITORIAIS},
        "personal": {chave: False for chave in CAMPOS_PESSOAIS},
        "inputs": [],
    }
    campos = page.locator("input, select, textarea")
    try:
        quantidade = min(campos.count(), 200)
    except Exception:
        quantidade = 0
    for indice in range(quantidade):
        campo = campos.nth(indice)
        texto = texto_elemento(campo)
        info = {
            "tag": campo.evaluate("el => el.tagName.toLowerCase()"),
            "type": campo.get_attribute("type"),
            "name": campo.get_attribute("name"),
            "id": campo.get_attribute("id"),
            "placeholder": campo.get_attribute("placeholder"),
            "ariaLabel": campo.get_attribute("aria-label"),
            "visible": campo.is_visible(),
        }
        resultado["inputs"].append(info)
        for chave, padrao in CAMPOS_TERRITORIAIS.items():
            if padrao.search(texto):
                resultado["territorial"][chave] = True
        for chave, padrao in CAMPOS_PESSOAIS.items():
            if padrao.search(texto):
                resultado["personal"][chave] = True
    return resultado


def classificar_metodo(campos):
    t = campos["territorial"]
    if t["cep"] and t["numero"]:
        return "cep_e_numero"
    if t["cep"]:
        return "cep"
    if t["cidade"] and t["uf"]:
        return "cidade_uf"
    if any(t.values()):
        return "territorial_parcial"
    return "nao_identificado"


def identificar_card(link):
    try:
        card = link.locator("xpath=ancestor::div[starts-with(@id,'fibra-') or starts-with(@id,'total-')][1]")
        if card.count() > 0:
            texto = re.sub(r"\s+", " ", card.first.inner_text()).strip()
            card_id = card.first.get_attribute("id")
            return card_id, texto[:700]
    except Exception:
        pass
    return None, None


def coletar_links(page):
    ofertas = []
    links = page.get_by_role("link", name=re.compile(r"^Consultar$", re.I))
    try:
        quantidade = links.count()
    except Exception:
        quantidade = 0
    for indice in range(quantidade):
        link = links.nth(indice)
        href = link.get_attribute("href")
        if not href:
            continue
        card_id, card_text = identificar_card(link)
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        ofertas.append({
            "index": indice + 1,
            "cardId": card_id,
            "cardText": card_text,
            "consultationUrl": href,
            "destinationHost": parsed.netloc,
            "destinationPath": parsed.path,
            "offerIds": query.get("offers", []) + query.get("productsIds", []),
        })
    return ofertas


def diagnosticar_destino(browser, oferta):
    nome = "%02d-%s" % (oferta["index"], slug(oferta.get("cardId") or "oferta"))
    html_file = EVIDENCIAS / (nome + ".html")
    screenshot = EVIDENCIAS / (nome + ".png")
    resultado = dict(oferta)
    resultado.update({
        "httpStatus": None,
        "finalUrl": None,
        "territorialFormFound": False,
        "method": "nao_identificado",
        "personalDataRequested": False,
        "blocked": False,
        "captchaDetected": False,
    })
    context = None
    try:
        context = browser.new_context(
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1440, "height": 1000},
        )
        page = context.new_page()
        page.set_default_timeout(TIMEOUT)
        response = page.goto(oferta["consultationUrl"], wait_until="domcontentloaded", timeout=TIMEOUT)
        page.wait_for_timeout(7000)
        resultado["httpStatus"] = response.status if response else None
        resultado["finalUrl"] = page.url
        corpo = page.locator("body").inner_text()
        resultado["captchaDetected"] = bool(re.search(r"captcha|recaptcha|nao sou um robo|não sou um robô", corpo, re.I))
        resultado["blocked"] = bool(
            (response and response.status in [401, 403, 429])
            or resultado["captchaDetected"]
            or re.search(r"access denied|acesso negado|forbidden", corpo, re.I)
        )
        campos = detectar_campos(page)
        resultado["fields"] = campos
        resultado["method"] = classificar_metodo(campos)
        resultado["territorialFormFound"] = resultado["method"] != "nao_identificado"
        resultado["personalDataRequested"] = any(campos["personal"].values())
        resultado["pageTitle"] = page.title()
        html_file.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(screenshot), full_page=True)
    except PlaywrightTimeoutError as erro:
        resultado["error"] = "Timeout Playwright: %s" % str(erro)[:180]
    except Exception as erro:
        resultado["error"] = "%s: %s" % (type(erro).__name__, str(erro)[:180])
    finally:
        if context:
            context.close()
    resultado["evidenceHtml"] = str(html_file.relative_to(RAIZ)) if html_file.exists() else None
    resultado["evidenceScreenshot"] = str(screenshot.relative_to(RAIZ)) if screenshot.exists() else None
    return resultado


def main():
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    resultado = {
        "operator": "Vivo",
        "city": "CAMPINAS",
        "uf": "SP",
        "generated": agora(),
        "landing": LANDING,
        "productionFilesChanged": False,
        "personalDataSubmitted": False,
        "offersChecked": [],
        "summary": {},
    }
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
            landing_context = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo")
            landing_page = landing_context.new_page()
            landing_page.set_default_timeout(TIMEOUT)
            response = landing_page.goto(LANDING, wait_until="domcontentloaded", timeout=TIMEOUT)
            landing_page.wait_for_timeout(6000)
            resultado["landingHttpStatus"] = response.status if response else None
            links = coletar_links(landing_page)
            resultado["linksFound"] = len(links)
            landing_context.close()

            for oferta in links:
                resultado["offersChecked"].append(diagnosticar_destino(browser, oferta))
            browser.close()
    except Exception as erro:
        resultado["error"] = "%s: %s" % (type(erro).__name__, str(erro)[:180])

    ofertas = resultado["offersChecked"]
    metodos = sorted(set(x.get("method") for x in ofertas if x.get("method") and x.get("method") != "nao_identificado"))
    resultado["summary"] = {
        "offersFound": resultado.get("linksFound", 0),
        "offersDiagnosed": len(ofertas),
        "territorialFormsFound": sum(1 for x in ofertas if x.get("territorialFormFound")),
        "personalDataRequested": sum(1 for x in ofertas if x.get("personalDataRequested")),
        "blockedOrCaptcha": sum(1 for x in ofertas if x.get("blocked") or x.get("captchaDetected")),
        "methods": metodos,
    }
    SAIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
