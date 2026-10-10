# ReplicAI — de skill a plataforma comercializável

## O problema que estamos resolvendo

Hoje o ReplicAI é uma skill do Claude Code: 2.309 linhas de Python que usam o
Chrome como renderizador. Para funcionar, a máquina precisa de **seis**
dependências instaladas (Python + 4 bibliotecas, Chrome, Higgsfield CLI, ffmpeg,
curl e o próprio Claude Code).

Nenhum cliente final instala isso. E cada um precisaria da própria conta paga no
Higgsfield — o que torna impossível controlar custo, preço e experiência.

**A decisão:** virar SaaS web. As seis dependências são instaladas **uma vez**, no
servidor, dentro de um contêiner. O cliente usa o navegador.

---

## O que isso resolve

| Problema hoje | Com a plataforma |
|---|---|
| Não roda em Windows sem ajuste | Roda em qualquer lugar: o cliente usa navegador |
| Cliente precisa de conta Higgsfield | Uma conta sua, embutida no preço |
| Atualizar = reenviar a pasta | Você publica, todo mundo já está na versão nova |
| Venda de cópia | Receita recorrente |
| Código aberto na mão do cliente | O motor fica no seu servidor |

---

## Fases

### Fase 0 — Fundação ✅ (feita)
- [x] `requirements.txt` com versões travadas — o que faltava para instalar em qualquer máquina
- [x] `Dockerfile` com Python + Chromium + ffmpeg + fontes
- [x] `docker-compose.yml` com api + worker + fila
- [ ] Instalar o Docker Desktop (ainda não está na máquina)
- [ ] Copiar o motor para `motor/` e subir o contêiner pela primeira vez

### Fase 1 — MVP funcional
O caminho mínimo que já tem valor: upload da arte-mãe → escolha de formatos →
download das peças.
- [ ] `api/main.py` — endpoints de upload, status do job e download
- [ ] Fila: renderizar peça leva minutos, não pode travar a requisição
- [ ] Adaptar o motor para receber caminhos de entrada/saída por parâmetro
- [ ] Front-end mínimo: uma página de upload e uma de resultado
- [ ] Testes do motor com pytest — **2.309 linhas sem rede de proteção hoje**

### Fase 2 — Produto vendável
- [ ] Login (e-mail + senha ou Google)
- [ ] Cobrança por assinatura (Stripe) com plano por volume de peças
- [ ] Limite de uso por plano e controle do custo de Higgsfield por cliente
- [ ] Histórico de projetos do cliente
- [ ] Página de preço e onboarding

### Fase 3 — Robustez
Aqui as skills de QA que você perguntou finalmente se aplicam, porque existe
front-end e back-end de verdade.
- [ ] Testes de API (contrato dos endpoints)
- [ ] Testes end-to-end do fluxo de upload a download
- [ ] Teste de carga: quantas peças simultâneas o servidor aguenta
- [ ] Monitoramento de erro em produção
- [ ] QA visual: a peça gerada saiu correta?

---

## Decisões de arquitetura, e por quê

**Backend em Python (FastAPI).** O motor já é Python. Reescrever em outra
linguagem jogaria fora 2.309 linhas testadas na prática.

**Fila de jobs (Redis + RQ).** Renderizar uma peça abre o Chromium e leva
segundos ou minutos. Sem fila, a requisição estoura e o cliente vê erro. Com
fila, ele vê "processando" e o worker trabalha em segundo plano.

**Worker separado da API.** A API é leve, o worker é pesado. Separados, você
escala só o que precisa — mais workers em dia de pico, sem mexer na API.

**Docker.** É o que torna "funciona em outras máquinas" verdade por construção:
a imagem carrega o Chromium e o ffmpeg dentro dela.

**O motor não muda de lugar.** A pasta-produto da skill `replicai` continua
existindo e funcionando. A plataforma usa uma cópia do motor em `motor/`.
Nada do que fizemos aqui alterou o ReplicAI original.
