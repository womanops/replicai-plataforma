"""A assinatura, no Asaas.

A chamada HTTP entra de fora, como no adaptador do modelo: a integração
inteira é testada sem chave e sem rede. O que estes testes protegem é
dinheiro — plano liberado sem pagamento, pagamento contado duas vezes, e
acesso que continua depois do atraso.
"""
import json
from datetime import date, timedelta

import pytest

from api import cobranca, contas


@pytest.fixture(autouse=True)
def disco(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("ASAAS_API_KEY", "chave-de-teste")
    import importlib
    from api import trabalhos
    importlib.reload(trabalhos)


@pytest.fixture
def conta():
    return contas.criar("Operandi", "ligia@exemplo.com", "senha-bem-comprida")


@pytest.fixture
def asaas(monkeypatch):
    """Um Asaas de mentira: guarda o que foi pedido, devolve o que ele devolve."""
    chamadas = []

    def falso(metodo, caminho, corpo=None):
        chamadas.append((metodo, caminho, corpo))
        if caminho == "/customers":
            return {"id": "cus_000001"}
        if caminho == "/subscriptions":
            return {"id": "sub_000001", "status": "ACTIVE"}
        return {}

    monkeypatch.setattr(cobranca, "chamar", falso)
    return chamadas


class TestAssinar:
    def test_cria_o_cliente_uma_vez_so(self, conta, asaas):
        cobranca.garantir_cliente(conta, "12345678900")
        cobranca.garantir_cliente(conta)
        assert [c[1] for c in asaas].count("/customers") == 1
        assert conta.asaas_cliente == "cus_000001"

    def test_o_cpf_vai_sem_pontuacao(self, conta, asaas):
        cobranca.garantir_cliente(conta, "123.456.789-00")
        assert asaas[0][2]["cpfCnpj"] == "12345678900"

    def test_a_assinatura_e_mensal_e_leva_a_conta_na_referencia(self, conta, asaas):
        cobranca.assinar(conta, "studio", "PIX")
        _, caminho, corpo = asaas[-1]
        assert caminho == "/subscriptions"
        assert corpo["cycle"] == "MONTHLY" and corpo["billingType"] == "PIX"
        assert corpo["value"] == cobranca.PRECOS["studio"]
        assert corpo["externalReference"] == f"{conta.id}:studio"

    def test_assinar_nao_libera_o_plano(self, conta, asaas):
        """Quem libera é o aviso de pagamento. Liberar aqui é dar de graça a
        quem clicou e não pagou."""
        cobranca.assinar(conta, "studio")
        assert contas.por_id(conta.id).plano == "demo"
        assert contas.por_id(conta.id).plano_pedido == "studio"

    def test_o_plano_de_entrada_nao_tem_assinatura(self, conta, asaas):
        with pytest.raises(cobranca.CobrancaIndisponivel):
            cobranca.assinar(conta, "demo")

    def test_forma_de_pagamento_torta_e_recusada(self, conta, asaas):
        with pytest.raises(cobranca.CobrancaIndisponivel, match="forma de pagamento"):
            cobranca.assinar(conta, "studio", "DINHEIRO")

    def test_cancelar_tira_a_assinatura(self, conta, asaas):
        cobranca.assinar(conta, "studio")
        assert cobranca.cancelar(conta) is True
        assert ("DELETE", "/subscriptions/sub_000001", None) in asaas
        assert contas.por_id(conta.id).asaas_assinatura == ""

    def test_cancelar_sem_assinatura_nao_quebra(self, conta, asaas):
        assert cobranca.cancelar(conta) is False


def aviso(evento, conta_id, plano="studio", vencimento=None, ident="evt_1"):
    return {"id": ident, "event": evento,
            "payment": {"externalReference": f"{conta_id}:{plano}",
                        "dueDate": (vencimento or date.today()).isoformat()}}


class TestOQueOAsaasAvisa:
    def test_pagamento_confirmado_libera_o_plano(self, conta, asaas):
        cobranca.assinar(conta, "studio")
        r = cobranca.aplicar_evento(aviso("PAYMENT_CONFIRMED", conta.id))
        assert r["feito"] == "aplicado"
        atual = contas.por_id(conta.id)
        assert atual.plano == "studio" and atual.em_atraso is False
        assert cobranca.plano_valendo(atual) == "studio"

    def test_o_mesmo_aviso_duas_vezes_nao_conta_duas(self, conta, asaas):
        """O Asaas reenvia quando não recebe 200. Processar de novo adiantaria
        o vencimento sem ninguém ter pago."""
        cobranca.assinar(conta, "studio")
        cobranca.aplicar_evento(aviso("PAYMENT_CONFIRMED", conta.id))
        primeiro = contas.por_id(conta.id).pago_ate
        r = cobranca.aplicar_evento(aviso("PAYMENT_CONFIRMED", conta.id))
        assert r["feito"] == "repetido"
        assert contas.por_id(conta.id).pago_ate == primeiro

    def test_atraso_marca_a_conta(self, conta, asaas):
        cobranca.assinar(conta, "studio")
        cobranca.aplicar_evento(aviso("PAYMENT_CONFIRMED", conta.id))
        cobranca.aplicar_evento(aviso("PAYMENT_OVERDUE", conta.id, ident="evt_2"))
        assert contas.por_id(conta.id).em_atraso is True

    def test_evento_de_conta_que_nao_existe_responde_sem_quebrar(self, asaas):
        """Responder 200 mesmo assim: senão o Asaas reenvia para sempre."""
        r = cobranca.aplicar_evento(aviso("PAYMENT_CONFIRMED", "nao-existe"))
        assert r["feito"] == "sem dono"

    def test_evento_que_nao_interessa_e_ignorado(self, conta, asaas):
        r = cobranca.aplicar_evento(aviso("PAYMENT_CREATED", conta.id))
        assert r["feito"] == "ignorado"

    def test_acha_a_conta_pelo_cliente_quando_falta_referencia(self, conta, asaas):
        cobranca.garantir_cliente(conta)
        r = cobranca.aplicar_evento({"id": "evt_9", "event": "PAYMENT_CONFIRMED",
                                     "payment": {"customer": "cus_000001"}})
        assert r["conta"] == conta.id


class TestOPlanoSoValePago:
    def test_sem_pagamento_nenhum_vale_teste(self, conta):
        conta.plano = "agency"
        assert cobranca.plano_valendo(conta) == "demo"

    def test_vencido_cai_para_teste(self, conta):
        conta.plano = "studio"
        conta.pago_ate = (date.today() - timedelta(days=1)).isoformat()
        assert cobranca.plano_valendo(conta) == "demo"

    def test_dentro_do_prazo_vale(self, conta):
        conta.plano = "studio"
        conta.pago_ate = (date.today() + timedelta(days=1)).isoformat()
        assert cobranca.plano_valendo(conta) == "studio"

    def test_o_contratado_nao_e_apagado_pelo_atraso(self, conta):
        """`plano` é o que foi comprado; `plano_valendo` é o que pode usar
        hoje. Misturar faria o atraso apagar a memória do que ela tinha."""
        conta.plano = "agency"
        conta.pago_ate = "2020-01-01"
        assert cobranca.plano_valendo(conta) == "demo"
        assert conta.plano == "agency"

    def test_data_torta_nao_libera(self, conta):
        conta.plano = "studio"
        conta.pago_ate = "nunca"
        assert cobranca.plano_valendo(conta) == "demo"

    def test_plano_que_sumiu_da_tabela_nao_libera(self, conta):
        conta.plano = "plano-antigo"
        conta.pago_ate = (date.today() + timedelta(days=30)).isoformat()
        assert cobranca.plano_valendo(conta) == "demo"


class TestSemChave:
    def test_sem_chave_a_chamada_recusa_antes_de_sair(self, monkeypatch):
        monkeypatch.delenv("ASAAS_API_KEY", raising=False)
        assert cobranca.configurada() is False
        with pytest.raises(cobranca.CobrancaIndisponivel, match="ASAAS_API_KEY"):
            cobranca.chamar("GET", "/customers")
