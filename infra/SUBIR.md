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
| Memória | 8 GB | **16 GB** | pelo `docker-compose.yml`: cada worker de peça custa 0,7 GB, o de vídeo 2 GB, e um PSD de 250 MB aberto para extração sobe bem acima do tamanho do arquivo |
| Disco | 160 GB SSD | **250 GB SSD** | medido em `api/faxina.py`: quarenta clientes geram 94 GB de material bruto por mês, dos quais o PSD é 85%. A faxina apaga o bruto com 30 dias e o acúmulo permanente cai para 8 GB por mês |
| Arquitetura | **x86_64 (amd64)** | — | a tipografia da peça está travada e conferida na esteira com um Chromium amd64. Outra arquitetura mede o texto de outro jeito e a peça sai diferente, sem erro nenhum para avisar |
| Sistema | Ubuntu 24.04 LTS ou Debian 13 | — | só precisa rodar Docker; o resto vem dentro da imagem |
| IP | IPv4 fixo | — | o certificado é emitido para o domínio que aponta para este IP |
| Tráfego | 2 TB/mês | — | sobe PSD de até 250 MB e desce pacote de peças |
| Swap | 2 GB | 4 GB | é o que segura o pico de abrir um PSD grande sem o sistema matar o worker |

Localização: **Brasil ou leste dos Estados Unidos**. O cliente sobe arquivos de
centenas de MB, e a distância aparece no tempo de upload — não na velocidade de
render.

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

## 9. Backup

O que não pode sumir é um volume só, o `dados`: contas, trabalhos e entregas.

```bash
docker run --rm -v infra_dados:/d -v /backup:/b alpine \
  tar czf /b/replicai-$(date +%F).tar.gz -C /d .
```

Diário, com o snapshot do provedor por cima. Conta perdida é cliente perdido.
