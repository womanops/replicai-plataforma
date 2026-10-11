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
MARGEM_ALVO = 0.70             # margem com o cliente usando a franquia inteira


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


def conta(pecas: int, preco: float) -> dict:
    """A conta aberta de um plano, para não precisar confiar no número."""
    custo = custo_peca() * pecas
    impostos = preco * IMPOSTO
    taxas = preco * GATEWAY
    margem = preco - custo - impostos - taxas
    return {"preco": round(preco, 2), "custo_cheio": round(custo, 2),
            "impostos": round(impostos, 2), "gateway": round(taxas, 2),
            "margem": round(margem, 2),
            "margem_pct": round(100 * margem / preco, 1) if preco else 0.0,
            "margem_na_metade": round(100 * (preco - custo / 2 - impostos - taxas)
                                      / preco, 1) if preco else 0.0,
            "custo_por_peca": round(custo_peca(), 4)}
