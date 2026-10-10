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
- [x] ~~Testes do motor com pytest~~ — **226 testes, começados em 10/10/2026**

### Sobre os testes

Rodar: `.venv/bin/python -m pytest`. A esteira roda a cada push, antes da prova
do contêiner, porque pega regressão de lógica em segundos.

Cobertura é 11%, e é de propósito. O alvo foi a lógica que **decide**, não a
contagem: `plan_fit` (cortar ou estender), o catálogo de formatos, a leitura de
entrada, as bandeiras do Chrome e a ida e volta de PSD. O resto de `replica.py`
são comandos que chamam Chrome, Higgsfield e ffmpeg — caros de testar e de valor
menor agora.

**Todo teste novo precisa falhar antes de passar.** Os primeiros que escrevi aqui
passavam com o motor sabotado: eu assertava que o corte continha a região
protegida, mas nos casos escolhidos o corte era a arte inteira, então a asserção
era verdadeira por acidente. Confira sabotando o motor de propósito e vendo o
teste quebrar; se não quebrar, o teste não existe.

Sabotagens já conferidas, todas pegas: ignorar a região protegida, centralizar o
corte em vez de seguir o protegido, trocar a estratégia padrão para `cover`,
parar de ler `CHROME_FLAGS`, e inverter largura com altura no PSD.

### Feito até agora (10/10/2026)

- `api/compositor.py` — a interface `Compositor` e duas implementações:
  `CompositorArquivo` (lê peça que alguém já escreveu) e `CompositorSimples`
  (regra determinística: arte vira fundo, texto na área segura). A composição
  automática continua em aberto — ver `docs/DECISAO-quem-compoe.md`.
- `api/pipeline.py` — `desdobrar(arte, formatos, compositor, pasta)`. Compõe,
  renderiza e grava `resultado.json`. Formato que falha não derruba os outros.
- 247 testes. Rápidos por padrão (2 s); os que abrem navegador ficam atrás do
  marcador `lento` e rodam na esteira.

- `api/fila.py` — `FilaRQ` (Redis, produção) e `FilaDireta` (roda na hora).
  Sem `REDIS_URL` cai para direta: a plataforma funciona inteira em máquina de
  desenvolvimento, só sem paralelismo.
- `api/trabalhos.py` — estado do trabalho em disco, porque API e worker são
  processos diferentes e a API pode cair.
- `api/main.py` — `POST /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/arquivos/...`,
  `/formatos`, `/saude`.
- `api/qualidade.py` — as quatro verificações de fundo e marca.
- 282 testes. Os rápidos em 4 s; os que abrem navegador ficam atrás de `lento`.

**`docker compose up` já vale**, agora que `api.main:app` existe.

- `web/index.html` — a tela. Uma só: a grade de formatos é o seletor **e** o
  acompanhamento. Cada retângulo está na proporção verdadeira do destino e se
  preenche com a peça quando ela fica pronta; o que falhou fica vermelho com o
  motivo no title. Não há página de resultado separada porque a replicação é o
  que a pessoa veio ver acontecer.

Herdou do Studio o que custou caro descobrir: a peça pode ser solta em qualquer
lugar da janela (a zona é pequena e, quando se erra, o navegador abre o arquivo
e a página não vê nada) e o PSD mostra medida e miniatura lendo o cabeçalho do
próprio arquivo, sem subir nada.

### Quem compõe: decidido (10/10/2026)

O modelo responde **papéis e zonas**, nunca pixels; a caixa é calculada em
`api/composicao.py`. Nada que ele responde chega ao render sem passar por
`conferir()`, e um erro vira uma volta de correção antes de desistir.

- `api/composicao.py` — o idioma, a conferência e a conversão em peça.
- `api/modelo.py` — a chamada à API da Anthropic (`claude-opus-5-5`), com saída
  forçada por esquema. Trocar de provedor é trocar este arquivo.
- `CompositorEmCadeia(modelo, regra)` — sem `ANTHROPIC_API_KEY` cai para a regra
  determinística. `/saude` diz qual está valendo.

### As verificações de qualidade rodam na esteira

`api/qualidade.py` tem quatro, e `api/pipeline.py` chama as que se aplicam a
cada peça: fidelidade do fundo e marca recortada como bloco opaco. O resultado
sai em `avisos`, por formato, e aparece na tela como "com ressalva".

**São ressalva, não barreira.** A peça é entregue com a observação; quem decide
se o fundo está bom o bastante é quem vai publicar.

Isso existe porque escrever a verificação e não chamá-la foi o erro de
10/10/2026 que deixou um fundo com lettering fantasma passar: a regra estava
escrita e ninguém a usava. Teste novo em `testes/test_pipeline.py` garante que
ela continue sendo chamada, não só existindo.

**Falta rodar com chave de verdade.** Tudo foi provado com modelo falso: o
contrato, a conferência, a correção, as caixas e o render. A chamada em si e o
custo por peça não foram exercitados — no teste de ponta a ponta com modelo
falso foram 5 chamadas para 3 formatos.

### Como os testes da API são rápidos

A fila é trocada por uma espiã que anota em vez de executar. Deixá-la executar
fazia cada teste abrir o Chrome e a suíte ia a 103 segundos — que é o mesmo que
não ter teste. O render tem cobertura própria no pipeline, e um caminho de ponta
a ponta roda marcado como `lento`.

**Já existe um Studio funcionando** em
`~/Desktop/OPERAÇÃO CLAUDE CODE/ReplicAI/studio/` — servidor em Python puro com
upload, fila, acompanhamento e edição de peça. Ele não é a arquitetura final,
mas resolveu problemas reais de produto (prévia de PSD lendo o cabeçalho do
arquivo, aviso de fundo faltante, animação por preset). Vale ler antes de
desenhar a API do zero.

### O Chromium está preso, e por quê

`infra/Dockerfile` fixa `chromium=154.0.8037.92-1~deb13u1` e a imagem base por
digest. Não é zelo de infraestrutura: **o Chromium é quem mede o texto.** O
motor acha o corpo da fonte por busca binária perguntando ao navegador se a
frase cabe na caixa. Outra versão, outra métrica, outro tamanho de texto em toda
peça — sem erro nenhum para avisar.

Quando o Debian publicar outra versão, o build falha com a instrução no log. É
de propósito: atualizar é decisão. Para subir, troque `CHROMIUM_VERSAO`,
reconstrua, e **olhe a peça de prova** antes de aceitar.

As versões de Chromium, fontes e ffmpeg ficam gravadas em `/app-versoes.json` e
aparecem em `/saude` → `desenhando_com`. É assim que se descobre que duas
máquinas estão desenhando diferente.

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
