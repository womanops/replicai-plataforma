"""Do clique em "assinar" até a pessoa produzindo a primeira peça.

É o caminho que ninguém da equipe percorre no dia a dia — quem desenvolve já
tem conta — e por isso é o que quebra sem ninguém ver. Cada teste aqui é um
degrau desse caminho, na ordem em que o cliente passa por eles:

    escolhe o plano → conta trancada nasce → paga no Asaas → aviso de aprovação
    → convite por e-mail → cria a senha → entra → produz

A regra que vale em todos: **nada de acesso antes da aprovação do pagamento**, e
nenhum e-mail leva senha escrita.
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def plataforma(tmp_path, monkeypatch):
    """A plataforma com o Asaas e o correio trocados por falsos."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("REPLICAI_SEGREDO", "segredo-de-teste")
    monkeypatch.setenv("ASAAS_AVISO_TOKEN", "segredo-do-aviso")
    monkeypatch.delenv("REDIS_URL", raising=False)
    from api import cobranca, contas, correio, main, trabalhos
    importlib.reload(trabalhos)
    importlib.reload(main)

    pedidos, cartas = [], []

    def asaas_falso(metodo, caminho, corpo=None):
        pedidos.append((metodo, caminho, corpo))
        if caminho == "/customers":
            return {"id": "cus_1"}
        if caminho == "/subscriptions":
            return {"id": "sub_1"}
        if caminho.endswith("/payments"):
            return {"data": [{"status": "PENDING", "id": "pay_1",
                              "invoiceUrl": "https://asaas.exemplo/pay_1"}]}
        return {}

    def correio_falso(para, assunto, texto):
        cartas.append({"para": para, "assunto": assunto, "texto": texto})
        return {"enviado": True, "id": f"em_{len(cartas)}"}

    monkeypatch.setattr(cobranca, "chamar", asaas_falso)
    monkeypatch.setattr(correio, "enviar", correio_falso)
    monkeypatch.setattr(correio, "painel", lambda: "https://app.exemplo.teste")

    c = TestClient(main.app)
    c.pedidos, c.cartas, c.contas, c.main = pedidos, cartas, contas, main
    return c


def contratar(c, plano="agency", email="dona@agencia.com", **extra):
    dados = {"plano": plano, "empresa": "Agência Teste", "email": email,
             "cpf_cnpj": "12.345.678/0001-90", **extra}
    return c.post("/assinatura", data=dados)


def convite_do_email(carta: str) -> str:
    """O convite que foi para o e-mail, como a pessoa o recebe."""
    for pedaco in carta.split():
        if "convite=" in pedaco:
            return pedaco.split("convite=")[1]
    raise AssertionError(f"não achei convite nesta carta:\n{carta}")


def aprovar(c, conta_id: str, plano: str = "agency"):
    return c.post("/cobranca/aviso",
                  headers={"asaas-access-token": "segredo-do-aviso"},
                  json={"event": "PAYMENT_CONFIRMED", "id": f"evt-{conta_id}",
                        "payment": {"customer": "cus_1", "dueDate": "2026-11-10",
                                    "externalReference": f"{conta_id}:{plano}"}})


class TestAContratacao:
    def test_a_contratacao_devolve_onde_pagar(self, plataforma):
        r = contratar(plataforma)
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["pagamento"] == "https://asaas.exemplo/pay_1"
        assert d["valor"] > 0
        assert "por e-mail" in d["aviso"]

    def test_a_conta_nasce_trancada(self, plataforma):
        """Sem senha e sem plano: ela existe para a cobrança ter dono."""
        d = contratar(plataforma).json()
        conta = plataforma.contas.por_id(d["conta"])
        assert conta.senha == ""
        assert conta.plano == "sem"
        assert conta.plano_pedido == "agency"

    def test_nada_de_e_mail_antes_de_pagar(self, plataforma):
        """Mandar o acesso no clique é dar o sistema a quem não pagou."""
        contratar(plataforma)
        assert plataforma.cartas == []

    def test_nao_se_entra_com_a_conta_recem_criada(self, plataforma):
        contratar(plataforma)
        r = plataforma.post("/entrar", data={"email": "dona@agencia.com",
                                             "senha": "qualquer-senha-aqui"})
        assert r.status_code == 401

    def test_plano_que_nao_esta_a_venda_e_recusado(self, plataforma):
        assert contratar(plataforma, plano="sem").status_code == 422
        assert contratar(plataforma, plano="inventado").status_code == 422

    def test_sem_documento_nao_da_porque_a_nota_exige(self, plataforma):
        r = plataforma.post("/assinatura", data={
            "plano": "basic", "empresa": "X", "email": "x@y.com", "cpf_cnpj": "  "})
        assert r.status_code == 422
        assert "nota fiscal" in r.json()["detail"]

    def test_o_mesmo_e_mail_nao_assina_duas_vezes(self, plataforma):
        contratar(plataforma)
        assert contratar(plataforma).status_code == 422

    def test_o_financeiro_fica_guardado_separado(self, plataforma):
        """Quem paga não é quem usa: a nota vai para um, o acesso para o outro."""
        d = contratar(plataforma, email_financeiro="financeiro@agencia.com").json()
        assert plataforma.contas.por_id(d["conta"]).email_financeiro \
            == "financeiro@agencia.com"


class TestOAcessoNasceDaAprovacao:
    def test_a_aprovacao_libera_o_plano_e_manda_o_convite(self, plataforma):
        d = contratar(plataforma).json()
        r = aprovar(plataforma, d["conta"])
        assert r.status_code == 200, r.text
        conta = plataforma.contas.por_id(d["conta"])
        assert conta.plano == "agency"
        assert conta.pago_ate
        assert len(plataforma.cartas) == 1
        assert plataforma.cartas[0]["para"] == "dona@agencia.com"

    def test_o_e_mail_nao_leva_senha(self, plataforma):
        """E-mail fica guardado para sempre na caixa de entrada de quem recebeu."""
        d = contratar(plataforma).json()
        aprovar(plataforma, d["conta"])
        carta = plataforma.cartas[0]["texto"]
        assert "senha" in carta.lower()          # fala de senha
        assert "/senha?convite=" in carta        # mas o que vai é o link
        conta = plataforma.contas.por_id(d["conta"])
        assert conta.senha == ""                 # e ela ainda não existe

    def test_o_convite_cria_a_senha_e_ja_entra(self, plataforma):
        d = contratar(plataforma).json()
        aprovar(plataforma, d["conta"])
        convite = convite_do_email(plataforma.cartas[0]["texto"])
        r = plataforma.post("/senha", data={"convite": convite,
                                            "senha": "senha-da-dona-1"})
        assert r.status_code == 200, r.text
        assert r.cookies.get("replicai_sessao")
        assert plataforma.get("/eu").json()["email"] == "dona@agencia.com"

    def test_o_convite_serve_uma_vez_so(self, plataforma):
        d = contratar(plataforma).json()
        aprovar(plataforma, d["conta"])
        convite = convite_do_email(plataforma.cartas[0]["texto"])
        plataforma.post("/senha", data={"convite": convite, "senha": "senha-da-dona-1"})
        r = plataforma.post("/senha", data={"convite": convite, "senha": "outra-senha-aqui"})
        assert r.status_code == 410

    def test_convite_vencido_nao_abre(self, plataforma, monkeypatch):
        d = contratar(plataforma).json()
        aprovar(plataforma, d["conta"])
        convite = convite_do_email(plataforma.cartas[0]["texto"])
        conta = plataforma.contas.por_id(d["conta"])
        conta.convite_ate = "2020-01-01T00:00:00+00:00"
        plataforma.contas._gravar(conta)
        assert plataforma.post("/senha", data={"convite": convite,
                                               "senha": "senha-da-dona-1"}).status_code == 410

    def test_senha_curta_e_recusada_com_motivo(self, plataforma):
        d = contratar(plataforma).json()
        aprovar(plataforma, d["conta"])
        convite = convite_do_email(plataforma.cartas[0]["texto"])
        r = plataforma.post("/senha", data={"convite": convite, "senha": "curta"})
        assert r.status_code == 422
        assert "10 caracteres" in r.json()["detail"]

    def test_convite_inventado_nao_abre_conta_de_ninguem(self, plataforma):
        contratar(plataforma)
        assert plataforma.post("/senha", data={"convite": "x" * 43,
                                               "senha": "senha-bem-comprida"}).status_code == 410

    def test_depois_de_entrar_ela_produz(self, plataforma):
        """O fim do caminho: a franquia do plano valendo."""
        d = contratar(plataforma).json()
        aprovar(plataforma, d["conta"])
        convite = convite_do_email(plataforma.cartas[0]["texto"])
        plataforma.post("/senha", data={"convite": convite, "senha": "senha-da-dona-1"})
        u = plataforma.get("/eu/uso").json()
        assert u["plano"]["id"] == "agency"
        assert u["resta"]["pecas"] == 1200

    def test_a_segunda_aprovacao_nao_manda_convite_de_novo(self, plataforma):
        """Renovação mensal não é estreia: convite novo invalidaria a senha que
        a pessoa já usa."""
        d = contratar(plataforma).json()
        aprovar(plataforma, d["conta"])
        convite = convite_do_email(plataforma.cartas[0]["texto"])
        plataforma.post("/senha", data={"convite": convite, "senha": "senha-da-dona-1"})
        plataforma.cartas.clear()
        plataforma.post("/cobranca/aviso",
                        headers={"asaas-access-token": "segredo-do-aviso"},
                        json={"event": "PAYMENT_CONFIRMED", "id": "evt-mes-2",
                              "payment": {"customer": "cus_1", "dueDate": "2026-12-10",
                                          "externalReference": f"{d['conta']}:agency"}})
        assert plataforma.cartas == []
        assert plataforma.contas.por_id(d["conta"]).senha != ""


class TestOAtrasoAvisa:
    def test_o_atraso_manda_carta_para_o_financeiro(self, plataforma):
        """Cliente que perde acesso sem aviso liga bravo, e com razão."""
        d = contratar(plataforma, email_financeiro="financeiro@agencia.com").json()
        aprovar(plataforma, d["conta"])
        plataforma.cartas.clear()
        plataforma.post("/cobranca/aviso",
                        headers={"asaas-access-token": "segredo-do-aviso"},
                        json={"event": "PAYMENT_OVERDUE", "id": "evt-atraso",
                              "payment": {"customer": "cus_1", "dueDate": "2026-12-10",
                                          "externalReference": f"{d['conta']}:agency"}})
        assert len(plataforma.cartas) == 1
        assert plataforma.cartas[0]["para"] == "financeiro@agencia.com"
        assert "download" in plataforma.cartas[0]["texto"]

    def test_o_e_mail_fora_do_ar_nao_desfaz_o_pagamento(self, plataforma, monkeypatch):
        """O Asaas reenviaria o evento para sempre, e o plano ficaria preso."""
        from api import correio
        monkeypatch.setattr(correio, "enviar",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("caiu")))
        d = contratar(plataforma).json()
        r = aprovar(plataforma, d["conta"])
        assert r.status_code == 200
        assert plataforma.contas.por_id(d["conta"]).plano == "agency"
        assert r.json()["carta"]["enviado"] is False


class TestAsPessoasDaAgencia:
    def _dentro(self, plataforma, plano="agency"):
        d = contratar(plataforma, plano=plano).json()
        aprovar(plataforma, d["conta"], plano)
        convite = convite_do_email(plataforma.cartas[0]["texto"])
        plataforma.post("/senha", data={"convite": convite, "senha": "senha-da-dona-1"})
        plataforma.cartas.clear()
        return d["conta"]

    def test_o_agency_cabe_tres_pessoas(self, plataforma):
        self._dentro(plataforma)
        assert plataforma.post("/eu/pessoas", data={"nome": "Ana",
                                                    "email": "ana@agencia.com"}).status_code == 201
        assert plataforma.post("/eu/pessoas", data={"nome": "Bia",
                                                    "email": "bia@agencia.com"}).status_code == 201
        r = plataforma.post("/eu/pessoas", data={"nome": "Cris", "email": "cris@agencia.com"})
        assert r.status_code == 422
        assert "3 pessoas" in r.json()["detail"]

    def test_o_basic_e_de_uma_pessoa(self, plataforma):
        self._dentro(plataforma, plano="basic")
        r = plataforma.post("/eu/pessoas", data={"nome": "Ana", "email": "ana@agencia.com"})
        assert r.status_code == 422
        assert "1 pessoa" in r.json()["detail"]

    def test_a_convidada_cria_a_senha_e_trabalha_na_mesma_conta(self, plataforma):
        conta = self._dentro(plataforma)
        plataforma.post("/eu/pessoas", data={"nome": "Ana", "email": "ana@agencia.com"})
        convite = convite_do_email(plataforma.cartas[0]["texto"])
        outra = TestClient(plataforma.main.app)
        assert outra.post("/senha", data={"convite": convite,
                                          "senha": "senha-da-ana-99"}).status_code == 200
        eu = outra.get("/eu").json()
        assert eu["id"] == conta                  # mesma conta da agência
        assert eu["eu"]["nome"] == "Ana"          # pessoa diferente
        assert eu["eu"]["dono"] is False
        assert outra.get("/eu/uso").json()["plano"]["id"] == "agency"

    def test_as_duas_trabalham_ao_mesmo_tempo(self, plataforma):
        """Era a dúvida que começou isto: três pessoas conseguem trabalhar."""
        self._dentro(plataforma)
        plataforma.post("/eu/pessoas", data={"nome": "Ana", "email": "ana@agencia.com"})
        convite = convite_do_email(plataforma.cartas[0]["texto"])
        ana = TestClient(plataforma.main.app)
        ana.post("/senha", data={"convite": convite, "senha": "senha-da-ana-99"})
        # as duas sessões vivas ao mesmo tempo, nenhuma derruba a outra
        assert plataforma.get("/eu").status_code == 200
        assert ana.get("/eu").status_code == 200
        assert plataforma.get("/eu").json()["eu"]["dono"] is True
        assert ana.get("/eu").json()["eu"]["dono"] is False

    def test_o_e_mail_de_quem_ja_tem_acesso_e_recusado(self, plataforma):
        self._dentro(plataforma)
        plataforma.post("/eu/pessoas", data={"nome": "Ana", "email": "ana@agencia.com"})
        r = plataforma.post("/eu/pessoas", data={"nome": "Ana de novo",
                                                 "email": "ana@agencia.com"})
        assert r.status_code == 422
        assert "já tem acesso" in r.json()["detail"]

    def test_tirar_quem_saiu_nao_mexe_na_senha_dos_outros(self, plataforma):
        """Era o custo da senha compartilhada: alguém sai e todo mundo troca."""
        self._dentro(plataforma)
        p1 = plataforma.post("/eu/pessoas", data={"nome": "Ana",
                                                  "email": "ana@agencia.com"}).json()
        convite = convite_do_email(plataforma.cartas[0]["texto"])
        ana = TestClient(plataforma.main.app)
        ana.post("/senha", data={"convite": convite, "senha": "senha-da-ana-99"})

        r = plataforma.delete(f"/eu/pessoas/{p1['pessoa']['id']}")
        assert r.status_code == 200 and r.json()["acessos"] == 1
        # a dona continua entrando com a senha dela
        outra = TestClient(plataforma.main.app)
        assert outra.post("/entrar", data={"email": "dona@agencia.com",
                                           "senha": "senha-da-dona-1"}).status_code == 200
        # e a sessão de quem saiu deixa de valer
        assert ana.get("/eu").status_code == 401

    def test_o_dono_nao_se_remove(self, plataforma):
        self._dentro(plataforma)
        r = plataforma.delete("/eu/pessoas/dono")
        assert r.status_code == 409

    def test_ninguem_remove_o_proprio_acesso(self, plataforma):
        self._dentro(plataforma)
        plataforma.post("/eu/pessoas", data={"nome": "Ana", "email": "ana@agencia.com"})
        convite = convite_do_email(plataforma.cartas[0]["texto"])
        ana = TestClient(plataforma.main.app)
        ana.post("/senha", data={"convite": convite, "senha": "senha-da-ana-99"})
        pessoas = ana.get("/eu/pessoas").json()
        eu = pessoas["eu"]
        assert ana.delete(f"/eu/pessoas/{eu}").status_code == 409

    def test_a_lista_de_pessoas_nao_entrega_senha_nem_convite(self, plataforma):
        self._dentro(plataforma)
        plataforma.post("/eu/pessoas", data={"nome": "Ana", "email": "ana@agencia.com"})
        bruto = plataforma.get("/eu/pessoas").text
        assert "senha" not in bruto
        assert "scrypt" not in bruto
        assert "convite" not in bruto.replace("convite_ate", "")

    def test_a_lista_diz_quem_ainda_nao_entrou(self, plataforma):
        """Convite perdido é a reclamação mais comum: a tela precisa mostrar."""
        self._dentro(plataforma)
        plataforma.post("/eu/pessoas", data={"nome": "Ana", "email": "ana@agencia.com"})
        pessoas = plataforma.get("/eu/pessoas").json()["pessoas"]
        ana = next(p for p in pessoas if p["email"] == "ana@agencia.com")
        assert ana["entrou"] is False
        assert ana["convite_ate"]

    def test_o_convite_pode_ser_reenviado(self, plataforma):
        self._dentro(plataforma)
        p1 = plataforma.post("/eu/pessoas", data={"nome": "Ana",
                                                  "email": "ana@agencia.com"}).json()
        primeiro = convite_do_email(plataforma.cartas[0]["texto"])
        plataforma.cartas.clear()
        r = plataforma.post(f"/eu/pessoas/{p1['pessoa']['id']}/convite")
        assert r.status_code == 200
        segundo = convite_do_email(plataforma.cartas[0]["texto"])
        assert segundo != primeiro
        # o primeiro morre: convite antigo circulando é porta esquecida aberta
        assert plataforma.post("/senha", data={"convite": primeiro,
                                               "senha": "senha-da-ana-99"}).status_code == 410
        assert plataforma.post("/senha", data={"convite": segundo,
                                               "senha": "senha-da-ana-99"}).status_code == 200

    def test_nao_se_reenvia_convite_para_quem_ja_tem_senha(self, plataforma):
        self._dentro(plataforma)
        assert plataforma.post("/eu/pessoas/dono/convite").status_code == 409

    def test_sem_plano_nao_se_convida_gente(self, plataforma):
        """Produzir é o que o pagamento abre — e gente nova é para produzir."""
        conta = self._dentro(plataforma)
        c = plataforma.contas.por_id(conta)
        c.pago_ate = "2020-01-01"
        plataforma.contas._gravar(c)
        r = plataforma.post("/eu/pessoas", data={"nome": "Ana", "email": "ana@agencia.com"})
        assert r.status_code == 402


class TestCriarContaNaMaoEDeAdministracao:
    """O endereço ficou aberto a internet enquanto a plataforma não vendia:
    qualquer um podia encher o disco de contas vazias."""

    def test_sem_token_nao_cria(self, plataforma, monkeypatch):
        monkeypatch.setenv("REPLICAI_ADMIN_TOKEN", "so-eu-sei")
        r = plataforma.post("/contas", data={"nome": "X", "email": "x@y.com",
                                             "senha": "senha-bem-comprida"})
        assert r.status_code == 401

    def test_com_token_cria(self, plataforma, monkeypatch):
        monkeypatch.setenv("REPLICAI_ADMIN_TOKEN", "so-eu-sei")
        r = plataforma.post("/contas", headers={"x-admin": "so-eu-sei"},
                            data={"nome": "X", "email": "x@y.com",
                                  "senha": "senha-bem-comprida"})
        assert r.status_code == 201

    def test_sem_token_configurado_o_endereco_nao_funciona(self, plataforma, monkeypatch):
        monkeypatch.delenv("REPLICAI_ADMIN_TOKEN", raising=False)
        r = plataforma.post("/contas", headers={"x-admin": "chute"},
                            data={"nome": "X", "email": "x@y.com",
                                  "senha": "senha-bem-comprida"})
        assert r.status_code == 503


class TestAsPaginasExistem:
    def test_a_pagina_de_assinar_responde(self, plataforma):
        r = plataforma.get("/assinar")
        assert r.status_code == 200
        assert "Ir para o pagamento" in r.text

    def test_a_pagina_de_senha_responde(self, plataforma):
        r = plataforma.get("/senha")
        assert r.status_code == 200
        assert "Crie sua senha" in r.text

    def test_a_pagina_de_senha_nao_pede_a_senha_antiga(self, plataforma):
        """Quem chega do convite não tem senha antiga nenhuma."""
        assert "senha atual" not in plataforma.get("/senha").text.lower()
