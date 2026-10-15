# O que a ReplicAI custa, o que ela cobra, e o que falta ligar

Atualizado em 15/10/2026. Os números daqui não são digitados: saem de
`api/precos.py` e `api/uso.py`, e mudam sozinhos quando a premissa muda. O que
está marcado como **premissa** é o que ainda espera confirmação de alguém.

---

## 1. O checklist das ligações

| # | O quê | Para quê | Custo | Hoje |
|---|---|---|---|---|
| 1 | **Servidor** ServerSP Cloud VPS 16GB SP, São Paulo | onde tudo roda | **R$ 249/mês** | **falta contratar** |
| 2 | **Domínio** + **backup semanal** | o endereço, e o que salva a máquina | **R$ 30/mês** (R$ 5 + R$ 25, conferido) | **falta contratar** |
| 3 | **Certificado HTTPS** | sem ele a senha trafega legível | grátis (Let's Encrypt) | pronto no contêiner |
| 4 | **Anthropic** | compõe a peça | US$ 0,039/peça | **ligado** |
| 5 | **Higgsfield** (plano Plus) | continua o desenho do fundo | **US$ 49/mês ≈ R$ 283** · 1.000 créditos | **ligado** |
| 6 | **Asaas** | cobrança e nota fiscal | 2% do faturamento | **falta a chave de produção** |
| 7 | **Resend** | o e-mail de acesso e o aviso de atraso | grátis até 3 mil/mês | **falta a conta e o domínio verificado** |
| 8 | **Segredo da sessão** (`REPLICAI_SEGREDO`) | sem ele, reiniciar desloga todo mundo | grátis | **falta gerar** |
| 9 | **Token de administração** (`REPLICAI_ADMIN_TOKEN`) | criar conta na mão | grátis | **falta gerar** |
| 10 | **Aviso de disco** (`REPLICAI_AVISO_PARA`) | o disco avisa antes de encher | grátis | **falta o seu e-mail** |
| 11 | **Cópia diária** (`REPLICAI_COPIA_*`) | o backup do provedor é semanal; isto salva o trabalho entregue | R$ 0,10 por GB guardado (Magalu) | **falta o armazenamento** |
| 12 | Redis (fila) | peça e vídeo em filas próprias | grátis, no contêiner | pronto |
| 13 | Fontes da marca | tipografia igual à da arte | grátis, pasta montada | pronto |

**Custo fixo: R$ 562/mês.** É o que sai do caixa com zero cliente — e a maior
fatia dele é o plano do Higgsfield, não o servidor.

São **dois fornecedores e duas contas**, e vale não confundir: o ServerSP vende
a máquina onde o sistema roda (e o backup semanal dela); a Magalu vende só um
depósito fora dessa máquina, para a cópia diária sobreviver ao dia em que a
máquina morrer. Com o plano de 8 GB (R$ 125 em vez de R$ 249), o fixo cai para
**R$ 438**.

O depósito é o único item que cresce com o uso: R$ 0,10 por GB guardado, o que
hoje dá centavos e, com dez clientes depois de um ano, cerca de R$ 7 por mês.
Por isso ele não entra no custo fixo.

O passo a passo de cada ligação está em [`infra/SUBIR.md`](infra/SUBIR.md).

**Onde estão a Anthropic e o Higgsfield.** São dois casos diferentes:

- **Anthropic** é pós-paga por uso: US$ 0,039 por peça, sem mensalidade. Com
  zero cliente, custa zero.
- **Higgsfield** é plano mensal: US$ 49 por 1.000 créditos que **não acumulam**.
  É custo fixo, e está na lista acima. Ele cobre **535 peças por mês**; acima
  disso, o fundo passa a custar crédito avulso.

A conta do mês inteiro, com o servidor de 8 GB:

| carteira | peças | créditos | fixo | leitura | fundo além do plano | **total** | receita |
|---|---|---|---|---|---|---|---|
| 1 Freelancer | 250 | 467 ✔ | R$ 438 | R$ 56 | — | **R$ 494** | R$ 1.990 |
| 3 Freelancer | 750 | 1.400 | R$ 438 | R$ 169 | R$ 104 | **R$ 711** | R$ 5.970 |
| 10 Freelancer | 2.500 | 4.667 | R$ 438 | R$ 563 | R$ 953 | **R$ 1.955** | R$ 19.900 |
| 5 Freel. + 3 Studio + 2 Agency | 5.450 | 10.173 | R$ 438 | R$ 1.228 | R$ 2.385 | **R$ 4.051** | R$ 34.850 |

(com o servidor de 16 GB, some R$ 124 em cada linha)

**Quando subir o plano do generativo:** a partir de 535 peças por mês — 3
Freelancers, ou 1 Studio — o plano estoura e o excedente sai por crédito
avulso. Nessa hora vale comparar: o Ultra (US$ 99/mês no anual, 3.000 créditos)
sai a US$ 0,033 por crédito contra US$ 0,045 do avulso. O ponto de virada é por
volta de 2.200 créditos por mês, e lá a receita já passa de R$ 10 mil.

---

## 2. Os planos

| plano | peças | vídeos | pessoas | preço | por peça | margem |
|---|---|---|---|---|---|---|
| **Freelancer** | 250 | 25 | 1 | **R$ 1.990** | R$ 7,96 | 81,1% |
| **Studio** | 600 | 60 | 2 | **R$ 3.900** | R$ 6,50 | 79,1% |
| **Agency** | 1.200 | 120 | 3 | **R$ 6.600** | R$ 5,50 | 77,1% |

**O Basic saiu em 16/10/2026.** Eram 80 peças por R$ 890, e ele deixava R$ 345
depois do custo fixo contra R$ 1.296 do Freelancer — dando o mesmo atendimento,
que é o que de fato custa numa conta pequena. Oitenta peças por mês também é
menos do que uma agência produz: era um plano que não descrevia ninguém. De
quebra, três planos é exatamente o que a landing comporta.

Vídeos são 10% do volume de peças. O degrau desconta de verdade: R$ 7,96 a
peça no Freelancer, R$ 6,50 no Studio, R$ 5,50 no Agency — é isso que faz subir
de plano valer a pena, e há teste que falha se alguém achatar a escada.

**A margem entregue é de 77% a 81%**, e o piso que dispara o alarme está em 75%:
os preços são decisão sua, e o piso existe para avisar quando o câmbio estiver
comendo a margem, não para empatar com ela.

**Um cliente de qualquer plano já paga o mês inteiro de infraestrutura.** Um
Basic deixa R$ 744 limpos contra R$ 304 de custo fixo. A partir do segundo, o
servidor some da conta.

---

## 3. Um cliente de cada plano, aberto até o fim

Tudo o que sai do caixa por **um** cliente, no mês em que ele usa a franquia
inteira. Para dez clientes, é só multiplicar as linhas de uso — **o custo fixo
entra uma vez só**, não dez.

Dois nomes, sem jargão:

- **Leitura e diagramação (Anthropic)**: é o Claude lendo a arte e decidindo
  onde cada texto cabe em cada formato. Cobrado por uso, US$ 0,039 por peça,
  sem mensalidade. Zero cliente, zero conta.
- **Fundo além do plano (Higgsfield)**: o plano de US$ 49 dá 1.000 créditos por
  mês e cada fundo come 2,80 — cobre **535 peças**. Só o que passar disso vira
  custo variável, a R$ 0,26 o crédito. O que está dentro do plano já foi pago
  na mensalidade.

Com o servidor de 8 GB (fixo de R$ 438). Com o de 16 GB, tire R$ 124 de cada
sobra.

| | **Freelancer** | **Studio** | **Agency** |
|---|---|---|---|
| preço | R$ 1.990 | R$ 3.900 | R$ 6.600 |
| peças no mês | 250 | 600 | 1.200 |
| créditos de fundo | 467 ✔ | 1.120 (passa 120) | 2.240 (passa 1.240) |
| leitura e diagramação | R$ 56,34 | R$ 135,21 | R$ 270,41 |
| fundo além do plano | — | R$ 31,20 | R$ 322,41 |
| imposto (Simples 8%) | R$ 159,20 | R$ 312,00 | R$ 528,00 |
| meio de pagamento (2%) | R$ 39,80 | R$ 78,00 | R$ 132,00 |
| custo fixo do mês | R$ 438,12 | R$ 438,12 | R$ 438,12 |
| **sobra** | **R$ 1.296,54** | **R$ 2.905,47** | **R$ 4.909,06** |
| | 65% | 74% | 74% |

**O que esta tabela diz:**

1. **Um cliente Freelancer sozinho já paga a casa e deixa R$ 1.296.** O custo
   fixo come 25% do que ele traz — era 63% no Basic, que por isso saiu.
2. **O Studio é o primeiro plano que estoura o plano de créditos**, e por pouco:
   120 créditos, R$ 31. O Agency estoura feio, R$ 322 — é aí que trocar para o
   Ultra começa a valer.
3. **Do segundo cliente em diante a sobra quase dobra**, porque o fixo já está
   pago pelo primeiro.
4. **O imposto custa mais que a produção inteira** em todos os planos. É o
   número mais importante a confirmar aqui, e não o preço da peça.

**Os vídeos não aparecem** porque não custam dinheiro por unidade: animam uma
peça que já existe, sem chamar serviço nenhum. Gastam tempo de máquina — por
isso são 10% do volume, para proteger a fila.

---

## 4. O custo, por unidade

### O que varia com o uso: R$ 0,711 por peça

| item | em dólar | em real | de onde veio |
|---|---|---|---|
| leitura e diagramação (Anthropic) | US$ 0,0390 | R$ 0,2253 | medido: US$ 0,117 por três peças |
| fundo gerado (Higgsfield), fora do plano | US$ 0,0840 | R$ 0,4854 | 2,80 créditos × US$ 0,045, em 2/3 das peças |
| **total** | **US$ 0,1230** | **R$ 0,7107** | |

O fundo custa o dobro do modelo: é o item mais caro da peça, e só acontece
quando a proporção muda (dois terços das peças de uma grade comum).

| premissa | valor |
|---|---|
| dólar | R$ 5,40 |
| IOF e spread do cartão | 7% |

**Vídeo não entra no custo por unidade**: ele anima uma peça que já existe, sem
chamar serviço nenhum. Gasta tempo de máquina, não dinheiro. O limite de 10%
existe para proteger a fila, não o caixa.

### O que não varia: R$ 304 por mês

Servidor, domínio e backup. **Não entram no preço de nenhum plano** — entram na
conta de quantos clientes o mês precisa. Rateá-los por cliente exigiria adivinhar
quantos clientes existem, e no começo esse palpite erra para o lado caro: preço
alto espanta justamente o primeiro cliente, que é quem paga o servidor.

### O que sai do faturamento

| item | quanto |
|---|---|
| imposto (Simples) | 8% — **premissa, a confirmar com a contabilidade** |
| meio de pagamento (Asaas) | 2% |

### O que a margem paga, e por isso não é custo

**O seu tempo.** Atendimento, demonstração, a peça que volta porque o cliente
não gostou. Somar a sua hora ao custo e ainda pedir 80% de margem em cima dela
cobraria a mesma hora duas vezes — e levaria o plano de entrada a R$ 1.900.

---

## 5. O piso, que protege a margem sozinho

O preço de cada plano é **decidido**, não calculado: está em `precos.TABELA`. O
número calculado a partir do custo medido virou **piso** — e quando a tabela
passa por baixo dele (o dólar sobe, o preço fica, a margem some em silêncio), o
sistema aponta qual plano em `/saude` e a esteira trava.

O preço nunca sobe sozinho: assinatura que muda de valor sem ninguém decidir é
coisa que o cliente descobre no extrato.

---

## 6. O que ainda espera alguém

| o quê | quem | o que muda |
|---|---|---|
| alíquota do Simples (hoje 8%) | contabilidade | um número em `api/precos.py`, e todos os planos se recalculam |
| cópia diária do que é dos clientes | decisão sua | o backup do ServerSP é SEMANAL: uma semana de trabalho entregue pode se perder |
| contratar servidor e domínio | você | tira o sistema do seu computador |
| conta no Resend e domínio verificado | você | sem isso o cliente paga e **não recebe acesso** |
| chaves do Asaas de produção | você | sem isso ninguém assina |
