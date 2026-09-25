#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Desktop lote 3 v2.

Replica o fluxo validado em Campinas para cada cidade individualmente:
- abre o modal territorial,
- digita a cidade,
- seleciona a opcao no autocomplete,
- confirma a localizacao,
- extrai Fibra e Fibra + Movel,
- registra diagnostico do autocomplete quando falhar.
"""
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / 'dados' / 'piloto-desktop-lote-3-v2.json'
EVID = RAIZ / 'evidencias-desktop-lote-3-v2'
URL = 'https://www.desktop.com.br/'
TIMEOUT = 60000
CIDADES = [
    "LEME",
    "LENCOIS PAULISTA",
    "LIMEIRA",
    "LINS",
    "LOUVEIRA",
    "MATAO",
    "MIRASSOL",
    "MOGI GUACU",
    "MOGI MIRIM",
    "MONGAGUA",
    "MONTE ALTO",
    "MONTE MOR",
    "NOVA ODESSA",
    "OLIMPIA",
    "PAULINIA",
    "PEDREIRA",
    "PERUIBE",
    "PIRACICABA",
    "PIRASSUNUNGA",
    "PORTO FERREIRA"
]


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def sem_acento(valor):
    texto = unicodedata.normalize('NFD', str(valor or ''))
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn')


def norm(valor):
    return re.sub(r'\s+', ' ', sem_acento(valor)).strip().upper()


def slug(valor):
    return re.sub(r'[^a-z0-9]+', '-', sem_acento(valor).lower()).strip('-')


def aceitar_cookies(page):
    page.evaluate(r"""() => {
      const n = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const vis = x => (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
      const el = [...document.querySelectorAll('button,a')]
        .find(x => vis(x) && /aceitar|concordar|entendi/.test(n(x.innerText || x.textContent)));
      if (el) el.click();
    }""")
    page.wait_for_timeout(800)


def abrir_modal(page):
    aberto = page.evaluate(r"""() => {
      const n = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const vis = x => (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
      const todos = [...document.querySelectorAll('button,a,[role=button],span,div')].filter(vis);
      let el = todos.find(x => /^mudar localiza/.test(n(x.innerText || x.textContent)));
      if (!el) el = todos.find(x => /mudar localiza/.test(n(x.innerText || x.textContent)));
      if (!el) return false;
      const clicavel = el.closest('button,a,[role=button]') || el;
      clicavel.scrollIntoView({block: 'center'});
      clicavel.click();
      return true;
    }""")
    page.wait_for_timeout(1800)
    return aberto


def campo_cidade(page):
    seletores = [
        "input[placeholder*='cidade' i]",
        "input[aria-label*='cidade' i]",
        "input[name*='cidade' i]",
        "input[name*='city' i]",
        "input[type='search']",
        "input[type='text']",
    ]
    for seletor in seletores:
        loc = page.locator(seletor)
        try:
            for i in range(min(loc.count(), 10)):
                campo = loc.nth(i)
                if campo.is_visible() and campo.is_enabled():
                    return campo
        except Exception:
            continue
    return None


def opcoes_visiveis(page):
    return page.evaluate(r"""() => {
      const n = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/\s+/g, ' ').trim().toUpperCase();
      const vis = x => (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
      const saida = [];
      for (const el of document.querySelectorAll('li,[role=option],button,a,p,span,div')) {
        if (!vis(el)) continue;
        const t = n(el.innerText || el.textContent);
        if (!t || t.length > 60) continue;
        if ([...el.children].some(c => n(c.innerText || c.textContent) === t)) continue;
        if (/^[A-Z][A-Z .'\-]{2,}(\/SP| - SP| SP)?$/.test(t)) saida.push(t);
      }
      return [...new Set(saida)].slice(0, 60);
    }""")


def clicar_opcao(page, cidade):
    return page.evaluate(r"""cidade => {
      const n = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/\s+/g, ' ').trim().toUpperCase();
      const vis = x => (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
      const alvo = n(cidade);
      const ok = t => t === alvo || t === alvo + '/SP' || t === alvo + ' - SP' || t === alvo + ' SP';
      const cands = [...document.querySelectorAll('li,[role=option],button,a,p,span,div')]
        .filter(el => {
          if (!vis(el)) return false;
          const t = n(el.innerText || el.textContent);
          if (!ok(t)) return false;
          return ![...el.children].some(c => ok(n(c.innerText || c.textContent)));
        });
      if (!cands.length) return {clicked: false};
      const el = cands[0];
      const clicavel = el.closest('li,[role=option],button,a') || el;
      clicavel.scrollIntoView({block: 'center'});
      clicavel.click();
      return {clicked: true, text: n(clicavel.innerText || clicavel.textContent)};
    }""", cidade)


def confirmar_localizacao(page):
    page.evaluate(r"""() => {
      const n = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const vis = x => (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
      const el = [...document.querySelectorAll('button,a,[role=button]')]
        .find(x => vis(x) && /confirmar localiza|^confirmar$/.test(n(x.innerText || x.textContent)));
      if (el) el.click();
    }""")
    page.wait_for_timeout(6500)


def selecionar_cidade(page, cidade):
    diagnostico = {
        'modalOpened': False,
        'typed': False,
        'optionClicked': False,
        'autocompleteOptions': [],
    }
    diagnostico['modalOpened'] = abrir_modal(page)

    campo = campo_cidade(page)
    if campo is None:
        return False, 'Campo de cidade nao localizado', diagnostico

    try:
        campo.click()
        campo.fill('')
        campo.type(cidade.title(), delay=110)
        diagnostico['typed'] = True
    except Exception as erro:
        return False, 'Falha ao digitar a cidade: %s' % str(erro)[:110], diagnostico

    page.wait_for_timeout(3500)
    diagnostico['autocompleteOptions'] = opcoes_visiveis(page)

    resultado = clicar_opcao(page, cidade)
    if not resultado.get('clicked'):
        try:
            campo.press('ArrowDown')
            page.wait_for_timeout(700)
            campo.press('Enter')
        except Exception:
            pass
        page.wait_for_timeout(1500)
        resultado = clicar_opcao(page, cidade)

    diagnostico['optionClicked'] = bool(resultado.get('clicked'))
    page.wait_for_timeout(1200)
    confirmar_localizacao(page)

    corpo = norm(page.locator('body').inner_text())
    confirmado = (norm(cidade) + '/SP' in corpo) or (
        norm(cidade) in corpo and 'CIDADE ALTERADA COM SUCESSO' in corpo
    )
    motivo = None if confirmado else '%s/SP nao confirmada' % cidade
    return confirmado, motivo, diagnostico


def clicar_aba(page, rotulo):
    page.evaluate(r"""label => {
      const n = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const vis = x => (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
      const el = [...document.querySelectorAll('button,a,[role=tab],[role=button]')]
        .find(x => vis(x) && n(x.innerText || x.textContent) === n(label));
      if (el) { el.scrollIntoView({block: 'center'}); el.click(); }
    }""", rotulo)
    page.wait_for_timeout(4000)


def cards_visiveis(page):
    return page.evaluate(r"""() => {
      const L = s => (s || '').replace(/\s+/g, ' ').trim();
      const vis = x => (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
      const ctas = [...document.querySelectorAll('a,button')]
        .filter(e => vis(e) && /^assine j[aá]$/i.test(L(e.innerText || e.textContent)));
      const saida = [];
      for (const cta of ctas) {
        let no = cta;
        for (let i = 0; i < 14 && no; i++, no = no.parentElement) {
          const t = L(no.innerText || no.textContent);
          if (/R\$\s*\d{1,4}[,.]\d{2}/i.test(t) &&
              /(?:600\s*MEGA|1\s*GIGA)/i.test(t) &&
              t.length >= 40 && t.length <= 1800) {
            saida.push(t);
            break;
          }
        }
      }
      return [...new Set(saida)];
    }""")


def valor(texto, posterior=False):
    texto = re.sub(r'\s+', ' ', texto or '').strip()
    if posterior:
        padrao = r'Ap[oó]s[,]?\s*R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})'
    else:
        padrao = r'R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})\s*Por\s+6\s+meses'
    m = re.search(padrao, texto, re.I)
    return round(float('%s.%s' % (m.group(1), m.group(2))), 2) if m else None


def oferta_fibra(texto):
    if not re.search(r'(600\s*MEGA|1\s*GIGA)\s*\+\s*DESKTOP\s*PLAY', texto, re.I):
        return None
    if not re.search(r'DESKTOP\s*PLAY\s*DE\s*CORTESIA', texto, re.I):
        return None
    atual = valor(texto)
    if atual is None:
        return None
    speed = 1000 if re.search(r'1\s*GIGA\s*\+\s*DESKTOP\s*PLAY', texto, re.I) else 600
    return {
        'offerType': 'fibra',
        'convergenceType': None,
        'name': 'Fibra ' + ('1 Giga' if speed == 1000 else '600 Mega'),
        'fixedSpeedMb': speed,
        'monthlyPrice': atual,
        'previousPrice': None,
        'postPromotionPrice': valor(texto, True),
        'desktopPlayIncluded': True,
        'desktopPlayCourtesy': True,
        'tvIncluded': False,
    }


def oferta_convergente(texto):
    m = re.search(r'600\s*MEGA\s*\+\s*(15|20)\s*GIGA\s*CELULAR', texto, re.I)
    if not m:
        return None
    atual = valor(texto)
    if atual is None:
        return None
    gb = int(m.group(1))
    return {
        'offerType': 'convergente',
        'convergenceType': 'fibra_movel',
        'name': '600 Mega + Movel %d GB' % gb,
        'fixedSpeedMb': 600,
        'mobilePlanType': 'movel',
        'mobileAllowanceGb': gb,
        'monthlyPrice': atual,
        'previousPrice': None,
        'postPromotionPrice': valor(texto, True),
        'tvIncluded': False,
    }


def coletar_cidade(browser, cidade):
    resultado = {
        'city': cidade,
        'uf': 'SP',
        'locationConfirmed': False,
        'fiberOffers': [],
        'fiberMobileOffers': [],
        'tvOffersAccepted': 0,
        'productionFilesChanged': False,
    }
    context = browser.new_context(
        locale='pt-BR',
        timezone_id='America/Sao_Paulo',
        viewport={'width': 1440, 'height': 1100},
    )
    page = context.new_page()
    page.set_default_timeout(TIMEOUT)
    try:
        resposta = page.goto(URL, wait_until='domcontentloaded', timeout=TIMEOUT)
        resultado['httpStatus'] = resposta.status if resposta else None
        page.wait_for_timeout(5000)
        aceitar_cookies(page)

        ok, motivo, diagnostico = selecionar_cidade(page, cidade)
        resultado['locationConfirmed'] = ok
        resultado['selectionDiagnostics'] = diagnostico
        if not ok:
            resultado['reason'] = motivo
        else:
            clicar_aba(page, 'Internet')
            resultado['fiberOffers'] = [
                x for x in (oferta_fibra(t) for t in cards_visiveis(page)) if x
            ]
            clicar_aba(page, 'Internet + Celular')
            resultado['fiberMobileOffers'] = [
                x for x in (oferta_convergente(t) for t in cards_visiveis(page)) if x
            ]
            resultado['fiberOffers'] = sorted(
                {x['fixedSpeedMb']: x for x in resultado['fiberOffers']}.values(),
                key=lambda x: x['fixedSpeedMb'],
            )
            resultado['fiberMobileOffers'] = sorted(
                {x['mobileAllowanceGb']: x for x in resultado['fiberMobileOffers']}.values(),
                key=lambda x: x['mobileAllowanceGb'],
            )
            if resultado['fiberOffers'] and resultado['fiberMobileOffers']:
                resultado['status'] = 'validada_piloto'
            else:
                resultado['status'] = 'cidade_confirmada_sem_ofertas_esperadas'

        (EVID / ('%s.html' % slug(cidade))).write_text(page.content(), encoding='utf-8')
        page.screenshot(path=str(EVID / ('%s.png' % slug(cidade))), full_page=True)
    except Exception as erro:
        resultado['reason'] = '%s: %s' % (type(erro).__name__, str(erro)[:170])
    context.close()
    return resultado


def main():
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    EVID.mkdir(parents=True, exist_ok=True)
    dados = {
        'operator': 'Desktop',
        'mode': 'lote_3_v2',
        'generated': agora(),
        'citiesExpected': len(CIDADES),
        'results': [],
        'productionFilesChanged': False,
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        for cidade in CIDADES:
            dados['results'].append(coletar_cidade(browser, cidade))
        browser.close()

    resultados = dados['results']
    dados['summary'] = {
        'citiesProcessed': len(resultados),
        'locationsConfirmed': sum(x['locationConfirmed'] for x in resultados),
        'citiesWithFiber': sum(bool(x['fiberOffers']) for x in resultados),
        'citiesWithFiberMobile': sum(bool(x['fiberMobileOffers']) for x in resultados),
        'tvOffersAccepted': 0,
        'technicalPending': sum(not x['locationConfirmed'] for x in resultados),
    }
    SAIDA.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dados['summary'], ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
