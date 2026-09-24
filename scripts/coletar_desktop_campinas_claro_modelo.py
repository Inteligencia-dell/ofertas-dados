#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Desktop Campinas no mesmo modelo analitico do piloto Claro.

Saida principal:
- locationConfirmed
- fiberOffers
- fiberMobileOffers
- tvOffersAccepted

Regras:
- Fibra: internet residencial pura ou com Desktop Play de cortesia.
- Fibra + Movel: internet residencial e Desktop Movel no mesmo card.
- TV linear, canais e Desktop Play pago sao excluidos.
- Nenhum arquivo de producao e alterado.
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
SAIDA = RAIZ / "dados" / "piloto-desktop-campinas-claro-modelo.json"
EVID = RAIZ / "evidencias-desktop-campinas-claro-modelo"
URL = "https://www.desktop.com.br/"
TIMEOUT = 60000


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def norm(valor):
    s = unicodedata.normalize("NFD", str(valor or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().upper()


def visivel(loc):
    try:
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def aceitar_cookies(page):
    for loc in [
        page.get_by_role("button", name=re.compile(r"aceitar|concordar|entendi", re.I)),
        page.get_by_text(re.compile(r"aceitar todos", re.I), exact=False),
    ]:
        if visivel(loc):
            try:
                loc.first.click(timeout=5000)
                page.wait_for_timeout(800)
                return
            except Exception:
                pass


def selecionar_campinas(page):
    page.wait_for_timeout(3500)
    texto = page.locator("body").inner_text()
    if re.search(r"Campinas\s*/\s*SP", texto, re.I):
        confirmar = page.get_by_role("button", name=re.compile(r"confirmar localiza", re.I))
        if visivel(confirmar):
            try:
                confirmar.first.click()
                page.wait_for_timeout(4000)
            except Exception:
                pass
        return True
    return False


def clicar_aba(page, rotulo):
    resultado = page.evaluate("""label => {
      const limpar = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
      const alvo = limpar(label);
      const elementos = Array.from(document.querySelectorAll('button,a,[role=tab],[role=button]'));
      const el = elementos.find(x => limpar(x.innerText || x.textContent) === alvo &&
        (x.offsetWidth || x.offsetHeight || x.getClientRects().length));
      if (!el) return {clicked:false};
      el.scrollIntoView({block:'center'});
      el.click();
      return {clicked:true, tag:el.tagName, text:(el.innerText || '').trim(), className:el.className || null};
    }""", rotulo)
    page.wait_for_timeout(4500)
    return resultado


def extrair_cards_visiveis(page):
    """Retorna o menor ancestral de cada CTA Assine ja que representa um card."""
    return page.evaluate("""() => {
      const limpar = s => (s || '').replace(/\\s+/g, ' ').trim();
      const ctas = Array.from(document.querySelectorAll('a,button')).filter(el => {
        const t = limpar(el.innerText || el.textContent);
        return /^assine j[aá]$/i.test(t) && (el.offsetWidth || el.offsetHeight || el.getClientRects().length);
      });
      const cards = [];
      for (const cta of ctas) {
        let n = cta;
        let eleito = null;
        for (let i=0; i<12 && n; i++, n=n.parentElement) {
          const t = limpar(n.innerText || n.textContent);
          if (/(?:\\d+\\s*mega|\\d+(?:[,.]\\d+)?\\s*giga)/i.test(t) &&
              /R\\$\\s*\\d+/i.test(t) && t.length >= 30 && t.length <= 1800) {
            eleito = t;
            break;
          }
        }
        if (eleito) cards.push(eleito);
      }
      return [...new Set(cards)];
    }""")


def velocidade(texto):
    m = re.search(r"(\d{2,5})\s*MEGA\b", texto, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"([0-9](?:[,.][0-9])?)\s*GIGA\b", texto, re.I)
    return int(round(float(m.group(1).replace(",", ".")) * 1000)) if m else None


def precos(texto):
    valores = []
    for m in re.finditer(r"R\$\s*([0-9]{1,4})[,.]([0-9]{2})", texto, re.I):
        try:
            valores.append(round(float(f"{m.group(1)}.{m.group(2)}"), 2))
        except Exception:
            pass
    return valores


def franquias_moveis(texto):
    encontrados = re.findall(r"(?:DESKTOP\s+M[OÓ]VEL|CELULAR)\s*(\d{1,4})\s*GB", texto, re.I)
    return sorted(set(int(x) for x in encontrados))


def rejeitado_por_tv(texto):
    t = norm(texto)
    return any(x in t for x in [
        "TV + INTERNET", "INTERNET + TV", "67 CANAIS", "60 CANAIS",
        "CANAIS EM HD", "CANAIS AO VIVO"
    ])


def classificar_fibra(texto):
    if rejeitado_por_tv(texto):
        return None
    t = norm(texto)
    play = "DESKTOP PLAY" in t
    play_cortesia = play and "CORTESIA" in t
    if play and not play_cortesia:
        return None
    if franquias_moveis(texto):
        return None
    speed = velocidade(texto)
    valores = precos(texto)
    if speed is None or not valores:
        return None
    atual = valores[0]
    posterior = valores[1] if len(valores) > 1 and valores[1] != atual else None
    nome = "Fibra " + ("1 Giga" if speed == 1000 else f"{speed} Mega")
    return {
        "offerType": "fibra",
        "convergenceType": None,
        "name": nome,
        "fixedSpeedMb": speed,
        "monthlyPrice": atual,
        "previousPrice": None,
        "postPromotionPrice": posterior,
        "desktopPlayIncluded": play,
        "desktopPlayCourtesy": play_cortesia,
        "tvIncluded": False,
        "sourceSection": "internet",
        "cardText": texto[:1000],
    }


def classificar_convergentes(texto):
    if rejeitado_por_tv(texto):
        return []
    speed = velocidade(texto)
    valores = precos(texto)
    gbs = franquias_moveis(texto)
    if speed is None or not valores or not gbs:
        return []
    atual = valores[0]
    posterior = valores[1] if len(valores) > 1 and valores[1] != atual else None
    saida = []
    for gb in gbs:
        saida.append({
            "offerType": "convergente",
            "convergenceType": "fibra_movel",
            "name": f"{speed} Mega + Movel {gb} GB",
            "fixedSpeedMb": speed,
            "mobilePlanType": "movel",
            "mobileAllowanceGb": gb,
            "monthlyPrice": atual,
            "previousPrice": None,
            "postPromotionPrice": posterior,
            "desktopPlayIncluded": "DESKTOP PLAY" in norm(texto),
            "desktopPlayCourtesy": "CORTESIA" in norm(texto),
            "tvIncluded": False,
            "sourceSection": "internet_celular",
            "cardText": texto[:1000],
        })
    return saida


def deduplicar(ofertas):
    unicos = {}
    for o in ofertas:
        chave = (o["name"], o["monthlyPrice"], o.get("postPromotionPrice"))
        unicos[chave] = o
    return list(unicos.values())


def salvar(page, nome):
    (EVID / f"{nome}.html").write_text(page.content(), encoding="utf-8")
    page.screenshot(path=str(EVID / f"{nome}.png"), full_page=True)


def main():
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    EVID.mkdir(parents=True, exist_ok=True)
    resultado = {
        "operator": "Desktop",
        "city": "CAMPINAS",
        "uf": "SP",
        "generated": agora(),
        "source": URL,
        "locationConfirmed": False,
        "fiberOffers": [],
        "fiberMobileOffers": [],
        "tvOffersAccepted": 0,
        "productionFilesChanged": False,
        "status": "a_validar",
    }
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo", viewport={"width":1440,"height":1100})
            page = context.new_page()
            page.set_default_timeout(TIMEOUT)
            response = page.goto(URL, wait_until="domcontentloaded", timeout=TIMEOUT)
            page.wait_for_timeout(6000)
            aceitar_cookies(page)
            resultado["httpStatus"] = response.status if response else None
            resultado["locationConfirmed"] = selecionar_campinas(page)
            corpo = page.locator("body").inner_text()
            resultado["campinasComingSoon"] = bool(re.search(r"Em breve estaremos na sua regi[aã]o", corpo, re.I))

            resultado["internetTabClick"] = clicar_aba(page, "Internet")
            textos_fibra = extrair_cards_visiveis(page)
            resultado["internetCardsInspected"] = len(textos_fibra)
            resultado["fiberOffers"] = deduplicar([x for x in (classificar_fibra(t) for t in textos_fibra) if x])
            salvar(page, "01-internet")

            resultado["internetMobileTabClick"] = clicar_aba(page, "Internet + Celular")
            textos_movel = extrair_cards_visiveis(page)
            resultado["internetMobileCardsInspected"] = len(textos_movel)
            convergentes = []
            for texto in textos_movel:
                convergentes.extend(classificar_convergentes(texto))
            resultado["fiberMobileOffers"] = deduplicar(convergentes)
            salvar(page, "02-internet-celular")

            resultado["fiberOffers"] = sorted(resultado["fiberOffers"], key=lambda x:(x["fixedSpeedMb"],x["monthlyPrice"]))
            resultado["fiberMobileOffers"] = sorted(resultado["fiberMobileOffers"], key=lambda x:(x["fixedSpeedMb"],x["mobileAllowanceGb"]))
            resultado["status"] = "validada_piloto" if resultado["fiberOffers"] and resultado["fiberMobileOffers"] else "extracao_incompleta"
            if resultado["status"] != "validada_piloto":
                resultado["reason"] = "A coleta exige ao menos uma oferta Fibra e uma oferta Fibra + Movel"
            context.close()
            browser.close()
    except PlaywrightTimeoutError as erro:
        resultado["reason"] = "Timeout Playwright: " + str(erro)[:180]
    except Exception as erro:
        resultado["reason"] = f"{type(erro).__name__}: {str(erro)[:180]}"

    SAIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
