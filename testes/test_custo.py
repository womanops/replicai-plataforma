"""A conta do modelo.

Os testes travam a aritmética, não a tabela de preços: preço muda, e quando
mudar é `PRECOS` que se corrige — os testes derivam o esperado da tabela.
"""
import threading

import pytest

from api import custo
from api.custo import PRECOS, Conta, medir, registrar


class Uso:
    def __init__(self, entrada=0, saida=0, leitura=0, escrita=0):
        self.input_tokens = entrada
        self.output_tokens = saida
        self.cache_read_input_tokens = leitura
        self.cache_creation_input_tokens = escrita


def test_soma_as_chamadas():
    c = Conta()
    c.somar("claude-opus-5-5", Uso(entrada=100, saida=10))
    c.somar("claude-opus-5-5", Uso(entrada=50, saida=5))
    assert c.chamadas == 2
    assert (c.entrada, c.saida) == (150, 15)


def test_o_dolar_vem_da_tabela():
    p = PRECOS["claude-opus-5-5"]
    c = Conta()
    c.somar("claude-opus-5-5", Uso(entrada=1_000_000, saida=1_000_000))
    assert c.dolares() == pytest.approx(p["entrada"] + p["saida"])


def test_cache_conta_no_preco_dele():
    p = PRECOS["claude-opus-5-5"]
    c = Conta()
    c.somar("claude-opus-5-5", Uso(leitura=1_000_000, escrita=1_000_000))
    assert c.dolares() == pytest.approx(p["cache_leitura"] + p["cache_escrita"])
    # leitura de cache é muito mais barata que entrada nova — se um dia a
    # tabela inverter isso, é erro de digitação
    assert p["cache_leitura"] < p["entrada"]


def test_modelo_fora_da_tabela_nao_vira_zero_silencioso():
    """Somar só o que tem preço daria um total mentindo para baixo."""
    c = Conta()
    c.somar("modelo-novo-sem-preco", Uso(entrada=1_000_000, saida=1_000_000))
    assert c.dolares() == 0.0
    r = c.resumo()
    assert "dolares" not in r              # não finge saber
    assert r["sem_preco"] == ["modelo-novo-sem-preco"]


def test_usage_ausente_nao_quebra():
    c = Conta()
    c.somar("claude-opus-5-5", None)
    assert c.chamadas == 1 and c.tokens == 0


def test_usage_como_dicionario():
    c = Conta()
    c.somar("claude-opus-5-5", {"input_tokens": 7, "output_tokens": 3})
    assert c.tokens == 10


def test_fora_do_medir_nao_explode():
    """O adaptador chama `registrar` sempre; sem ninguém contando, é um nada."""
    assert custo.atual() is None
    registrar("claude-opus-5-5", Uso(entrada=10))     # não levanta


def test_medir_pega_o_que_rodou_dentro():
    with medir() as conta:
        registrar("claude-opus-5-5", Uso(entrada=10, saida=2))
    assert conta.chamadas == 1
    registrar("claude-opus-5-5", Uso(entrada=999))    # já fora
    assert conta.chamadas == 1


def test_medir_aninhado_devolve_a_conta_de_fora():
    with medir() as fora:
        with medir() as dentro:
            registrar("claude-opus-5-5", Uso(entrada=5))
        registrar("claude-opus-5-5", Uso(entrada=7))
    assert dentro.entrada == 5
    assert fora.entrada == 7


def test_dois_trabalhos_ao_mesmo_tempo_nao_se_misturam():
    """O custo é por trabalho. Um balcão único somaria dois clientes."""
    contas = {}
    porta = threading.Barrier(2)

    def trabalho(nome, tokens):
        with medir() as c:
            porta.wait()                  # força a sobreposição
            registrar("claude-opus-5-5", Uso(entrada=tokens))
            porta.wait()
            contas[nome] = c.entrada

    a = threading.Thread(target=trabalho, args=("a", 100))
    b = threading.Thread(target=trabalho, args=("b", 7))
    a.start(); b.start(); a.join(); b.join()
    assert contas == {"a": 100, "b": 7}


def test_resumo_traz_o_que_entra_no_preco():
    with medir() as c:
        registrar("claude-opus-5-5", Uso(entrada=1000, saida=100))
    r = c.resumo()
    assert r["chamadas"] == 1 and r["tokens"] == 1100
    assert r["modelos"] == ["claude-opus-5-5"]
    assert r["dolares"] > 0
