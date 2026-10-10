# ReplicAI — Plataforma (SaaS)

Fale com a pessoa em **português**. Compatibilidade **Mac e Windows** é obrigatória.

## Gatilho

Se a pessoa disser "vamos começar", "começar", "start", "bora" ou "oi": leia este
arquivo e o `docs/ROADMAP.md`, diga em duas linhas onde o projeto está e qual é o
próximo passo, e pergunte se pode seguir. **Não abra menu genérico.**

---

## O que é este projeto

Transformar o **ReplicAI** — hoje uma skill do Claude Code — em uma **plataforma
SaaS comercializável**.

O ReplicAI replica e desdobra uma peça-base (arte-mãe) em quantos formatos e
canais forem pedidos, re-diagramando de verdade: fundo estendido em vez de
cortado, texto real refeito, logo e tipografia preservados.

## Por que SaaS, e não venda de pasta

Para rodar hoje, a máquina precisa de **seis** dependências: Python + 4
bibliotecas, Google Chrome, Higgsfield CLI (pago), ffmpeg, curl e o próprio
Claude Code. Nenhum cliente final instala isso, e cada um precisaria da própria
conta no Higgsfield — o que torna impossível controlar custo, preço e
experiência.

Em SaaS, essas seis dependências são instaladas **uma vez**, no servidor, dentro
de um contêiner Docker. O cliente usa o navegador. Isso elimina o problema de
portabilidade por construção e coloca o custo do Higgsfield sob controle de quem
vende.

---

## Estado atual: Fase 0 concluída

| Arquivo | O que é |
|---|---|
| `requirements.txt` | As 4 deps do motor, versões travadas. **Resolução já validada com `pip --dry-run`.** |
| `requirements-api.txt` | FastAPI, uvicorn, Redis, RQ, boto3 |
| `requirements-dev.txt` | pytest, pytest-cov, httpx |
| `infra/Dockerfile` | Python 3.14 + Chromium + ffmpeg + fontes. É o que torna portável. |
| `infra/docker-compose.yml` | api + worker + redis |
| `motor/replica.py` | **O produto: 2.309 linhas.** Cópia do original. |
| `motor/psd_io.py` | Leitura de PSD |
| `motor/assets/` | `template.html` (motor de composição) e `formatos.json` |
| `docs/ROADMAP.md` | O plano em 4 fases e as decisões de arquitetura |

**Pendência que bloqueia o próximo passo:** não há como rodar Docker nesta
máquina. Verificado em 10/10/2026:

| | |
|---|---|
| Máquina | MacBook Pro 13" 2017 (MacBookPro14,1), i5 dois núcleos, 8 GB, 26 GB livres |
| Sistema | macOS 13.7.8 Ventura — **é o teto deste modelo**, a Apple cortou o 2017 no Sonoma |
| Docker Desktop | exige Sonoma (14+). Não instala |
| OrbStack | exige Sonoma desde a versão 2.0. Não instala |
| Colima / Rancher / Podman | instalam, mas o Homebrew não tem mais pacote pronto para Ventura: compila da fonte. E todos sobem uma VM Linux — com 8 GB e dois núcleos, rodando Chromium dentro, é terreno ruim |

Não é configuração errada: a máquina saiu da janela de suporte do ecossistema.

**Consequência para o projeto:** o passo 3 não deve ser provado aqui. Ele prova
que o motor roda em Linux dentro de um contêiner — e isso se prova melhor onde o
produto vai de fato rodar, num servidor Linux. A Fase 1 (API em Python) continua
podendo ser desenvolvida e testada nesta máquina normalmente, sem contêiner.

---

## Próximo passo

1. Instalar o Docker Desktop: `brew install --cask docker`, depois abrir o app
   uma vez e esperar a baleia aparecer na barra de menu
2. `docker compose -f infra/docker-compose.yml build`
3. Provar o render dentro do contêiner:
   `docker compose -f infra/docker-compose.yml run --rm api python testes/prova_container.py`
4. Só então seguir para a Fase 1 (API + fila)

Não construa a Fase 1 antes de provar o passo 3. Se o Chromium não renderizar no
contêiner, toda a arquitetura em cima muda.

**Use `run`, não `up`.** O `docker compose up` sobe a api, e o CMD da imagem
chama `uvicorn api.main:app`, que ainda não existe — o serviço entraria em ciclo
de reinício e pareceria falha de contêiner. `up` passa a valer na Fase 1.

### Três armadilhas já desarmadas (09–10/10/2026)

Encontradas antes do Docker existir na máquina, lendo o código. Cada uma faria o
passo 3 falhar com mensagem que não aponta a causa:

- **Chromium como root não abre sem `--no-sandbox`.** O motor agora aceita
  `CHROME_FLAGS` do ambiente e o Dockerfile define
  `--no-sandbox --disable-dev-shm-usage`. No Mac a variável não existe e nada muda.
- **`assets/` ficava fora do alcance.** Na skill os assets moram um nível acima
  do script; aqui o motor é um pacote e eles ficam ao lado. O motor procura nos
  dois lugares.
- **`../fontes` não existia** e o compose monta essa pasta. Criada com `.gitkeep`.

O `testes/prova_container.py` já passa na máquina local (Chrome do Mac), então o
teste está correto: o que o passo 3 mede é só o ambiente.

---

## Regras invioláveis

- **Não altere a pasta-produto original** em
  `~/Desktop/OPERAÇÃO CLAUDE CODE/ReplicAI/`. A skill `replicai` continua
  existindo e funcionando. Esta plataforma usa uma **cópia** do motor em `motor/`.
  Se o motor precisar de correção, corrija aqui e depois decida consciente se
  vale levar para a skill.
- **Geração de imagem roda em dois motores, nunca outro:** Higgsfield CLI ou
  Magnific MCP. Vídeo é exclusivo do Higgsfield CLI. Não use fal.ai, Flow,
  Midjourney ou Higgs MCP.
- **Nunca comite credencial.** Chave de Higgsfield, Stripe e storage vão em
  variável de ambiente, e `.env` fica no `.gitignore`.
- **O motor não muda de assinatura sem necessidade.** Ele é um CLI com
  subcomandos (`prep`, `analyze`, `crop`, `clean`, `render`, `video`,
  `formatos`). A API chama esses subcomandos; ela não reescreve a lógica.
- **Teste antes de ampliar.** Hoje são 2.309 linhas sem um único teste. Toda
  correção no motor nasce com um teste em `testes/`.

## Decisões já tomadas (não relitigar)

- **Backend em Python/FastAPI** — o motor já é Python; reescrever jogaria fora
  2.309 linhas validadas na prática.
- **Fila assíncrona (Redis + RQ)** — renderizar peça abre o Chromium e leva
  minutos. Sem fila, a requisição estoura por timeout.
- **Worker separado da API** — a API é leve, o worker é pesado. Separados,
  escala-se só o worker em dia de pico.
- **Docker** — é o que faz "funciona em outra máquina" ser verdade por
  construção.
