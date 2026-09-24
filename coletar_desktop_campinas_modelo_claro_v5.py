#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Desktop Campinas v5, padronizado no mesmo modelo da Claro.

Extrai especificamente:
- Fibra: 600 Mega + Desktop Play de cortesia; 1 Giga + Desktop Play de cortesia.
- Fibra + Movel: 600 Mega + 15 Giga Celular; 600 Mega + 20 Giga Celular.

Nao usa velocidades de upload, textos de rodape ou cards de outras categorias.
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
SAIDA = RAIZ / "dados" / "piloto-desktop-campinas-modelo-claro-v5.json"
EVID = RAIZ / "evidencias-desktop-campinas-modelo-claro-v5"
URL = "https://www.desktop.com.br/"
TIMEOUT = 60000


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


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
    if not re.search(r"Campinas\s*/\s*SP", texto, re.I):
        return False
    confirmar = page.get_by_role("button", name=re.compile(r"confirmar localiza", re.I))
    if visivel(confirmar):
        try:
            confirmar.first.click()
            page.wait_for_timeout(4000)
        except Exception:
            pass
    return True


def clicar_aba(page, rotulo):
    retorno = page.evaluate("""label => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
      const alvo = norm(label);
      const elementos = Array.from(document.querySelectorAll('button,a,[role=tab],[role=button]'));
      const el = elementos.find(x => norm(x.innerText || x.textContent) === alvo &&
        (x.offsetWidth || x.offsetHeight || x.getClientRects().length));
      if (!el) return {clicked:false};
      el.scrollIntoView({block:'center'});
      el.click();
      return {clicked:true, tag:el.tagName, text:(el.innerText || '').trim()};
    }""", rotulo)
    page.wait_for_timeout(4500)
    return retorno


def cards_por_titulo(page, padrao_titulo):
    """Seleciona cards pelo titulo comercial, e nao pelo primeiro numero do ancestral."""
    return page.evaluate("""pattern => {
      const rx = new RegExp(pattern, 'i');
      const limpar = s => (s || '').replace(/\\s+/g, ' ').trim();
      const elementos = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,strong,p,span,div'))
        .filter(el => (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
      const titulos = elementos.filter(el => {
        const proprio = limpar(el.innerText || el.textContent);
        if (!rx.test(proprio) || proprio.length > 100) return false;
        return !Array.from(el.children || []).some(f => rx.test(limpar(f.innerText || f.textContent)));
      });
      const cards=[];
      for(const titulo of titulos){
        let n=titulo;
        for(let i=0;i<12 && n;i++,n=n.parentElement){
          const t=limpar(n.innerText || n.textContent);
          const temPreco=/R\\$\\s*\\d{1,4}[,.]\\d{2}/i.test(t);
          const temCTA=/assine j[aá]|contratar/i.test(t);
          if(temPreco && temCTA && t.length>=40 && t.length<=1600){cards.push(t);break;}
        }
      }
      return [...new Set(cards)];
    }""", padrao_titulo)


def preco_atual(texto):
    m = re.search(r"R\$\s*([0-9]{1,4})[,.]([0-9]{2})", texto, re.I)
    return round(float(f"{m.group(1)}.{m.group(2)}"), 2) if m else None


def preco_posterior(texto):
    m = re.search(r"Ap[oó]s[,]?\s*R\$\s*([0-9]{1,4})[,.]([0-9]{2})", texto, re.I)
    return round(float(f"{m.group(1)}.{m.group(2)}"), 2) if m else None


def oferta_fibra(texto):
    titulo = re.search(r"\b(600\s*MEGA|1\s*GIGA)\s*\+\s*DESKTOP\s*PLAY\b", texto, re.I)
    if not titulo or not re.search(r"DESKTOP\s*PLAY\s*DE\s*CORTESIA", texto, re.I):
        return None
    speed = 1000 if re.search(r"1\s*GIGA", titulo.group(1), re.I) else 600
    atual = preco_atual(texto)
    if atual is None:
        return None
    return {
        "offerType": "fibra",
        "convergenceType": None,
        "name": "Fibra " + ("1 Giga" if speed == 1000 else "600 Mega"),
        "fixedSpeedMb": speed,
        "monthlyPrice": atual,
        "previousPrice": None,
        "postPromotionPrice": preco_posterior(texto),
        "desktopPlayIncluded": True,
        "desktopPlayCourtesy": True,
        "tvIncluded": False,
        "sourceSection": "internet",
        "cardText": texto[:1000],
    }


def oferta_convergente(texto):
    titulo = re.search(r"600\s*MEGA\s*\+\s*(15|20)\s*GIGA\s*CELULAR", texto, re.I)
    if not titulo:
        return None
    franquia = int(titulo.group(1))
    atual = preco_atual(texto)
    if atual is None:
        return None
    return {
        "offerType": "convergente",
        "convergenceType": "fibra_movel",
        "name": f"600 Mega + Movel {franquia} GB",
        "fixedSpeedMb": 600,
        "mobilePlanType": "movel",
        "mobileAllowanceGb": franquia,
        "monthlyPrice": atual,
        "previousPrice": None,
        "postPromotionPrice": preco_posterior(texto),
        "desktopPlayIncluded": False,
        "desktopPlayCourtesy": False,
        "tvIncluded": False,
        "sourceSection": "internet_celular",
        "cardText": texto[:1000],
    }


def salvar(page, nome):
    (EVID / f"{nome}.html").write_text(page.content(), encoding="utf-8")
    page.screenshot(path=str(EVID / f"{nome}.png"), full_page=True)


def main():
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    EVID.mkdir(parents=True, exist_ok=True)
    d = {
        "operator": "Desktop", "city": "CAMPINAS", "uf": "SP",
        "generated": agora(), "source": URL, "locationConfirmed": False,
        "fiberOffers": [], "fiberMobileOffers": [], "tvOffersAccepted": 0,
        "status": "a_validar", "productionFilesChanged": False,
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
            d["httpStatus"] = response.status if response else None
            d["locationConfirmed"] = selecionar_campinas(page)
            corpo = page.locator("body").inner_text()
            d["campinasComingSoon"] = bool(re.search(r"Em breve estaremos na sua regi[aã]o", corpo, re.I))

            d["internetTabClick"] = clicar_aba(page, "Internet")
            cards_fibra = cards_por_titulo(page, r"^(600\\s*MEGA|1\\s*GIGA)\\s*\\+\\s*DESKTOP\\s*PLAY$")
            d["internetCardsMatched"] = len(cards_fibra)
            d["fiberOffers"] = [x for x in (oferta_fibra(t) for t in cards_fibra) if x]
            salvar(page, "01-internet")

            d["internetMobileTabClick"] = clicar_aba(page, "Internet + Celular")
            cards_movel = cards_por_titulo(page, r"^600\\s*MEGA\\s*\\+\\s*(15|20)\\s*GIGA\\s*CELULAR$")
            d["internetMobileCardsMatched"] = len(cards_movel)
            d["fiberMobileOffers"] = [x for x in (oferta_convergente(t) for t in cards_movel) if x]
            salvar(page, "02-internet-celular")

            d["fiberOffers"] = sorted({(o["fixedSpeedMb"],o["monthlyPrice"]):o for o in d["fiberOffers"]}.values(), key=lambda x:x["fixedSpeedMb"])
            d["fiberMobileOffers"] = sorted({o["mobileAllowanceGb"]:o for o in d["fiberMobileOffers"]}.values(), key=lambda x:x["mobileAllowanceGb"])
            esperado = len(d["fiberOffers"]) == 2 and len(d["fiberMobileOffers"]) == 2
            d["status"] = "validada_piloto" if esperado else "extracao_incompleta"
            if not esperado:
                d["reason"] = "Esperadas 2 ofertas Fibra com Desktop Play de cortesia e 2 ofertas Fibra + Movel"
            context.close()
            browser.close()
    except PlaywrightTimeoutError as erro:
        d["reason"] = "Timeout Playwright: " + str(erro)[:180]
    except Exception as erro:
        d["reason"] = f"{type(erro).__name__}: {str(erro)[:180]}"
    SAIDA.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(d, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
