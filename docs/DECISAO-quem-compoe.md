# Quem compõe a peça?

**Status:** o caminho A foi provado em 10/10/2026 — ver *A prova*, no fim.
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


---

# A prova (10/10/2026)

## Como foi feito

Não dá para chamar a API da Anthropic daqui: exige chave, e credencial não passa
por mim. Então o experimento foi outro, e mede a mesma coisa: **compor em uma
passada só**, sem ver a referência e sem iterar — que é o que uma chamada de API
faz.

- **Peça:** Save the Date do Energiza 2027.
- **Formato:** `gdn-728x90`, escolhido por ser o mais duro. Numa faixa 8:1 um
  compositor ruim produz lixo e um bom precisa escolher o que sacrificar.
- **Entradas:** a arte sem o texto informativo (`fundo-limpo.png`, saída de um
  passo mecânico), o brief e a ficha do formato. Nada mais.
- **Saída:** recortes de marca + peça JSON, de uma vez.

A referência do agente só foi aberta **depois**.

## Resultado

As duas peças saíram com **a mesma estrutura**: marca à esquerda, frase no
centro, botão à direita. As decisões de sacrifício bateram: ambas largaram o
parágrafo e o local, e fundiram lettering e data numa frase só.

Onde a passada única errou:

| | uma passada | o agente |
|---|---|---|
| Recorte da marca | 450x185 — **cortou a assinatura no meio** | 450x216 (inteira) ou 450x146 (sem assinatura) |
| Hierarquia | tudo branco, data separada por um ponto | data em ciano, destacada |
| Acabamento | sem divisor | divisor vertical entre marca e frase |
| CTA | "Inscreva-se" (11 caracteres, dentro do limite) | "Preencher formulário" (20, **acima dos 12 do catálogo**) |

O recorte revela o padrão: **a coordenada horizontal saiu exata** (450 px, mesma
borda esquerda), e a vertical caiu entre as duas opções válidas. Não é falta de
julgamento, é falta de precisão de pixel.

## O que isso conclui

**A composição se divide em duas naturezas, e só uma precisa de modelo.**

- **Estrutura, copy e hierarquia** — o que entra, o que sai, onde fica, como se
  encurta. Transferiu inteiro para uma passada. É julgamento, e é caro de
  automatizar de outro jeito.
- **Coordenada exata** — onde começa e termina a marca na arte. É onde a passada
  única erra, e é trabalho determinístico: com PSD, as camadas dão o bbox de
  graça; com base achatada, precisa de detecção ou de confirmação humana.

Separar as duas corta o custo e o risco: o modelo responde a estrutura, a
máquina acha as coordenadas, e o render executa.

## Dois achados de quebra

**O limite de CTA do catálogo está apertado demais.** `gdn-728x90` declara
`cta_max: 12`, e o agente usou 20 caracteres porque "Preencher formulário" diz o
que "Inscreva-se" não diz. Ou o limite sobe, ou o compositor automático vai
entregar CTA pior que o humano por obediência. **Decidir antes de automatizar.**

**A passada única obedeceu o limite e o agente não.** Modelo seguindo regra ao pé
da letra produz peça pior. O prompt precisa dizer quando a regra cede.
