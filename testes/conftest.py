"""Põe a raiz do projeto no caminho para `from motor import ...` funcionar
sem instalar o pacote."""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
