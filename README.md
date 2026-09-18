# ofertas-dados

Coleta automática de ofertas de banda larga a partir das **URLs oficiais das
operadoras** (coluna FONTE_SITE da aba COMPARATIVO_OFERTAS).

Este repositório é **público** e contém apenas dados de preço já divulgados
publicamente pelas próprias operadoras nos seus sites. Nenhuma informação
interna, de market share ou de base de clientes é publicada aqui.

---

## Endpoint publicado

```
https://inteligencia-dell.github.io/ofertas-dados/dados/ofertas.json
https://inteligencia-dell.github.io/ofertas-dados/dados/status/
```

No dashboard, aba **4. Atualizar Dashboard**, campo **URL DA API**, informe
apenas a base — **sem** `/ofertas.json`:

```
https://inteligencia-dell.github.io/ofertas-dados/dados
```

---

## Cobertura

| Indicador | Valor |
|---|---|
| Ofertas monitoradas | 560 |
| Com FONTE_SITE cadastrada | 542 (96,8%) |
| Sem FONTE_SITE | 18 |
| URLs distintas | 67 |
| Operadoras | 8 |
| Cidades | 139 |

**Concentração:** 7 URLs nacionais cobrem 424 pontos (78%); 60 ISPs locais
cobrem os 118 restantes.

| Operadora | Ofertas | FONTE_SITE |
|---|---|---|
| Claro | 138 | `claro.com.br/internet` |
| Vivo | 97 | `vivo.com.br/.../melhores-ofertas` |
| Desktop | 83 | `desktop.com.br/internet/` |
| Vero | 38 | `querovero.com.br/.../planos-internet-residencial` |
| Alares | 28 | `alaresinternet.com.br` |
| Weclix | 21 | `weclix.com.br/planos/` |
| Algar | 19 | `loja.algar.com.br` |

---

## Semáforo

| Cor | Condição | Ação sobre o dado |
|---|---|---|
| 🟢 **Verde** | A FONTE_SITE comprovou mudança de preço ou velocidade | Atualiza e registra o valor anterior em `previous` |
| 🟡 **Amarelo** | A FONTE_SITE confirmou o valor vigente | Mantém |
| 🔴 **Vermelho** | A FONTE_SITE não permitiu extrair a oferta | **Preserva o último valor comprovado** |

Uma oferta **nunca** é alterada sem evidência na fonte. Se a página cair, o
registro anterior permanece intacto, marcado "a validar" com confiança baixa.
Se **nenhuma** fonte responder e não houver histórico, a gravação é bloqueada
e o `ofertas.json` anterior fica preservado.

### Pareamento preço × velocidade

O coletor prioriza a velocidade que aparece **antes** do preço — padrão dos
cartões comerciais ("600 Mega … por R$ 99,90") — e, entre os candidatos,
escolhe o **mais aderente ao baseline da planilha**. Nos testes isso fez a
Claro capturar o plano de 600 Mega, e não o de 1 Giga da mesma página.

### As 18 ofertas sem FONTE_SITE

Permanecem em vermelho até receberem URL na planilha:

- **TRÊS LAGOAS** (MS) — Claro, Vivo, Vero e ISP local
- **ISP local sem URL** em 14 cidades: CASA BRANCA, CORDEIRÓPOLIS, GUAPIAÇU,
  IBIÚNA, JAÚ, MIRASSOL, MOCOCA, MOGI GUAÇU, MONTE ALTO, PONTAL,
  SANTA CRUZ DAS PALMEIRAS, SANTA GERTRUDES, TAMBAÚ, VINHEDO

---

## Uso

```bash
# atualizar tudo
python scripts/coletar_ofertas.py --ambiente producao

# validar sem gravar
python scripts/coletar_ofertas.py --dry-run

# só uma operadora
python scripts/coletar_ofertas.py --operadora Claro

# regenerar o cadastro quando a planilha mudar
python scripts/gerar_fontes.py
```

**No GitHub:** Actions ▸ Atualizar ofertas ▸ Run workflow. Agendado para
06:25, 12:25 e 18:25 (Brasília).

---

## Configuração do repositório

1. **Settings ▸ Actions ▸ General ▸ Workflow permissions** →
   *Read and write permissions* → Save
2. **Settings ▸ Pages** → *Deploy from a branch* → `main` + `/(raiz)` → Save

Sem o passo 1 o coletor consulta as fontes, mas não consegue publicar.

---

## Limitação

O coletor lê **HTML estático**. Operadoras que montam preços via JavaScript
retornarão vermelho — comportamento correto e seguro, pois nunca inventa dado.

O diagnóstico de quais fontes exigem renderização sai na **primeira execução
real**, no resumo da aba Actions, que lista fonte por fonte o motivo de cada
vermelho. Se uma fonte relevante aparecer, adicione renderização ao workflow:

```yaml
      - name: Instalar Playwright
        run: |
          pip install playwright
          playwright install --with-deps chromium
```

e adapte a função `baixar()` para renderizar antes de extrair.

---

## Testes executados

| Cenário | Resultado |
|---|---|
| Extração aderente ao baseline | Capturou 600 Mega, ignorou 1 Giga da mesma página |
| Mudança de preço | Verde, com `previous` registrando o valor anterior |
| Reexecução sem mudança | Tudo amarelo — sem commit desnecessário |
| FONTE_SITE fora do ar | Preço preservado, vermelho, confiança baixa |
| Página sem preço extraível | Preservado, vermelho, alerta gerado |
| Falha total sem histórico | Gravação bloqueada, arquivo anterior intacto |
| Contrato com o dashboard | 5/5 aprovadas pela `validateOffer` do V.18.09 |
