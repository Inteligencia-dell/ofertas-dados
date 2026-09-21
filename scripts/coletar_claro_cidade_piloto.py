#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piloto seguro: seleciona Campinas/SP e extrai somente Fibra residencial.

Nao altera dados/ofertas.json nem dados/status/index.json.
Gera apenas dados/piloto-claro-cidade.json e evidencias temporarias.
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
SAIDA = RAIZ / "dados" / "piloto-claro-cidade.json"
EVIDENCIAS = RAIZ / "evidencias-claro-cidade"
URL = "https://www.claro.com.br/"
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
        page.get_by_role("button", name=re.compile(r"aceitar|concordar|continuar", re.I)),
        page.get_by_text(re.compile(r"aceitar todos", re.I)),
    ])
    if botao:
        try:
            botao.click(timeout=5000)
        except Exception:
            pass


def abrir_seletor(page):
    candidatos = [
        page.get_by_text(re.compile(r"voce esta em|trocar cidade|alterar cidade|ofertas para", re.I)),
        page.get_by_role("button", name=re.compile(r"localizacao|cidade|alterar", re.I)),
        page.locator("[aria-label*='cidade' i]"),
        page.locator("[class*='location' i]"),
    ]
    alvo = primeiro_visivel(candidatos)
    if alvo:
        try:
            alvo.click(timeout=10000)
            page.wait_for_timeout(1500)
            return True
        except Exception:
            pass
    return False


def localizar_campo_cidade(page):
    seletores = [
        "input[name='autocompleteCities']",
        "input[placeholder*='cidade' i]",
        "input[aria-label*='cidade' i]",
        "input[name*='cidade' i]",
        "input[id*='cidade' i]",
        "input[type='search']",
        "input[type='text']",
        "textarea[placeholder*='cidade' i]",
        "[contenteditable='true']",
    ]
    for seletor in seletores:
        candidatos = page.locator(seletor)
        try:
            quantidade = candidatos.count()
        except Exception:
            continue
        for indice in range(quantidade):
            candidato = candidatos.nth(indice)
            try:
                if candidato.is_visible() and candidato.is_enabled() and candidato.is_editable():
                    return candidato
            except Exception:
                continue
    return None


def selecionar_cidade(page):
    page.wait_for_timeout(3000)
    opcoes = [
        page.locator("button[data-gtm-event-label='lista-cidades-padrao-campinas-sp']"),
        page.get_by_role("button", name=re.compile(r"^\s*Campinas\s*/\s*SP\s*$", re.I)),
    ]
    opcao = primeiro_visivel(opcoes)
    if opcao is None:
        abrir_seletor(page)
        page.wait_for_timeout(2500)
        opcao = primeiro_visivel(opcoes)
    if opcao is None:
        return False, "Botao direto Campinas/SP nao localizado"
    try:
        opcao.click()
    except Exception as erro:
        return False, "Falha ao clicar em Campinas/SP: %s" % str(erro)[:150]
    page.wait_for_timeout(8000)
    return True, None


def local_confirmado(texto):
    t = norm(texto)
    return "CAMPINAS" in t and bool(re.search(r"(^|[\s/\-(])SP([\s/\-)]|$)", t))


def converter_preco(valor_inteiro, valor_centavos):
    try:
        inteiro = re.sub(r"\D", "", str(valor_inteiro or ""))
        centavos = re.sub(r"\D", "", str(valor_centavos or ""))
        if not inteiro:
            return None
        centavos = (centavos + "00")[:2]
        return round(float("%s.%s" % (inteiro, centavos)), 2)
    except Exception:
        return None


def extrair_ofertas(page):
    """Extrai somente cards Fibra residenciais, pareando dentro do mesmo card."""
       secao_residencial = page.locator(
        "section.cms-Card360.has-title"
    ).filter(
        has_text=re.compile(
            r"As melhores ofertas de conectividade "
            r"para sua casa e seu celular",
            re.I,
        )
    ).first

    cards = secao_residencial.locator(
        "div.mdn-Card.mdn-Card--default"
    )
    if secao_residencial.count() == 0:
        return []
    ofertas = []
    vistos = set()

    for indice in range(cards.count()):
        card = cards.nth(indice)
        try:
            texto = re.sub(r"\s+", " ", card.inner_text()).strip()
        except Exception:
            continue

        if not re.match(r"^Fibra\b", texto, re.I):
            continue

        velocidade = re.search(r"(\d{2,5})\s*Mega\b", texto, re.I)
        if not velocidade:
            continue

        preco_inteiro = card.locator(".mdn-Price-main-price")
        preco_centavos = card.locator(".mdn-Price-main-cents")
        if preco_inteiro.count() == 0:
            continue

        try:
            inteiro = preco_inteiro.first.inner_text()
            centavos = preco_centavos.first.inner_text() if preco_centavos.count() else "00"
        except Exception:
            continue

        preco = converter_preco(inteiro, centavos)
        if preco is None:
            continue

        speed = int(velocidade.group(1))
        chave = (speed, preco)
        if chave in vistos:
            continue
        vistos.add(chave)

        beneficios = []
        texto_normalizado = norm(texto)
        mapa = [
            ("WI-FI GRATIS", "Wi-Fi grátis"),
            ("INSTALACAO RAPIDA", "Instalação rápida"),
            ("STREAMING INCLUSO", "Streaming incluso"),
            ("APPS INCLUSOS", "Apps inclusos"),
        ]
        for termo, descricao in mapa:
            if termo in texto_normalizado:
                beneficios.append(descricao)

        ofertas.append({
            "name": "Fibra %d Mega" % speed,
            "speed": speed,
            "price": preco,
            "category": "internet_residencial",
            "benefits": beneficios,
            "cardText": texto[:500],
        })

    return sorted(ofertas, key=lambda oferta: (oferta["speed"], oferta["price"]))


def main():
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    resultado = {
        "operator": "Claro",
        "city": CIDADE,
        "uf": UF,
        "source": URL,
        "generated": agora(),
        "locationConfirmed": False,
        "offersFound": [],
        "status": "a validar",
        "productionFilesChanged": False,
    }

    screenshot = EVIDENCIAS / "claro-campinas.png"
    html_file = EVIDENCIAS / "claro-campinas.html"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )
            context = browser.new_context(
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 1440, "height": 1000},
            )
            page = context.new_page()
            page.set_default_timeout(TIMEOUT)
            response = page.goto(URL, wait_until="domcontentloaded", timeout=TIMEOUT)
            page.wait_for_timeout(4000)
            resultado["httpStatus"] = response.status if response else None

            if response and response.status >= 400:
                resultado["reason"] = "HTTP %s recebido antes da selecao da cidade" % response.status
            else:
                aceitar_cookies(page)
                ok, erro = selecionar_cidade(page)
                texto = page.locator("body").inner_text()
                resultado["locationConfirmed"] = ok and local_confirmado(texto)
                resultado["offersFound"] = (
                    extrair_ofertas(page)
                    if resultado["locationConfirmed"]
                    else []
                )
                if not ok:
                    resultado["reason"] = erro
                elif not resultado["locationConfirmed"]:
                    resultado["reason"] = "Campinas/SP nao confirmada no conteudo retornado"
                elif not resultado["offersFound"]:
                    resultado["reason"] = "Cidade confirmada, mas nenhuma oferta residencial extraida"
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

    resultado["evidenceScreenshot"] = str(screenshot.relative_to(RAIZ)) if screenshot.exists() else None
    resultado["evidenceHtml"] = str(html_file.relative_to(RAIZ)) if html_file.exists() else None
    SAIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
