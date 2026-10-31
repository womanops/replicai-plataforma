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


# CREDENCIAL QUE SAI DA MÁQUINA. Toda variável de ambiente daqui compra algo
# ou fala com alguém de fora: o modelo cobra por chamada, o Asaas cria cobrança
# de verdade, o Resend manda e-mail de verdade, o armazenamento sobe arquivo, o
# Redis entrega trabalho para um worker que não é desta suíte.
FORA_DA_MAQUINA = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",   # modelo: cobra por chamada
    "ASAAS_API_KEY", "ASAAS_AVISO_TOKEN",          # cobrança de verdade
    "RESEND_API_KEY",                              # e-mail de verdade
    "REPLICAI_COPIA_CHAVE", "REPLICAI_COPIA_SEGREDO",   # sobe arquivo
    "REDIS_URL",                                   # fila fora do processo
)


@pytest.fixture(autouse=True)
def nada_sai_da_maquina(monkeypatch):
    """Nenhum teste fala com o mundo por fora da porta de quem desenvolve.

    O `.env` da raiz é lido na importação de `api.main`, e basta um teste
    importar a tela para a chave do modelo entrar no ambiente de toda a suíte.
    Daí em diante a direção de arte passa a ser decidida pelo modelo, de
    verdade, em cada peça recomposta: chamada paga numa suíte que devia custar
    zero, e resultado que depende do que o modelo respondeu naquela hora.
    Medido: `pytest testes/test_conteiner.py testes/test_psd.py` fazia três
    chamadas pagas, e era isto que fazia `test_o_lockup_recomposto_fica_abaixo_
    da_arte` passar sozinho e falhar acompanhado. Não era ordem de teste, era a
    chave entrando pela importação — e quanto se gastava dependia de quais
    arquivos você rodasse, que é o pior tipo de conta.

    Em branco e não apagada de propósito: `ambiente.carregar()` só escreve o
    que ainda não está no ambiente, então a variável vazia também barra o
    `.env` de repor a chave no meio do teste. Todo leitor dela usa `.get` e
    trata vazio como ausente.

    Quem testa o caminho COM credencial põe a sua, de mentira, no próprio
    teste — e aí esta trava sai da frente, porque a do teste vem depois.
    """
    for nome in FORA_DA_MAQUINA:
        monkeypatch.setenv(nome, "")


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
