#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piloto Vivo: extrai ofertas publicas Fibra e Fibra + Pos.

A landing Vivo Fibra + Pos nao possui seletor territorial. Portanto, as ofertas
sao registradas como publicas, sem atribui-las indevidamente a Campinas/SP.
Nao altera arquivos de producao.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "dados" / "piloto-vivo-fibra-movel-campinas.json"
EVIDENCIAS = RAIZ / "evidencias-vivo-fibra-movel-campinas"
URL = "https://internet.vivo.com.br/ofertas/fibra-e-pos/"
TIMEOUT = 60000


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def valor_preco(texto):
    m = re.search(r"R\$\s*([0-9]{1,4})(?:[,.]\s*([0-9]{2}))?", texto, re.I)
    if not m:
        return None
    try:
        return round(float("%s.%s" % (m.group(1), m.group(2) or "00")), 2)
    except Exception:
        return None


def todos_precos(texto):
    valores = []
    for m in re.finditer(r"R\$\s*([0-9]{1,4})(?:[,.]\s*([0-9]{2}))?", texto, re.I):
        try:
            valores.append(round(float("%s.%s" % (m.group(1), m.group(2) or "00")), 2))
        except Exception:
            pass
    return valores


def velocidade(texto):
    m = re.search(r"(\d{2,5})\s*Mega\b", texto, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"([0-9](?:[,.][0-9])?)\s*Giga\b", texto, re.I)
    if m:
        return int(round(float(m.group(1).replace(",", ".")) * 1000))
    return None


def franquias(texto):
    total = re.search(r"(\d{1,4})\s*GB\s*de Vivo P[oó]s", texto, re.I)
    bonus = re.search(r"(\d{1,4})\s*GB de franquia\s*\+\s*(\d{1,4})\s*GB de b[oô]nus", texto, re.I)
    return {
        "total": int(total.group(1)) if total else None,
        "base": int(bonus.group(1)) if bonus else None,
        "bonus": int(bonus.group(2)) if bonus else None,
    }


def texto_card(card):
    return re.sub(r"\s+", " ", card.inner_text()).strip()


def extrair(page):
    fibra = []
    convergente = []

    cards_fibra = page.locator("div[id^='fibra-']")
    for i in range(cards_fibra.count()):
        card = cards_fibra.nth(i)
        texto = texto_card(card)
        speed = velocidade(texto)
        precos = todos_precos(texto)
        if speed is None or not precos:
            continue
        atual = precos[-1]
        anterior = precos[-2] if len(precos) > 1 and precos[-2] != atual else None
        fibra.append({
            "offerType": "fibra",
            "convergenceType": None,
            "name": "Vivo Fibra %s" % ("1 Giga" if speed == 1000 else "%d Mega" % speed),
            "fixedSpeedMb": speed,
            "monthlyPrice": atual,
            "previousPrice": anterior,
            "tvIncluded": False,
            "sourceSection": "vivo_fibra",
            "cardText": texto[:800],
        })

    cards_total = page.locator("div[id^='total-']")
    for i in range(cards_total.count()):
        card = cards_total.nth(i)
        texto = texto_card(card)
        if re.search(r"\bTV\b|canais ao vivo", texto, re.I):
            continue
        speed = velocidade(texto)
        dados = franquias(texto)
        precos = todos_precos(texto)
        if speed is None or dados["total"] is None or not precos:
            continue
        atual = precos[-1]
        anterior = precos[-2] if len(precos) > 1 and precos[-2] != atual else None
        nome_plano = re.search(r"(Vivo Total[^0-9]+?)\s+\d{2,5}\s*(?:Mega|Giga)", texto, re.I)
        convergente.append({
            "offerType": "convergente",
            "convergenceType": "fibra_movel",
            "name": "%s + Pos %d GB" % ("1 Giga" if speed == 1000 else "%d Mega" % speed, dados["total"]),
            "commercialName": nome_plano.group(1).strip() if nome_plano else None,
            "fixedSpeedMb": speed,
            "mobilePlanType": "pos",
            "mobileAllowanceGb": dados["total"],
            "mobileBaseAllowanceGb": dados["base"],
            "mobileBonusGb": dados["bonus"],
            "monthlyPrice": atual,
            "previousPrice": anterior,
            "tvIncluded": False,
            "sourceSection": "vivo_total",
            "cardText": texto[:900],
        })

    return fibra, convergente


def main():
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    html_file = EVIDENCIAS / "vivo-campinas-sp.html"
    screenshot = EVIDENCIAS / "vivo-campinas-sp.png"
    resultado = {
        "operator": "Vivo",
        "city": "CAMPINAS",
        "uf": "SP",
        "source": URL,
        "generated": agora(),
        "httpStatus": None,
        "territorialScope": "publico_nao_confirmado",
        "locationConfirmed": False,
        "fiberOffers": [],
        "fiberMobileOffers": [],
        "tvOffersAccepted": 0,
        "status": "a validar",
        "productionFilesChanged": False,
    }
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
            context = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo", viewport={"width": 1440, "height": 1100})
            page = context.new_page()
            page.set_default_timeout(TIMEOUT)
            response = page.goto(URL, wait_until="domcontentloaded", timeout=TIMEOUT)
            resultado["httpStatus"] = response.status if response else None
            page.wait_for_timeout(7000)
            if response and response.status < 400:
                resultado["fiberOffers"], resultado["fiberMobileOffers"] = extrair(page)
                if resultado["fiberOffers"]:
                    resultado["status"] = "validada_oferta_publica"
                    resultado["reason"] = "Landing sem seletor territorial; ofertas extraidas sem atribuir a Campinas/SP"
                else:
                    resultado["reason"] = "Landing carregada, mas nenhuma oferta Fibra foi extraida"
            else:
                resultado["reason"] = "HTTP %s na landing Vivo Fibra + Pos" % resultado["httpStatus"]
            html_file.write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(screenshot), full_page=True)
            context.close()
            browser.close()
    except PlaywrightTimeoutError as erro:
        resultado["reason"] = "Timeout Playwright: %s" % str(erro)[:180]
    except Exception as erro:
        resultado["reason"] = "%s: %s" % (type(erro).__name__, str(erro)[:180])

    resultado["evidenceHtml"] = str(html_file.relative_to(RAIZ)) if html_file.exists() else None
    resultado["evidenceScreenshot"] = str(screenshot.relative_to(RAIZ)) if screenshot.exists() else None
    SAIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
