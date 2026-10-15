"""De onde sai o preço de cada plano.

Preço escrito à mão envelhece calado: o dólar sobe, o custo sobe junto, e a
margem some sem ninguém perceber. Aqui o preço é **derivado** do custo medido,
e o que se ajusta é a premissa — o dólar, o imposto, a margem pretendida.

O custo por peça não é estimativa: saiu de rodadas reais. O modelo cobrou
US$ 0,117 por três peças, e o extrato do serviço generativo mostrou 2,80
créditos por fundo. Fundo só é preciso quando a proporção muda, o que deu
dois terços das peças na grade que a gente roda.

**O fundo generativo é comprado por plano mensal**, não por peça: o Higgsfield
cobra US$ 49 por 1.000 créditos que não acumulam. Isso o torna custo FIXO — e o
preço por crédito que aparece no custo da peça é o do crédito AVULSO, que é o
que se paga quando o plano acaba. Dentro do plano o fundo já está pago.

**Vídeo não entra na conta de custo.** Ele anima uma peça que já existe, sem
chamar serviço nenhum: gasta tempo de máquina, não dinheiro por unidade. O
limite de vídeo existe para proteger a fila, não o caixa.

**O que entra no preço e o que é pago pela margem.** No preço entra o que só
existe porque o cliente existe: as peças que ele produz, o imposto sobre o que
ele paga e a taxa do meio de pagamento. A margem pretendida vem em cima disso.
O que existe mesmo sem cliente nenhum — servidor, ferramentas, o tempo de quem
atende — é pago POR essa margem, e está aqui embaixo em `custo_fixo_mes()`.

A separação não é detalhe de contador: somar a hora de quem atende ao custo e
ainda pedir margem em cima dela cobra duas vezes pela mesma hora, e o preço
sai do mercado (o plano de entrada iria a R$ 1.900 com 80% de margem). O que o
custo fixo decide não é o preço — é **quantos clientes o mês precisa**, e isso
é o `ponto_de_equilibrio()`.
"""
from __future__ import annotations

import math

# --- o que custa, medido -----------------------------------------------------
MODELO_POR_PECA = 0.039        # US$, de US$ 0,117 por três peças
CREDITOS_POR_FUNDO = 2.80      # do extrato do serviço generativo
DOLAR_POR_CREDITO = 0.045      # pacote avulso sai a US$ 5 por 100 créditos
FUNDOS_POR_PECA = 2 / 3        # peça de mesma proporção não precisa de fundo novo

# --- as premissas, que mudam com o tempo -------------------------------------
DOLAR = 5.40                   # câmbio de referência
IOF_E_SPREAD = 0.07            # o que o cartão cobra além da cotação
IMPOSTO = 0.08                 # Simples sobre o faturamento — confirme o anexo
GATEWAY = 0.02                 # média entre Pix por valor fixo e cartão
# A margem que o PISO protege. A tabela entrega de 77% a 81%; o alvo fica em
# 75% para o alarme tocar quando a margem começar a ficar desconfortável, e não
# ao primeiro centavo de variação do dólar — Studio e Agency ficariam a poucos
# reais do piso se ele fosse fixado na margem que eles entregam hoje.
MARGEM_ALVO = 0.75             # margem com o cliente usando a franquia inteira

# --- o que custa mesmo sem cliente nenhum ------------------------------------
# Não entra no preço de cada plano: entra na conta de quantos clientes o mês
# precisa. Rateá-lo por conta exigiria adivinhar quantas contas existem, e no
# começo esse palpite erra para o lado caro — preço alto espanta o primeiro
# cliente, que é justamente quem paga o servidor.
# ServerSP, Cloud VPS 16GB SP, mensal sem fidelidade: 8 vCPU, 16 GB, 200 GB
# NVMe em São Paulo. Preço conferido em 15/10/2026 — a comparação com Vultr e
# Magalu está em `infra/SUBIR.md`
SERVIDOR_MES = 249.0
# a alternativa menor do mesmo fornecedor (4 vCPU, 8 GB, 100 GB): é por onde
# faz sentido começar enquanto a carteira não cresce, e `CUSTOS.md` abre as
# contas com ela. Fica aqui para documento e código não divergirem
SERVIDOR_8GB_MES = 125.0
# domínio (~R$ 50/ano no Registro.br, R$ 5/mês) e backup do servidor (R$ 25,
# conferido com o ServerSP em 16/10/2026 — e é SEMANAL, não diário, o que não
# protege o trabalho entregue de um cliente: a cópia diária do que é dos
# clientes é assunto à parte, e ainda não existe).
# O envio de e-mail (Resend) não entra: até 3 mil e-mails por mês é de graça, e
# o acesso de um cliente são dois ou três e-mails no mês inteiro
FERRAMENTAS_MES = 30.0
# O plano do Higgsfield, que é onde o fundo generativo é comprado. Plano Plus:
# 1.000 créditos por mês por US$ 49. É custo FIXO — sai do caixa com zero
# cliente, e o crédito não acumula de um mês para o outro.
#
# Ele cobre `creditos_do_plano / (CREDITOS_POR_FUNDO * FUNDOS_POR_PECA)` peças,
# hoje 536 por mês. Acima disso o fundo passa a custar crédito avulso, que é o
# preço usado em `custo_peca()` — o teto, não o piso: dentro do plano o fundo
# já está pago, e contar os dois seria cobrar duas vezes pela mesma coisa.
HIGGSFIELD_MES_USD = 49.0
HIGGSFIELD_CREDITOS = 1000

ATENDIMENTO_MES = 0.0          # o tempo de quem atende, se você quiser vê-lo
                               # aqui como linha. Fica em zero porque a margem
                               # é o que paga esse tempo — somar aqui e pedir
                               # margem em cima cobraria duas vezes


def custo_peca_dolar() -> float:
    return MODELO_POR_PECA + FUNDOS_POR_PECA * CREDITOS_POR_FUNDO * DOLAR_POR_CREDITO


def custo_peca() -> float:
    """O que uma peça custa em reais, já com IOF e spread do cartão."""
    return custo_peca_dolar() * DOLAR * (1 + IOF_E_SPREAD)


def preco_de(pecas: int, margem: float = MARGEM_ALVO) -> float:
    """O preço que entrega a margem pretendida com a franquia toda usada.

    Margem cheia é o pior caso: cliente que usa tudo. Quem usa metade deixa
    margem maior, e é o que acontece na maioria — por isso a franquia é
    dimensionada com folga.
    """
    sobra = 1 - IMPOSTO - GATEWAY - margem
    if sobra <= 0:
        raise ValueError("imposto, gateway e margem somam 100% ou mais")
    bruto = custo_peca() * pecas / sobra
    return float(math.ceil(bruto / 10) * 10)       # múltiplo de dez, para cima


# --- o preço de tabela, decidido ---------------------------------------------
# O número derivado acima é o PISO: abaixo dele a margem pretendida não se
# paga. O que se COBRA é decisão de negócio, e está aqui.
#
# A entrada começa em R$ 890 porque conta pequena dá o mesmo atendimento que
# conta grande — o custo das peças é a menor parte do que um cliente custa. E o
# preço por peça cai conforme o volume (R$ 11,13 no Basic, R$ 5,83 no Agency):
# é isso que faz subir de plano valer a pena para quem produz muito.
TABELA = {
    "freelancer": 1990.0,   # a entrada, acima do piso de 80% (R$ 1.780)
    "studio":     3900.0,   # R$ 6,50 por peça, decidido
    "agency":     6600.0,   # R$ 5,50 por peça, decidido
}


def de_tabela(plano: str, pecas: int) -> float:
    """O que se cobra pelo plano. Plano fora da tabela sai pelo piso derivado."""
    return float(TABELA.get(plano) or preco_de(pecas))


def abaixo_do_piso(planos: dict) -> list[str]:
    """Os planos cujo preço de tabela já não entrega a margem pretendida.

    O preço NÃO sobe sozinho: mexer no que o cliente paga é decisão, não efeito
    colateral do câmbio — ninguém descobre no extrato que a assinatura mudou.
    O que o sistema faz é avisar, antes que a margem suma em silêncio. A
    esteira confere isso a cada empurrão.
    """
    furados = []
    for plano, lim in planos.items():
        if plano not in TABELA or not lim.get("pecas"):
            continue
        if TABELA[plano] < preco_de(lim["pecas"]):
            furados.append(plano)
    return furados


def higgsfield_mes() -> float:
    """O plano do generativo em reais, com o que o cartão cobra por fora."""
    return HIGGSFIELD_MES_USD * DOLAR * (1 + IOF_E_SPREAD)


def pecas_do_plano_generativo() -> int:
    """Quantas peças por mês o plano do Higgsfield cobre."""
    por_peca = CREDITOS_POR_FUNDO * FUNDOS_POR_PECA
    return int(HIGGSFIELD_CREDITOS / por_peca) if por_peca else 0


def custo_fixo_mes() -> float:
    """O que sai do caixa todo mês com zero cliente."""
    return SERVIDOR_MES + FERRAMENTAS_MES + ATENDIMENTO_MES + higgsfield_mes()


def sobra_de(pecas: int, preco: float) -> float:
    """O que sobra de um cliente depois do que ele mesmo custa.

    É daqui que sai o dinheiro do servidor, das ferramentas e do seu tempo.
    """
    return preco - custo_peca() * pecas - preco * (IMPOSTO + GATEWAY)


def ponto_de_equilibrio(planos: dict) -> dict:
    """Quantos clientes de cada plano pagam a conta fixa do mês.

    O número que importa não é a margem em porcentagem — é este. Margem de 80%
    com um cliente só não paga servidor nenhum.
    """
    fixo = custo_fixo_mes()
    quantos = {}
    for plano, lim in planos.items():
        if plano not in TABELA or not lim.get("pecas"):
            continue
        sobra = sobra_de(lim["pecas"], TABELA[plano])
        quantos[plano] = math.ceil(fixo / sobra) if sobra > 0 else None
    return {"custo_fixo_mes": round(fixo, 2), "contas_para_empatar": quantos}


def conta(pecas: int, preco: float) -> dict:
    """A conta aberta de um plano, para não precisar confiar no número."""
    custo = custo_peca() * pecas
    impostos = preco * IMPOSTO
    taxas = preco * GATEWAY
    margem = preco - custo - impostos - taxas
    if not preco:
        # plano de graça não tem margem, tem custo de aquisição: o que você
        # paga para alguém experimentar. Chamar isso de margem zero esconderia
        # que o dinheiro sai.
        return {"preco": 0.0, "custo_cheio": round(custo, 2), "impostos": 0.0,
                "gateway": 0.0, "margem": round(-custo, 2), "margem_pct": 0.0,
                "margem_na_metade": 0.0, "custo_de_aquisicao": round(custo, 2),
                "custo_por_peca": round(custo_peca(), 4)}
    return {"preco": round(preco, 2), "custo_cheio": round(custo, 2),
            "impostos": round(impostos, 2), "gateway": round(taxas, 2),
            "margem": round(margem, 2),
            "margem_pct": round(100 * margem / preco, 1) if preco else 0.0,
            "margem_na_metade": round(100 * (preco - custo / 2 - impostos - taxas)
                                      / preco, 1) if preco else 0.0,
            "custo_por_peca": round(custo_peca(), 4)}
