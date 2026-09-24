#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piloto Desktop Campinas/SP v3.

Regras:
- Internet residencial: aceita plano puro e Desktop Play DE CORTESIA sem acrescimo.
- Convergente: exige internet residencial + Desktop Movel no mesmo card.
- Exclui TV, canais e Desktop Play pago/adicional.
- Nao altera producao.
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
SAIDA=RAIZ/'dados'/'piloto-desktop-campinas-v3.json'
EVIDENCIAS=RAIZ/'evidencias-desktop-campinas-v3'
HOME='https://www.desktop.com.br/'
TIMEOUT=60000


def agora(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def norm(v):
    s=unicodedata.normalize('NFD',str(v or ''))
    s=''.join(c for c in s if unicodedata.category(c)!='Mn')
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
        try:b.click(timeout=5000);page.wait_for_timeout(800)
        except Exception:pass

def localizar_campo(page):
    return primeiro_visivel([page.get_by_placeholder(re.compile(r'cidade|localiza',re.I)),page.get_by_label(re.compile(r'cidade|localiza',re.I)),page.locator("input[name*='city' i],input[name*='cidade' i],input[id*='city' i],input[id*='cidade' i],input[type='search']")])
def abrir_seletor(page):
    if localizar_campo(page):return True
    a=primeiro_visivel([page.get_by_text(re.compile(r'mudar localiza[cç][aã]o|Campinas/SP|localiza[cç][aã]o',re.I),exact=False),page.get_by_role('button',name=re.compile(r'mudar localiza|cidade|localiza',re.I))])
    if a:
        try:a.click(timeout=10000);page.wait_for_timeout(1800)
        except Exception:pass
    return localizar_campo(page) is not None

def selecionar_campinas(page):
    page.wait_for_timeout(3000); texto=page.locator('body').inner_text()
    if re.search(r'Campinas\s*/\s*SP',texto,re.I):
        b=primeiro_visivel([page.get_by_role('button',name=re.compile(r'confirmar localiza',re.I))])
        if b:
            try:b.click();page.wait_for_timeout(4000)
            except Exception:pass
        return True,None
    if not abrir_seletor(page):return False,'Seletor de cidade nao localizado'
    campo=localizar_campo(page);campo.click();campo.fill('Campinas');page.wait_for_timeout(2500)
    opcao=primeiro_visivel([page.get_by_role('option',name=re.compile(r'Campinas.*SP',re.I)),page.locator("[role='option'],li").filter(has_text=re.compile(r'Campinas',re.I)),page.get_by_text(re.compile(r'Campinas.*SP',re.I),exact=False)])
    if not opcao:return False,'Opcao Campinas/SP nao localizada'
    opcao.click();page.wait_for_timeout(1200)
    b=primeiro_visivel([page.get_by_role('button',name=re.compile(r'confirmar localiza|^confirmar$',re.I))])
    if b:b.click();page.wait_for_timeout(5000)
    return bool(re.search(r'Campinas\s*/\s*SP',page.locator('body').inner_text(),re.I)),None

def disponibilidade(page):
    t=page.locator('body').inner_text()
    em_breve=bool(re.search(r'Em breve estaremos na sua regi[aã]o',t,re.I))
    selecionada=bool(re.search(r'Campinas\s*/\s*SP',t,re.I))
    return selecionada,selecionada and not em_breve,em_breve

def precos(texto):
    vals=[]
    for m in re.finditer(r'R\$\s*([0-9]{1,4})[,.]([0-9]{2})',texto,re.I):
        try:vals.append(round(float(f'{m.group(1)}.{m.group(2)}'),2))
        except Exception:pass
    return vals

def velocidade(texto):
    m=re.search(r'(\d{2,5})\s*MEGA\b',texto,re.I)
    if m:return int(m.group(1))
    m=re.search(r'([0-9](?:[,.][0-9])?)\s*GIGA\b',texto,re.I)
    return int(round(float(m.group(1).replace(',','.'))*1000)) if m else None

def clicar_aba(page,nome):
    candidatos=[page.get_by_role('tab',name=re.compile(r'^'+re.escape(nome)+r'$',re.I)),page.get_by_text(re.compile(r'^'+re.escape(nome)+r'$',re.I),exact=True)]
    a=primeiro_visivel(candidatos)
    if not a:return False
    try:a.scroll_into_view_if_needed();a.click(timeout=10000);page.wait_for_timeout(3500);return True
    except Exception:return False

def cards_por_cta(page):
    """Escolhe o menor ancestral de cada CTA contendo velocidade e preco."""
    ctas=page.get_by_text(re.compile(r'^(Assine j[aá]|Quero contratar|Contratar)$',re.I),exact=True)
    cards=[]; vistos=set()
    try:q=ctas.count()
    except Exception:q=0
    for i in range(q):
        cta=ctas.nth(i)
        try:
            if not cta.is_visible():continue
            dados=cta.evaluate("""el => {
              let n=el; let best=null;
              for(let i=0;i<10 && n;i++,n=n.parentElement){
                const t=(n.innerText||'').replace(/\\s+/g,' ').trim();
                if(/(?:MEGA|GIGA)/i.test(t) && /R\\$/i.test(t) && t.length<2200){best={text:t,html:n.outerHTML};break;}
              }
              return best;
            }""")
            if not dados:continue
            texto=dados['text']; chave=norm(texto)
            if chave in vistos:continue
            vistos.add(chave);cards.append(texto)
        except Exception:continue
    return cards

def classificar_card(texto,categoria):
    t=norm(texto); speed=velocidade(texto); ps=precos(texto)
    if speed is None or not ps:return None,'incompleto'
    atual=ps[0]; posterior=ps[1] if len(ps)>1 and ps[1]!=atual else None
    tem_tv=any(x in t for x in ['TV + INTERNET','67 CANAIS','CANAIS EM HD','CANAIS AO VIVO'])
    play='DESKTOP PLAY' in t
    play_cortesia=play and ('DE CORTESIA' in t or 'CORTESIA' in t)
    play_pago=play and not play_cortesia
    if tem_tv or play_pago:return None,'tv_ou_play_pago'
    gbs=[int(x) for x in re.findall(r'DESKTOP M[OÓ]VEL\s*(\d{1,4})\s*GB',texto,re.I)]
    if categoria=='internet_celular':
        if not gbs:return None,'sem_franquia_movel'
        return [{
            'offerType':'convergente','convergenceType':'fibra_movel',
            'name':f'{speed} Mega + Desktop Movel {gb} GB','fixedSpeedMb':speed,
            'mobilePlanType':'movel','mobileAllowanceGb':gb,'monthlyPrice':atual,
            'postPromotionPrice':posterior,'desktopPlayIncluded':play,
            'desktopPlayCourtesy':play_cortesia,'tvIncluded':False,
            'sourceSection':'internet_celular','cardText':texto[:1000]
        } for gb in sorted(set(gbs))],None
    if gbs:return None,'convergente_fora_da_aba'
    return [{
        'offerType':'fibra','convergenceType':None,
        'name':'Desktop '+('1 Giga' if speed==1000 else f'{speed} Mega'),
        'fixedSpeedMb':speed,'monthlyPrice':atual,'postPromotionPrice':posterior,
        'desktopPlayIncluded':play,'desktopPlayCourtesy':play_cortesia,
        'tvIncluded':False,'sourceSection':'internet','cardText':texto[:1000]
    }],None

def coletar_categoria(page,nome,categoria):
    abriu=clicar_aba(page,nome)
    cards=cards_por_cta(page) if abriu else []
    ofertas=[]; rejeicoes=[]
    for texto in cards:
        itens,motivo=classificar_card(texto,categoria)
        if itens:ofertas.extend(itens)
        else:rejeicoes.append({'reason':motivo,'cardText':texto[:700]})
    unicos={}
    for o in ofertas:unicos[(o['name'],o['monthlyPrice'],o.get('desktopPlayCourtesy'))]=o
    return abriu,list(unicos.values()),rejeicoes

def main():
    SAIDA.parent.mkdir(parents=True,exist_ok=True);EVIDENCIAS.mkdir(parents=True,exist_ok=True)
    d={'operator':'Desktop','city':'CAMPINAS','uf':'SP','generated':agora(),'source':HOME,
       'citySelected':False,'cityAvailabilityConfirmed':False,'campinasComingSoon':False,
       'fiberOffers':[],'fiberMobileOffers':[],'rejectedCards':[],'tvOffersAccepted':0,
       'status':'a_validar','productionFilesChanged':False}
    try:
        with sync_playwright() as p:
            b=p.chromium.launch(headless=True,args=['--disable-dev-shm-usage','--no-sandbox'])
            ctx=b.new_context(locale='pt-BR',timezone_id='America/Sao_Paulo',viewport={'width':1440,'height':1100})
            page=ctx.new_page();page.set_default_timeout(TIMEOUT)
            r=page.goto(HOME,wait_until='domcontentloaded',timeout=TIMEOUT);d['httpStatus']=r.status if r else None
            page.wait_for_timeout(5000);aceitar_cookies(page);selecionar_campinas(page)
            d['citySelected'],d['cityAvailabilityConfirmed'],d['campinasComingSoon']=disponibilidade(page)
            abriu_i,fibra,rej_i=coletar_categoria(page,'Internet','internet')
            page.screenshot(path=str(EVIDENCIAS/'01-internet.png'),full_page=True)
            (EVIDENCIAS/'01-internet.html').write_text(page.content(),encoding='utf-8')
            abriu_m,movel,rej_m=coletar_categoria(page,'Internet + Celular','internet_celular')
            page.screenshot(path=str(EVIDENCIAS/'02-internet-celular.png'),full_page=True)
            (EVIDENCIAS/'02-internet-celular.html').write_text(page.content(),encoding='utf-8')
            d['internetTabOpened']=abriu_i;d['internetMobileTabOpened']=abriu_m
            d['fiberOffers']=sorted(fibra,key=lambda x:(x['fixedSpeedMb'],x['monthlyPrice']))
            d['fiberMobileOffers']=sorted(movel,key=lambda x:(x['fixedSpeedMb'],x['mobileAllowanceGb']))
            d['rejectedCards']=rej_i+rej_m
            d['desktopPlayCourtesyOffers']=sum(1 for x in d['fiberOffers'] if x.get('desktopPlayCourtesy'))
            if d['fiberOffers'] and d['fiberMobileOffers']:
                d['status']='portfolio_padronizado_validado'
            elif d['fiberOffers']:
                d['status']='fibra_validada_convergente_nao_extraida'
                d['reason']='Ofertas de internet residencial extraidas, mas nenhuma oferta Internet + Celular foi identificada no mesmo card'
            else:
                d['status']='sem_ofertas_extraidas';d['reason']='Nenhuma oferta elegivel foi extraida'
            if d['campinasComingSoon']:
                d['territorialScope']='portfolio_publico_campinas_em_breve'
            else:d['territorialScope']='campinas_confirmada' if d['cityAvailabilityConfirmed'] else 'publico_nao_confirmado'
            ctx.close();b.close()
    except PlaywrightTimeoutError as e:d['reason']='Timeout Playwright: '+str(e)[:180]
    except Exception as e:d['reason']=f'{type(e).__name__}: {str(e)[:180]}'
    SAIDA.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(d,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':sys.exit(main())
