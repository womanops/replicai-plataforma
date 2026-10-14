"""Põe a raiz do projeto no caminho para `from motor import ...` funcionar
sem instalar o pacote."""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


import pytest


@pytest.fixture(autouse=True)
def sem_generativo(monkeypatch):
    """Nenhum teste chama o serviço generativo.

    Um teste de entrega passou a rodar outpaint de verdade sem ninguém notar:
    52 segundos e crédito gasto numa suíte que levava 15. Teste que gasta
    dinheiro é teste que ninguém roda.
    """
    monkeypatch.setenv("REPLICAI_FUNDO", "solid")


@pytest.fixture(autouse=True)
def franquia_valendo(monkeypatch):
    """A suíte testa o produto, não a máquina de quem está desenvolvendo.

    O `.env` da raiz é lido ao subir a api, e o de quem desenvolve tem
    `REPLICAI_SEM_LIMITE=1` para poder rodar a mesma peça vinte vezes. Com ele
    ligado, todo teste de franquia passa sem conferir nada — e os três que
    cobram o limite do plano quebravam aqui e passavam na esteira, que não tem
    `.env`. Quem precisa da franquia desligada liga por conta própria.
    """
    monkeypatch.setenv("REPLICAI_SEM_LIMITE", "0")


def assinatura_valendo(conta, plano="agency"):
    """Põe na conta um plano pago valendo hoje, e devolve a conta.

    A conta nasce da assinatura: sem plano ativo ela não produz nada. Quase
    todo teste daqui quer olhar o que acontece DEPOIS da porta do pagamento, e
    para isso a conta precisa ser de quem pagou. O plano maior de propósito:
    assim a franquia não entra no caminho de quem está testando outra coisa —
    quem testa o teto do plano escolhe o plano que quer.
    """
    from datetime import date, timedelta

    from api import contas
    conta.plano = plano
    conta.pago_ate = (date.today() + timedelta(days=30)).isoformat()
    contas._gravar(conta)
    return conta
