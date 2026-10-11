"""Os três modos de desdobrar, e o ajuste na mão.

Quem sobe uma peça escolhe o quanto a plataforma pode mexer nela: só o quadro,
o quadro e a diagramação, ou também o texto. Essa escolha não existia, e a
plataforma escrevia sempre — foi assim que o Stories real saiu com a chamada e
o CTA duplicados por cima do lettering que a arte já trazia, nas mesmas
palavras, porque ninguém tinha pedido texto novo.
"""
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from testes.test_api import FilaEspia, arte_png, cliente, enviar      # noqa: F401


class TestEscolhaDoModo:
    def test_sem_modo_a_plataforma_nao_escreve(self, cliente):
        """O padrão é conservador. Entre inventar texto e não inventar, o
        erro barato é não inventar: dá para pedir de novo pedindo texto."""
        r = enviar(cliente)
        assert r.status_code == 202
        assert cliente.fila.pedidos[-1][1][-1] == "com"

    def test_so_formato_nao_exige_chamada(self, cliente):
        """Quem quer a mesma peça noutro formato não tem chamada a escrever,
        e a tela travava o começo do trabalho pedindo uma."""
        r = cliente.post("/jobs", files={"arte": ("arte.png", arte_png(), "image/png")},
                         data={"formatos": "gdn-300x250", "modo": "sem"})
        assert r.status_code == 202

    def test_texto_novo_sem_chamada_e_recusado(self, cliente):
        r = cliente.post("/jobs", files={"arte": ("arte.png", arte_png(), "image/png")},
                         data={"formatos": "gdn-300x250", "modo": "novo"})
        assert r.status_code == 422
        assert "chamada" in r.json()["detail"]

    def test_modo_inventado_e_recusado(self, cliente):
        r = enviar(cliente, modo="turbo")
        assert r.status_code == 422
        assert "turbo" in r.json()["detail"]

    def test_o_modo_chega_ate_a_fila(self, cliente):
        enviar(cliente, modo="novo")
        nome, args = cliente.fila.pedidos[-1]
        assert nome == "processar"
        assert args[-1] == "novo"

    def test_o_modo_sobrevive_a_exportacao_final(self, cliente):
        """Finalizar refaz o trabalho. Refazer com outro modo entregaria uma
        peça diferente da que foi aprovada no rascunho."""
        from api import trabalhos
        job = enviar(cliente, modo="sem").json()["job"]
        trabalhos.gravar(cliente.conta.id, job,
                         {"status": "pronto", "prontas": ["gdn-300x250"]})
        cliente.post(f"/jobs/{job}/finalizar")
        assert cliente.fila.pedidos[-1][1][-1] == "sem"


class TestQuemPreservaNaoEscreve:
    def test_a_peca_sai_sem_elemento_nenhum(self, tmp_path):
        """A peça do modo conservador é a arte reenquadrada, e só. Qualquer
        elemento aqui é texto repetido por cima do que a arte já diz."""
        from api.compositor import CompositorPreserva
        from api.pipeline import desdobrar
        base = tmp_path / "arte.png"
        Image.new("RGB", (1200, 1200), (12, 42, 102)).save(base)
        r = desdobrar(base, ["gdn-300x250"], CompositorPreserva(), tmp_path / "saida")
        montada = json.loads(
            (tmp_path / "saida" / "pecas" / "gdn-300x250.json").read_text(encoding="utf-8"))
        assert montada["elementos"] == []
        assert montada["via"] == "reenquadra"

    def test_nao_gasta_chamada_de_modelo(self, tmp_path):
        """Sem texto a escrever não há o que perguntar: nem para ler a arte.
        É o que faz este modo custar zero por peça."""
        from api.compositor import CompositorPreserva
        from api.pipeline import desdobrar
        chamou = []

        def leitor(arte):
            chamou.append(arte)
            raise AssertionError("ninguém deveria ler a arte neste modo")

        base = tmp_path / "arte.png"
        Image.new("RGB", (1200, 1200), (12, 42, 102)).save(base)
        desdobrar(base, ["gdn-300x250"], CompositorPreserva(), tmp_path / "saida",
                  leitor=leitor)
        assert chamou == []

    def test_o_fundo_nao_corta_a_arte(self, tmp_path):
        """Preservar 100% é a promessa do modo. Com `cover` a peça 1:1 vinda
        de uma 16:9 perdia as pontas — foi o "energiza" virando "energ"."""
        from api.compositor import CompositorPreserva
        from api.pipeline import desdobrar
        base = tmp_path / "arte.png"
        Image.new("RGB", (1600, 900), (12, 42, 102)).save(base)
        desdobrar(base, ["ig-feed-1x1"], CompositorPreserva(), tmp_path / "saida")
        montada = json.loads(
            (tmp_path / "saida" / "pecas" / "ig-feed-1x1.json").read_text(encoding="utf-8"))
        # o fundo é o preparado, não a arte crua servida em cover
        assert montada["fundo"]["src"] == "fundo-ig-feed-1x1.png"


class TestAjusteNaMao:
    def _com_peca(self, cliente):
        from api import trabalhos
        job = enviar(cliente, modo="com").json()["job"]
        pasta = trabalhos.pasta_do(cliente.conta.id, job)
        (pasta / "pecas").mkdir(parents=True, exist_ok=True)
        (pasta / "pecas" / "gdn-300x250.json").write_text(json.dumps({
            "formato": "gdn-300x250", "canvas": {"w": 300, "h": 250},
            "safe": {"top": 0, "bottom": 0, "left": 8, "right": 8},
            "saida": "gdn-300x250.png", "fundo": {"tipo": "cor", "cor": "#000"},
            "elementos": [{"tipo": "texto", "papel": "headline", "texto": "Oi",
                           "box": {"x": 10, "y": 10, "w": 100, "h": 40}}],
        }), encoding="utf-8")
        return job

    def test_mover_grava_a_caixa_nova_e_manda_desenhar(self, cliente):
        job = self._com_peca(cliente)
        r = cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={
            "elementos": [{"i": 0, "box": {"x": 40, "y": 90, "w": 120, "h": 50}}]})
        assert r.status_code == 202
        d = cliente.get(f"/jobs/{job}/pecas/gdn-300x250").json()
        assert d["elementos"][0]["box"] == {"x": 40, "y": 90, "w": 120, "h": 50}
        assert d["elementos"][0]["texto"] == "Oi"      # o resto do elemento fica
        assert cliente.fila.pedidos[-1][0] == "redesenhar"

    def test_elemento_que_nao_volta_sai_da_peca(self, cliente):
        job = self._com_peca(cliente)
        cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={"elementos": []})
        d = cliente.get(f"/jobs/{job}/pecas/gdn-300x250").json()
        assert d["elementos"] == []

    def test_a_tela_nao_escolhe_que_arquivo_o_motor_desenha(self, cliente):
        """`src` não está na lista do que se pode ajustar. Sem isso um pedido
        forjado faria o motor desenhar — e devolver dentro do PNG — qualquer
        arquivo que a máquina conseguisse abrir."""
        job = self._com_peca(cliente)
        cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={"elementos": [
            {"i": 0, "src": "../../../etc/passwd", "tipo": "imagem",
             "box": {"x": 0, "y": 0, "w": 10, "h": 10}}]})
        d = cliente.get(f"/jobs/{job}/pecas/gdn-300x250").json()
        assert "src" not in d["elementos"][0]
        assert d["elementos"][0]["tipo"] == "texto"

    def test_indice_fora_da_peca_e_recusado(self, cliente):
        job = self._com_peca(cliente)
        r = cliente.post(f"/jobs/{job}/pecas/gdn-300x250",
                         json={"elementos": [{"i": 7, "box": {"x": 0, "y": 0, "w": 1, "h": 1}}]})
        assert r.status_code == 422

    def test_formato_sem_peca_montada_nao_abre(self, cliente):
        job = self._com_peca(cliente)
        assert cliente.get(f"/jobs/{job}/pecas/ig-stories").status_code == 404

    def test_ajustar_nao_conta_peca_de_novo(self, cliente):
        """A franquia é por peça produzida. Cobrar de novo porque a pessoa
        discordou da diagramação é cobrar por discordar."""
        from api import uso
        job = self._com_peca(cliente)
        antes = uso.resumo(cliente.conta.id)["pecas"]
        cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={
            "elementos": [{"i": 0, "box": {"x": 1, "y": 1, "w": 10, "h": 10}}]})
        assert uso.resumo(cliente.conta.id)["pecas"] == antes


class TestMedidaLivre:
    def test_a_api_aceita_medida_fora_do_catalogo(self, cliente):
        """O catálogo cobre os destinos conhecidos. Fora deles havia só o
        impasse: ou o formato existia na lista, ou a peça não saía."""
        r = enviar(cliente, formatos="livre-1080x1350", modo="sem")
        assert r.status_code == 202

    def test_medida_absurda_continua_recusada(self, cliente):
        for fid in ("livre-10x10", "livre-99999x200", "livre-abcxdef"):
            r = enviar(cliente, formatos=fid, modo="sem")
            assert r.status_code == 422, fid

    def test_a_margem_e_proporcional_e_o_lado_maior_nao_manda_nela(self):
        """Margem calculada sobre o lado maior esmagaria a faixa de um banner
        3000x500 até sobrar menos do que o texto precisa."""
        from motor.replica import formato_by_id
        f = formato_by_id("livre-3000x500")
        assert f["safe"]["top"] == f["safe"]["left"]
        assert 0 < f["safe"]["top"] < 500 * 0.1

    def test_a_proporcao_vem_simplificada(self):
        from motor.replica import formato_by_id
        assert formato_by_id("livre-1920x1080")["ratio"] == "16:9"

    def test_a_peca_sai_na_medida_pedida(self, tmp_path):
        from api.compositor import CompositorPreserva
        from api.pipeline import desdobrar
        base = tmp_path / "arte.png"
        Image.new("RGB", (1200, 1200), (12, 42, 102)).save(base)
        desdobrar(base, ["livre-900x1600"], CompositorPreserva(), tmp_path / "saida")
        with Image.open(tmp_path / "saida" / "livre-900x1600.png") as im:
            assert im.size == (900, 1600)


class TestOMotivoDoFundo:
    """O aviso da queda do generativo tem que dizer o que houve de verdade."""

    def test_recusa_rapida_nao_e_relatada_como_demora(self, monkeypatch, tmp_path):
        """Dizer "não respondeu em 180s" quando a recusa voltou em dois
        segundos manda quem lê procurar lentidão onde o problema é crédito."""
        from api import fundo
        monkeypatch.setattr(fundo, "_outpaint_higgsfield",
                            lambda *a, **k: (None, {"erro": "sem URL de resultado"}))
        relogio = iter([0.0, 2.0])
        import time as _t
        monkeypatch.setattr(_t, "monotonic", lambda: next(relogio))
        base = Image.new("RGB", (100, 100), (0, 0, 0))
        _, motivo = fundo._continuar(base, {"left": 0, "right": 0, "top": 0, "bottom": 10}, 180)
        assert "180s" not in motivo
        assert "crédito" in motivo

    def test_demora_de_verdade_continua_sendo_demora(self, monkeypatch):
        from api import fundo
        monkeypatch.setattr(fundo, "_outpaint_higgsfield",
                            lambda *a, **k: (None, {"erro": "sem resposta"}))
        relogio = iter([0.0, 180.0])
        import time as _t
        monkeypatch.setattr(_t, "monotonic", lambda: next(relogio))
        base = Image.new("RGB", (100, 100), (0, 0, 0))
        _, motivo = fundo._continuar(base, {"left": 0, "right": 0, "top": 0, "bottom": 10}, 180)
        assert "não respondeu em 180s" in motivo


class TestOAjusteSobreviveAExportacao:
    """A exportação final refaz o trabalho inteiro — é assim que ela insiste
    no fundo generativo. Refazendo, ela reescrevia a peça por cima do ajuste:
    a pessoa movia o CTA, clicava em exportar e o CTA voltava sozinho."""

    def _peca(self, pasta, via, x):
        import json as _j
        (pasta / "pecas").mkdir(parents=True, exist_ok=True)
        (pasta / "pecas" / "gdn-300x250.json").write_text(_j.dumps({
            "formato": "gdn-300x250", "via": via,
            "elementos": [{"tipo": "texto", "papel": "cta", "texto": "Oi",
                           "box": {"x": x, "y": 5, "w": 50, "h": 20}}]}), encoding="utf-8")

    def test_a_montagem_feita_a_mao_volta_para_a_peca(self, tmp_path):
        from api.pipeline import manter_a_mao
        self._peca(tmp_path, "psd-reenquadra+mao", 99)
        nova = {"via": "psd-reenquadra", "elementos": [{"tipo": "texto", "papel": "cta",
                                                        "box": {"x": 5, "y": 5, "w": 50, "h": 20}}]}
        avisos = manter_a_mao(nova, tmp_path, "gdn-300x250")
        assert nova["elementos"][0]["box"]["x"] == 99
        assert "+mao" in nova["via"]
        assert avisos and "à mão" in avisos[0]

    def test_peca_que_ninguem_ajustou_e_recomposta_normalmente(self, tmp_path):
        from api.pipeline import manter_a_mao
        self._peca(tmp_path, "psd-reenquadra", 99)
        nova = {"via": "psd-reenquadra", "elementos": [{"box": {"x": 5, "y": 5, "w": 1, "h": 1}}]}
        assert manter_a_mao(nova, tmp_path, "gdn-300x250") == []
        assert nova["elementos"][0]["box"]["x"] == 5

    def test_so_a_montagem_volta_o_fundo_novo_fica(self, tmp_path):
        """O fundo refeito é justamente o que a exportação final foi buscar."""
        from api.pipeline import manter_a_mao
        self._peca(tmp_path, "psd-reenquadra+mao", 99)
        nova = {"via": "psd-reenquadra", "elementos": [],
                "fundo": {"tipo": "imagem", "src": "fundo-novo.png"}}
        manter_a_mao(nova, tmp_path, "gdn-300x250")
        assert nova["fundo"]["src"] == "fundo-novo.png"
