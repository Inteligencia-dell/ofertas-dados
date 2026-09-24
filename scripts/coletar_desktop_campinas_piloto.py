#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piloto Desktop Campinas/SP: Internet e Internet + Celular.
Exclui Desktop Play, TV + Internet e cards com canais/TV. Nao altera producao.
"""
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

RAIZ=Path(__file__).resolve().parent.parent
SAIDA=RAIZ/'dados'/'piloto-desktop-campinas.json'
EVIDENCIAS=RAIZ/'evidencias-desktop-campinas'
HOME='https://www.desktop.com.br/'
LOJA='https://lojaonline.desktop.com.br/'
TIMEOUT=60000


def agora(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def norm(v):
    s=unicodedata.normalize('NFD',str(v or '')); s=''.join(c for c in s if unicodedata.category(c)!='Mn')
    return re.sub(r'\s+',' ',s).strip().upper()
def primeiro_visivel(xs):
    for x in xs:
        try:
            if x.count() and x.first.is_visible(): return x.first
        except Exception: pass
    return None

def aceitar_cookies(page):
    b=primeiro_visivel([page.get_by_role('button',name=re.compile(r'aceitar|concordar|entendi',re.I)),page.get_by_text(re.compile(r'aceitar todos',re.I),exact=False)])
    if b:
        try: b.click(timeout=5000); page.wait_for_timeout(800)
        except Exception: pass

def localizar_campo(page):
    return primeiro_visivel([page.get_by_placeholder(re.compile(r'cidade|localiza',re.I)),page.get_by_label(re.compile(r'cidade|localiza',re.I)),page.locator("input[name*='city' i],input[name*='cidade' i],input[id*='city' i],input[id*='cidade' i],input[type='search']")])
def abrir_seletor(page):
    if localizar_campo(page): return True
    a=primeiro_visivel([page.get_by_text(re.compile(r'mudar localiza[cç][aã]o|Campinas/SP|localiza[cç][aã]o',re.I),exact=False),page.get_by_role('button',name=re.compile(r'mudar localiza|cidade|localiza',re.I)),page.locator("[aria-label*='cidade' i],[aria-label*='localiza' i]")])
    if a:
        try: a.click(timeout=10000); page.wait_for_timeout(1800)
        except Exception: pass
    return localizar_campo(page) is not None

def selecionar_campinas(page):
    page.wait_for_timeout(3500); texto=page.locator('body').inner_text()
    if re.search(r'Campinas\s*/\s*SP',texto,re.I):
        confirmar=primeiro_visivel([page.get_by_role('button',name=re.compile(r'confirmar localiza',re.I))])
        if confirmar:
            try: confirmar.click(); page.wait_for_timeout(5000)
            except Exception: pass
        return True,None
    if not abrir_seletor(page): return False,'Seletor de cidade nao localizado'
    campo=localizar_campo(page)
    try: campo.click(); campo.fill('Campinas')
    except Exception: campo.click(); campo.press('Control+A'); campo.press_sequentially('Campinas',delay=120)
    page.wait_for_timeout(3000)
    opcao=primeiro_visivel([page.get_by_role('option',name=re.compile(r'Campinas.*SP',re.I)),page.get_by_role('button',name=re.compile(r'Campinas.*SP',re.I)),page.locator("[role='option'],li").filter(has_text=re.compile(r'Campinas',re.I)),page.get_by_text(re.compile(r'Campinas.*SP',re.I),exact=False)])
    if not opcao: return False,'Opcao Campinas/SP nao localizada'
    opcao.click(); page.wait_for_timeout(1500)
    confirmar=primeiro_visivel([page.get_by_role('button',name=re.compile(r'confirmar localiza|^confirmar$',re.I))])
    if confirmar: confirmar.click(); page.wait_for_timeout(6000)
    return bool(re.search(r'Campinas\s*/\s*SP',page.locator('body').inner_text(),re.I)),None

def precos(texto):
    vals=[]
    for m in re.finditer(r'R\$?\s*([0-9]{1,4})[,.]([0-9]{2})|\b([0-9]{2,4})\.([0-9]{2})\b',texto,re.I):
        a=m.group(1) or m.group(3); b=m.group(2) or m.group(4)
        try: vals.append(round(float(f'{a}.{b}'),2))
        except Exception: pass
    return vals

def velocidade(texto):
    m=re.search(r'(\d{2,5})\s*MEGA\b',texto,re.I)
    if m:return int(m.group(1))
    m=re.search(r'([0-9](?:[,.][0-9])?)\s*GIGA\b',texto,re.I)
    return int(round(float(m.group(1).replace(',','.'))*1000)) if m else None

def cards_da_secao(page, cgid):
    url=f'https://lojaonline.desktop.com.br/planos?cgid={cgid}'
    r=page.goto(url,wait_until='domcontentloaded',timeout=TIMEOUT); page.wait_for_timeout(6000)
    seletores=['article',"[class*='product-tile' i]","[class*='product-card' i]","[class*='card' i]","[data-pid]"]
    saida=[]; vistos=set()
    for seletor in seletores:
        grupo=page.locator(seletor)
        try:q=min(grupo.count(),250)
        except Exception:continue
        for i in range(q):
            c=grupo.nth(i)
            try:
                texto=re.sub(r'\s+',' ',c.inner_text()).strip()
                if not c.is_visible() or not re.search(r'\b(?:MEGA|GIGA)\b',texto,re.I):continue
            except Exception:continue
            chave=norm(texto)
            if chave in vistos or len(texto)>1800:continue
            vistos.add(chave); saida.append((c,texto,url))
    return r,saida

def extrair(page):
    fibra=[]; movel=[]; tv_rejeitadas=0
    secoes=[('internet','fibra'),('internetCelular','fibra_movel')]
    for cgid,tipo in secoes:
        _,cards=cards_da_secao(page,cgid)
        for card,texto,url in cards:
            t=norm(texto)
            tem_tv=any(x in t for x in ['TV + INTERNET','DESKTOP PLAY','67 CANAIS','CANAIS EM HD','CANAIS AO VIVO'])
            if tem_tv: tv_rejeitadas+=1; continue
            speed=velocidade(texto); ps=precos(texto)
            if speed is None or not ps:continue
            atual=ps[0]; posterior=ps[1] if len(ps)>1 and ps[1]!=atual else None
            if tipo=='fibra_movel':
                gbs=[int(x) for x in re.findall(r'DESKTOP M[OÓ]VEL\s*(\d{1,4})\s*GB',texto,re.I)]
                if not gbs:continue
                for gb in sorted(set(gbs)):
                    movel.append({'offerType':'convergente','convergenceType':'fibra_movel','name':f'{speed} Mega + Desktop Movel {gb} GB','fixedSpeedMb':speed,'mobilePlanType':'movel','mobileAllowanceGb':gb,'monthlyPrice':atual,'postPromotionPrice':posterior,'tvIncluded':False,'sourceSection':'internetCelular','source':url,'cardText':texto[:900]})
            else:
                fibra.append({'offerType':'fibra','convergenceType':None,'name':'Desktop '+('1 Giga' if speed==1000 else f'{speed} Mega'),'fixedSpeedMb':speed,'monthlyPrice':atual,'postPromotionPrice':posterior,'tvIncluded':False,'sourceSection':'internet','source':url,'cardText':texto[:900]})
    uniq=lambda xs:list({(x['name'],x['monthlyPrice']):x for x in xs}.values())
    return sorted(uniq(fibra),key=lambda x:(x['fixedSpeedMb'],x['monthlyPrice'])),sorted(uniq(movel),key=lambda x:(x['fixedSpeedMb'],x['mobileAllowanceGb'])),tv_rejeitadas

def main():
    SAIDA.parent.mkdir(parents=True,exist_ok=True); EVIDENCIAS.mkdir(parents=True,exist_ok=True)
    html=EVIDENCIAS/'desktop-campinas.html'; png=EVIDENCIAS/'desktop-campinas.png'
    d={'operator':'Desktop','city':'CAMPINAS','uf':'SP','generated':agora(),'source':HOME,'httpStatus':None,'locationConfirmed':False,'fiberOffers':[],'fiberMobileOffers':[],'tvOffersAccepted':0,'tvOffersRejected':0,'status':'a_validar','productionFilesChanged':False}
    try:
        with sync_playwright() as p:
            b=p.chromium.launch(headless=True,args=['--disable-dev-shm-usage','--no-sandbox']); ctx=b.new_context(locale='pt-BR',timezone_id='America/Sao_Paulo',viewport={'width':1440,'height':1100})
            page=ctx.new_page(); page.set_default_timeout(TIMEOUT); r=page.goto(HOME,wait_until='domcontentloaded',timeout=TIMEOUT); d['httpStatus']=r.status if r else None; page.wait_for_timeout(5000); aceitar_cookies(page)
            ok,erro=selecionar_campinas(page); d['locationConfirmed']=ok
            if ok:
                d['fiberOffers'],d['fiberMobileOffers'],d['tvOffersRejected']=extrair(page)
                d['status']='validada_piloto' if d['fiberOffers'] else 'cidade_confirmada_sem_fibra_extraida'
                if not d['fiberOffers']:d['reason']='Campinas confirmada, mas nenhuma oferta Internet foi extraida'
            else:d['reason']=erro or 'Campinas/SP nao confirmada'
            html.write_text(page.content(),encoding='utf-8'); page.screenshot(path=str(png),full_page=True); ctx.close(); b.close()
    except PlaywrightTimeoutError as e:d['reason']='Timeout Playwright: '+str(e)[:180]
    except Exception as e:d['reason']=f'{type(e).__name__}: {str(e)[:180]}'
    d['evidenceHtml']=str(html.relative_to(RAIZ)) if html.exists() else None; d['evidenceScreenshot']=str(png.relative_to(RAIZ)) if png.exists() else None
    SAIDA.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(d,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__':sys.exit(main())
