"""A assinatura, no Asaas.

A chamada HTTP entra de fora, como no adaptador do modelo: a integração
inteira é testada sem chave e sem rede. O que estes testes protegem é
dinheiro — plano liberado sem pagamento, pagamento contado duas vezes, e
acesso que continua depois do atraso.
"""
import json
from datetime import date, timedelta

import pytest

from api import cobranca, contas, uso


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
        assert contas.por_id(conta.id).plano == uso.PLANO_PADRAO
        assert contas.por_id(conta.id).plano_pedido == "studio"

    def test_o_estado_sem_plano_nao_se_assina(self, conta, asaas):
        """"sem" não é um degrau da escada: é a ausência dela."""
        with pytest.raises(cobranca.CobrancaIndisponivel):
            cobranca.assinar(conta, uso.PLANO_PADRAO)

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
    """A conta existe porque alguém assinou. Sem pagamento em dia ela cai para
    "sem plano", que não é uma franquia pequena — é sem sistema: o que já foi
    produzido continua baixável, e gerar ou ajustar espera o pagamento."""

    def test_sem_pagamento_nenhum_fica_sem_plano(self, conta):
        conta.plano = "agency"
        assert cobranca.plano_valendo(conta) == "sem"

    def test_vencido_fica_sem_plano(self, conta):
        conta.plano = "studio"
        conta.pago_ate = (date.today() - timedelta(days=1)).isoformat()
        assert cobranca.plano_valendo(conta) == "sem"

    def test_dentro_do_prazo_vale(self, conta):
        conta.plano = "studio"
        conta.pago_ate = (date.today() + timedelta(days=1)).isoformat()
        assert cobranca.plano_valendo(conta) == "studio"

    def test_o_contratado_nao_e_apagado_pelo_atraso(self, conta):
        """`plano` é o que foi comprado; `plano_valendo` é o que pode usar
        hoje. Misturar faria o atraso apagar a memória do que ela tinha."""
        conta.plano = "agency"
        conta.pago_ate = "2020-01-01"
        assert cobranca.plano_valendo(conta) == "sem"
        assert conta.plano == "agency"

    def test_data_torta_nao_libera(self, conta):
        conta.plano = "studio"
        conta.pago_ate = "nunca"
        assert cobranca.plano_valendo(conta) == "sem"

    def test_plano_que_sumiu_da_tabela_nao_libera(self, conta):
        conta.plano = "plano-antigo"
        conta.pago_ate = (date.today() + timedelta(days=30)).isoformat()
        assert cobranca.plano_valendo(conta) == "sem"


class TestSemChave:
    def test_sem_chave_a_chamada_recusa_antes_de_sair(self, monkeypatch):
        monkeypatch.delenv("ASAAS_API_KEY", raising=False)
        assert cobranca.configurada() is False
        with pytest.raises(cobranca.CobrancaIndisponivel, match="ASAAS_API_KEY"):
            cobranca.chamar("GET", "/customers")


class TestOPlanoDeEntradaEPago:
    """Não há degrau de graça: a conta nasce de uma assinatura. Quem quer
    conhecer antes pede uma demonstração, e isso acontece fora do sistema."""

    def test_sem_plano_nao_tem_preco(self):
        from api import uso
        assert cobranca.PRECO(uso.PLANO_PADRAO) == 0.0

    def test_a_entrada_e_paga(self):
        from api import uso
        assert cobranca.PRECO(uso.A_VENDA[0]) > 0

    def test_os_outros_tem(self):
        assert cobranca.PRECO("freelancer") > 0
        assert cobranca.PRECO("agency") > cobranca.PRECO("studio")

    def test_nao_se_assina_o_sem_plano(self, conta):
        """"Sem plano" é estado, não produto: vendê-lo seria vender nada."""
        from api import uso
        with pytest.raises(cobranca.CobrancaIndisponivel):
            cobranca.assinar(conta, uso.PLANO_PADRAO)

    def test_o_dolar_nao_mexe_na_assinatura_de_ninguem(self, monkeypatch):
        """O que se cobra é decisão, não efeito colateral do câmbio: ninguém
        descobre pelo extrato que a assinatura mudou de preço."""
        from api import precos
        antes = cobranca.PRECO("studio")
        monkeypatch.setattr(precos, "DOLAR", precos.DOLAR * 1.2)
        assert cobranca.PRECO("studio") == antes

    def test_mas_o_piso_acompanha_e_avisa(self, monkeypatch):
        """Preço parado com custo subindo come a margem calado. O piso continua
        derivado do custo medido, e quando a tabela passa por baixo dele o
        sistema aponta qual plano — para alguém decidir, não para corrigir
        sozinho."""
        from api import precos, uso
        assert precos.abaixo_do_piso(uso.PLANOS) == []
        monkeypatch.setattr(precos, "DOLAR", precos.DOLAR * 5)
        assert precos.abaixo_do_piso(uso.PLANOS)

    def test_a_entrada_custa_o_que_foi_decidido(self):
        """R$ 890 é decisão de negócio: conta pequena dá o mesmo atendimento
        que conta grande."""
        assert cobranca.PRECO("basic") == 890.0

    def test_a_margem_pretendida_e_entregue(self):
        from api import precos, uso
        for plano in ("freelancer", "studio", "agency"):
            c = precos.conta(uso.PLANOS[plano]["pecas"], cobranca.PRECO(plano))
            assert c["margem_pct"] >= precos.MARGEM_ALVO * 100


class TestOCustoQueNaoEPorPeca:
    """Servidor e ferramentas existem com zero cliente. Eles não entram no
    preço de cada plano — entram na conta de quantos clientes o mês precisa."""

    def test_a_margem_de_80_vale_em_todos_os_planos(self):
        from api import precos, uso
        assert precos.MARGEM_ALVO == 0.80
        for plano in uso.A_VENDA:
            c = precos.conta(uso.PLANOS[plano]["pecas"], cobranca.PRECO(plano))
            assert c["margem_pct"] >= 80.0, (plano, c["margem_pct"])

    def test_a_hora_de_quem_atende_nao_e_cobrada_duas_vezes(self):
        """Somar a hora ao custo e pedir margem em cima dela cobra a mesma hora
        duas vezes — e o plano de entrada iria a R$ 1.900."""
        from api import precos
        assert precos.ATENDIMENTO_MES == 0.0

    def test_o_custo_fixo_e_a_soma_do_que_sai_sem_cliente(self):
        from api import precos
        assert precos.custo_fixo_mes() == (precos.SERVIDOR_MES
                                           + precos.FERRAMENTAS_MES
                                           + precos.ATENDIMENTO_MES)

    def test_o_equilibrio_diz_quantos_clientes_o_mes_precisa(self):
        """Margem em porcentagem não paga servidor: cliente paga."""
        from api import precos, uso
        eq = precos.ponto_de_equilibrio(uso.PLANOS)
        assert eq["custo_fixo_mes"] == precos.custo_fixo_mes()
        for plano in uso.A_VENDA:
            assert eq["contas_para_empatar"][plano] >= 1

    def test_servidor_mais_caro_pede_mais_cliente_e_nao_mais_preco(self, monkeypatch):
        from api import precos, uso
        antes = precos.ponto_de_equilibrio(uso.PLANOS)["contas_para_empatar"]["basic"]
        preco_antes = cobranca.PRECO("basic")
        monkeypatch.setattr(precos, "SERVIDOR_MES", precos.SERVIDOR_MES * 10)
        assert precos.ponto_de_equilibrio(uso.PLANOS)["contas_para_empatar"]["basic"] > antes
        assert cobranca.PRECO("basic") == preco_antes

    def test_a_sobra_de_um_cliente_e_o_que_paga_o_fixo(self):
        from api import precos, uso
        n = uso.PLANOS["basic"]["pecas"]
        sobra = precos.sobra_de(n, cobranca.PRECO("basic"))
        c = precos.conta(n, cobranca.PRECO("basic"))
        assert round(sobra, 2) == c["margem"]


class TestADesligarAAreia:
    """`ASAAS_AREIA=0` tem que significar o que diz: qualquer valor contava
    como ligado, e desligar escrevendo zero deixava a cobrança de mentira com
    cara de produção — tudo responde 200 e ninguém paga."""

    def test_vazio_e_producao(self, monkeypatch):
        monkeypatch.delenv("ASAAS_AREIA", raising=False)
        assert cobranca.base() == cobranca.PRODUCAO

    def test_zero_e_nao_contam_como_desligado(self, monkeypatch):
        for valor in ("0", "nao", "não", "false", ""):
            monkeypatch.setenv("ASAAS_AREIA", valor)
            assert cobranca.base() == cobranca.PRODUCAO, valor

    def test_ligado_fala_com_a_areia(self, monkeypatch):
        monkeypatch.setenv("ASAAS_AREIA", "1")
        assert cobranca.base() == cobranca.AREIA

    def test_a_saude_denuncia_cobranca_de_mentira(self, monkeypatch):
        from fastapi.testclient import TestClient
        from api import main
        monkeypatch.setenv("ASAAS_AREIA", "1")
        assert "mentira" in TestClient(main.app).get("/saude").json()["cobranca"]
