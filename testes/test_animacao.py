"""A peça parada vira vídeo.

O layout não é tocado aqui: ele já foi decidido por formato. A animação só diz
quando e como cada coisa entra — por isso trocar de preset não mexe em caixa
nenhuma, e é isso que estes testes travam.
"""
import json

import pytest
from PIL import Image

from api import animacao
from api.animacao import VideoImpossivel, animar, preparar


@pytest.fixture
def job(tmp_path, monkeypatch):
    """Um trabalho com uma peça composta, fundo e fonte."""
    monkeypatch.setattr(animacao, "VIDEO", tmp_path / "video")
    (tmp_path / "video" / "props").mkdir(parents=True)
    pasta = tmp_path / "trab"
    (pasta / "pecas").mkdir(parents=True)
    Image.new("RGB", (1080, 1080), "#0a1a55").save(pasta / "fundo-x.png")
    (pasta / "fonte.ttf").write_bytes(b"fonte")
    (pasta / "pecas" / "ig-feed-1x1.json").write_text(json.dumps({
        "canvas": {"w": 1080, "h": 1080},
        "fundo": {"tipo": "imagem", "src": "fundo-x.png", "fit": "cover"},
        "fontes": [{"familia": "PecaSans", "arquivo": "fonte.ttf"}],
        "elementos": [
            {"tipo": "texto", "papel": "headline", "texto": "oi",
             "box": {"x": 0, "y": 0, "w": 100, "h": 50}},
            {"tipo": "botao", "papel": "cta", "texto": "Vem",
             "box": {"x": 0, "y": 900, "w": 200, "h": 60}, "fundo": "#fff"},
        ]}), encoding="utf-8")
    return pasta


class TestPreparar:
    def test_leva_fundo_fonte_e_imagens_para_o_projeto(self, job):
        props, slug = preparar(job, "ig-feed-1x1")
        levados = {p.name for p in (animacao.VIDEO / "public" / "peca" / slug).iterdir()}
        assert levados == {"fundo-x.png", "fonte.ttf"}
        d = json.loads(props.read_text())
        assert d["base"] == f"peca/{slug}"
        assert d["canvas"] == {"w": 1080, "h": 1080}

    def test_o_src_vira_nome_e_nao_caminho(self, job):
        """Caminho absoluto prenderia o vídeo à máquina que o renderizou."""
        props, _ = preparar(job, "ig-feed-1x1")
        d = json.loads(props.read_text())
        assert d["fundo"]["src"] == "fundo-x.png"
        assert "/" not in d["fundo"]["src"]

    def test_o_botao_chega_inteiro_nos_props(self, job):
        """Sem o tipo `botao`, o CTA cai no ramo de texto e some no fundo."""
        props, _ = preparar(job, "ig-feed-1x1")
        d = json.loads(props.read_text())
        cta = next(e for e in d["elementos"] if e["papel"] == "cta")
        assert cta["tipo"] == "botao" and cta["fundo"] == "#fff"


    def test_imagem_que_nao_existe_e_descartada(self, job):
        arq = job / "pecas" / "ig-feed-1x1.json"
        peca = json.loads(arq.read_text())
        peca["elementos"].append({"tipo": "imagem", "papel": "marca", "src": "nao-existe.png",
                                  "box": {"x": 0, "y": 0, "w": 10, "h": 10}})
        arq.write_text(json.dumps(peca))
        props, _ = preparar(job, "ig-feed-1x1")
        d = json.loads(props.read_text())
        assert all(e.get("src") != "nao-existe.png" for e in d["elementos"])

    def test_preset_desconhecido_cai_no_padrao(self, job):
        props, _ = preparar(job, "ig-feed-1x1", preset="inventado")
        assert json.loads(props.read_text())["preset"] == animacao.PRESET_PADRAO

    def test_a_duracao_vira_props(self, job):
        props, _ = preparar(job, "ig-feed-1x1", segundos=8)
        assert json.loads(props.read_text())["segundos"] == 8.0

    def test_formato_sem_peca_composta_e_recusado(self, job):
        with pytest.raises(VideoImpossivel, match="não existe peça composta"):
            preparar(job, "ig-stories")

    def test_refazer_limpa_o_que_estava_la(self, job):
        _, slug = preparar(job, "ig-feed-1x1")
        velho = animacao.VIDEO / "public" / "peca" / slug / "lixo.png"
        velho.write_bytes(b"x")
        preparar(job, "ig-feed-1x1")
        assert not velho.exists()


def render_falso(props, destino, **k):
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(b"mp4")
    return destino


class TestAnimar:
    def test_um_formato_que_falha_nao_derruba_os_outros(self, job, monkeypatch):
        monkeypatch.setattr(animacao, "renderizar", render_falso)
        prontos, falhas = animar(job, ["ig-feed-1x1", "ig-stories"])
        assert set(prontos) == {"ig-feed-1x1"}
        assert "não existe peça composta" in falhas["ig-stories"]

    def test_o_video_fica_na_pasta_do_trabalho(self, job, monkeypatch):
        monkeypatch.setattr(animacao, "renderizar", render_falso)
        prontos, _ = animar(job, ["ig-feed-1x1"], preset="lettering")
        assert prontos["ig-feed-1x1"] == job / "video" / "ig-feed-1x1-lettering.mp4"


class TestSemProjeto:
    def test_sem_node_modules_diz_o_que_fazer(self, job, monkeypatch):
        monkeypatch.setattr(animacao, "instalado", lambda: False)
        with pytest.raises(VideoImpossivel, match="npm install"):
            animacao.renderizar(job / "x.json", job / "y.mp4")
