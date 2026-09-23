#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piloto Vivo para Campinas/SP: Fibra e Fibra + Movel.

Gera somente JSON e evidencias de diagnostico.
Nao altera dados/ofertas.json nem dados/status/index.json.
"""
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "dados" / "piloto-vivo-fibra-movel-campinas.json"
EVIDENCIAS = RAIZ / "evidencias-vivo-fibra-movel-campinas"
URLS = [
    "https://vivo.com.br/para-voce/produtos-e-servicos/melhores-ofertas",
    "https://internet.vivo.com.br/ofertas/fibra-e-pos/",
    "https://vivo.com.br/para-voce/produtos-e-servicos/para-casa/internet",
]
URL = URLS[0]
CIDADE = "CAMPINAS"
UF = "SP"
TIMEOUT = 60000


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def norm(valor):
    texto = unicodedata.normalize("NFD", str(valor or ""))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip().upper()


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


def localizar_campo_cidade(page):
    candidatos = [
        page.get_by_placeholder(re.compile(r"cidade|localizacao|localização", re.I)),
        page.get_by_label(re.compile(r"cidade|localizacao|localização", re.I)),
        page.locator("input[name*='city' i]"),
        page.locator("input[name*='cidade' i]"),
        page.locator("input[id*='city' i]"),
        page.locator("input[id*='cidade' i]"),
        page.locator("input[type='search']"),
    ]
    return primeiro_visivel(candidatos)


def abrir_seletor_cidade(page):
    if localizar_campo_cidade(page) is not None:
        return True
    candidatos = [
        page.get_by_text(re.compile(r"ofertas para|trocar cidade|alterar cidade|sua cidade|localizacao|localização", re.I), exact=False),
        page.get_by_role("button", name=re.compile(r"cidade|localizacao|localização|alterar|trocar", re.I)),
        page.locator("[aria-label*='cidade' i]"),
        page.locator("[data-testid*='location' i]"),
        page.locator("[class*='location' i]"),
    ]
    alvo = primeiro_visivel(candidatos)
    if alvo:
        try:
            alvo.click(timeout=10000)
            page.wait_for_timeout(2000)
        except Exception:
            pass
    return localizar_campo_cidade(page) is not None


def localizar_opcao_campinas(page):
    padrao = re.compile(r"CAMPINAS\s*(?:/|\(|-|,)\s*SP\s*\)?", re.I)
    candidatos = [
        page.get_by_role("option", name=padrao),
        page.get_by_role("button", name=padrao),
        page.get_by_role("link", name=padrao),
        page.locator("[role='option']").filter(has_text=re.compile(r"Campinas", re.I)),
        page.locator("li").filter(has_text=padrao),
        page.get_by_text(padrao, exact=False),
    ]
    return primeiro_visivel(candidatos)


def selecionar_cidade(page):
    abrir_seletor_cidade(page)
    campo = localizar_campo_cidade(page)
    if campo is None:
        return False, "Campo editavel de cidade nao localizado"
    try:
        campo.click()
        campo.fill("Campinas")
    except Exception:
        try:
            campo.click()
            campo.press("Control+A")
            campo.press_sequentially("Campinas", delay=120)
        except Exception as erro:
            return False, "Falha ao preencher Campinas: %s" % str(erro)[:150]
    page.wait_for_timeout(4000)
    opcao = localizar_opcao_campinas(page)
    if opcao is None:
        return False, "Opcao Campinas/SP nao localizada"
    try:
        opcao.click()
    except Exception as erro:
        return False, "Falha ao selecionar Campinas/SP: %s" % str(erro)[:150]
    page.wait_for_timeout(8000)
    confirmar = primeiro_visivel([
        page.get_by_role("button", name=re.compile(r"confirmar|continuar|aplicar", re.I)),
    ])
    if confirmar:
        try:
            confirmar.click()
            page.wait_for_timeout(5000)
        except Exception:
            pass
    return True, None


def local_confirmado(page):
    texto = norm(page.locator("body").inner_text())
    url = norm(page.url)
    return "CAMPINAS" in texto and (
        bool(re.search(r"(^|[\s/\-(,])SP([\s/\-)]|$)", texto)) or "CAMPINAS" in url
    )


def converter_preco(inteiro, centavos="00"):
    try:
        i = re.sub(r"\D", "", str(inteiro or ""))
        c = re.sub(r"\D", "", str(centavos or ""))
        if not i:
            return None
        return round(float("%s.%s" % (i, (c + "00")[:2])), 2)
    except Exception:
        return None


def extrair_precos(texto):
    valores = []
    for m in re.finditer(r"R\$\s*([0-9]{1,4})(?:[,.]\s*([0-9]{2}))?", texto, re.I):
        valor = converter_preco(m.group(1), m.group(2) or "00")
        if valor is not None:
            valores.append(valor)
    return valores


def extrair_velocidade(texto):
    m = re.search(r"(\d{2,5})\s*(?:MEGA|MBPS)\b", texto, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"([0-9](?:[,.][0-9])?)\s*(?:GIGA|GBPS)\b", texto, re.I)
    if m:
        return int(round(float(m.group(1).replace(",", ".")) * 1000))
    return None


def extrair_franquia(texto):
    candidatos = [int(x) for x in re.findall(r"(\d{1,4})\s*GB\b", texto, re.I)]
    return max(candidatos) if candidatos else None


def card_tem_tv(texto):
    t = norm(texto)
    return any(x in t for x in ["VIVO TV", "TV INCLUSA", "FIBRA + TV", "APP + TV", "CANAIS AO VIVO"])


def localizar_cards(page):
    seletores = [
        "article",
        "[data-testid*='card' i]",
        "[class*='offer-card' i]",
        "[class*='plan-card' i]",
        "[class*='product-card' i]",
        "[class*='card' i]",
    ]
    vistos = set()
    cards = []
    for seletor in seletores:
        grupo = page.locator(seletor)
        try:
            quantidade = min(grupo.count(), 300)
        except Exception:
            continue
        for indice in range(quantidade):
            card = grupo.nth(indice)
            try:
                if not card.is_visible():
                    continue
                texto = re.sub(r"\s+", " ", card.inner_text()).strip()
            except Exception:
                continue
            if not (re.search(r"\bFibra\b", texto, re.I) and re.search(r"R\$", texto)):
                continue
            chave = norm(texto)
            if chave in vistos or len(texto) > 2500:
                continue
            vistos.add(chave)
            cards.append((card, texto))
    return cards


def extrair_ofertas(page):
    fibra = []
    fibra_movel = []
    vistos_fibra = set()
    vistos_convergente = set()

    for card, texto in localizar_cards(page):
        if card_tem_tv(texto):
            continue
        velocidade = extrair_velocidade(texto)
        precos = extrair_precos(texto)
        if velocidade is None or not precos:
            continue
        preco_atual = precos[-1]
        preco_anterior = precos[-2] if len(precos) > 1 and precos[-2] != preco_atual else None
        t = norm(texto)
        tem_movel = bool(re.search(r"\b(VIVO TOTAL|VIVO POS|POS|CONTROLE|FIBRA\s*\+\s*POS)\b", t))
        franquia = extrair_franquia(texto) if tem_movel else None

        if tem_movel and franquia:
            chave = (velocidade, franquia, preco_atual)
            if chave in vistos_convergente:
                continue
            vistos_convergente.add(chave)
            fibra_movel.append({
                "offerType": "convergente",
                "convergenceType": "fibra_movel",
                "name": "%s + Pos %d GB" % (
                    "1 Giga" if velocidade == 1000 else "%d Mega" % velocidade,
                    franquia,
                ),
                "fixedSpeedMb": velocidade,
                "mobilePlanType": "pos",
                "mobileAllowanceGb": franquia,
                "tvIncluded": False,
                "monthlyPrice": preco_atual,
                "previousPrice": preco_anterior,
                "sourceSection": "vivo_total",
                "cardText": texto[:900],
            })
        elif not tem_movel:
            chave = (velocidade, preco_atual)
            if chave in vistos_fibra:
                continue
            vistos_fibra.add(chave)
            fibra.append({
                "offerType": "fibra",
                "convergenceType": None,
                "name": "Vivo Fibra %s" % ("1 Giga" if velocidade == 1000 else "%d Mega" % velocidade),
                "fixedSpeedMb": velocidade,
                "tvIncluded": False,
                "monthlyPrice": preco_atual,
                "previousPrice": preco_anterior,
                "sourceSection": "vivo_fibra",
                "cardText": texto[:900],
            })

    return (
        sorted(fibra, key=lambda x: (x["fixedSpeedMb"], x["monthlyPrice"])),
        sorted(fibra_movel, key=lambda x: (x["fixedSpeedMb"], x["mobileAllowanceGb"], x["monthlyPrice"])),
    )


def abrir_primeira_url_disponivel(page):
    """Testa paginas oficiais da Vivo sem contornar controles de acesso."""
    tentativas = []
    for url in URLS:
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
            status = response.status if response else None
            page.wait_for_timeout(5000)
            tentativas.append({"url": url, "httpStatus": status, "finalUrl": page.url})
            if status is not None and status < 400:
                return response, url, tentativas
        except Exception as erro:
            tentativas.append({"url": url, "error": "%s: %s" % (type(erro).__name__, str(erro)[:160])})
    return None, None, tentativas


def main():
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    screenshot = EVIDENCIAS / "vivo-campinas-sp.png"
    html_file = EVIDENCIAS / "vivo-campinas-sp.html"
    resultado = {
        "operator": "Vivo",
        "city": CIDADE,
        "uf": UF,
        "source": URL,
        "generated": agora(),
        "httpStatus": None,
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
            context = browser.new_context(
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 1440, "height": 1100},
            )
            page = context.new_page()
            page.set_default_timeout(TIMEOUT)
            response, url_utilizada, tentativas = abrir_primeira_url_disponivel(page)
            resultado["sourceAttempts"] = tentativas
            resultado["source"] = url_utilizada or URLS[0]
            resultado["httpStatus"] = response.status if response else None

            if response is None:
                codigos = [str(x.get("httpStatus")) for x in tentativas if x.get("httpStatus") is not None]
                resultado["reason"] = "Todas as URLs oficiais da Vivo falharam no runner. HTTP: %s" % ", ".join(codigos)
            elif response.status >= 400:
                resultado["reason"] = "HTTP %s antes da selecao da cidade" % response.status
            else:
                aceitar_cookies(page)
                ok, erro = selecionar_cidade(page)
                resultado["locationConfirmed"] = ok and local_confirmado(page)
                if resultado["locationConfirmed"]:
                    resultado["fiberOffers"], resultado["fiberMobileOffers"] = extrair_ofertas(page)
                if not ok:
                    resultado["reason"] = erro
                elif not resultado["locationConfirmed"]:
                    resultado["reason"] = "Campinas/SP nao confirmada no conteudo retornado"
                elif not resultado["fiberOffers"]:
                    resultado["reason"] = "Cidade confirmada, mas nenhuma oferta Vivo Fibra foi extraida"
                else:
                    resultado["status"] = "validada_piloto"

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
