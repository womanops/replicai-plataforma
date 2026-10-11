"""A assinatura, no Asaas.

Asaas e não Stripe por uma razão só, da qual as outras decorrem: ele emite a
nota fiscal junto da cobrança. Vender serviço no Brasil exige nota, e sem isso
seria preciso colar um emissor por fora. De quebra, Pix e boleto — que é como
agência brasileira paga — saem por taxa fixa baixa em vez de percentual.

A chamada HTTP entra de fora, como no adaptador do modelo. Assim a integração
inteira é testável sem chave e sem rede, e trocar de meio de pagamento é
trocar este arquivo.

**O plano só vale enquanto está pago.** Quando a cobrança atrasa, a conta cai
para o plano de teste em vez de ser bloqueada: ela continua alcançando o que
já produziu, com a franquia pequena. Bloquear quem esqueceu o boleto é perder
cliente por atrito.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PRODUCAO = "https://api.asaas.com/v3"
AREIA = "https://api-sandbox.asaas.com/v3"

# Preço mensal de cada plano, em reais. **Estes números são provisórios.**
# A base medida: cada peça custa de US$ 0,15 a 0,18 entre modelo e fundo
# generativo — perto de R$ 1,00 com dólar a 5,40 e os 6% de IOF e spread que o
# cartão cobra por cima. O resto é margem, e margem é decisão de quem vende.
PRECOS = {"teste": 0.0, "estudio": 697.0, "agencia": 2497.0}

FORMAS = ("PIX", "BOLETO", "CREDIT_CARD", "UNDEFINED")

# quantos dias de folga depois do vencimento antes de a conta cair para teste.
# Boleto compensa em dias úteis, e derrubar cliente que pagou ontem é atrito
# criado por nós.
CARENCIA = 5


class CobrancaIndisponivel(RuntimeError):
    """O meio de pagamento não respondeu. Quem chamou decide o que dizer."""


def configurada() -> bool:
    return bool(os.environ.get("ASAAS_API_KEY"))


def base() -> str:
    return AREIA if os.environ.get("ASAAS_AREIA") else PRODUCAO


def chamar(metodo: str, caminho: str, corpo: dict | None = None) -> dict:
    """Fala com o Asaas. Trocada por uma falsa nos testes."""
    import httpx

    chave = os.environ.get("ASAAS_API_KEY")
    if not chave:
        raise CobrancaIndisponivel("ASAAS_API_KEY não está configurada")
    try:
        r = httpx.request(metodo, f"{base()}{caminho}", json=corpo, timeout=30,
                          headers={"access_token": chave,
                                   "User-Agent": "ReplicAI/1.0",
                                   "accept": "application/json"})
    except Exception as e:
        raise CobrancaIndisponivel(f"o Asaas não respondeu: {e}") from e
    if r.status_code >= 400:
        try:
            erros = r.json().get("errors") or []
            recado = "; ".join(e.get("description", "") for e in erros)
        except Exception:
            recado = r.text[:200]
        raise CobrancaIndisponivel(recado or f"o Asaas devolveu {r.status_code}")
    return r.json()


# ----------------------------------------------------------------- assinar

def garantir_cliente(conta, cpf_cnpj: str = "") -> str:
    """O cliente no Asaas, criado uma vez e guardado na conta."""
    from api import contas

    if conta.asaas_cliente:
        return conta.asaas_cliente
    corpo = {"name": conta.nome, "email": conta.email,
             "externalReference": conta.id}
    if cpf_cnpj:
        corpo["cpfCnpj"] = "".join(c for c in cpf_cnpj if c.isdigit())
    criado = chamar("POST", "/customers", corpo)
    conta.asaas_cliente = criado["id"]
    contas._gravar(conta)
    return conta.asaas_cliente


def assinar(conta, plano: str, forma: str = "PIX", cpf_cnpj: str = "") -> dict:
    """Cria a assinatura mensal. Não confirma pagamento nenhum.

    O Asaas gera as cobranças ao longo da recorrência; quem diz que foi pago é
    o webhook. Por isso a conta **não** muda de plano aqui.
    """
    from api import contas, uso

    if plano not in uso.PLANOS or plano == "teste":
        raise CobrancaIndisponivel(f"não há assinatura para o plano `{plano}`")
    if forma not in FORMAS:
        raise CobrancaIndisponivel(f"forma de pagamento desconhecida: `{forma}`")

    cliente = garantir_cliente(conta, cpf_cnpj)
    criada = chamar("POST", "/subscriptions", {
        "customer": cliente,
        "billingType": forma,
        "value": PRECOS[plano],
        "nextDueDate": (date.today() + timedelta(days=1)).isoformat(),
        "cycle": "MONTHLY",
        "description": f"ReplicAI — plano {uso.limites(plano)['nome']}",
        "externalReference": f"{conta.id}:{plano}",
    })
    conta.asaas_assinatura = criada["id"]
    conta.plano_pedido = plano
    contas._gravar(conta)
    return {"assinatura": criada["id"], "plano": plano, "valor": PRECOS[plano],
            "forma": forma}


def cancelar(conta) -> bool:
    from api import contas

    if not conta.asaas_assinatura:
        return False
    chamar("DELETE", f"/subscriptions/{conta.asaas_assinatura}")
    conta.asaas_assinatura = ""
    conta.plano_pedido = ""
    contas._gravar(conta)
    return True


# ----------------------------------------------------------------- o que o Asaas avisa

# o que cada evento de cobrança significa para o acesso
PAGOU = {"PAYMENT_CONFIRMED", "PAYMENT_RECEIVED", "PAYMENT_RECEIVED_IN_CASH"}
PERDEU = {"PAYMENT_OVERDUE", "PAYMENT_DELETED", "PAYMENT_REFUNDED",
          "PAYMENT_CHARGEBACK_REQUESTED", "PAYMENT_REVERSED"}


def _ja_visto(ident: str) -> bool:
    """O Asaas reenvia o mesmo evento quando não recebe 200. Processar duas
    vezes um pagamento adianta o vencimento sem o cliente ter pago de novo."""
    from api.contas import pasta

    f = pasta() / "eventos.json"
    try:
        vistos = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        vistos = []
    if ident in vistos:
        return True
    vistos.append(ident)
    f.write_text(json.dumps(vistos[-2000:]), encoding="utf-8")
    return False


def _conta_do_evento(corpo: dict):
    from api import contas

    pagamento = corpo.get("payment") or {}
    ref = pagamento.get("externalReference") or ""
    if ":" in ref:
        c = contas.por_id(ref.split(":", 1)[0])
        if c:
            return c
    cliente = pagamento.get("customer")
    if cliente:
        return next((c for c in contas.todas() if c.asaas_cliente == cliente), None)
    return None


def aplicar_evento(corpo: dict) -> dict:
    """Lê um aviso do Asaas e ajusta o acesso da conta.

    Pagou: o plano pedido passa a valer, com validade até o próximo
    vencimento. Atrasou: a conta cai para teste depois da carência.
    """
    from api import contas

    tipo = corpo.get("event") or ""
    ident = corpo.get("id") or ""
    if ident and _ja_visto(ident):
        return {"feito": "repetido", "evento": tipo}

    conta = _conta_do_evento(corpo)
    if conta is None:
        # não é nossa, ou é de uma conta apagada: responder 200 mesmo assim,
        # senão o Asaas reenvia para sempre
        return {"feito": "sem dono", "evento": tipo}

    pagamento = corpo.get("payment") or {}
    if tipo in PAGOU:
        plano = conta.plano_pedido or conta.plano
        conta.plano = plano
        conta.pago_ate = _ate(pagamento)
        conta.em_atraso = False
    elif tipo in PERDEU:
        conta.em_atraso = True
    else:
        return {"feito": "ignorado", "evento": tipo, "conta": conta.id}

    contas._gravar(conta)
    return {"feito": "aplicado", "evento": tipo, "conta": conta.id,
            "plano": conta.plano, "pago_ate": conta.pago_ate}


def _ate(pagamento: dict) -> str:
    """Até quando o acesso vale. Um mês a partir do vencimento pago, mais a
    carência: boleto compensa em dias úteis."""
    bruto = pagamento.get("dueDate") or date.today().isoformat()
    try:
        venc = date.fromisoformat(bruto[:10])
    except ValueError:
        venc = date.today()
    return (venc + timedelta(days=30 + CARENCIA)).isoformat()


def dia_do_ciclo(conta) -> int:
    """Em que dia do mês a franquia zera.

    O dia da assinatura, e não o dia 1º: quem assina dia 20 teria a franquia
    zerada nove dias depois de pagar. Sem assinatura, vale o dia em que a
    conta nasceu, para o teste também ter um ciclo próprio.
    """
    for bruto in (conta.pago_ate, conta.criada):
        try:
            return date.fromisoformat((bruto or "")[:10]).day
        except ValueError:
            continue
    return 1


def plano_valendo(conta) -> str:
    """O plano que vale agora, não o que foi contratado.

    Separado de propósito: o campo `plano` diz o que a pessoa comprou, e isto
    diz o que ela pode usar hoje. Misturar os dois faria o atraso apagar a
    memória do que ela tinha.
    """
    from api import uso

    if conta.plano == "teste" or not conta.plano:
        return "teste"
    if not conta.pago_ate:
        return "teste"
    try:
        if date.fromisoformat(conta.pago_ate) < date.today():
            return "teste"
    except ValueError:
        return "teste"
    return conta.plano if conta.plano in uso.PLANOS else "teste"
