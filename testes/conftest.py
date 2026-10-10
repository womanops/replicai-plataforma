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
