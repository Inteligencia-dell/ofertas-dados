#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piloto seguro da Claro por cidade para cinco localidades.

Consulta apenas a vitrine residencial da Claro por cidade, gera evidencias e
NAO altera dados/ofertas.json nem dados/status/index.json.
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
SAIDA = RAIZ / "dados" / "piloto-claro-fibra-movel-5-cidades.json"
EVIDENCIAS = RAIZ / "evidencias-claro-fibra-movel-5-cidades"
URL = "https://www.claro.com.br/"
TIMEOUT = 60000
ESPERA_CIDADE = 8000

CIDADES = [
    {"city": "ADAMANTINA", "uf": "SP"},
    {"city": "CAMPINAS", "uf": "SP"},
    {"city": "RIBEIRAO PRETO", "uf": "SP"},
    {"city": "SAO JOSE DOS CAMPOS", "uf": "SP"},
    {"city": "SOROCABA", "uf": "SP"},
]


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def norm(valor):
    texto = unicodedata.normalize("NFD", str(valor or ""))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip().upper()


def slug(valor):
    return re.sub(r"[^a-z0-9]+", "-", norm(valor).lower()).strip("-")


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


def modal_cidade_aberto(page):
    campo = page.locator("input[name='autocompleteCities']")
    try:
        return campo.count() > 0 and campo.first.is_visible()
    except Exception:
        return False


def abrir_seletor(page):
    if modal_cidade_aberto(page):
        return True
    candidatos = [
        page.get_by_text(re.compile(r"voc[eê] est[aá] em|trocar cidade|alterar cidade|ofertas para", re.I)),
        page.get_by_role("button", name=re.compile(r"localiza[cç][aã]o|cidade|alterar", re.I)),
        page.locator("button[data-gtm-event-action='clique:modal-cidades']"),
        page.locator("[aria-label*='cidade' i]"),
        page.locator("[class*='location' i]"),
    ]
    for grupo in candidatos:
        try:
            quantidade = grupo.count()
        except Exception:
            continue
        for indice in range(min(quantidade, 30)):
            item = grupo.nth(indice)
            try:
                if not item.is_visible():
                    continue
                item.click(timeout=10000)
                page.wait_for_timeout(1800)
                if modal_cidade_aberto(page):
                    return True
            except Exception:
                continue
    return modal_cidade_aberto(page)

def localizar_campo_cidade(page):
    seletores = [
        "input[name='autocompleteCities']",
        "input[placeholder*='cidade' i]",
        "input[aria-label*='cidade' i]",
        "input[name*='cidade' i]",
        "input[id*='cidade' i]",
        "input[type='search']",
    ]
    for seletor in seletores:
        candidatos = page.locator(seletor)
        for indice in range(candidatos.count()):
            candidato = candidatos.nth(indice)
            try:
                if candidato.is_visible() and candidato.is_enabled() and candidato.is_editable():
                    return candidato
            except Exception:
                continue
    return None


def localizar_opcao_cidade(page, cidade, uf):
    seletor = (
        "button[data-gtm-event-label='alterar-cidade-%s-%s']"
        % (slug(cidade), uf.lower())
    )
    opcao = primeiro_visivel([page.locator(seletor)])
    if opcao is not None:
        return opcao
    alvo_cidade = norm(cidade)
    alvo_uf = norm(uf)
    candidatos = page.locator("button[data-gtm-event-label^='alterar-cidade-']")
    for indice in range(candidatos.count()):
        candidato = candidatos.nth(indice)
        try:
            if not candidato.is_visible():
                continue
            texto = norm(candidato.inner_text())
            if alvo_cidade in texto and re.search(
                r"(^|[\s/\-(])%s([\s/\-)]|$)" % re.escape(alvo_uf), texto
            ):
                return candidato
        except Exception:
            continue
    return None


def selecionar_cidade(page, cidade, uf):
    page.wait_for_timeout(2500)
    label_padrao = "lista-cidades-padrao-%s-%s" % (slug(cidade), uf.lower())
    opcao = primeiro_visivel([
        page.locator("button[data-gtm-event-label='%s']" % label_padrao),
    ])
    if opcao is None:
        abrir_seletor(page)
        page.wait_for_timeout(1800)
        opcao = primeiro_visivel([
            page.locator("button[data-gtm-event-label='%s']" % label_padrao),
        ])
    if opcao is None:
        campo = localizar_campo_cidade(page)
        if campo is None:
            abrir_seletor(page)
            page.wait_for_timeout(2000)
            campo = localizar_campo_cidade(page)
        if campo is None:
            return False, "Campo editavel de cidade nao localizado"
        try:
            campo.click()
            campo.fill(cidade.title())
        except Exception:
            try:
                campo.click()
                campo.press("Control+A")
                campo.press_sequentially(cidade.title(), delay=120)
            except Exception as erro:
                return False, "Falha ao preencher cidade: %s" % str(erro)[:150]
        page.wait_for_timeout(4000)
        opcao = localizar_opcao_cidade(page, cidade, uf)
    if opcao is None:
        return False, "Opcao %s/%s nao localizada" % (cidade, uf)
    try:
        opcao.click()
    except Exception as erro:
        return False, "Falha ao selecionar %s/%s: %s" % (cidade, uf, str(erro)[:130])
    page.wait_for_timeout(ESPERA_CIDADE)
    return True, None

def local_confirmado(texto, cidade, uf):
    pagina = norm(texto)
    cidade_ok = norm(cidade) in pagina
    uf_ok = bool(re.search(r"(^|[\s/\-(])%s([\s/\-)]|$)" % re.escape(norm(uf)), pagina))
    return cidade_ok and uf_ok


def converter_preco(valor_inteiro, valor_centavos):
    try:
        inteiro = re.sub(r"\D", "", str(valor_inteiro or ""))
        centavos = re.sub(r"\D", "", str(valor_centavos or ""))
        if not inteiro:
            return None
        return round(float("%s.%s" % (inteiro, (centavos + "00")[:2])), 2)
    except Exception:
        return None


def extrair_ofertas(page):
    secoes = page.locator("section.cms-Card360.has-title")
    secao_residencial = None
    for indice in range(secoes.count()):
        secao = secoes.nth(indice)
        try:
            texto_secao = norm(secao.inner_text())
        except Exception:
            continue
        if "MELHORES OFERTAS DE CONECTIVIDADE PARA SUA CASA E SEU CELULAR" in texto_secao:
            secao_residencial = secao
            break
    if secao_residencial is None:
        return []

    ofertas = []
    vistos = set()
    cards = secao_residencial.locator("div.mdn-Card.mdn-Card--default")
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
        inteiros = card.locator(".mdn-Price-main-price")
        centavos = card.locator(".mdn-Price-main-cents")
        if inteiros.count() == 0:
            continue
        try:
            preco = converter_preco(
                inteiros.first.inner_text(),
                centavos.first.inner_text() if centavos.count() else "00",
            )
        except Exception:
            continue
        if preco is None:
            continue
        speed = int(velocidade.group(1))
        chave = (speed, preco)
        if chave in vistos:
            continue
        vistos.add(chave)
        ofertas.append({
            "name": "Fibra %d Mega" % speed,
            "speed": speed,
            "price": preco,
            "category": "internet_residencial",
            "cardText": texto[:500],
        })
    return sorted(ofertas, key=lambda oferta: (oferta["speed"], oferta["price"]))


def extrair_preco_anterior(texto):
    achados = re.findall(
        r"De:\s*R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+)[,.]([0-9]{2})",
        texto,
        re.I,
    )
    if not achados:
        return None
    inteiro, centavos = achados[0]
    return converter_preco(inteiro, centavos)


def extrair_velocidade(texto):
    mega = re.search(r"(\d{2,5})\s*Mega\b", texto, re.I)
    if mega:
        return int(mega.group(1))
    giga = re.search(r"([0-9](?:[,.][0-9])?)\s*Giga\b", texto, re.I)
    if giga:
        return int(round(float(giga.group(1).replace(",", ".")) * 1000))
    return None


def extrair_ofertas_fibra_movel(page):
    """Aceita somente Fibra + Movel. Rejeita qualquer componente de TV."""
    secoes = page.locator("section.cms-Card360.has-title")
    secao_multi = None
    for indice in range(secoes.count()):
        secao = secoes.nth(indice)
        try:
            texto_secao = norm(secao.inner_text())
        except Exception:
            continue
        if "CLARO MULTI: GIGAVELOCIDADE, 5G E STREAMINGS JUNTOS" in texto_secao:
            secao_multi = secao
            break
    if secao_multi is None:
        return []

    ofertas = []
    vistos = set()
    cards = secao_multi.locator("div.mdn-Card.mdn-Card--default")
    for indice in range(cards.count()):
        card = cards.nth(indice)
        try:
            texto = re.sub(r"\s+", " ", card.inner_text()).strip()
        except Exception:
            continue
        texto_norm = norm(texto)
        velocidade = extrair_velocidade(texto)
        movel = re.search(r"\b(P[oó]s|Controle)\s*(\d+)\s*GB\b", texto, re.I)
        if velocidade is None or not movel:
            continue
        if any(termo in texto_norm for termo in [
            "CLARO TV", "TV+", "TV +", "BOX", "CANAIS AO VIVO",
        ]):
            continue

        inteiros = card.locator(".mdn-Price-main-price")
        centavos = card.locator(".mdn-Price-main-cents")
        if inteiros.count() == 0:
            continue
        preco = converter_preco(
            inteiros.first.inner_text(),
            centavos.first.inner_text() if centavos.count() else "00",
        )
        if preco is None:
            continue

        franquia_total = int(movel.group(2))
        bonus = re.search(r"(\d+)\s*GB\s*\+\s*(\d+)\s*GB\s*B[oô]nus", texto, re.I)
        base_gb = int(bonus.group(1)) if bonus else None
        bonus_gb = int(bonus.group(2)) if bonus else None
        tipo_movel = "pos" if norm(movel.group(1)) == "POS" else "controle"
        chave = (velocidade, tipo_movel, franquia_total, preco)
        if chave in vistos:
            continue
        vistos.add(chave)

        ofertas.append({
            "offerType": "convergente",
            "convergenceType": "fibra_movel",
            "name": "%s + %s %d GB" % (
                "1 Giga" if velocidade == 1000 else "%d Mega" % velocidade,
                "Pós" if tipo_movel == "pos" else "Controle",
                franquia_total,
            ),
            "fixedSpeedMb": velocidade,
            "mobilePlanType": tipo_movel,
            "mobileAllowanceGb": franquia_total,
            "mobileBaseAllowanceGb": base_gb,
            "mobileBonusGb": bonus_gb,
            "tvIncluded": False,
            "monthlyPrice": preco,
            "previousPrice": extrair_preco_anterior(texto),
            "sourceSection": "claro_multi",
            "cardText": texto[:700],
        })
    return sorted(
        ofertas,
        key=lambda oferta: (
            oferta["fixedSpeedMb"],
            oferta["mobileAllowanceGb"],
            oferta["monthlyPrice"],
        ),
    )


def consultar_cidade(browser, cidade, uf):
    nome_slug = "%s-%s" % (slug(cidade), uf.lower())
    screenshot = EVIDENCIAS / (nome_slug + ".png")
    html_file = EVIDENCIAS / (nome_slug + ".html")
    resultado = {
        "operator": "Claro", "city": cidade, "uf": uf, "source": URL,
        "generated": agora(), "locationConfirmed": False, "offersFound": [],
        "status": "a validar", "productionFilesChanged": False,
        "fiberOffers": [], "fiberMobileOffers": [], "tvOffersAccepted": 0,
    }
    context = None
    try:
        context = browser.new_context(
            locale="pt-BR", timezone_id="America/Sao_Paulo",
            viewport={"width": 1440, "height": 1000},
        )
        page = context.new_page()
        page.set_default_timeout(TIMEOUT)
        response = page.goto(URL, wait_until="domcontentloaded", timeout=TIMEOUT)
        page.wait_for_timeout(4000)
        resultado["httpStatus"] = response.status if response else None
        if response and response.status >= 400:
            resultado["reason"] = "HTTP %s antes da selecao da cidade" % response.status
        else:
            aceitar_cookies(page)
            ok, erro = selecionar_cidade(page, cidade, uf)
            texto = page.locator("body").inner_text()
            resultado["locationConfirmed"] = ok and local_confirmado(texto, cidade, uf)
            resultado["fiberOffers"] = extrair_ofertas(page) if resultado["locationConfirmed"] else []
            resultado["fiberMobileOffers"] = extrair_ofertas_fibra_movel(page) if resultado["locationConfirmed"] else []
            resultado["offersFound"] = resultado["fiberOffers"] + resultado["fiberMobileOffers"]
            if not ok:
                resultado["reason"] = erro
            elif not resultado["locationConfirmed"]:
                resultado["reason"] = "%s/%s nao confirmada no conteudo" % (cidade, uf)
            elif not resultado["offersFound"]:
                resultado["reason"] = "Cidade confirmada, mas nenhuma oferta Fibra ou Fibra + Movel extraida"
            else:
                resultado["status"] = "validada_piloto"
        html_file.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(screenshot), full_page=True)
    except PlaywrightTimeoutError as erro:
        resultado["reason"] = "Timeout Playwright: %s" % str(erro)[:170]
    except Exception as erro:
        resultado["reason"] = "%s: %s" % (type(erro).__name__, str(erro)[:170])
    finally:
        if context:
            context.close()
    resultado["evidenceScreenshot"] = str(screenshot.relative_to(RAIZ)) if screenshot.exists() else None
    resultado["evidenceHtml"] = str(html_file.relative_to(RAIZ)) if html_file.exists() else None
    return resultado


def main():
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    resultados = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
        for alvo in CIDADES:
            resultado = consultar_cidade(browser, alvo["city"], alvo["uf"])
            resultados.append(resultado)
            print("[piloto] %-24s/%s | confirmado=%s | ofertas=%d | %s" % (
                alvo["city"], alvo["uf"], resultado["locationConfirmed"],
                len(resultado["offersFound"]), resultado.get("reason", resultado["status"])))
        browser.close()
    payload = {
        "meta": {"generated": agora(), "mode": "piloto_claro_fibra_movel_5_cidades", "productionFilesChanged": False},
        "summary": {
            "cities": len(resultados),
            "confirmed": sum(1 for r in resultados if r["locationConfirmed"]),
            "withOffers": sum(1 for r in resultados if r["offersFound"]),
            "pending": sum(1 for r in resultados if r["status"] == "a validar"),
        },
        "results": resultados,
    }
    SAIDA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
