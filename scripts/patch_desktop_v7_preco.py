#!/usr/bin/env python3
from pathlib import Path

SCRIPT = Path('scripts/coletar_desktop_campinas_modelo_claro_v7.py')
if not SCRIPT.exists():
    raise SystemExit(f'Arquivo nao encontrado: {SCRIPT}')

texto = SCRIPT.read_text(encoding='utf-8')
inicio = texto.index('def valor(texto,posterior=False):')
fim = texto.index('\ndef fibra(', inicio)

nova_funcao = r'''def valor(texto,posterior=False):
    """Extrai o preco comercial, ignorando R$ 29,99 do texto do Desktop Play."""
    texto = re.sub(r'\s+', ' ', texto or '').strip()
    if posterior:
        padrao = r'Ap[oó]s[,]?\s*R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})'
    else:
        padrao = r'R\$\s*([0-9]{1,4})\s*[,.]\s*([0-9]{2})\s*Por\s+6\s+meses'
    m = re.search(padrao, texto, re.I)
    return round(float(f'{m.group(1)}.{m.group(2)}'), 2) if m else None
'''

texto = texto[:inicio] + nova_funcao + texto[fim:]
SCRIPT.write_text(texto, encoding='utf-8')
print('Correcao aplicada:', SCRIPT)
