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
        """O Basic (80 peças, R$ 890) saiu: deixava R$ 345 depois do custo fixo
        e dava o mesmo atendimento de uma conta grande. A entrada agora é o
        Freelancer."""
        from api import uso
        assert uso.A_VENDA[0] == "freelancer"
        assert cobranca.PRECO("freelancer") == 1990.0
        assert "basic" not in uso.PLANOS

    def test_a_margem_pretendida_e_entregue(self):
        from api import precos, uso
        for plano in ("freelancer", "studio", "agency"):
            c = precos.conta(uso.PLANOS[plano]["pecas"], cobranca.PRECO(plano))
            assert c["margem_pct"] >= precos.MARGEM_ALVO * 100


class TestOCustoQueNaoEPorPeca:
    """Servidor e ferramentas existem com zero cliente. Eles não entram no
    preço de cada plano — entram na conta de quantos clientes o mês precisa."""

    def test_todo_plano_entrega_mais_que_o_piso(self):
        """Os preços são decisão dela; o piso é o alarme. Ele tem que ficar
        ABAIXO do que a tabela entrega, senão toca no primeiro centavo de
        variação do dólar e vira ruído."""
        from api import precos, uso
        for plano in uso.A_VENDA:
            c = precos.conta(uso.PLANOS[plano]["pecas"], cobranca.PRECO(plano))
            assert c["margem_pct"] > precos.MARGEM_ALVO * 100, (plano, c["margem_pct"])

    def test_a_margem_entregue_nao_cai_abaixo_de_tres_quartos(self):
        """Abaixo disso não é mais o mesmo negócio, e a conversa tem que
        acontecer de propósito — não por um preço mexido sem olhar a conta."""
        from api import precos, uso
        for plano in uso.A_VENDA:
            c = precos.conta(uso.PLANOS[plano]["pecas"], cobranca.PRECO(plano))
            assert c["margem_pct"] >= 75.0, (plano, c["margem_pct"])

    def test_a_hora_de_quem_atende_nao_e_cobrada_duas_vezes(self):
        """Somar a hora ao custo e pedir margem em cima dela cobra a mesma hora
        duas vezes — e o plano de entrada iria a R$ 1.900."""
        from api import precos
        assert precos.ATENDIMENTO_MES == 0.0

    def test_o_custo_fixo_e_a_soma_do_que_sai_sem_cliente(self):
        from api import precos
        assert precos.custo_fixo_mes() == (precos.SERVIDOR_MES
                                           + precos.FERRAMENTAS_MES
                                           + precos.ATENDIMENTO_MES
                                           + precos.higgsfield_mes())

    def test_o_plano_do_generativo_e_custo_fixo(self):
        """Ele cobra por mês, com ou sem cliente, e o crédito não acumula."""
        from api import precos
        assert precos.higgsfield_mes() > 0
        assert precos.custo_fixo_mes() > precos.SERVIDOR_MES + precos.FERRAMENTAS_MES

    def test_o_plano_diz_quantas_peças_cobre(self):
        """Acima disso o fundo passa a custar crédito avulso — é o momento de
        comparar planos, e quem avisa é este número."""
        from api import precos
        cobre = precos.pecas_do_plano_generativo()
        gastos = cobre * precos.FUNDOS_POR_PECA * precos.CREDITOS_POR_FUNDO
        assert gastos <= precos.HIGGSFIELD_CREDITOS
        assert (cobre + 1) * precos.FUNDOS_POR_PECA * precos.CREDITOS_POR_FUNDO \
            > precos.HIGGSFIELD_CREDITOS

    def test_o_equilibrio_diz_quantos_clientes_o_mes_precisa(self):
        """Margem em porcentagem não paga servidor: cliente paga."""
        from api import precos, uso
        eq = precos.ponto_de_equilibrio(uso.PLANOS)
        assert eq["custo_fixo_mes"] == round(precos.custo_fixo_mes(), 2)
        for plano in uso.A_VENDA:
            assert eq["contas_para_empatar"][plano] >= 1

    def test_servidor_mais_caro_pede_mais_cliente_e_nao_mais_preco(self, monkeypatch):
        from api import precos, uso
        antes = precos.ponto_de_equilibrio(uso.PLANOS)["contas_para_empatar"]["freelancer"]
        preco_antes = cobranca.PRECO("freelancer")
        monkeypatch.setattr(precos, "SERVIDOR_MES", precos.SERVIDOR_MES * 10)
        assert precos.ponto_de_equilibrio(uso.PLANOS)["contas_para_empatar"]["freelancer"] > antes
        assert cobranca.PRECO("freelancer") == preco_antes

    def test_a_sobra_de_um_cliente_e_o_que_paga_o_fixo(self):
        from api import precos, uso
        n = uso.PLANOS["freelancer"]["pecas"]
        sobra = precos.sobra_de(n, cobranca.PRECO("freelancer"))
        c = precos.conta(n, cobranca.PRECO("freelancer"))
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


class TestOCustosEscritoNaoMente:
    """`CUSTOS.md` é o papel que a Ligia lê para decidir. Número escrito à mão
    num documento envelhece calado — este teste casa o documento com o código,
    e quebra na esteira quando um dos dois mudar sozinho."""

    def _papel(self):
        from pathlib import Path
        return Path("CUSTOS.md").read_text(encoding="utf-8")

    def test_o_custo_fixo_bate_com_o_codigo(self):
        from api import precos
        assert f"R$ {precos.custo_fixo_mes():.0f}/mês" in self._papel()

    def test_o_servidor_escolhido_bate(self):
        from api import precos
        assert f"R$ {precos.SERVIDOR_MES:.0f}/mês" in self._papel()

    def test_os_precos_dos_planos_batem(self):
        from api import uso
        papel = self._papel()
        for plano in uso.A_VENDA:
            preco = cobranca.PRECO(plano)
            escrito = f"R$ {preco:,.0f}".replace(",", ".")
            assert escrito in papel, (plano, escrito)

    def test_as_franquias_e_os_acessos_batem(self):
        from api import uso
        papel = self._papel()
        for plano in uso.A_VENDA:
            lim = uso.PLANOS[plano]
            assert lim["nome"] in papel
            assert str(lim["videos"]) in papel
            assert str(lim["acessos"]) in papel

    def test_o_custo_por_peca_bate(self):
        from api import precos
        assert f"R$ {precos.custo_peca():.3f}".replace(".", ",") in self._papel()

    def test_o_que_ainda_e_premissa_esta_marcado(self):
        """Quem lê precisa saber qual número foi medido e qual foi suposto."""
        papel = self._papel()
        assert "premissa" in papel.lower()
        assert "8%" in papel and "contabilidade" in papel


class TestAAberturaPorPlanoBate:
    """A tabela de um cliente de cada plano é o que ela olha para decidir. O
    jeito de ela ficar errada é o código mudar e o papel não."""

    def _papel(self):
        from pathlib import Path
        return Path("CUSTOS.md").read_text(encoding="utf-8")

    def _reais(self, v):
        return f"R$ {v:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")

    def _conta(self, plano):
        """A mesma conta do documento: um cliente, franquia inteira, 8 GB."""
        from api import precos, uso
        n = uso.PLANOS[plano]["pecas"]
        preco = cobranca.PRECO(plano)
        k = precos.DOLAR * (1 + precos.IOF_E_SPREAD)
        creditos = n * precos.FUNDOS_POR_PECA * precos.CREDITOS_POR_FUNDO
        extra = max(0, creditos - precos.HIGGSFIELD_CREDITOS)
        fixo = (precos.custo_fixo_mes() - precos.SERVIDOR_MES
                + precos.SERVIDOR_8GB_MES)
        itens = {"anthropic": n * precos.MODELO_POR_PECA * k,
                 "fundo": extra * precos.DOLAR_POR_CREDITO * k,
                 "imposto": preco * precos.IMPOSTO,
                 "gateway": preco * precos.GATEWAY,
                 "fixo": fixo}
        itens["sobra"] = preco - sum(v for c, v in itens.items())
        return itens

    def test_cada_item_de_cada_plano_bate(self):
        from api import uso
        papel = self._papel()
        for plano in uso.A_VENDA:
            for conta, valor in self._conta(plano).items():
                if conta == "fundo" and valor == 0:
                    continue          # aparece como "—", e não como R$ 0,00
                assert self._reais(valor) in papel, (plano, conta, self._reais(valor))

    def test_a_sobra_de_um_cliente_bate(self):
        from api import uso
        papel = self._papel()
        for plano in uso.A_VENDA:
            assert self._reais(self._conta(plano)["sobra"]) in papel, plano

    def test_o_documento_nao_fala_em_modelo(self):
        """"Modelo" e "fundo além do plano" eram jargão meu: ela leu e não
        entendeu, que é o teste que vale."""
        papel = self._papel()
        assert "leitura e diagramação" in papel
        assert "modelo que compõe" not in papel

    def test_o_que_o_plano_de_creditos_cobre_bate(self):
        from api import precos
        assert f"cobre **{precos.pecas_do_plano_generativo()} peças**" in self._papel()
