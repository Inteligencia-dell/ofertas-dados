#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Desktop, lote 4, no mesmo modelo validado da Claro."""
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

RAIZ=Path(__file__).resolve().parent.parent
SAIDA=RAIZ/'dados'/'piloto-desktop-lote-4.json'
EVID=RAIZ/'evidencias-desktop-lote-4'
URL='https://www.desktop.com.br/'
TIMEOUT=60000
ESPERA_CIDADE=5500
CIDADES=[
  "PRAIA GRANDE",
  "RAFARD",
  "RIBEIRAO PRETO",
  "RIO CLARO",
  "SANTA BARBARA D OESTE",
  "SANTA CRUZ DAS PALMEIRAS",
  "SANTA GERTRUDES",
  "SANTA ROSA DE VITERBO",
  "SANTOS",
  "SAO CARLOS",
  "SAO JOSE DO RIO PRETO",
  "SAO JOSE DOS CAMPOS",
  "SAO VICENTE",
  "SOROCABA",
  "SUMARE",
  "TAMBAU",
  "TATUI",
  "TAUBATE",
  "TIETE",
  "TREMEMBE"
]

def agora(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def sem_acento(v):
    s=unicodedata.normalize('NFD',str(v or ''));return ''.join(c for c in s if unicodedata.category(c)!='Mn')
def normalizar(v): return re.sub(r'\s+',' ',sem_acento(v)).strip().upper()
def visivel(loc):
    try:return loc.count()>0 and loc.first.is_visible()
    except Exception:return False

def aceitar_cookies(page):
    for loc in [page.get_by_role('button',name=re.compile(r'aceitar|concordar|entendi',re.I)),page.get_by_text(re.compile(r'aceitar todos',re.I),exact=False)]:
        if visivel(loc):
            try:loc.first.click(timeout=5000);page.wait_for_timeout(800);return
            except Exception:pass

def localizar_campo(page):
    candidatos=[page.get_by_placeholder(re.compile(r'cidade|localiza',re.I)),page.get_by_label(re.compile(r'cidade|localiza',re.I)),page.locator("input[name*='city' i],input[name*='cidade' i],input[id*='city' i],input[id*='cidade' i],input[type='search']")]
    for loc in candidatos:
        if visivel(loc):return loc.first
    return None

def abrir_seletor(page):
    if localizar_campo(page):return True
    candidatos=[page.get_by_text(re.compile(r'mudar localiza[cç][aã]o',re.I),exact=False),page.get_by_role('button',name=re.compile(r'mudar localiza|cidade|localiza',re.I)),page.locator("[aria-label*='cidade' i],[aria-label*='localiza' i]")]
    for loc in candidatos:
        if visivel(loc):
            try:loc.first.click(timeout=10000);page.wait_for_timeout(1800);break
            except Exception:pass
    return localizar_campo(page) is not None

def selecionar_cidade(page,cidade):
    texto=page.locator('body').inner_text()
    if re.search(re.escape(cidade)+r'\s*/\s*SP',normalizar(texto),re.I):
        b=page.get_by_role('button',name=re.compile(r'confirmar localiza',re.I))
        if visivel(b):
            try:b.first.click();page.wait_for_timeout(3500)
            except Exception:pass
        return True,None
    if not abrir_seletor(page):return False,'Seletor de cidade nao localizado'
    campo=localizar_campo(page)
    try:campo.click();campo.fill(cidade.title())
    except Exception:
        campo.click();campo.press('Control+A');campo.press_sequentially(cidade.title(),delay=100)
    page.wait_for_timeout(3000)
    alvo=normalizar(cidade)
    candidatos=page.locator("[role='option'],li,button,a")
    opcao=None
    try:q=min(candidatos.count(),400)
    except Exception:q=0
    for i in range(q):
        loc=candidatos.nth(i)
        try:
            if not loc.is_visible():continue
            t=normalizar(loc.inner_text())
            if alvo in t and re.search(r'(^|[ /\\-])SP([ /\\-]|$)',t):opcao=loc;break
        except Exception:pass
    if opcao is None:return False,f'Opcao {cidade}/SP nao localizada'
    try:opcao.click();page.wait_for_timeout(1200)
    except Exception as e:return False,f'Falha ao selecionar: {str(e)[:120]}'
    b=page.get_by_role('button',name=re.compile(r'confirmar localiza|^confirmar$',re.I))
    if visivel(b):
        try:b.first.click();page.wait_for_timeout(ESPERA_CIDADE)
        except Exception:pass
    confirmado=alvo in normalizar(page.locator('body').inner_text())
    return confirmado,None if confirmado else f'{cidade}/SP nao confirmada'

def clicar_aba(page,rotulo):
    r=page.evaluate(r"""label=>{const n=s=>(s||'').replace(/\s+/g,' ').trim().toLowerCase();const el=[...document.querySelectorAll('button,a,[role=tab],[role=button]')].find(x=>n(x.innerText||x.textContent)===n(label)&&(x.offsetWidth||x.offsetHeight||x.getClientRects().length));if(!el)return {clicked:false};el.scrollIntoView({block:'center'});el.click();return {clicked:true};}""",rotulo)
    page.wait_for_timeout(4000);return r

def cards_visiveis(page):
    return page.evaluate(r"""()=>{const limpar=s=>(s||'').replace(/\s+/g,' ').trim();const ctas=[...document.querySelectorAll('a,button')].filter(el=>/^assine j[aá]$/i.test(limpar(el.innerText||el.textContent))&&(el.offsetWidth||el.offsetHeight||el.getClientRects().length));const cards=[];for(const cta of ctas){let cur=cta;for(let i=0;i<14&&cur;i++,cur=cur.parentElement){const t=limpar(cur.innerText||cur.textContent);if(/R\$\s*\d{1,4}[,.]\d{2}/i.test(t)&&/(?:600\s*MEGA|1\s*GIGA)/i.test(t)&&t.length>=40&&t.length<=1800){cards.push(t);break;}}}return [...new Set(cards)];}""")

def valor(texto,posterior=False):
    texto=re.sub(r'\s+',' ',texto or '').strip()
    padrao=r'Ap[oó]s[,]?\s*R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})' if posterior else r'R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})\s*Por\s+6\s+meses'
    m=re.search(padrao,texto,re.I);return round(float(f'{m.group(1)}.{m.group(2)}'),2) if m else None

def fibra(texto):
    if not re.search(r'(600\s*MEGA|1\s*GIGA)\s*\+\s*DESKTOP\s*PLAY',texto,re.I) or not re.search(r'DESKTOP\s*PLAY\s*DE\s*CORTESIA',texto,re.I):return None
    speed=1000 if re.search(r'1\s*GIGA\s*\+\s*DESKTOP\s*PLAY',texto,re.I) else 600;atual=valor(texto)
    if atual is None:return None
    return {'offerType':'fibra','convergenceType':None,'name':'Fibra '+('1 Giga' if speed==1000 else '600 Mega'),'fixedSpeedMb':speed,'monthlyPrice':atual,'previousPrice':None,'postPromotionPrice':valor(texto,True),'desktopPlayIncluded':True,'desktopPlayCourtesy':True,'tvIncluded':False}

def movel(texto):
    m=re.search(r'600\s*MEGA\s*\+\s*(15|20)\s*GIGA\s*CELULAR',texto,re.I)
    if not m:return None
    gb=int(m.group(1));atual=valor(texto)
    if atual is None:return None
    return {'offerType':'convergente','convergenceType':'fibra_movel','name':f'600 Mega + Movel {gb} GB','fixedSpeedMb':600,'mobilePlanType':'movel','mobileAllowanceGb':gb,'monthlyPrice':atual,'previousPrice':None,'postPromotionPrice':valor(texto,True),'tvIncluded':False}

def coletar_cidade(browser,cidade):
    r={'city':cidade,'uf':'SP','locationConfirmed':False,'fiberOffers':[],'fiberMobileOffers':[],'tvOffersAccepted':0,'productionFilesChanged':False}
    ctx=browser.new_context(locale='pt-BR',timezone_id='America/Sao_Paulo',viewport={'width':1440,'height':1100});page=ctx.new_page();page.set_default_timeout(TIMEOUT)
    try:
        resp=page.goto(URL,wait_until='domcontentloaded',timeout=TIMEOUT);r['httpStatus']=resp.status if resp else None;page.wait_for_timeout(5000);aceitar_cookies(page)
        ok,erro=selecionar_cidade(page,cidade);r['locationConfirmed']=ok
        if not ok:r['reason']=erro
        else:
            clicar_aba(page,'Internet');r['fiberOffers']=[x for x in (fibra(t) for t in cards_visiveis(page)) if x]
            clicar_aba(page,'Internet + Celular');r['fiberMobileOffers']=[x for x in (movel(t) for t in cards_visiveis(page)) if x]
            r['fiberOffers']=sorted({x['fixedSpeedMb']:x for x in r['fiberOffers']}.values(),key=lambda x:x['fixedSpeedMb'])
            r['fiberMobileOffers']=sorted({x['mobileAllowanceGb']:x for x in r['fiberMobileOffers']}.values(),key=lambda x:x['mobileAllowanceGb'])
            r['status']='validada_piloto' if len(r['fiberOffers'])==2 and len(r['fiberMobileOffers'])==2 else 'extracao_incompleta'
            if r['status']!='validada_piloto':r['reason']='Esperadas 2 ofertas Fibra e 2 ofertas Fibra + Movel'
        slug=re.sub(r'[^a-z0-9]+','-',sem_acento(cidade).lower()).strip('-')
        (EVID/f'{slug}.html').write_text(page.content(),encoding='utf-8');page.screenshot(path=str(EVID/f'{slug}.png'),full_page=True)
    except Exception as e:r['reason']=f'{type(e).__name__}: {str(e)[:180]}'
    ctx.close();return r

def main():
    SAIDA.parent.mkdir(parents=True,exist_ok=True);EVID.mkdir(parents=True,exist_ok=True)
    d={'operator':'Desktop','mode':'lote_4','generated':agora(),'citiesExpected':len(CIDADES),'results':[],'productionFilesChanged':False}
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for c in CIDADES:d['results'].append(coletar_cidade(b,c))
        b.close()
    d['summary']={'citiesProcessed':len(d['results']),'locationsConfirmed':sum(x['locationConfirmed'] for x in d['results']),'citiesWithFiber':sum(bool(x['fiberOffers']) for x in d['results']),'citiesWithFiberMobile':sum(bool(x['fiberMobileOffers']) for x in d['results']),'tvOffersAccepted':sum(x['tvOffersAccepted'] for x in d['results']),'technicalPending':sum(x.get('status')!='validada_piloto' for x in d['results'])}
    SAIDA.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(d,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':sys.exit(main())
