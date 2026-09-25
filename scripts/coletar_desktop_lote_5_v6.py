#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Desktop lote 5 v6.

Combina duas partes ja validadas:
1. Selecao de cidade aprovada na versao anterior, com nome oficial acentuado.
2. Separacao de ofertas do modelo aprovado em Campinas, que gerou:
   Fibra 600 Mega + Desktop Play de cortesia - R$ 99,99 - apos R$ 109,99
   Fibra 1 Giga + Desktop Play de cortesia   - R$ 119,99 - apos R$ 139,99
   600 Mega + Movel 15 GB                    - R$ 129,99 - apos R$ 139,99
   600 Mega + Movel 20 GB                    - R$ 139,99 - apos R$ 149,99

Os cards das duas abas sao acumulados e classificados pelo proprio conteudo,
entao a separacao nao depende da troca de aba ter alterado a tela.
"""
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / 'dados' / 'piloto-desktop-lote-5-v6.json'
EVID = RAIZ / 'evidencias-desktop-lote-5-v6'
URL = 'https://www.desktop.com.br/'
TIMEOUT = 60000
CIDADES = [
    [
        "VALINHOS",
        "Valinhos"
    ],
    [
        "VINHEDO",
        "Vinhedo"
    ],
    [
        "VOTORANTIM",
        "Votorantim"
    ]
]


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def sem_acento(valor):
    texto = unicodedata.normalize('NFD', str(valor or ''))
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn')


def norm(valor):
    texto = re.sub(r"[^A-Za-z0-9/ -]", ' ', sem_acento(valor))
    return re.sub(r'\s+', ' ', texto).strip().upper()


def slug(valor):
    return re.sub(r'[^a-z0-9]+', '-', sem_acento(valor).lower()).strip('-')


# ----------------------------------------------------------------------------
# Selecao de cidade, mantida da versao aprovada.
# ----------------------------------------------------------------------------
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
      if (!el) el = todos.find(x => {
        const t = n(x.innerText || x.textContent);
        return /\/sp$/.test(t) && t.length < 40;
      });
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
        "input[placeholder*='pesquis' i]", "input[placeholder*='cidade' i]",
        "input[aria-label*='cidade' i]", "input[name*='cidade' i]",
        "input[name*='city' i]", "input[type='search']", "input[type='text']",
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
    return page.evaluate(r"""() => {
      const n = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/[^A-Za-z0-9/ -]/g, ' ').replace(/\s+/g, ' ').trim().toUpperCase();
      const vis = x => (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
      const saida = [];
      for (const el of document.querySelectorAll('li,[role=option],button,a,p,span,div')) {
        if (!vis(el)) continue;
        const t = n(el.innerText || el.textContent);
        if (!t || t.length > 60) continue;
        if ([...el.children].some(c => n(c.innerText || c.textContent) === t)) continue;
        if (/^[A-Z][A-Z0-9 '\-]{2,}(\/SP| - SP| SP)?$/.test(t)) saida.push(t);
      }
      return [...new Set(saida)].slice(0, 60);
    }""")


def encontrou_cidade(page, chave):
    for opcao in opcoes_visiveis(page):
        if opcao.replace('/SP', '').replace(' - SP', '').strip() == chave:
            return True
    return False


def clicar_opcao(page, chave):
    return page.evaluate(r"""chave => {
      const n = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/[^A-Za-z0-9/ -]/g, ' ').replace(/\s+/g, ' ').trim().toUpperCase();
      const vis = x => (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
      const alvo = n(chave);
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
      return {clicked: true};
    }""", chave)


def termos_de_busca(nome_oficial):
    base = nome_oficial.strip()
    termos = [base]
    atual = base
    while len(atual) > 2:
        atual = atual[:-1]
        if atual.endswith(' ') or atual.endswith("'"):
            continue
        termos.append(atual)
    return termos


def digitar_e_localizar(page, campo, chave, nome_oficial):
    tentativas = []
    for termo in termos_de_busca(nome_oficial):
        try:
            campo.click()
            campo.fill('')
            page.wait_for_timeout(350)
            campo.type(termo, delay=110)
        except Exception:
            continue
        page.wait_for_timeout(2300)
        tentativas.append(termo)
        if encontrou_cidade(page, chave):
            return True, tentativas
        if len(tentativas) >= 8:
            break
    return False, tentativas


def confirmar_localizacao(page):
    page.evaluate(r"""() => {
      const n = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const vis = x => (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
      const el = [...document.querySelectorAll('button,a,[role=button]')]
        .find(x => vis(x) && /confirmar localiza|^confirmar$/.test(n(x.innerText || x.textContent)));
      if (el) el.click();
    }""")
    page.wait_for_timeout(6500)


def cidade_aplicada(page, chave):
    corpo = norm(page.locator('body').inner_text())
    return (chave + '/SP' in corpo) or (
        chave in corpo and 'CIDADE ALTERADA COM SUCESSO' in corpo
    )


def selecionar_cidade(page, chave, nome_oficial):
    diagnostico = {'modalOpened': False, 'searchTermsTried': [],
                   'autocompleteReady': False, 'optionClicked': False}
    diagnostico['modalOpened'] = abrir_modal(page)

    campo = campo_busca(page)
    if campo is None:
        return False, 'Campo de busca de cidade nao localizado', diagnostico

    pronto, tentativas = digitar_e_localizar(page, campo, chave, nome_oficial)
    diagnostico['searchTermsTried'] = tentativas
    diagnostico['autocompleteReady'] = pronto

    resultado = clicar_opcao(page, chave)
    if not resultado.get('clicked'):
        try:
            campo.press('ArrowDown')
            page.wait_for_timeout(700)
            campo.press('Enter')
        except Exception:
            pass
        page.wait_for_timeout(1600)
        resultado = clicar_opcao(page, chave)

    diagnostico['optionClicked'] = bool(resultado.get('clicked'))
    page.wait_for_timeout(1200)
    confirmar_localizacao(page)
    if not cidade_aplicada(page, chave):
        page.wait_for_timeout(3000)

    confirmado = cidade_aplicada(page, chave)
    return confirmado, None if confirmado else '%s/SP nao confirmada' % chave, diagnostico


# ----------------------------------------------------------------------------
# Extracao e separacao de ofertas, no modelo aprovado em Campinas.
# ----------------------------------------------------------------------------
def clicar_aba(page, rotulo):
    """Mesmo clique por texto exato usado no piloto de Campinas."""
    clicou = page.evaluate(r"""label => {
      const n = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const vis = x => (x.offsetWidth || x.offsetHeight || x.getClientRects().length);
      const el = [...document.querySelectorAll('button,a,[role=tab],[role=button]')]
        .find(x => vis(x) && n(x.innerText || x.textContent) === n(label));
      if (!el) return false;
      el.scrollIntoView({block: 'center'});
      el.click();
      return true;
    }""", rotulo)
    page.wait_for_timeout(4500)
    return clicou


def cards_visiveis(page):
    """Menor ancestral de cada CTA Assine ja, como no piloto de Campinas."""
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


def coletar_cards_das_abas(page):
    """Acumula os cards das duas abas, sem depender da troca visual."""
    acumulados = []
    diagnostico = {'tabsClicked': [], 'cardsPerTab': {}}

    for rotulo in ['Internet', 'Internet + Celular', 'Internet e Celular']:
        clicou = clicar_aba(page, rotulo)
        if not clicou:
            continue
        diagnostico['tabsClicked'].append(rotulo)
        atuais = cards_visiveis(page)
        diagnostico['cardsPerTab'][rotulo] = len(atuais)
        acumulados.extend(atuais)

    if not acumulados:
        acumulados = cards_visiveis(page)

    vistos = set()
    unicos = []
    for texto in acumulados:
        chave = re.sub(r'\s+', ' ', texto).strip()[:200]
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(texto)
    diagnostico['totalCards'] = len(unicos)
    return unicos, diagnostico


def preco_posterior(texto):
    texto = re.sub(r'\s+', ' ', texto or '').strip()
    m = re.search(r'Ap[oó]s[^R]{0,30}R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})', texto, re.I)
    return round(float('%s.%s' % (m.group(1), m.group(2))), 2) if m else None


def preco_atual(texto):
    """Preco vigente, com qualquer vigencia, sem valor assumido."""
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
    posterior = preco_posterior(texto)
    for inteiro, centavos in re.findall(r'R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})', texto, re.I):
        valor = round(float('%s.%s' % (inteiro, centavos)), 2)
        if posterior is None or valor != posterior:
            return valor
    return None


def vigencia(texto):
    m = re.search(r'Por\s+(\d+)\s+(?:mes|meses)', texto or '', re.I)
    return int(m.group(1)) if m else None


def velocidade(texto):
    m = re.search(r'(\d{2,5})\s*MEGA', texto, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d(?:[,.]\d)?)\s*GIGA(?!\s*CELULAR)', texto, re.I)
    if m:
        return int(round(float(m.group(1).replace(',', '.')) * 1000))
    return None


def franquia_movel(texto):
    m = re.search(r'(\d{1,4})\s*GIGA\s*CELULAR', texto, re.I)
    if not m:
        m = re.search(r'(?:DESKTOP\s*)?M[OÓ]VEL\s*(\d{1,4})\s*GB', texto, re.I)
    if not m:
        m = re.search(r'(\d{1,4})\s*GB\s*(?:de\s*)?(?:internet\s*)?(?:m[oó]vel|celular)', texto, re.I)
    return int(m.group(1)) if m else None


def tem_tv(texto):
    t = norm(texto)
    return any(x in t for x in ['TV + INTERNET', 'INTERNET + TV',
                                'CANAIS EM HD', 'CANAIS AO VIVO'])


def classificar_card(texto):
    """Separa o card em Fibra ou Fibra + Movel, como no piloto de Campinas."""
    if tem_tv(texto):
        return None, 'tv'

    speed = velocidade(texto)
    atual = preco_atual(texto)
    if speed is None or atual is None:
        return None, 'incompleto'

    posterior = preco_posterior(texto)
    meses = vigencia(texto)
    gb = franquia_movel(texto)
    play = bool(re.search(r'DESKTOP\s*PLAY', texto, re.I))
    cortesia = bool(re.search(r'DESKTOP\s*PLAY\s*(?:de\s*)?cortesia', texto, re.I))

    if gb:
        item = {
            'offerType': 'convergente',
            'convergenceType': 'fibra_movel',
            'name': '%s + Movel %d GB' % (
                '1 Giga' if speed == 1000 else '%d Mega' % speed, gb),
            'fixedSpeedMb': speed,
            'mobilePlanType': 'movel',
            'mobileAllowanceGb': gb,
            'monthlyPrice': atual,
            'previousPrice': None,
            'postPromotionPrice': posterior,
            'promotionMonths': meses,
            'desktopPlayIncluded': play,
            'desktopPlayCourtesy': cortesia,
            'tvIncluded': False,
            'cardText': texto[:900],
        }
        return item, 'convergente'

    if play and not cortesia:
        return None, 'play_pago'

    item = {
        'offerType': 'fibra',
        'convergenceType': None,
        'name': 'Fibra ' + ('1 Giga' if speed == 1000 else '%d Mega' % speed),
        'fixedSpeedMb': speed,
        'monthlyPrice': atual,
        'previousPrice': None,
        'postPromotionPrice': posterior,
        'promotionMonths': meses,
        'desktopPlayIncluded': play,
        'desktopPlayCourtesy': cortesia,
        'tvIncluded': False,
        'cardText': texto[:900],
    }
    return item, 'fibra'


def separar_ofertas(cards):
    fibra = {}
    convergente = {}
    rejeitados = {'tv': 0, 'incompleto': 0, 'play_pago': 0}
    for texto in cards:
        item, tipo = classificar_card(texto)
        if item is None:
            rejeitados[tipo] = rejeitados.get(tipo, 0) + 1
            continue
        if tipo == 'fibra':
            fibra[(item['fixedSpeedMb'], item['monthlyPrice'])] = item
        else:
            convergente[(item['fixedSpeedMb'], item['mobileAllowanceGb'])] = item

    lista_fibra = sorted(fibra.values(), key=lambda x: (x['fixedSpeedMb'], x['monthlyPrice']))
    lista_conv = sorted(convergente.values(),
                        key=lambda x: (x['fixedSpeedMb'], x['mobileAllowanceGb']))
    return lista_fibra, lista_conv, rejeitados


def coletar_cidade(browser, chave, nome_oficial):
    resultado = {
        'city': chave, 'cityLabel': nome_oficial, 'uf': 'SP',
        'locationConfirmed': False, 'fiberOffers': [], 'fiberMobileOffers': [],
        'tvOffersAccepted': 0, 'productionFilesChanged': False,
    }
    context = browser.new_context(locale='pt-BR', timezone_id='America/Sao_Paulo',
                                  viewport={'width': 1440, 'height': 1100})
    page = context.new_page()
    page.set_default_timeout(TIMEOUT)
    try:
        resposta = page.goto(URL, wait_until='domcontentloaded', timeout=TIMEOUT)
        resultado['httpStatus'] = resposta.status if resposta else None
        page.wait_for_timeout(5000)
        aceitar_cookies(page)

        ok, motivo, diagnostico = selecionar_cidade(page, chave, nome_oficial)
        resultado['locationConfirmed'] = ok
        resultado['selectionDiagnostics'] = diagnostico
        if not ok:
            resultado['reason'] = motivo
        else:
            cards, diag_abas = coletar_cards_das_abas(page)
            fibra, convergente, rejeitados = separar_ofertas(cards)
            resultado['fiberOffers'] = fibra
            resultado['fiberMobileOffers'] = convergente
            resultado['tabDiagnostics'] = diag_abas
            resultado['rejectedCards'] = rejeitados

            if fibra and convergente:
                resultado['status'] = 'validada_piloto'
            elif fibra:
                resultado['status'] = 'somente_fibra_disponivel'
            else:
                resultado['status'] = 'cidade_confirmada_sem_ofertas'

        (EVID / ('%s.html' % slug(chave))).write_text(page.content(), encoding='utf-8')
        page.screenshot(path=str(EVID / ('%s.png' % slug(chave))), full_page=True)
    except Exception as erro:
        resultado['reason'] = '%s: %s' % (type(erro).__name__, str(erro)[:170])
    context.close()
    return resultado


def main():
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    EVID.mkdir(parents=True, exist_ok=True)
    dados = {'operator': 'Desktop', 'mode': 'lote_5_v6', 'generated': agora(),
             'citiesExpected': len(CIDADES), 'results': [], 'productionFilesChanged': False}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        for chave, oficial in CIDADES:
            dados['results'].append(coletar_cidade(browser, chave, oficial))
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
