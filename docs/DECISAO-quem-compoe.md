# Quem compõe a peça?

**Status:** decidido e implementado em 10/10/2026. Ver *A decisão*, no fim.
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


---

# O fundo (10/10/2026, depois de três tentativas)

A Ligia olhou o banner e disse o que a medição não tinha visto: o fundo perdeu o
grafismo, e os elementos estavam carimbados por cima. Estava certa nas duas.

## O que descobri tentando consertar

**Primeira tentativa.** Recortei uma faixa "limpa" da arte. Saiu um degradê quase
liso: 34% do grafismo da arte-mãe. A grade quadriculada e os arcos da esfera
sumiram — a peça ficou com a cor da marca e a cara de outra.

**Segunda.** Escrevi uma medida de estrutura e procurei a faixa que pontuasse
mais. Achei uma com 211% e usei. O banner saiu com o rabo do lettering
"energiza" fantasma atrás de tudo: **a faixa que eu escolhi passava por cima do
logo.** A minha própria conferência aprovou, porque texto também é estrutura.

**Terceira.** Com a regra de não invadir as marcas, saiu perto da referência. O
que sobrou de defeito foi o recorte do logo colado como retângulo opaco, com a
moldura aparecendo — o "carimbado" que ela apontou.

## As três regras, e por que precisam valer juntas

| Regra | O que pega | O que não pega |
|---|---|---|
| Fundo preserva ≥50% do grafismo da arte | degradê liso no lugar da trama | fundo com texto embutido |
| Recorte de fundo não cruza as caixas de marca | lettering fantasma | fundo chapado |
| Elemento de marca vem com alfa, não como bloco | moldura em volta do logo | as duas acima |

Nenhuma sozinha basta. A primeira, isolada, **aprovou a peça pior das três**.

## O que isso diz sobre composição automática

A regra que faltava já estava escrita no `CLAUDE.md` da skill: *"fundo estendido
em vez de cortado"*. Eu procurei faixa duas vezes em vez de estender, e o
resultado foi exatamente o que a regra existia para evitar.

Para o compositor automático, isso quer dizer duas coisas:

1. **As regras da casa precisam chegar ao compositor como restrição, não como
   texto de apoio.** Um modelo com o PIPELINE.md no prompt ainda assim escolhe o
   caminho errado se a verificação não existir.
2. **Verificar depois é obrigatório, e uma verificação só não serve.** As três
   regras estão em `api/qualidade.py`, com teste, inclusive o caso que me
   enganou.


---

# Por que o fundo nunca fechava (10/10/2026)

Depois de quatro tentativas no banner do Energiza, a causa não era o método.

**O grafismo da arte mora embaixo do texto.** Os arcos da esfera ficam atrás do
"SAVE THE DATE"; a grade, atrás do parágrafo e da data. Isso fecha as três
saídas de uma vez:

- fugir do texto para achar fundo leva às áreas vazias da peça — foi o meu
  borrão, e o outpaint estendeu fielmente o vazio que eu dei a ele;
- apagar o texto destrói o grafismo junto — a cicatriz de 1,4% de nitidez;
- esticar deforma — 2,02x, arcos em ângulo que não existe na arte.

**A base do Energiza é um PNG achatado.** Com PSD o problema não existe: a
camada de fundo chega inteira, sem texto por cima, e no caso da Consigaz ela
mede 1200x1463 numa prancheta de 1200x1200 — sobra material real para estender.

Para esta peça, o limite é o arquivo de entrada, não o motor.

## O que entrou no código

`api/qualidade.py`, com teste nos dois sentidos:

| Verificação | O que pega |
|---|---|
| `fidelidade_do_fundo` | degradê liso no lugar da trama |
| `fundo_invade_marca` | recorte de fundo que pega logo ou lettering |
| `recorte_e_retangulo` | marca colada como bloco opaco, com moldura |
| `grafismo_sob_texto` | **arte cujo grafismo só existe atrás do texto: avisa no envio que sem PSD o fundo vai sair liso** |

A última mede o **anel em volta** das áreas de texto, não o miolo. Medindo por
dentro, as próprias letras inflavam a conta e uma peça com fotos longe do texto
acusava igual a uma com grade atrás dele. Energiza dá 6x; Candidate-se, que tem
as fotos longe, não dispara.


---

# A decisão (10/10/2026)

**Caminho A, com C atrás como rede** — e a divisão que o experimento apontou.

## O modelo não responde pixels

Ele responde **papéis e zonas**: `headline` em `meio-esquerda`, `cta` em
`baixo-esquerda`. A caixa exata é calculada por `api/composicao.py`, a partir da
área segura e das convenções do formato.

Isso tira dele a parte que faz mal — coordenada — e mantém a que faz bem:
o que entra, o que sai, o que se encurta, qual a hierarquia.

## Nada que o modelo responde chega ao render sem passar por conferência

`conferir()` recusa papel desconhecido, zona desconhecida, papel repetido, texto
acima do limite do formato, papel que o formato não comporta, e `descartados`
que não diga o motivo. Peça torta entregue é pior do que peça não entregue.

Recusar na primeira, porém, é desperdício: o compositor **diz o erro ao modelo e
pede de novo**, uma vez. No teste de ponta a ponta foram 5 chamadas para 3
formatos — duas precisaram da volta. Esse número é o custo por peça, e agora é
medível.

## A cadeia

`CompositorEmCadeia(modelo, regra)`. Com credencial, o modelo decide e a regra
fica atrás; sem credencial, só a regra. A plataforma funciona nos dois casos, com
qualidades diferentes, em vez de recusar a subir. `/saude` diz qual está valendo.

## O que o render ensinou que o teste não pegava

Duas sobreposições só apareceram na peça pronta, e viraram teste:

- zonas da mesma faixa vertical disputavam a largura — "meio-centro" pegava tudo
  e o botão em "meio-direita" caía em cima;
- o corpo mínimo do texto vinha só do canvas, então o apoio não conseguia
  encolher, estourava a caixa e escrevia por cima do vizinho.

E uma terceira: resolver faixa a faixa deixava o grupo do meio descer até 80% da
altura enquanto o de baixo começava em 68%. Agora cada coluna é resolvida
inteira, e um grupo empurra o seguinte.

## O que falta antes de ligar em produção

Rodar com chave de verdade. Tudo foi provado com modelo falso: o contrato, a
conferência, a volta de correção, as caixas e o render. O que não foi exercitado
é a chamada em si — e o custo real por peça.