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
| 5 | **Higgsfield** | continua o desenho do fundo | 2,80 créditos/fundo | **ligado** |
| 6 | **Asaas** | cobrança e nota fiscal | 2% do faturamento | **falta a chave de produção** |
| 7 | **Resend** | o e-mail de acesso e o aviso de atraso | grátis até 3 mil/mês | **falta a conta e o domínio verificado** |
| 8 | **Segredo da sessão** (`REPLICAI_SEGREDO`) | sem ele, reiniciar desloga todo mundo | grátis | **falta gerar** |
| 9 | **Token de administração** (`REPLICAI_ADMIN_TOKEN`) | criar conta na mão | grátis | **falta gerar** |
| 10 | **Aviso de disco** (`REPLICAI_AVISO_PARA`) | o disco avisa antes de encher | grátis | **falta o seu e-mail** |
| 11 | **Cópia diária** (`REPLICAI_COPIA_*`) | o backup do provedor é semanal; isto salva o trabalho entregue | poucos reais/mês | **falta o armazenamento** |
| 12 | Redis (fila) | peça e vídeo em filas próprias | grátis, no contêiner | pronto |
| 13 | Fontes da marca | tipografia igual à da arte | grátis, pasta montada | pronto |

**Custo fixo: R$ 279/mês.** É o que sai do caixa com zero cliente.

O passo a passo de cada ligação está em [`infra/SUBIR.md`](infra/SUBIR.md).

---

## 2. Os planos

| plano | peças | vídeos | pessoas | preço | por peça | margem |
|---|---|---|---|---|---|---|
| **Basic** | 80 | 8 | 1 | **R$ 890** | R$ 11,12 | 83,6% |
| **Freelancer** | 250 | 25 | 1 | **R$ 1.990** | R$ 7,96 | 81,1% |
| **Studio** | 600 | 60 | 2 | **R$ 4.490** | R$ 7,48 | 80,5% |
| **Agency** | 1.200 | 120 | 3 | **R$ 8.530** | R$ 7,11 | 80,0% |

Vídeos são 10% do volume de peças. Cada degrau desconta de verdade no preço da
peça — é isso que faz subir de plano valer a pena, e há teste que falha se
alguém achatar a escada.

**Um cliente de qualquer plano já paga o mês inteiro de infraestrutura.** Um
Basic deixa R$ 744 limpos contra R$ 304 de custo fixo. A partir do segundo, o
servidor some da conta.

---

## 3. Cada plano, aberto até o fim

Tudo o que sai de cada mensalidade, item por item. Os três primeiros variam com
o uso; o imposto e o gateway são percentuais do que o cliente paga.

### Basic · R$ 890 · 80 peças

| item | valor | do preço |
|---|---|---|
| modelo que compõe (Anthropic) | R$ 18,03 | 2,0% |
| fundo generativo (Higgsfield) | R$ 38,83 | 4,4% |
| imposto (Simples 8%) | R$ 71,20 | 8,0% |
| meio de pagamento (Asaas 2%) | R$ 17,80 | 2,0% |
| **sobra** | **R$ 744,14** | **83,6%** |
| sobra depois do custo fixo do mês | R$ 465,14 | |

### Freelancer · R$ 1.990 · 250 peças

| item | valor | do preço |
|---|---|---|
| modelo que compõe (Anthropic) | R$ 56,34 | 2,8% |
| fundo generativo (Higgsfield) | R$ 121,34 | 6,1% |
| imposto (Simples 8%) | R$ 159,20 | 8,0% |
| meio de pagamento (Asaas 2%) | R$ 39,80 | 2,0% |
| **sobra** | **R$ 1.613,33** | **81,1%** |
| sobra depois do custo fixo do mês | R$ 1.334,33 | |

### Studio · R$ 4.490 · 600 peças

| item | valor | do preço |
|---|---|---|
| modelo que compõe (Anthropic) | R$ 135,21 | 3,0% |
| fundo generativo (Higgsfield) | R$ 291,21 | 6,5% |
| imposto (Simples 8%) | R$ 359,20 | 8,0% |
| meio de pagamento (Asaas 2%) | R$ 89,80 | 2,0% |
| **sobra** | **R$ 3.614,58** | **80,5%** |
| sobra depois do custo fixo do mês | R$ 3.335,58 | |

### Agency · R$ 8.530 · 1.200 peças

| item | valor | do preço |
|---|---|---|
| modelo que compõe (Anthropic) | R$ 270,41 | 3,2% |
| fundo generativo (Higgsfield) | R$ 582,42 | 6,8% |
| imposto (Simples 8%) | R$ 682,40 | 8,0% |
| meio de pagamento (Asaas 2%) | R$ 170,60 | 2,0% |
| **sobra** | **R$ 6.824,17** | **80,0%** |
| sobra depois do custo fixo do mês | R$ 6.545,17 | |

**O que esses números dizem.** O custo de produzir é a menor parte de tudo:
entre 6% e 10% do que o cliente paga, mesmo quando ele usa a franquia inteira.
O imposto custa mais que o modelo e o fundo somados em todos os planos — por
isso a alíquota é o número mais importante a confirmar aqui, e não o preço da
peça. E o custo fixo do mês some: ele pesa 37% no Basic e 4% no Agency, o que é
outra forma de dizer que o primeiro cliente paga a casa.

**Os vídeos não aparecem** porque não custam dinheiro por unidade: animam uma
peça que já existe, sem chamar serviço nenhum. Gastam tempo de máquina — por
isso são 10% do volume, para proteger a fila.

**Essas contas valem para o pior caso**, o cliente que gasta a franquia inteira.
Quem usa metade deixa quase o dobro de sobra, e é o que acontece na maioria.

---

## 4. O custo, por unidade

### O que varia com o uso: R$ 0,711 por peça

| item | em dólar | em real | de onde veio |
|---|---|---|---|
| modelo que compõe | US$ 0,0390 | R$ 0,2253 | medido: US$ 0,117 por três peças |
| fundo generativo | US$ 0,0840 | R$ 0,4854 | 2,80 créditos × US$ 0,045, em 2/3 das peças |
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
