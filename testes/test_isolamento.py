"""Um cliente não alcança o que é do outro.

Antes das contas, quem chegasse à porta criava trabalho e todos viviam na
mesma pasta. Estes testes existem para que isso não volte por descuido: cada
endereço que fala de trabalho é tentado sem credencial e com a credencial da
conta errada.
"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image


class FilaEspia:
    def __init__(self):
        self.pedidos = []

    def enfileirar(self, fn, *args, fila="", **kwargs):
        self.pedidos.append((fn.__name__, args))
        return f"espiado-{len(self.pedidos)}"


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("REPLICAI_SEGREDO", "segredo-de-teste")
    monkeypatch.delenv("REDIS_URL", raising=False)
    import importlib
    from api import contas, main, trabalhos
    importlib.reload(trabalhos)
    importlib.reload(main)
    main.FILA = FilaEspia()
    return main, contas


def cliente_de(servidor, nome, email):
    main, contas = servidor
    conta = contas.criar(nome, email, "senha-bem-comprida")
    chave = contas.nova_chave(conta)
    c = TestClient(main.app, headers={"Authorization": f"Bearer {chave}"})
    c.conta = conta
    return c


def arte():
    buf = io.BytesIO()
    Image.new("RGB", (1200, 1200), (12, 42, 102)).save(buf, "PNG")
    buf.seek(0)
    return buf


def criar_trabalho(c):
    r = c.post("/jobs", files={"arte": ("a.png", arte(), "image/png")},
               data={"formatos": "ig-feed-1x1", "headline": "Oi"})
    assert r.status_code == 202, r.text
    return r.json()["job"]


ENDERECOS = [
    ("get", "/jobs/{job}"),
    ("get", "/jobs/{job}/zip"),
    ("get", "/jobs/{job}/arquivos/arte.png"),
    ("post", "/jobs/{job}/animar"),
    ("post", "/jobs/{job}/prancheta"),
]


class TestSemCredencial:
    @pytest.mark.parametrize("metodo,rota", ENDERECOS)
    def test_nenhum_endereco_de_trabalho_responde(self, servidor, metodo, rota):
        main, _ = servidor
        dono = cliente_de(servidor, "Dono", "dono@exemplo.com")
        job = criar_trabalho(dono)
        anonimo = TestClient(main.app)
        alvo = rota.format(job=job)
        r = (anonimo.get(alvo) if metodo == "get"
             else anonimo.post(alvo, data={"nome": "x"}))
        assert r.status_code == 401, f"{metodo} {rota} respondeu {r.status_code}"

    def test_nem_criar_trabalho(self, servidor):
        main, _ = servidor
        anonimo = TestClient(main.app)
        r = anonimo.post("/jobs", files={"arte": ("a.png", arte(), "image/png")},
                         data={"formatos": "ig-feed-1x1", "headline": "Oi"})
        assert r.status_code == 401

    def test_nem_listar(self, servidor):
        main, _ = servidor
        assert TestClient(main.app).get("/jobs").status_code == 401

    def test_a_saude_continua_aberta(self, servidor):
        """Sem ela não dá para monitorar o serviço."""
        main, _ = servidor
        assert TestClient(main.app).get("/saude").status_code == 200


class TestContaErrada:
    @pytest.mark.parametrize("metodo,rota", ENDERECOS)
    def test_o_trabalho_do_outro_nao_existe_para_mim(self, servidor, metodo, rota):
        dono = cliente_de(servidor, "Dono", "dono@exemplo.com")
        outro = cliente_de(servidor, "Outro", "outro@exemplo.com")
        job = criar_trabalho(dono)
        alvo = rota.format(job=job)
        r = (outro.get(alvo) if metodo == "get"
             else outro.post(alvo, data={"nome": "x"}))
        assert r.status_code == 404, f"{metodo} {rota} respondeu {r.status_code}"

    def test_a_lista_so_traz_o_que_e_meu(self, servidor):
        dono = cliente_de(servidor, "Dono", "dono@exemplo.com")
        outro = cliente_de(servidor, "Outro", "outro@exemplo.com")
        meu = criar_trabalho(dono)
        seu = criar_trabalho(outro)
        assert [t["job"] for t in dono.get("/jobs").json()["trabalhos"]] == [meu]
        assert [t["job"] for t in outro.get("/jobs").json()["trabalhos"]] == [seu]

    def test_o_arquivo_do_outro_nao_vem(self, servidor, tmp_path):
        dono = cliente_de(servidor, "Dono", "dono@exemplo.com")
        outro = cliente_de(servidor, "Outro", "outro@exemplo.com")
        job = criar_trabalho(dono)
        assert (tmp_path / dono.conta.id / job / "arte.png").exists()
        assert outro.get(f"/jobs/{job}/arquivos/arte.png").status_code == 404


class TestChave:
    def test_chave_revogada_para_de_entrar(self, servidor):
        main, contas = servidor
        c = cliente_de(servidor, "Dono", "dono@exemplo.com")
        assert c.get("/eu").status_code == 200
        contas.revogar(c.conta, c.conta.chaves[-1]["id"])
        assert c.get("/eu").status_code == 401

    def test_chave_inventada_nao_entra(self, servidor):
        main, _ = servidor
        c = TestClient(main.app, headers={"Authorization": "Bearer rpl_inventada"})
        assert c.get("/eu").status_code == 401

    def test_a_chave_aparece_uma_vez_e_some(self, servidor):
        c = cliente_de(servidor, "Dono", "dono@exemplo.com")
        nova = c.post("/eu/chaves", data={"apelido": "servidor"}).json()
        assert nova["chave"].startswith("rpl_")
        # a partir daqui, nenhum endereço devolve o valor
        assert nova["chave"] not in c.get("/eu").text


class TestSessaoDaTela:
    def test_entrar_devolve_biscoito_que_autentica(self, servidor):
        main, contas = servidor
        contas.criar("Dono", "dono@exemplo.com", "senha-bem-comprida")
        c = TestClient(main.app)
        assert c.post("/entrar", data={"email": "dono@exemplo.com",
                                       "senha": "senha-bem-comprida"}).status_code == 200
        assert c.get("/eu").status_code == 200

    def test_senha_errada_nao_abre_sessao(self, servidor):
        main, contas = servidor
        contas.criar("Dono", "dono@exemplo.com", "senha-bem-comprida")
        c = TestClient(main.app)
        r = c.post("/entrar", data={"email": "dono@exemplo.com", "senha": "outra"})
        assert r.status_code == 401
        assert c.get("/eu").status_code == 401

    def test_a_resposta_nao_diz_se_o_email_existe(self, servidor):
        main, contas = servidor
        contas.criar("Dono", "dono@exemplo.com", "senha-bem-comprida")
        c = TestClient(main.app)
        a = c.post("/entrar", data={"email": "dono@exemplo.com", "senha": "errada"})
        b = c.post("/entrar", data={"email": "ninguem@exemplo.com", "senha": "errada"})
        assert a.status_code == b.status_code and a.json() == b.json()

    def test_sair_derruba_a_sessao(self, servidor):
        main, contas = servidor
        contas.criar("Dono", "dono@exemplo.com", "senha-bem-comprida")
        c = TestClient(main.app)
        c.post("/entrar", data={"email": "dono@exemplo.com", "senha": "senha-bem-comprida"})
        c.post("/sair")
        assert c.get("/eu").status_code == 401


class TestPlanoNaPorta:
    """Barrar antes de enfileirar: recusar um trabalho já renderizado é gastar
    o custo e não poder cobrar."""

    def test_estourar_o_plano_recusa_o_trabalho(self, servidor):
        from api import uso
        c = cliente_de(servidor, "Dono", "dono@exemplo.com")
        for _ in range(uso.limites("teste")["pecas"]):
            uso.registrar(c.conta.id, uso.PECA)
        r = c.post("/jobs", files={"arte": ("a.png", arte(), "image/png")},
                   data={"formatos": "ig-feed-1x1", "headline": "Oi"})
        assert r.status_code == 402
        assert "peças por mês" in r.json()["detail"]

    def test_o_trabalho_recusado_nao_entra_na_fila(self, servidor):
        from api import uso
        main, _ = servidor
        c = cliente_de(servidor, "Dono", "dono@exemplo.com")
        for _ in range(uso.limites("teste")["pecas"]):
            uso.registrar(c.conta.id, uso.PECA)
        c.post("/jobs", files={"arte": ("a.png", arte(), "image/png")},
               data={"formatos": "ig-feed-1x1", "headline": "Oi"})
        assert main.FILA.pedidos == []

    def test_o_uso_de_um_nao_conta_para_o_outro(self, servidor):
        from api import uso
        um = cliente_de(servidor, "Um", "um@exemplo.com")
        dois = cliente_de(servidor, "Dois", "dois@exemplo.com")
        for _ in range(uso.limites("teste")["pecas"]):
            uso.registrar(um.conta.id, uso.PECA)
        assert um.get("/eu/uso").json()["resta"]["pecas"] == 0
        assert dois.get("/eu/uso").json()["resta"]["pecas"] == uso.limites("teste")["pecas"]
        r = dois.post("/jobs", files={"arte": ("a.png", arte(), "image/png")},
                      data={"formatos": "ig-feed-1x1", "headline": "Oi"})
        assert r.status_code == 202

    def test_o_uso_so_sai_para_o_dono(self, servidor):
        from api import uso
        um = cliente_de(servidor, "Um", "um@exemplo.com")
        uso.registrar(um.conta.id, uso.PECA, job="segredo-do-um")
        dois = cliente_de(servidor, "Dois", "dois@exemplo.com")
        assert dois.get("/eu/uso/eventos").json()["eventos"] == []

    def test_o_relatorio_traz_a_lista_e_nao_so_o_numero(self, servidor):
        from api import uso
        c = cliente_de(servidor, "Um", "um@exemplo.com")
        uso.registrar(c.conta.id, uso.PECA, job="j1", formato="ig-stories")
        eventos = c.get("/eu/uso/eventos").json()["eventos"]
        assert eventos[0]["formato"] == "ig-stories" and eventos[0]["job"] == "j1"
