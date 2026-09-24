#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coletor recorrente do portfolio publico Vivo para 97 cidades de referencia.

Metodologia:
- coleta uma unica landing publica Vivo Fibra + Pos;
- replica o portfolio como REFERENCIA PUBLICA para as 97 cidades informadas;
- nunca marca disponibilidade/localizacao municipal como confirmada;
- exclui cards com TV;
- preserva o ultimo resultado valido em caso de falha tecnica;
- nao altera dados/ofertas.json nem dados/status/index.json.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
SAIDA = DADOS / "vivo-portfolio-publico-97-cidades.json"
ULTIMO_VALIDO = DADOS / "vivo-portfolio-publico-97-cidades-ultimo-valido.json"
EVIDENCIAS = RAIZ / "evidencias-vivo-portfolio-publico-97-cidades"
URL = "https://internet.vivo.com.br/ofertas/fibra-e-pos/"
TIMEOUT = 60000
UF = "SP"

CIDADES = [
"ADAMANTINA","AMERICANA","AMERICO BRASILIENSE","AMPARO","ANDRADINA","APARECIDA","ARACATUBA","ARARAQUARA","ARARAS","ARTUR NOGUEIRA","AVARE","BARRETOS","BAURU","BEBEDOURO","BERTIOGA","BIRIGUI","BOITUVA","BOTUCATU","CACAPAVA","CAMPINAS","CAMPOS DO JORDAO","CARAGUATATUBA","CATANDUVA","COSMOPOLIS","CRUZEIRO","CUBATAO","DESCALVADO","DRACENA","ESPIRITO SANTO DO PINHAL","FERNANDOPOLIS","FRANCA","GARCA","GUARARAPES","GUARATINGUETA","GUARUJA","HORTOLANDIA","INDAIATUBA","ITANHAEM","ITAPETININGA","ITAPEVA","ITAPIRA","JABOTICABAL","JACAREI","JAGUARIUNA","JALES","JAU","LEME","LENCOIS PAULISTA","LIMEIRA","LINS","LORENA","LOUVEIRA","MARILIA","MATAO","MIRASSOL","MOCOCA","MOGI GUACU","MOGI MIRIM","NOVA ODESSA","OLIMPIA","OURINHOS","PAULINIA","PEDREIRA","PENAPOLIS","PERUIBE","PINDAMONHANGABA","PIRACICABA","PIRASSUNUNGA","PORTO FELIZ","PRAIA GRANDE","PRESIDENTE PRUDENTE","REGISTRO","RIBEIRAO PRETO","RIO CLARO","SANTA BARBARA D OESTE","SANTA CRUZ DO RIO PARDO","SANTOS","SAO CARLOS","SAO JOAO DA BOA VISTA","SAO JOSE DO RIO PARDO","SAO JOSE DO RIO PRETO","SAO JOSE DOS CAMPOS","SAO SEBASTIAO","SAO VICENTE","SERRA NEGRA","SERTAOZINHO","SOROCABA","SUMARE","TATUI","TAUBATE","TIETE","TREMEMBE","UBATUBA","VALINHOS","VINHEDO","VOTORANTIM","VOTUPORANGA"
]


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def todos_precos(texto):
    valores=[]
    for m in re.finditer(r"R\$\s*([0-9]{1,4})(?:[,.]\s*([0-9]{2}))?", texto, re.I):
        try: valores.append(round(float(f"{m.group(1)}.{m.group(2) or '00'}"),2))
        except Exception: pass
    return valores


def preco_do_card(card):
    """Le o preco comercial nos elementos de preco, ignorando valores de tooltips."""
    atual = None
    anterior = None
    try:
        loc = card.locator("span[id='price']")
        if loc.count():
            valores = todos_precos(loc.first.inner_text())
            atual = valores[-1] if valores else None
    except Exception:
        pass
    try:
        loc = card.locator("span[class*='oldPrice']")
        if loc.count():
            valores = todos_precos(loc.first.inner_text())
            anterior = valores[-1] if valores else None
    except Exception:
        pass
    return atual, anterior


def velocidade(texto):
    m=re.search(r"(\d{2,5})\s*Mega\b",texto,re.I)
    if m: return int(m.group(1))
    m=re.search(r"([0-9](?:[,.][0-9])?)\s*Giga\b",texto,re.I)
    return int(round(float(m.group(1).replace(',','.'))*1000)) if m else None


def franquias(texto):
    total=re.search(r"(\d{1,4})\s*GB\s*de Vivo P[oó]s",texto,re.I)
    bonus=re.search(r"(\d{1,4})\s*GB de franquia\s*\+\s*(\d{1,4})\s*GB de b[oô]nus",texto,re.I)
    return {
        "total": int(total.group(1)) if total else None,
        "base": int(bonus.group(1)) if bonus else None,
        "bonus": int(bonus.group(2)) if bonus else None,
    }


def texto_card(card):
    return re.sub(r"\s+"," ",card.inner_text()).strip()


def extrair(page):
    fibra=[]; movel=[]
    for i in range(page.locator("div[id^='fibra-']").count()):
        card=page.locator("div[id^='fibra-']").nth(i); texto=texto_card(card)
        if re.search(r"\bTV\b|canais ao vivo",texto,re.I): continue
        speed=velocidade(texto); atual,anterior=preco_do_card(card)
        if speed is None or atual is None: continue
        fibra.append({
            "offerType":"fibra","convergenceType":None,
            "name":"Vivo Fibra "+("1 Giga" if speed==1000 else f"{speed} Mega"),
            "fixedSpeedMb":speed,"monthlyPrice":atual,"previousPrice":anterior,
            "tvIncluded":False,"sourceSection":"vivo_fibra","cardId":card.get_attribute("id")
        })
    for i in range(page.locator("div[id^='total-']").count()):
        card=page.locator("div[id^='total-']").nth(i); texto=texto_card(card)
        if re.search(r"\bTV\b|canais ao vivo",texto,re.I): continue
        speed=velocidade(texto); dados=franquias(texto); atual,anterior=preco_do_card(card)
        if speed is None or dados["total"] is None or atual is None: continue
        comercial=re.search(r"(Vivo Total[^0-9]+?)\s+\d{2,5}\s*(?:Mega|Giga)",texto,re.I)
        movel.append({
            "offerType":"convergente","convergenceType":"fibra_movel",
            "name":f"{speed} Mega + Pos {dados['total']} GB",
            "commercialName":comercial.group(1).strip() if comercial else None,
            "fixedSpeedMb":speed,"mobilePlanType":"pos","mobileAllowanceGb":dados["total"],
            "mobileBaseAllowanceGb":dados["base"],"mobileBonusGb":dados["bonus"],
            "monthlyPrice":atual,"previousPrice":anterior,"tvIncluded":False,
            "sourceSection":"vivo_total","cardId":card.get_attribute("id")
        })
    return fibra,movel


def assinatura(ofertas):
    return json.dumps(ofertas,ensure_ascii=False,sort_keys=True,separators=(",",":"))


def carregar_ultimo():
    if not ULTIMO_VALIDO.exists(): return None
    try: return json.loads(ULTIMO_VALIDO.read_text(encoding="utf-8"))
    except Exception: return None


def main():
    assert len(CIDADES)==97, f"Esperadas 97 cidades, recebidas {len(CIDADES)}"
    DADOS.mkdir(parents=True,exist_ok=True); EVIDENCIAS.mkdir(parents=True,exist_ok=True)
    html=EVIDENCIAS/"vivo-portfolio-publico.html"; png=EVIDENCIAS/"vivo-portfolio-publico.png"
    ultimo=carregar_ultimo()
    resultado={
        "operator":"Vivo","generated":agora(),"source":URL,
        "collectionMode":"portfolio_publico_replicado_como_referencia",
        "territorialScope":"publico_nao_confirmado","locationConfirmed":False,
        "municipalAvailabilityConfirmed":False,"technicalFeasibilityRequired":True,
        "citiesExpected":97,"cities":[],"fiberOffers":[],"fiberMobileOffers":[],
        "tvOffersAccepted":0,"status":"a_validar","usedLastValid":False,
        "productionFilesChanged":False,
        "disclaimer":"Oferta publica de referencia. Disponibilidade, preco e viabilidade tecnica nao confirmados por municipio."
    }
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--disable-dev-shm-usage","--no-sandbox"])
            context=browser.new_context(locale="pt-BR",timezone_id="America/Sao_Paulo",viewport={"width":1440,"height":1100})
            page=context.new_page(); page.set_default_timeout(TIMEOUT)
            response=page.goto(URL,wait_until="domcontentloaded",timeout=TIMEOUT); page.wait_for_timeout(7000)
            resultado["httpStatus"]=response.status if response else None
            if response and response.status<400:
                resultado["fiberOffers"],resultado["fiberMobileOffers"]=extrair(page)
            html.write_text(page.content(),encoding="utf-8"); page.screenshot(path=str(png),full_page=True)
            context.close(); browser.close()
    except PlaywrightTimeoutError as erro:
        resultado["reason"]="Timeout Playwright: "+str(erro)[:180]
    except Exception as erro:
        resultado["reason"]=f"{type(erro).__name__}: {str(erro)[:180]}"

    valido=(resultado.get("httpStatus")==200 and len(resultado["fiberOffers"])>0 and len(resultado["fiberMobileOffers"])>0 and resultado["tvOffersAccepted"]==0)
    if valido:
        resultado["status"]="validada_oferta_publica"
        resultado["portfolioChanged"]=bool(ultimo and assinatura({"f":resultado["fiberOffers"],"m":resultado["fiberMobileOffers"]}) != assinatura({"f":ultimo.get("fiberOffers",[]),"m":ultimo.get("fiberMobileOffers",[])}))
        for cidade in CIDADES:
            resultado["cities"].append({
                "city":cidade,"uf":UF,"portfolioReference":True,
                "territorialScope":"publico_nao_confirmado","locationConfirmed":False,
                "municipalAvailabilityConfirmed":False,"fiberOffers":resultado["fiberOffers"],
                "fiberMobileOffers":resultado["fiberMobileOffers"],"tvOffersAccepted":0
            })
        ULTIMO_VALIDO.write_text(json.dumps(resultado,ensure_ascii=False,indent=2),encoding="utf-8")
    elif ultimo:
        preservado=dict(ultimo)
        preservado.update({
            "generated":agora(),"status":"ultimo_valido_preservado","usedLastValid":True,
            "collectionFailureHttpStatus":resultado.get("httpStatus"),
            "collectionFailureReason":resultado.get("reason","Extracao atual sem portfolio valido"),
            "productionFilesChanged":False
        })
        resultado=preservado
    else:
        resultado["status"]="falha_sem_ultimo_valido"
        resultado["reason"]=resultado.get("reason","Extracao atual sem portfolio valido")

    resultado["evidenceHtml"]=str(html.relative_to(RAIZ)) if html.exists() else None
    resultado["evidenceScreenshot"]=str(png.relative_to(RAIZ)) if png.exists() else None
    SAIDA.write_text(json.dumps(resultado,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(resultado,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__": sys.exit(main())
