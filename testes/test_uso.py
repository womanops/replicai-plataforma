"""O que cada cliente consumiu.

O custo é por peça: uma conta que roda mil peças custa cem vezes mais do que
uma que roda dez. Contar é o que permite cobrar por volume — e barrar antes de
gastar é o que impede renderizar de graça.
"""
import json

import pytest

from api import uso


@pytest.fixture(autouse=True)
def disco(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    import importlib
    from api import trabalhos
    importlib.reload(trabalhos)


CONTA = "cliente-um"


class TestRegistro:
    def test_uma_linha_por_consumo(self, tmp_path):
        uso.registrar(CONTA, uso.PECA, job="j1", formato="ig-stories")
        uso.registrar(CONTA, uso.PECA, job="j1", formato="ig-feed-1x1")
        linhas = uso.arquivo(CONTA).read_text().strip().splitlines()
        assert len(linhas) == 2
        assert json.loads(linhas[0])["formato"] == "ig-stories"

    def test_o_registro_diz_se_gravou(self):
        """Faturamento que some calado é a pior queda calada: o cliente usa,
        ninguém cobra, e nada denuncia."""
        assert uso.registrar(CONTA, uso.PECA)["gravado"] is True
        ruim = uso.registrar("c1", uso.PECA)       # identificador curto demais
        assert ruim["gravado"] is False and "porque" in ruim

    def test_linha_quebrada_nao_derruba_o_relatorio(self):
        uso.registrar(CONTA, uso.PECA, job="j1")
        with open(uso.arquivo(CONTA), "a") as f:
            f.write("{isto não é json\n")
        uso.registrar(CONTA, uso.PECA, job="j2")
        assert len(uso.eventos(CONTA)) == 2


class TestResumo:
    def test_soma_por_tipo(self):
        uso.registrar(CONTA, uso.PECA, job="j1", dolares=0.04)
        uso.registrar(CONTA, uso.PECA, job="j2", dolares=0.04)
        uso.registrar(CONTA, uso.VIDEO, job="j1")
        uso.registrar(CONTA, uso.FUNDO, job="j1", quantas=3)
        r = uso.resumo(CONTA)
        assert (r["pecas"], r["videos"], r["fundos_generativos"]) == (2, 1, 3)
        assert r["custo_dolares"] == pytest.approx(0.08)
        assert r["trabalhos"] == 2

    def test_mes_sem_nada_e_zero(self):
        assert uso.resumo(CONTA, "2020-01")["pecas"] == 0

    def test_cada_mes_no_seu_arquivo(self):
        uso.registrar(CONTA, uso.PECA)
        assert uso.meses(CONTA) == [uso._mes()]


class TestPlano:
    def test_cabe_enquanto_nao_estoura(self):
        for _ in range(10):
            uso.registrar(CONTA, uso.PECA)
        assert uso.cabe(CONTA, "teste", pecas=5)[0] is True

    def test_nao_cabe_e_diz_o_numero(self):
        for _ in range(28):
            uso.registrar(CONTA, uso.PECA)
        pode, porque = uso.cabe(CONTA, "teste", pecas=5)
        assert pode is False
        assert "30 peças" in porque and "33" in porque

    def test_video_tem_limite_proprio(self):
        for _ in range(5):
            uso.registrar(CONTA, uso.VIDEO)
        assert uso.cabe(CONTA, "teste", videos=1)[0] is False
        assert uso.cabe(CONTA, "teste", pecas=1)[0] is True

    def test_plano_maior_cabe_mais(self):
        for _ in range(100):
            uso.registrar(CONTA, uso.PECA)
        assert uso.cabe(CONTA, "teste", pecas=1)[0] is False
        assert uso.cabe(CONTA, "estudio", pecas=1)[0] is True

    def test_plano_desconhecido_cai_no_mais_apertado(self):
        """Plano torto não pode virar uso ilimitado."""
        assert uso.limites("inventado") == uso.limites(uso.PLANO_PADRAO)


class TestNaEsteira:
    """Contar e não ser chamado é o defeito recorrente deste projeto. Aqui ele
    custaria faturamento: o cliente usa, ninguém cobra, nada denuncia."""

    @pytest.fixture
    def esteira(self, tmp_path, monkeypatch):
        from PIL import Image
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        import importlib
        from api import tarefas, trabalhos
        importlib.reload(trabalhos)
        monkeypatch.setattr(tarefas, "trabalhos", trabalhos)

        class Serve:
            def compor(self, base, formato_id, brief="", terreno=None):
                return {"canvas": {"w": 100, "h": 100},
                        "fundo": {"tipo": "cor", "cor": "#000"},
                        "elementos": [], "saida": f"{formato_id}.png"}

        import api.pipeline as pl
        monkeypatch.setattr(pl, "render_peca", lambda a, d: d.write_bytes(b"x"))
        monkeypatch.setattr(tarefas, "compositor", lambda *a: Serve())
        monkeypatch.setattr(tarefas, "leitor", lambda: None)

        arte = tmp_path / "arte.png"
        Image.new("RGB", (1920, 1080), "#0a1a55").save(arte)
        return tarefas, trabalhos, arte

    def test_cada_peca_entregue_vira_consumo(self, esteira):
        tarefas, trabalhos, arte = esteira
        job = trabalhos.novo_id("x")
        tarefas.processar(CONTA, job, str(arte), ["ig-feed-1x1", "ig-stories"],
                          "Oi", "", "")
        r = uso.resumo(CONTA)
        assert r["pecas"] == 2
        formatos = {e.get("formato") for e in uso.eventos(CONTA)
                    if e["tipo"] == uso.PECA}
        assert formatos == {"ig-feed-1x1", "ig-stories"}

    def test_o_consumo_e_da_conta_certa(self, esteira):
        tarefas, trabalhos, arte = esteira
        tarefas.processar("cliente-dois", trabalhos.novo_id("x"), str(arte),
                          ["ig-feed-1x1"], "Oi", "", "")
        assert uso.resumo(CONTA)["pecas"] == 0
        assert uso.resumo("cliente-dois")["pecas"] == 1

    def test_formato_que_falhou_nao_e_cobrado(self, esteira, monkeypatch):
        """Cobrar por peça que não saiu é cobrar por nada."""
        tarefas, trabalhos, arte = esteira
        import api.pipeline as pl

        def so_um(arq, destino):
            if "stories" in str(destino):
                raise RuntimeError("o Chrome não abriu")
            destino.write_bytes(b"x")

        monkeypatch.setattr(pl, "render_peca", so_um)
        tarefas.processar(CONTA, trabalhos.novo_id("x"), str(arte),
                          ["ig-feed-1x1", "ig-stories"], "Oi", "", "")
        assert uso.resumo(CONTA)["pecas"] == 1
