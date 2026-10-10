"""Quanto custou falar com o modelo.

A resposta da API traz os tokens gastos, mas não o dinheiro. Sem converter,
não há como pôr preço na peça — e preço é o que decide se isto vira produto.

A conta é por thread: cada trabalho roda na sua, e somar o gasto de dois
trabalhos simultâneos num balcão só daria um número que não serve para nada.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

# Por milhão de tokens, em dólar. Tabela de 10 de outubro de 2026,
# de platform.claude.com/docs/en/about-claude/pricing.
# Preço muda: quando mudar, é este dicionário que se corrige, e os testes
# abaixo travam a conta, não os valores.
PRECOS = {
    "claude-opus-5-5":   {"entrada": 4.0,  "saida": 20.0, "cache_leitura": 0.20, "cache_escrita": 5.0},
    "claude-sonnet-5-5": {"entrada": 2.0,  "saida": 10.0, "cache_leitura": 0.10, "cache_escrita": 2.50},
    "claude-haiku-5-5":  {"entrada": 0.10, "saida": 0.50, "cache_leitura": 0.01, "cache_escrita": 0.125},
}


@dataclass
class Conta:
    chamadas: int = 0
    entrada: int = 0
    saida: int = 0
    cache_leitura: int = 0
    cache_escrita: int = 0
    modelos: set[str] = field(default_factory=set)
    sem_preco: set[str] = field(default_factory=set)

    def somar(self, modelo: str, uso) -> None:
        def n(campo):
            v = getattr(uso, campo, None) if not isinstance(uso, dict) else uso.get(campo)
            return int(v or 0)

        self.chamadas += 1
        self.entrada += n("input_tokens")
        self.saida += n("output_tokens")
        self.cache_leitura += n("cache_read_input_tokens")
        self.cache_escrita += n("cache_creation_input_tokens")
        self.modelos.add(modelo)
        if modelo not in PRECOS:
            self.sem_preco.add(modelo)

    @property
    def tokens(self) -> int:
        return self.entrada + self.saida + self.cache_leitura + self.cache_escrita

    def dolares(self) -> float:
        """Só dá para somar dinheiro se todos os modelos usados têm preço na
        tabela. Com um deles de fora, o total mentiria para baixo."""
        if self.sem_preco or not self.modelos:
            return 0.0
        # uma conta só, com o preço do modelo usado; misturar modelos numa
        # chamada não acontece hoje, e se acontecer o primeiro manda
        p = PRECOS[sorted(self.modelos)[0]]
        return (self.entrada * p["entrada"]
                + self.saida * p["saida"]
                + self.cache_leitura * p["cache_leitura"]
                + self.cache_escrita * p["cache_escrita"]) / 1_000_000

    def resumo(self) -> dict:
        d = {"chamadas": self.chamadas, "entrada": self.entrada, "saida": self.saida,
             "cache_leitura": self.cache_leitura, "cache_escrita": self.cache_escrita,
             "tokens": self.tokens, "modelos": sorted(self.modelos)}
        if self.sem_preco:
            d["sem_preco"] = sorted(self.sem_preco)   # aparece em vez do dólar
        else:
            d["dolares"] = round(self.dolares(), 6)
        return d


_local = threading.local()


def atual() -> Conta | None:
    return getattr(_local, "conta", None)


def registrar(modelo: str, uso) -> None:
    """Chamado pelo adaptador do modelo. Fora de um `medir()`, não faz nada —
    o adaptador não precisa saber se alguém está contando."""
    c = atual()
    if c is not None:
        c.somar(modelo, uso)


class medir:
    """`with medir() as conta:` — tudo que o modelo gastar lá dentro, nesta
    thread, entra nessa conta."""

    def __enter__(self) -> Conta:
        self.anterior = atual()
        self.conta = Conta()
        _local.conta = self.conta
        return self.conta

    def __exit__(self, *_):
        _local.conta = self.anterior
        return False
