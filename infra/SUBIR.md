# Subir a ReplicAI num servidor

O que contratar, o que configurar e como conferir que ficou de pé. A ordem
importa: cada passo depende do anterior, e o último é uma peça real saindo
certa — enquanto ela não sair, o servidor não está pronto, por mais verde que
esteja tudo o resto.

---

## 1. A máquina

| | mínimo | recomendado | por quê |
|---|---|---|---|
| Processador | 4 vCPU | **8 vCPU** | o motor mede o texto abrindo um Chromium por peça, e o vídeo renderiza quadro a quadro |
| Memória | 8 GB | **16 GB** | cada worker de peça custa 0,7 GB em repouso e o de vídeo 2 GB (está no `docker-compose.yml`); a extração de um PSD custa de 0,4 a 1,3 GB por cima disso, medido em oito KVs reais |
| Disco | 160 GB SSD | **250 GB SSD** | medido em `api/faxina.py`: quarenta clientes geram 94 GB de material bruto por mês, dos quais o PSD é 85%. A faxina apaga o bruto com 30 dias e o acúmulo permanente cai para 8 GB por mês |
| Arquitetura | **x86_64 (amd64)** | — | a tipografia da peça está travada e conferida na esteira com um Chromium amd64. Outra arquitetura mede o texto de outro jeito e a peça sai diferente, sem erro nenhum para avisar |
| Sistema | Ubuntu 24.04 LTS ou Debian 13 | — | só precisa rodar Docker; o resto vem dentro da imagem |
| IP | IPv4 fixo | — | o certificado é emitido para o domínio que aponta para este IP |
| Tráfego | 2 TB/mês | — | sobe PSD de até 250 MB e desce pacote de peças |
| Swap | 2 GB | 4 GB | é o que segura o pico de abrir um PSD grande sem o sistema matar o worker |

**Sobre a memória do PSD**, porque é a linha que decide entre 8 e 16 GB: o pico
não acompanha o tamanho do arquivo. Medido nos KVs reais que passaram por aqui,
um PSD de 201 MB custou 0,73 GB e levou 9 segundos, enquanto um de 24 MB custou
1,30 GB e levou 22 — o que pesa é a quantidade e o tamanho das camadas abertas
para recorte, não os bytes do arquivo. Com 16 GB, dois workers podem extrair ao
mesmo tempo no pior caso medido e ainda sobra folga. Com 8 GB funciona, mas uma
peça espera a outra quando as duas são pesadas.

Localização: **Brasil ou leste dos Estados Unidos**. O cliente sobe arquivos de
centenas de MB, e a distância aparece no tempo de upload — não na velocidade de
render.

### Começar com 8 GB

Faz sentido quando ainda não se sabe a que velocidade a carteira cresce — que é
o caso. O plano de 8 GB do ServerSP (4 vCPU, 8 GB, **100 GB**) sai por
**R$ 125/mês** no mensal, contra R$ 249 do de 16 GB.

**Duas condições**, as duas medidas:

1. **`REPLICAI_WORKERS=1` no `.env`.** Com 8 GB, dois workers abrindo PSD ao
   mesmo tempo chegam a 7,3 GB e o sistema vai para o swap — a peça passa a
   demorar mais do que se tivesse simplesmente esperado na fila. Com um worker,
   o pico é de 5,3 GB e sobra folga. O custo é que dois trabalhos não correm em
   paralelo: o segundo espera um ou dois minutos.
2. **Confirmar antes de assinar que dá para crescer sem recriar a máquina** —
   disco e memória. É o que torna começar pequeno uma decisão barata em vez de
   uma dívida.

**Até quando os 100 GB duram**, pelos números medidos (2,41 MB por peça
entregue, para sempre; 160 MB de bruto por trabalho com PSD, por 30 dias):

| carteira | peças/mês | enche em |
|---|---|---|
| 2 Freelancer | 500 | mais de 3 anos |
| 3 Freelancer | 750 | mais de 3 anos |
| 5 Freelancer | 1.250 | 22 meses |
| 2 Studio | 1.200 | 23 meses |
| 10 Freelancer | 2.500 | **7 meses** |

Ou seja: até quatro ou cinco clientes, 100 GB está confortável. O aviso de disco
avisa com semanas de antecedência quando for hora de crescer, e crescer é
aumentar o disco — não trocar de máquina.

### Onde contratar — comparação de 15/10/2026

Na mesma configuração de 8 vCPU e 16 GB:

| | ServerSP · São Paulo | Vultr · São Paulo | Magalu Cloud · Brasil |
|---|---|---|---|
| Disco | 200 GB NVMe | 350 GB NVMe | 40 GB + bloco à parte |
| Preço/mês | **R$ 249** sem fidelidade (R$ 174 com 36 meses) | US$ 96 ≈ R$ 518 | ~R$ 300–350 + disco (estimado) |
| Tráfego | 1 Gbps ilimitado, uso justo | 8 TB | conforme contratação |
| Pagamento | real, nota fiscal | dólar, com IOF e câmbio | real, nota fiscal |
| Suporte | ticket 24/7, WhatsApp e telefone, em português | ticket em inglês | em português |
| Backup | adicional pago | adicional (~20%) | adicional |

**Escolhido: ServerSP, Cloud VPS 16GB SP, mensal sem fidelidade.** Está em São
Paulo (o argumento é upload de PSD pesado, não latência de tela), custa metade
do Vultr na mesma configuração, cobra em real com nota fiscal e atende em
português. Os 30 dias de garantia tornam o teste barato.

**Não assinar 36 meses no começo**: são R$ 6.264 adiantados numa empresa ainda
não testada. Depois de três meses rodando, o plano de 12 meses dá 10%.

O preço da Magalu é estimativa: a calculadora deles roda por script e não abriu
para leitura; a faixa saiu interpolando entre configurações publicadas (2 vCPU /
4 GB a R$ 103 e 16 vCPU / 32 GB a R$ 610), e a VM deles vem com 40 GB, com o
resto cobrado à parte. Para decidir por ela, peça cotação.

Antes de fechar com qualquer um: quanto custa o backup automático diário, se dá
para restaurar a máquina inteira por snapshot, e se o disco cresce sem recriar a
máquina. Os 200 GB do plano ficam abaixo dos 250 recomendados, e isso só é
aceitável porque a faxina mantém o acúmulo permanente em 8 GB por mês.

O que **não** é preciso: GPU, banco de dados gerenciado, balanceador, Kubernetes.
O estado vive em disco e a fila é um Redis que sobe junto.

---

## 2. O domínio

Dois nomes, cada um com um trabalho:

- `seudominio.com.br` → a landing, que vende
- `app.seudominio.com.br` → a plataforma

No DNS, um registro **A** de `app` apontando para o IP do servidor. O certificado
é pedido e renovado sozinho pelo Caddy, de graça, assim que o nome responder.

---

## 3. Instalar

```bash
# no servidor, uma vez
curl -fsSL https://get.docker.com | sh
# o repositório é privado: no servidor, uma chave de implantação (deploy key)
# só de leitura, ou um token pessoal na URL
git clone git@github.com:womanops/replicai-plataforma.git
cd replicai-plataforma
cp .env.example .env
```

---

## 4. Preencher o `.env`

Sem estes, o sistema sobe e **parece** funcionar — é o pior jeito de faltar
configuração, e por isso cada um aparece em `/saude`:

| variável | sem ela | onde se consegue |
|---|---|---|
| `DOMINIO` | o certificado não é emitido e o site fica em HTTP puro | o domínio de cima |
| `REPLICAI_SEGREDO` | reiniciar o servidor desloga todo mundo | invente 40 caracteres aleatórios |
| `ANTHROPIC_API_KEY` | as peças saem pela régua, sem o modelo decidir o que sacrificar | console.anthropic.com |
| `RESEND_API_KEY` + `REPLICAI_EMAIL_DE` | **o cliente paga e não recebe acesso**: o e-mail é gravado num arquivo | resend.com, com o domínio verificado |
| `REPLICAI_PAINEL` | o e-mail de acesso não diz onde entrar | `https://app.seudominio.com.br` |
| `ASAAS_API_KEY` | não dá para assinar plano nenhum | painel do Asaas, em produção |
| `ASAAS_AVISO_TOKEN` | o aviso de pagamento é recusado e nenhum plano é liberado | invente, e repita no webhook do Asaas |
| `ASAAS_AREIA` | com `0` ou apagado é cobrança de verdade; com `1` é de mentira, e `/saude` denuncia | — |
| `REPLICAI_ADMIN_TOKEN` | você não consegue criar conta na mão | invente 40 caracteres aleatórios |
| `REPLICAI_SITE_PLANOS` | a porta não mostra onde assinar | `https://seudominio.com.br#precos` |

E **não** ponha `REPLICAI_SEM_LIMITE` em produção: ele desliga a franquia dos
planos. `/saude` denuncia quando está ligado.

---

## 5. Subir

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

Para dar conta de mais clientes, suba `replicas` nos **workers**, não na `api`:
a tranca que segura quem fica tentando senha conta na memória do processo, e
duas apis contariam cada uma por si — oito tentativas viram dezesseis. Uma api
atende muita gente; quem faz força é o worker.

Uma vez só, para o fundo generativo ter login:

```bash
docker compose -f infra/docker-compose.yml run --rm worker higgsfield auth login
```

---

## 6. Avisar o Asaas

No painel do Asaas, cadastrar o webhook:

- endereço: `https://app.seudominio.com.br/cobranca/aviso`
- token: o mesmo `ASAAS_AVISO_TOKEN` do `.env`
- eventos: pagamento confirmado, recebido, vencido, estornado

É esse aviso que libera o plano e dispara o e-mail de acesso. Sem ele, o cliente
paga e nada acontece.

---

## 7. Conferir — nesta ordem

```bash
curl -s https://app.seudominio.com.br/saude | python3 -m json.tool
```

Tem que dizer, sem exceção:

- `"sessao": "segredo configurado"`
- `"correio": "configurado"`
- `"franquia": "valendo"`
- `"precos": "valendo"`
- `"compositor": "modelo+regra"`
- `"disco"` com `nivel: "folga"` e um e-mail em `avisa`
- `"cobranca": "valendo"`

Depois, o teste que realmente vale: **uma contratação de ponta a ponta**, com o
Asaas ainda em areia (`ASAAS_AREIA=1`) para não mexer dinheiro:

1. abrir `https://app.seudominio.com.br/assinar?plano=basic`
2. preencher e ir até a página de pagamento
3. pagar na areia do Asaas
4. ver o e-mail de acesso chegar na caixa de entrada — não no arquivo
5. criar a senha pelo link e entrar
6. subir uma arte real e esperar as peças

Se os seis passos acontecerem, o servidor está pronto. Aí sim: apagar o
`ASAAS_AREIA`, pôr as chaves de produção do Asaas, reiniciar e conferir que
`/saude` diz `"cobranca": "valendo"`.

---

## 8. Fechar a máquina

A plataforma se defende do que chega pela porta — senha amassada com `scrypt`,
tranca depois de oito tentativas erradas, sessão assinada, conta que não enxerga
a conta do outro, cabeçalhos que o navegador obedece. O que ela não faz é
defender o servidor: isso é configuração, e são cinco linhas.

```bash
# 1. entrar só com chave, nunca com senha
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sudo systemctl restart ssh

# 2. só três portas abertas ao mundo
sudo ufw default deny incoming && sudo ufw allow 22 && sudo ufw allow 80 \
  && sudo ufw allow 443 && sudo ufw --force enable

# 3. quem insistir no SSH leva banimento
sudo apt install -y fail2ban && sudo systemctl enable --now fail2ban

# 4. correção de segurança aplicada sozinha
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

E uma regra que não é comando: **o `.env` do servidor é o cofre**. Chave do
modelo, segredo da sessão, chaves do Asaas e do Resend vivem só ali, com
`chmod 600`, e nunca no repositório — há teste disso na esteira.

Quem tem acesso ao servidor tem acesso a tudo: o código, os arquivos dos
clientes e as chaves. Uma chave SSH por pessoa, e tirar a chave de quem sai no
mesmo dia.

---

## 9. Quantos clientes a máquina atende

Medido nos trabalhos reais em 15/10/2026: cada **peça entregue ocupa 2,41 MB
para sempre**, e o material bruto de um trabalho ocupa de **15 MB** (arte
chapada) a **420 MB** (PSD pesado) durante os 30 dias até a faxina passar.

| plano | peças/mês | acúmulo permanente | bruto em trânsito |
|---|---|---|---|
| Basic | 80 | 0,19 GB/mês | 0,1–1,6 GB |
| Freelancer | 250 | 0,60 GB/mês | 0,5–5 GB |
| Studio | 600 | 1,45 GB/mês | 1,1–12 GB |
| Agency | 1.200 | 2,89 GB/mês | 2,2–24 GB |

Numa carteira de dez clientes de porte médio (2.520 peças/mês), os 200 GB do
plano ficam em **39% no fim do primeiro ano** com arte chapada, e em **62%** com
PSD de verdade. No segundo ano chegam a 98% — é quando o disco precisa crescer.

**Processador e memória não limitam**: essa mesma carteira usa 2,5 horas de
máquina no mês inteiro, contra 176 horas úteis, e o pico de memória é de uns
8 GB dos 16. O que enche é o disco, e só ele.

**O servidor avisa sozinho.** A faxina mede o disco todo dia depois de varrer,
guarda o histórico e manda e-mail para `REPLICAI_AVISO_PARA` quando a situação
**piora**: acima de 70% é atenção, acima de 85% é aperto. O aviso traz a
previsão — "no ritmo dos últimos dias, enche em tantos dias" —, porque
porcentagem não move ninguém e prazo move. Mesmo nível no dia seguinte não
repete a carta.

Quando o aviso chegar, em ordem: aumentar o disco do servidor (não troca a
máquina), ou baixar `REPLICAI_FAXINA_DIAS` de 30 para 15, o que corta pela
metade o que fica em trânsito.

---

## 10. Backup — e por que são dois

| | o que salva | de quê | com que frequência |
|---|---|---|---|
| **do ServerSP** (R$ 25/mês) | a máquina inteira | disco que morreu, sistema quebrado | **semanal** |
| **a cópia diária** (`api/copia.py`) | o trabalho entregue e as contas | engano, apagão, máquina perdida | **diária, fora do servidor** |

O do provedor é semanal: um problema na quinta perde o que foi feito desde
domingo. Numa agência que produz 250 peças por mês, isso é uma semana de
trabalho que ninguém tem como devolver — o cliente pagou por ela.

**A cópia diária leva o mesmo que a faxina guarda**: as contas e, de cada
trabalho, as peças entregues, os vídeos, a apresentação e os JSONs da montagem.
O material bruto fica de fora de propósito: ele já tem prazo de 30 dias e é 85%
do disco.

**É espelho, não pacote diário.** Peça entregue nunca muda, então cada arquivo
sobe uma vez e fica. Empacotar tudo todo dia e guardar catorze custaria catorze
vezes o tamanho dos dados — a R$ 0,10 por GB da Magalu, com dez clientes por um
ano, **R$ 102 por mês de pacotes contra R$ 7,29 de espelho**. As contas, que
mudam, sobem também como pacote datado minúsculo, e dessas ficam as últimas
catorze: um arquivo de conta corrompido hoje não pode apagar o bom.

**Nada é apagado de lá porque sumiu daqui.** Backup que apaga o que foi apagado
não protege do engano, que é metade do motivo de existir.

Ela sai para armazenamento de objetos — **fora do servidor**, porque cópia no
mesmo disco não protege do caso que importa, que é a máquina morrer. Serve
qualquer um que fale S3: **Magalu Object Storage** (R$ 0,10/GB, em real e com
nota fiscal, conferido em 16/10/2026), Cloudflare R2, Backblaze B2, AWS.
Preencha `REPLICAI_COPIA_*` no `.env`; sem isso **nenhuma cópia acontece** e
`/saude` diz `"copia": "desligada"`.

Para ver o que entraria, antes de ligar o armazenamento:

```bash
docker compose -f infra/docker-compose.yml run --rm copia python -m api.copia --sem-enviar
```

**Restaurar** é descer os arquivos por cima da pasta de dados — o caminho lá
dentro é o mesmo daqui, para não haver adivinhação na pior hora:

```bash
# com a api parada
docker compose -f infra/docker-compose.yml stop api worker worker-video
aws s3 sync s3://SEU-BALDE/replicai/arquivos/ /dados/ --endpoint-url SEU-ENDPOINT
# e, se o problema for uma conta corrompida, a versão de um dia bom:
aws s3 cp s3://SEU-BALDE/replicai/contas/contas-2026-10-16.tar.gz .
tar xzf contas-2026-10-16.tar.gz -C /dados
docker compose -f infra/docker-compose.yml start api worker worker-video
```

## 11. Backup do volume, na mão

O que não pode sumir é um volume só, o `dados`: contas, trabalhos e entregas.

```bash
docker run --rm -v infra_dados:/d -v /backup:/b alpine \
  tar czf /b/replicai-$(date +%F).tar.gz -C /d .
```

Diário, com o snapshot do provedor por cima. Conta perdida é cliente perdido.
