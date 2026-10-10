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

**O passo 3 está provado.** Em 10/10/2026 a esteira do GitHub Actions construiu
a imagem e renderizou a peça de prova dentro de um contêiner Linux. Commit
`b1f9258`. O motor roda em qualquer servidor — a fundação da Fase 1 está de pé.

### Por que a prova roda no GitHub Actions, e não aqui

| | |
|---|---|
| Máquina | MacBook Pro 13" 2017, i5 dois núcleos, 8 GB |
| Sistema | macOS 13.7.8 Ventura — **teto deste modelo**, a Apple cortou o 2017 no Sonoma |
| Docker Desktop e OrbStack | exigem Sonoma. Não instalam |
| Colima / Rancher / Podman | o Homebrew não tem mais pacote pronto para Ventura: compila da fonte, e ainda sobem uma VM Linux com Chromium dentro |

Não é configuração errada: a máquina saiu da janela de suporte. A Fase 1 (API em
Python) se desenvolve e testa aqui normalmente, sem contêiner. A esteira verifica
o contêiner a cada push — que é onde isso importa.

Para publicar, use o **GitHub Desktop** (instalado). O push por token no terminal
não funcionou: a colagem não chega no prompt escondido.

### Três armadilhas desarmadas antes da prova

Achadas lendo o código, antes de existir Docker. Cada uma faria o passo 3 falhar
com mensagem que não aponta a causa:

- **Chromium como root não abre sem `--no-sandbox`.** O motor lê `CHROME_FLAGS`
  do ambiente; o Dockerfile define, o Mac não tem.
- **`assets/` fora de alcance.** Na skill eles ficam um nível acima do script;
  aqui o motor é pacote e eles ficam ao lado. Procura nos dois.
- **Pastas vazias somem no git.** `api/`, `web/` e `fontes/` ganharam `.gitkeep`,
  senão o `COPY` do Dockerfile quebraria só no servidor.

## Próximo passo

Fase 1 — MVP funcional. O caminho mínimo que já tem valor: subir a arte-mãe,
escolher formatos, baixar as peças.

- [ ] `api/main.py` — upload, status do job, download
- [ ] Fila (Redis + RQ): renderizar leva minutos e não cabe numa requisição
- [ ] Motor recebendo caminhos de entrada e saída por parâmetro
- [ ] Front-end mínimo: uma página de upload, uma de resultado
- [ ] Testes do motor com pytest — 2.309 linhas sem rede de proteção hoje

Comece pelos testes do motor ou pela API, não pelo front-end: o que decide se o
produto existe é o caminho upload → peça pronta.

**Já existe um Studio funcionando** em
`~/Desktop/OPERAÇÃO CLAUDE CODE/ReplicAI/studio/` — servidor em Python puro com
upload, fila, acompanhamento e edição de peça. Ele não é a arquitetura final,
mas resolveu problemas reais de produto (prévia de PSD lendo o cabeçalho do
arquivo, aviso de fundo faltante, animação por preset). Vale ler antes de
desenhar a API do zero.

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
