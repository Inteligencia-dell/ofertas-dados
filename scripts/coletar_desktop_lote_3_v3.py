#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Desktop lote 3 v3.

Correcoes desta versao:
- comparacao de cidade sempre sem acentos, nos dois lados;
- espera ativa pelo autocomplete filtrado antes de clicar;
- preco aceita qualquer vigencia: Por 3 meses, Por 6 meses, Valor fixo etc.;
- nenhum preco fixo e assumido, pois varia por cidade.
"""
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / 'dados' / 'piloto-desktop-lote-3-v3.json'
EVID = RAIZ / 'evidencias-desktop-lote-3-v3'
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
      if (!el) el = todos.find(x => /\/sp$/.test(n(x.innerText || x.textContent)) &&
                                    n(x.innerText || x.textContent).length < 40);
      if (!el) return false;
      const clicavel = el.closest('button,a,[role=button]') || el;
      clicavel.scrollIntoView({block: 'center'});
      clicavel.click();
      return true;
    }""")
    page.wait_for_timeout(2000)
    return aberto


def campo_busca(page):
    seletores = [
        "input[placeholder*='pesquis' i]",
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
            for i in range(min(loc.count(), 12)):
                campo = loc.nth(i)
                if campo.is_visible() and campo.is_enabled():
                    return campo
        except Exception:
            continue
    return None


def opcoes_visiveis(page):
    """Lista textos curtos visiveis que parecem itens do autocomplete."""
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
    """Clica no item cujo texto, sem acentos, corresponde exatamente a cidade."""
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


def digitar_com_recuo(page, campo, cidade):
    """Digita a cidade e recua caracteres ate o autocomplete responder.

    O filtro da Desktop usa o nome acentuado. Como a base interna nao tem acentos,
    o texto sem acento pode nao casar no final da palavra, por exemplo Ibate e Ibate.
    Por isso o script apaga o ultimo caractere ate a lista apresentar a cidade.
    """
    base = sem_acento(cidade).title()
    campo.click()
    campo.fill('')
    page.wait_for_timeout(400)
    campo.type(base, delay=120)
    page.wait_for_timeout(2200)

    tentado = [base]
    if encontrou_cidade(page, cidade):
        return True, tentado

    minimo = max(3, len(base) // 2)
    atual = base
    while len(atual) > minimo:
        atual = atual[:-1]
        try:
            campo.press('Backspace')
        except Exception:
            campo.fill(atual)
        page.wait_for_timeout(1600)
        tentado.append(atual)
        if encontrou_cidade(page, cidade):
            return True, tentado
    return False, tentado


def encontrou_cidade(page, cidade):
    """Confirma se a cidade digitada ja aparece entre as opcoes visiveis."""
    alvo = norm(cidade)
    for opcao in opcoes_visiveis(page):
        base = opcao.replace('/SP', '').replace(' - SP', '').strip()
        if base == alvo:
            return True
    return False

def confirmar_localizacao(page):
    page.evaluate(r"""() => {
      const n = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const vis = x => (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
      const el = [...document.querySelectorAll('button,a,[role=button]')]
        .find(x => vis(x) && /confirmar localiza|^confirmar$/.test(n(x.innerText || x.textContent)));
      if (el) el.click();
    }""")
    page.wait_for_timeout(6500)


def cidade_aplicada(page, cidade):
    corpo = norm(page.locator('body').inner_text())
    alvo = norm(cidade)
    return (alvo + '/SP' in corpo) or (
        alvo in corpo and 'CIDADE ALTERADA COM SUCESSO' in corpo
    )


def selecionar_cidade(page, cidade):
    diagnostico = {
        'modalOpened': False,
        'typed': False,
        'autocompleteReady': False,
        'optionClicked': False,
        'autocompleteOptions': [],
    }
    diagnostico['modalOpened'] = abrir_modal(page)

    campo = campo_busca(page)
    if campo is None:
        return False, 'Campo de busca de cidade nao localizado', diagnostico

    try:
        pronto, tentativas = digitar_com_recuo(page, campo, cidade)
        diagnostico['typed'] = True
        diagnostico['autocompleteReady'] = pronto
        diagnostico['typedAttempts'] = tentativas
    except Exception as erro:
        return False, 'Falha ao digitar a cidade: %s' % str(erro)[:110], diagnostico

    diagnostico['autocompleteOptions'] = opcoes_visiveis(page)

    resultado = clicar_opcao(page, cidade)
    if not resultado.get('clicked'):
        try:
            campo.press('ArrowDown')
            page.wait_for_timeout(700)
            campo.press('Enter')
        except Exception:
            pass
        page.wait_for_timeout(1600)
        resultado = clicar_opcao(page, cidade)

    diagnostico['optionClicked'] = bool(resultado.get('clicked'))
    page.wait_for_timeout(1200)
    confirmar_localizacao(page)

    if not cidade_aplicada(page, cidade):
        page.wait_for_timeout(3000)

    confirmado = cidade_aplicada(page, cidade)
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
    page.wait_for_timeout(4200)


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
              /(?:\d{2,4}\s*MEGA|\d\s*GIGA)/i.test(t) &&
              t.length >= 40 && t.length <= 1800) {
            saida.push(t);
            break;
          }
        }
      }
      return [...new Set(saida)];
    }""")


def preco_atual(texto):
    """Le o preco vigente sem assumir valor ou vigencia fixa."""
    texto = re.sub(r'\s+', ' ', texto or '').strip()
    padroes = [
        r'R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})\s*(?:/m[eê]s\s*)?Por\s+\d+\s+(?:mes|meses)',
        r'R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})\s*(?:/m[eê]s\s*)?Valor\s+fixo',
        r'R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})\s*(?:/m[eê]s\s*)?Por\s+apenas',
    ]
    for padrao in padroes:
        m = re.search(padrao, texto, re.I)
        if m:
            return round(float('%s.%s' % (m.group(1), m.group(2))), 2)
    # Fallback: ultimo preco do card que nao seja o valor pos promocional.
    valores = re.findall(r'R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})', texto, re.I)
    posterior = preco_posterior(texto)
    for inteiro, centavos in valores:
        valor = round(float('%s.%s' % (inteiro, centavos)), 2)
        if posterior is None or valor != posterior:
            return valor
    return None


def preco_posterior(texto):
    texto = re.sub(r'\s+', ' ', texto or '').strip()
    m = re.search(r'Ap[oó]s[^R]{0,30}R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})', texto, re.I)
    return round(float('%s.%s' % (m.group(1), m.group(2))), 2) if m else None


def vigencia(texto):
    m = re.search(r'Por\s+(\d+)\s+(?:mes|meses)', texto or '', re.I)
    if m:
        return int(m.group(1))
    if re.search(r'Valor\s+fixo', texto or '', re.I):
        return None
    return None


def velocidade(texto):
    m = re.search(r'(\d{2,5})\s*MEGA', texto, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d(?:[,.]\d)?)\s*GIGA', texto, re.I)
    if m:
        return int(round(float(m.group(1).replace(',', '.')) * 1000))
    return None


def tem_tv(texto):
    t = norm(texto)
    return any(x in t for x in ['TV + INTERNET', 'INTERNET + TV', 'CANAIS EM HD', 'CANAIS AO VIVO'])


def oferta_fibra(texto):
    """Internet residencial, com ou sem Desktop Play de cortesia."""
    if tem_tv(texto):
        return None
    if re.search(r'DESKTOP\s*M[OÓ]VEL|GIGA\s*CELULAR', texto, re.I):
        return None
    play = bool(re.search(r'DESKTOP\s*PLAY', texto, re.I))
    cortesia = bool(re.search(r'DESKTOP\s*PLAY\s*(?:de\s*)?cortesia', texto, re.I))
    if play and not cortesia:
        return None
    speed = velocidade(texto)
    atual = preco_atual(texto)
    if speed is None or atual is None:
        return None
    nome = 'Fibra ' + ('1 Giga' if speed == 1000 else '%d Mega' % speed)
    return {
        'offerType': 'fibra',
        'convergenceType': None,
        'name': nome,
        'fixedSpeedMb': speed,
        'monthlyPrice': atual,
        'previousPrice': None,
        'postPromotionPrice': preco_posterior(texto),
        'promotionMonths': vigencia(texto),
        'desktopPlayIncluded': play,
        'desktopPlayCourtesy': cortesia,
        'tvIncluded': False,
        'cardText': texto[:900],
    }


def oferta_convergente(texto):
    """Internet residencial somada a plano de celular no mesmo card."""
    if tem_tv(texto):
        return None
    m = re.search(r'(\d{1,4})\s*GIGA\s*CELULAR', texto, re.I)
    if not m:
        m = re.search(r'DESKTOP\s*M[OÓ]VEL\s*(\d{1,4})\s*GB', texto, re.I)
    if not m:
        return None
    speed = velocidade(texto)
    atual = preco_atual(texto)
    if speed is None or atual is None:
        return None
    gb = int(m.group(1))
    nome = '%s + Movel %d GB' % (
        '1 Giga' if speed == 1000 else '%d Mega' % speed, gb
    )
    return {
        'offerType': 'convergente',
        'convergenceType': 'fibra_movel',
        'name': nome,
        'fixedSpeedMb': speed,
        'mobilePlanType': 'movel',
        'mobileAllowanceGb': gb,
        'monthlyPrice': atual,
        'previousPrice': None,
        'postPromotionPrice': preco_posterior(texto),
        'promotionMonths': vigencia(texto),
        'tvIncluded': False,
        'cardText': texto[:900],
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
            fibra = [x for x in (oferta_fibra(t) for t in cards_visiveis(page)) if x]
            clicar_aba(page, 'Internet + Celular')
            convergentes = [x for x in (oferta_convergente(t) for t in cards_visiveis(page)) if x]

            resultado['fiberOffers'] = sorted(
                {(x['fixedSpeedMb'], x['monthlyPrice']): x for x in fibra}.values(),
                key=lambda x: (x['fixedSpeedMb'], x['monthlyPrice']),
            )
            resultado['fiberMobileOffers'] = sorted(
                {(x['fixedSpeedMb'], x['mobileAllowanceGb']): x for x in convergentes}.values(),
                key=lambda x: (x['fixedSpeedMb'], x['mobileAllowanceGb']),
            )
            if resultado['fiberOffers'] and resultado['fiberMobileOffers']:
                resultado['status'] = 'validada_piloto'
            elif resultado['fiberOffers']:
                resultado['status'] = 'somente_fibra_disponivel'
            else:
                resultado['status'] = 'cidade_confirmada_sem_ofertas'

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
        'mode': 'lote_3_v3',
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
        'territorialPending': sum(not x['locationConfirmed'] for x in resultados),
    }
    SAIDA.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dados['summary'], ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
