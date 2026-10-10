# Quem compõe a peça?

**Status:** aberto. Bloqueia o desenho da Fase 1.
**Levantado em:** 10/10/2026

## O buraco

O `ROADMAP.md` lista o Claude Code entre as seis dependências a eliminar, ao
lado de Chrome e ffmpeg. Isso trata o Claude como runtime. Ele não é: ele é a
parte que **decide**.

Evidência, não opinião:

- O motor tem dezesseis subcomandos — `prep`, `grid`, `analyze`, `crop`, `clean`,
  `fit`, `extend`, `render`, `video`, `export-psd`, `export-svg`, `validate`,
  `sheet`, `manifest`, `save-external`, `formatos`. **Nenhum compõe uma peça.**
  Todos executam uma ordem já dada.
- A peça do Feed no job `candidate-se-animar` tem **13 elementos**, cada um com
  caixa, papel e ordem de empilhamento decididos.
- O texto é reescrito por formato. No Feed virou `E ESTAMOS / COM **VAGAS** /
  **ABERTAS!}`: as quebras de linha e os realces são escolha de composição. No
  banner 300x250 a linha "Faça parte da nossa equipe" foi **cortada** porque não
  cabia — outra decisão.

Hoje quem faz isso é o Claude Code lendo o `PIPELINE.md`. O Studio atual confirma:
ele dispara `claude -p` por job.

**Tirar o Claude sem substituir a decisão deixa a plataforma com um renderizador
de JSON que ninguém escreve.**

## O custo que isso tem hoje

No job `candidate-se-animar` (3 formatos, PSD de 63 MB), o trabalho do agente
levou cerca de **10 minutos de ponta a ponta**. É o custo unitário real de uma
entrega, e precisa caber no preço.

## Os três caminhos

### A. A plataforma chama a API da Anthropic
O worker monta o prompt, manda a arte e a grade, recebe a peça JSON de volta.

- A favor: é o produto de verdade. Custo por job medível, cobrável e sob
  controle de quem vende. Nenhuma dependência de CLI ou de login de pessoa.
- Contra: custo variável por entrega. Exige transformar o `PIPELINE.md` numa
  conversa estruturada com saída validável — é trabalho de verdade, não cola.
- Risco a provar antes de construir em cima: a composição sai boa o bastante em
  uma passada, ou precisa das idas e voltas que o agente faz hoje?

### B. Claude Code dentro do contêiner
Empacotar o CLI na imagem, como está no Studio.

- A favor: funciona hoje, sem reescrever a composição.
- Contra: o CLI pede login de uma pessoa e não foi feito para rodar como serviço
  multi-inquilino. Dá para ficar de pé, não dá para vender em cima.

### C. Composição determinística para um subconjunto
Regras fixas para casos simples: uma headline, um CTA, um logo, grade conhecida.

- A favor: custo zero por job, resposta em segundos, testável.
- Contra: resolve o fácil. A peça da Consigaz tem 13 camadas, mascote recortado e
  lettering ilustrado — fora do alcance de regra.

## Recomendação

**A, com C por baixo.** Regra determinística onde ela dá conta, API da Anthropic
onde precisa de julgamento. Assim o custo por job cai nos casos simples e a
qualidade se mantém nos difíceis.

Mas **antes de construir a API em volta disso, provar o caminho A** numa peça
real — do mesmo jeito que se provou o contêiner antes da Fase 1. Se a composição
em uma passada não sai utilizável, o desenho da fila e do worker muda.

## O que não muda em nenhum caminho

Upload, fila, worker, storage, download, e o motor executando `prep`/`extend`/
`render`/`validate`. Isso pode ser construído já, com a composição atrás de uma
interface — `compositor(arte, formato, brief) -> peça JSON` — que hoje aceita um
JSON pronto e amanhã chama o que for decidido.
