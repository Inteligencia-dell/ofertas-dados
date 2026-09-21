#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piloto seguro: seleciona Campinas/SP no site principal da Claro.

Nao altera dados/ofertas.json nem dados/status/index.json.
Gera apenas dados/piloto-claro-cidade.json e evidencias temporarias.
"""

import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

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
                if (
                    candidato.is_visible()
                    and candidato.is_enabled()
                    and candidato.is_editable()
                ):
                    return candidato
            except Exception:
                continue

    return None
def selecionar_cidade(page):
    abrir_seletor(page)
    page.wait_for_timeout(2000)

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
            campo.press_sequentially(
                "Campinas",
                delay=120,
            )
        except Exception as erro:
            return (
                False,
                "Falha ao preencher campo de cidade: %s"
                % str(erro)[:150],
            )

    page.wait_for_timeout(3500)

    opcoes = [
        page.get_by_text(
            re.compile(
                r"Campinas\s*/\s*SP",
                re.I,
            ),
            exact=False,
        ),
        page.get_by_text(
            re.compile(
                r"Campinas\s*\(\s*SP\s*\)",
                re.I,
            ),
            exact=False,
        ),
        page.get_by_role(
            "option",
            name=re.compile(
                r"Campinas",
                re.I,
            ),
        ),
        page.get_by_role(
            "link",
            name=re.compile(
                r"Campinas",
                re.I,
            ),
        ),
        page.locator(
            "[role='option']"
        ).filter(
            has_text=re.compile(
                r"Campinas",
                re.I,
            ),
        ),
        page.locator(
            "li"
        ).filter(
            has_text=re.compile(
                r"Campinas",
                re.I,
            ),
        ),
    ]

    opcao = primeiro_visivel(opcoes)

    if opcao is None:
        return False, "Opcao Campinas/SP nao localizada"

    try:
        opcao.click()
    except Exception as erro:
        return (
            False,
            "Falha ao selecionar Campinas/SP: %s"
            % str(erro)[:150],
        )

    page.wait_for_timeout(6000)

    confirmar = primeiro_visivel([
        page.get_by_role(
            "button",
            name=re.compile(
                r"confirmar|continuar|selecionar",
                re.I,
            ),
        ),
        page.get_by_text(
            re.compile(
                r"^confirmar$",
                re.I,
            ),
        ),
    ])

    if confirmar:
        try:
            confirmar.click()
            page.wait_for_timeout(5000)
        except Exception:
            pass

    return True, None

def local_confirmado(texto):
    t = norm(texto)
    return "CAMPINAS" in t and bool(re.search(r"(^|[\s/\-(])SP([\s/\-)]|$)", t))


def extrair_ofertas(texto):
    precos = []
    for m in re.finditer(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+)(?:[,.]([0-9]{2}))?", texto):
        try:
            valor = float(m.group(1).replace(".", "") + "." + (m.group(2) or "00"))
        except ValueError:
            continue
        if 19 <= valor <= 2500:
            precos.append((valor, m.start()))

    velocidades = []
    for m in re.finditer(r"([0-9]{2,5})\s*(?:MEGA|MB|MBPS)\b", texto, re.I):
        v = int(m.group(1))
        if 50 <= v <= 10000:
            velocidades.append((v, m.start()))
    for m in re.finditer(r"([0-9](?:[,.][0-9])?)\s*(?:GIGA|GBPS)\b", texto, re.I):
        v = int(round(float(m.group(1).replace(",", ".")) * 1000))
        if 500 <= v <= 10000:
            velocidades.append((v, m.start()))

    pares = []
    vistos = set()
    for preco, pp in precos:
        if not velocidades:
            break
        vel, vp = min(velocidades, key=lambda x: abs(x[1] - pp))
        if abs(vp - pp) <= 550 and (vel, preco) not in vistos:
            vistos.add((vel, preco))
            pares.append({"speed": vel, "price": round(preco, 2), "distance": abs(vp - pp)})
    return sorted(pares, key=lambda x: (x["speed"], x["price"]))


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
            browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
            context = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo", viewport={"width": 1440, "height": 1000})
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
                resultado["offersFound"] = extrair_ofertas(texto) if resultado["locationConfirmed"] else []
                if not ok:
                    resultado["reason"] = erro
                elif not resultado["locationConfirmed"]:
                    resultado["reason"] = "Campinas/SP nao confirmada no conteudo retornado"
                elif not resultado["offersFound"]:
                    resultado["reason"] = "Cidade confirmada, mas nenhuma oferta pareada"
                else:
                    resultado["status"] = "validada_piloto"

            html_file.write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(screenshot), full_page=True)
            context.close()
            browser.close()

    except PlaywrightTimeoutError as e:
        resultado["reason"] = "Timeout Playwright: %s" % str(e)[:180]
    except Exception as e:
        resultado["reason"] = "%s: %s" % (type(e).__name__, str(e)[:180])

    resultado["evidenceScreenshot"] = str(screenshot.relative_to(RAIZ)) if screenshot.exists() else None
    resultado["evidenceHtml"] = str(html_file.relative_to(RAIZ)) if html_file.exists() else None
    SAIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
