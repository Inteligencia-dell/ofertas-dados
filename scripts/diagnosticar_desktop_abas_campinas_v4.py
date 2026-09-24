#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostico Desktop v4: identifica e aciona as abas Internet e Internet + Celular.
Nao altera arquivos de producao.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

RAIZ=Path(__file__).resolve().parent.parent
SAIDA=RAIZ/'dados'/'diagnostico-desktop-abas-campinas-v4.json'
EVID=RAIZ/'evidencias-desktop-abas-campinas-v4'
URL='https://www.desktop.com.br/'
TIMEOUT=60000


def agora(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def visible(loc):
    try:return loc.count()>0 and loc.first.is_visible()
    except Exception:return False

def aceitar(page):
    for loc in [page.get_by_role('button',name=re.compile(r'aceitar|concordar|entendi',re.I)),page.get_by_text(re.compile(r'aceitar todos',re.I),exact=False)]:
        if visible(loc):
            try:loc.first.click(timeout=4000);page.wait_for_timeout(800);return
            except Exception:pass

def selecionar_campinas(page):
    page.wait_for_timeout(4000)
    text=page.locator('body').inner_text()
    if re.search(r'Campinas\s*/\s*SP',text,re.I):
        b=page.get_by_role('button',name=re.compile(r'confirmar localiza',re.I))
        if visible(b):
            try:b.first.click();page.wait_for_timeout(4000)
            except Exception:pass
        return True
    return False

def inventario_clicaveis(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('a,button,[role=tab],[role=button]')).map((el,i)=>({
      i,tag:el.tagName.toLowerCase(),text:(el.innerText||el.textContent||'').replace(/\\s+/g,' ').trim(),
      href:el.getAttribute('href'),role:el.getAttribute('role'),id:el.id||null,
      cls:typeof el.className==='string'?el.className:null,visible:!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length)
    })).filter(x=>x.visible && /internet|celular/i.test(x.text)).slice(0,100)""")

def clicar_por_texto_js(page, rotulo):
    return page.evaluate("""label => {
      const norm=s=>(s||'').replace(/\\s+/g,' ').trim().toLowerCase();
      const wanted=norm(label);
      const all=Array.from(document.querySelectorAll('a,button,[role=tab],[role=button],li,span,div'));
      const exact=all.filter(el=>norm(el.innerText||el.textContent)===wanted && (el.offsetWidth||el.offsetHeight||el.getClientRects().length));
      const el=exact.find(x=>['A','BUTTON'].includes(x.tagName)||['tab','button'].includes(x.getAttribute('role'))) || exact[0];
      if(!el)return {clicked:false};
      const target=el.closest('a,button,[role=tab],[role=button]')||el;
      target.scrollIntoView({block:'center'}); target.click();
      return {clicked:true,tag:target.tagName,text:(target.innerText||target.textContent||'').trim(),href:target.getAttribute('href'),id:target.id||null,cls:typeof target.className==='string'?target.className:null};
    }""",rotulo)

def card_texts(page):
    return page.evaluate("""() => {
      const ctas=Array.from(document.querySelectorAll('a,button')).filter(el=>/assine j[aá]|contratar|quero/i.test((el.innerText||'').trim()) && (el.offsetWidth||el.offsetHeight));
      const out=[];
      for(const cta of ctas){
        let n=cta;
        for(let i=0;i<12&&n;i++,n=n.parentElement){
          const t=(n.innerText||'').replace(/\\s+/g,' ').trim();
          if(/(?:mega|giga)/i.test(t)&&/R\\$/i.test(t)&&t.length<2500){out.push(t);break;}
        }
      }
      return [...new Set(out)];
    }""")

def salvar(page,prefix):
    (EVID/(prefix+'.html')).write_text(page.content(),encoding='utf-8')
    page.screenshot(path=str(EVID/(prefix+'.png')),full_page=True)

def main():
    SAIDA.parent.mkdir(parents=True,exist_ok=True);EVID.mkdir(parents=True,exist_ok=True)
    d={'operator':'Desktop','city':'CAMPINAS','uf':'SP','generated':agora(),'source':URL,'productionFilesChanged':False,'tabs':{}}
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        ctx=b.new_context(locale='pt-BR',timezone_id='America/Sao_Paulo',viewport={'width':1440,'height':1100})
        page=ctx.new_page();page.set_default_timeout(TIMEOUT)
        r=page.goto(URL,wait_until='domcontentloaded',timeout=TIMEOUT);page.wait_for_timeout(6000);aceitar(page)
        d['httpStatus']=r.status if r else None;d['citySelected']=selecionar_campinas(page)
        page.locator('text=CONHEÇA OS PLANOS').first.scroll_into_view_if_needed() if page.locator('text=CONHEÇA OS PLANOS').count() else None
        page.wait_for_timeout(1200)
        d['clickableInventory']=inventario_clicaveis(page)
        for idx,(label,key) in enumerate([('Internet','internet'),('Internet + Celular','internet_celular')],1):
            before=page.locator('body').inner_text()
            click=clicar_por_texto_js(page,label);page.wait_for_timeout(5000)
            after=page.locator('body').inner_text()
            cards=card_texts(page)
            d['tabs'][key]={'label':label,'click':click,'bodyChanged':before!=after,'url':page.url,'cardsFound':len(cards),'cards':cards}
            salvar(page,f'{idx:02d}-{key}')
        ctx.close();b.close()
    SAIDA.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(d,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':sys.exit(main())
