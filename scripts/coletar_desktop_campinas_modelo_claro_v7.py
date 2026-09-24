#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Desktop Campinas v6 no modelo Claro.
Extrai exatamente 2 ofertas Fibra e 2 ofertas Fibra + Movel.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

RAIZ=Path(__file__).resolve().parent.parent
SAIDA=RAIZ/'dados'/'piloto-desktop-campinas-modelo-claro-v7.json'
EVID=RAIZ/'evidencias-desktop-campinas-modelo-claro-v7'
URL='https://www.desktop.com.br/'
TIMEOUT=60000


def agora(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def visivel(loc):
    try:return loc.count()>0 and loc.first.is_visible()
    except Exception:return False

def aceitar_cookies(page):
    for loc in [page.get_by_role('button',name=re.compile(r'aceitar|concordar|entendi',re.I)),page.get_by_text(re.compile(r'aceitar todos',re.I),exact=False)]:
        if visivel(loc):
            try:loc.first.click(timeout=5000);page.wait_for_timeout(800);return
            except Exception:pass

def selecionar_campinas(page):
    page.wait_for_timeout(3500)
    if not re.search(r'Campinas\s*/\s*SP',page.locator('body').inner_text(),re.I):return False
    b=page.get_by_role('button',name=re.compile(r'confirmar localiza',re.I))
    if visivel(b):
        try:b.first.click();page.wait_for_timeout(4000)
        except Exception:pass
    return True

def clicar_aba(page,rotulo):
    result=page.evaluate(r"""label=>{
      const n=s=>(s||'').replace(/\s+/g,' ').trim().toLowerCase();
      const el=[...document.querySelectorAll('button,a,[role=tab],[role=button]')]
        .find(x=>n(x.innerText||x.textContent)===n(label)&&(x.offsetWidth||x.offsetHeight||x.getClientRects().length));
      if(!el)return {clicked:false};
      el.scrollIntoView({block:'center'});el.click();return {clicked:true,tag:el.tagName,text:n(el.innerText)};
    }""",rotulo)
    page.wait_for_timeout(4500)
    return result

def cards_visiveis_por_cta(page):
    """Coleta somente o menor ancestral visivel de cada CTA Assine ja."""
    return page.evaluate(r"""() => {
      const limpar = s => (s || '').replace(/\s+/g, ' ').trim();
      const ctas = [...document.querySelectorAll('a,button')].filter(el =>
        /^assine j[aá]$/i.test(limpar(el.innerText || el.textContent)) &&
        (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
      const cards = [];
      for (const cta of ctas) {
        let cur = cta;
        for (let i=0; i<14 && cur; i++, cur=cur.parentElement) {
          const t = limpar(cur.innerText || cur.textContent);
          if (/R\$\s*\d{1,4}[,.]\d{2}/i.test(t) &&
              /(?:600\s*MEGA|1\s*GIGA)/i.test(t) &&
              t.length >= 40 && t.length <= 1800) {
            cards.push(t); break;
          }
        }
      }
      return [...new Set(cards)];
    }""")


def selecionar_cards(textos, categoria):
    selecionados=[]
    for texto in textos:
        t=re.sub(r'\s+',' ',texto).strip()
        if categoria=='fibra' and re.search(r'\b(?:600\s*MEGA|1\s*GIGA)\s*\+\s*DESKTOP\s*PLAY\b',t,re.I) and re.search(r'DESKTOP\s*PLAY\s*DE\s*CORTESIA',t,re.I):
            selecionados.append(t)
        elif categoria=='movel' and re.search(r'600\s*MEGA\s*\+\s*(?:15|20)\s*GIGA\s*CELULAR',t,re.I):
            selecionados.append(t)
    return selecionados

def valor(texto,posterior=False):
    padrao=r'Ap[oó]s[,]?\s*R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})' if posterior else r'R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})'
    m=re.search(padrao,texto or '',re.I)
    return round(float(f'{m.group(1)}.{m.group(2)}'),2) if m else None

def fibra(item):
    texto=item.get('card');titulo=item.get('title','')
    if not texto or not re.search(r'DESKTOP\s*PLAY\s*DE\s*CORTESIA',texto,re.I):return None
    speed=1000 if re.search(r'1\s*GIGA\s*\+\s*DESKTOP\s*PLAY',texto,re.I) else 600
    atual=valor(texto)
    if atual is None:return None
    return {'offerType':'fibra','convergenceType':None,'name':'Fibra '+('1 Giga' if speed==1000 else '600 Mega'),'fixedSpeedMb':speed,'monthlyPrice':atual,'previousPrice':None,'postPromotionPrice':valor(texto,True),'desktopPlayIncluded':True,'desktopPlayCourtesy':True,'tvIncluded':False,'sourceSection':'internet','cardText':texto[:1000]}
def convergente(item):
    texto=item.get('card');titulo=item.get('title','')
    if not texto:return None
    m=re.search(r'600\s*MEGA\s*\+\s*(15|20)\s*GIGA\s*CELULAR',texto,re.I)
    if not m:return None
    gb=int(m.group(1));atual=valor(texto)
    if atual is None:return None
    return {'offerType':'convergente','convergenceType':'fibra_movel','name':f'600 Mega + Movel {gb} GB','fixedSpeedMb':600,'mobilePlanType':'movel','mobileAllowanceGb':gb,'monthlyPrice':atual,'previousPrice':None,'postPromotionPrice':valor(texto,True),'desktopPlayIncluded':False,'desktopPlayCourtesy':False,'tvIncluded':False,'sourceSection':'internet_celular','cardText':texto[:1000]}
def salvar(page,nome):
    (EVID/f'{nome}.html').write_text(page.content(),encoding='utf-8');page.screenshot(path=str(EVID/f'{nome}.png'),full_page=True)

def main():
    SAIDA.parent.mkdir(parents=True,exist_ok=True);EVID.mkdir(parents=True,exist_ok=True)
    d={'operator':'Desktop','city':'CAMPINAS','uf':'SP','generated':agora(),'source':URL,'locationConfirmed':False,'fiberOffers':[],'fiberMobileOffers':[],'tvOffersAccepted':0,'status':'a_validar','productionFilesChanged':False}
    try:
        with sync_playwright() as p:
            b=p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage']);ctx=b.new_context(locale='pt-BR',timezone_id='America/Sao_Paulo',viewport={'width':1440,'height':1100})
            page=ctx.new_page();page.set_default_timeout(TIMEOUT);r=page.goto(URL,wait_until='domcontentloaded',timeout=TIMEOUT);page.wait_for_timeout(6000);aceitar_cookies(page)
            d['httpStatus']=r.status if r else None;d['locationConfirmed']=selecionar_campinas(page);d['campinasComingSoon']=bool(re.search(r'Em breve estaremos na sua regi[aã]o',page.locator('body').inner_text(),re.I))
            d['internetTabClick']=clicar_aba(page,'Internet')
            textos_fibra=cards_visiveis_por_cta(page);fi=selecionar_cards(textos_fibra,'fibra');d['fiberCardDiagnostics']=fi;d['fiberOffers']=[x for x in (fibra({'title':t,'card':t}) for t in fi) if x];salvar(page,'01-internet')
            d['internetMobileTabClick']=clicar_aba(page,'Internet + Celular')
            textos_movel=cards_visiveis_por_cta(page);mo=selecionar_cards(textos_movel,'movel');d['fiberMobileCardDiagnostics']=mo;d['fiberMobileOffers']=[x for x in (convergente({'title':t,'card':t}) for t in mo) if x];salvar(page,'02-internet-celular')
            d['fiberOffers']=sorted(d['fiberOffers'],key=lambda x:x['fixedSpeedMb']);d['fiberMobileOffers']=sorted(d['fiberMobileOffers'],key=lambda x:x['mobileAllowanceGb'])
            d['status']='validada_piloto' if len(d['fiberOffers'])==2 and len(d['fiberMobileOffers'])==2 else 'extracao_incompleta'
            if d['status']!='validada_piloto':d['reason']='Esperadas 2 ofertas Fibra e 2 ofertas Fibra + Movel; consulte os diagnosticos de titulo/card no JSON'
            ctx.close();b.close()
    except PlaywrightTimeoutError as e:d['reason']='Timeout Playwright: '+str(e)[:180]
    except Exception as e:d['reason']=f'{type(e).__name__}: {str(e)[:180]}'
    SAIDA.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(d,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':sys.exit(main())
