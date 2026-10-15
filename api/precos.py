"""De onde sai o preço de cada plano.

Preço escrito à mão envelhece calado: o dólar sobe, o custo sobe junto, e a
margem some sem ninguém perceber. Aqui o preço é **derivado** do custo medido,
e o que se ajusta é a premissa — o dólar, o imposto, a margem pretendida.

O custo por peça não é estimativa: saiu de rodadas reais. O modelo cobrou
US$ 0,117 por três peças, e o extrato do serviço generativo mostrou 2,80
créditos por fundo. Fundo só é preciso quando a proporção muda, o que deu
dois terços das peças na grade que a gente roda.

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
MARGEM_ALVO = 0.80             # margem com o cliente usando a franquia inteira

# --- o que custa mesmo sem cliente nenhum ------------------------------------
# Não entra no preço de cada plano: entra na conta de quantos clientes o mês
# precisa. Rateá-lo por conta exigiria adivinhar quantas contas existem, e no
# começo esse palpite erra para o lado caro — preço alto espanta o primeiro
# cliente, que é justamente quem paga o servidor.
SERVIDOR_MES = 600.0           # a confirmar: a máquina que roda api, worker,
                               # Chromium e Remotion, com disco para o bruto
FERRAMENTAS_MES = 0.0          # assinaturas (domínio, e-mail, o que vier);
                               # os créditos do generativo já são por peça
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
    "basic":       890.0,   # acima do piso de 80% (R$ 570): entrada decidida
    "freelancer": 1990.0,   # acima do piso de 80% (R$ 1.780)
    "studio":     4490.0,   # acima do piso de 80% (R$ 4.270) de propósito:
                           # no piso exato o Studio sai a R$ 7,12 por peça e
                           # o Agency a R$ 7,11 — subir de plano deixava de
                           # ser vantagem. Com R$ 4.490 o desconto volta a
                           # aparecer: R$ 7,48 contra R$ 7,11
    "agency":     8530.0,   # o piso de 80% exato
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


def custo_fixo_mes() -> float:
    """O que sai do caixa todo mês com zero cliente."""
    return SERVIDOR_MES + FERRAMENTAS_MES + ATENDIMENTO_MES


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
