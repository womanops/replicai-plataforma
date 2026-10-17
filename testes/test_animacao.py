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


class TestDarSinalDeVida:
    """"Quando solicito animação da peça não dá pra saber se está ou não
    acontecendo, fica parado sem barra de progresso."

    O render leva minutos e era o único pedaço da plataforma que não contava
    nada enquanto rodava: o estado do vídeo só era gravado no começo e no fim,
    então a tela dividia zero prontos por quatro formatos e mostrava 0% do
    princípio ao fim. De fora, isso é igual a um travamento.
    """

    def test_cada_passo_e_contado(self, job, monkeypatch):
        monkeypatch.setattr(animacao, "renderizar", render_falso)
        passos = []
        animar(job, ["ig-feed-1x1"], progresso=passos.append)
        assert [p["etapa"] for p in passos] == ["montando a cena",
                                                "renderizando o vídeo", "pronto"]
        assert passos[-1]["feito"] == 1 and passos[0]["feito"] == 0

    def test_o_que_ja_saiu_vai_junto(self, job, monkeypatch):
        """Senão a tela só sabe dos vídeos quando o último terminar."""
        monkeypatch.setattr(animacao, "renderizar", render_falso)
        passos = []
        animar(job, ["ig-feed-1x1", "ig-stories"], progresso=passos.append)
        assert passos[-1]["prontos"] == ["ig-feed-1x1"]
        assert passos[-1]["total"] == 2

    def test_o_formato_que_falha_tambem_avança(self, job, monkeypatch):
        """A barra não pode parar no formato que não saiu: o trabalho segue."""
        monkeypatch.setattr(animacao, "renderizar", render_falso)
        passos = []
        animar(job, ["ig-stories"], progresso=passos.append)
        assert passos[-1]["feito"] == 1
        assert passos[-1]["falhas"], "a falha não chegou ao andamento"

    def test_sem_callback_continua_funcionando(self, job, monkeypatch):
        """Quem chama de fora da esteira (teste, script) não precisa saber."""
        monkeypatch.setattr(animacao, "renderizar", render_falso)
        prontos, _ = animar(job, ["ig-feed-1x1"])
        assert set(prontos) == {"ig-feed-1x1"}


class TestSemProjeto:
    def test_sem_node_modules_diz_o_que_fazer(self, job, monkeypatch):
        monkeypatch.setattr(animacao, "instalado", lambda: False)
        with pytest.raises(VideoImpossivel, match="npm install"):
            animacao.renderizar(job / "x.json", job / "y.mp4")


class TestOQueAJanelaMostra:
    """Escolher movimento por uma palavra solta é adivinhar. A janela de
    Animar mostrava "seco", "energia", "editorial", "lettering" e mais nada:
    quatro palavras que não dizem o que vai acontecer com a peça, e o render
    é caro demais para se descobrir testando."""

    def test_todo_preset_tem_nome_e_descricao(self):
        assert set(animacao.SOBRE) == set(animacao.PRESETS)
        for pid, s in animacao.SOBRE.items():
            assert s["nome"] and len(s["diz"]) > 40, pid

    def test_o_nome_e_o_mesmo_do_movimento(self):
        """O nome de exibição existe aqui e no `movimento.ts`. Divergir é
        mostrar na tela um nome que o vídeo não usa."""
        import re
        from pathlib import Path
        fonte = Path("video/src/peca/movimento.ts").read_text(encoding="utf-8")
        for pid, s in animacao.SOBRE.items():
            bloco = re.search(rf"^  {pid}: \{{(.+?)^  \}},", fonte, re.S | re.M)
            assert bloco, f"`{pid}` não está no movimento.ts"
            assert f"nome: '{s['nome']}'" in bloco.group(1), pid

    def test_o_exemplo_de_cada_um_esta_no_lugar(self):
        """O arquivo que a tela promete. Sem ele a janela mostra só o texto —
        o que é correto, mas é a entrega pela metade."""
        from pathlib import Path
        for pid in animacao.PRESETS:
            assert (Path("web/assets") / f"exemplo-{pid}.webp").exists(), pid


class TestOAndamentoChegaNaTela:
    """De nada adianta contar os passos se o estado gravado não os carrega: é
    o `trabalho.json` que a tela lê de dois em dois segundos e meio."""

    def test_o_estado_do_video_guarda_o_passo_e_o_relogio(self, tmp_path, monkeypatch):
        from api import animacao, tarefas, trabalhos, uso
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(uso, "registrar", lambda *a, **k: {"gravado": True})

        fotos = []

        def animar_devagar(pasta, formatos, preset, segundos, progresso=None):
            progresso({"etapa": "renderizando o vídeo", "formato": formatos[0],
                       "feito": 0, "total": len(formatos), "prontos": [],
                       "falhas": {}, "desde_formato": 1.0})
            fotos.append(trabalhos.ler("conta-teste", "job-teste")["video"])
            return {f: pasta / f for f in formatos}, {}

        monkeypatch.setattr(animacao, "animar", animar_devagar)
        tarefas.processar_video("conta-teste", "job-teste", ["ig-feed-1x1", "ig-stories"], "seco", 6.0)

        meio = fotos[0]
        assert meio["status"] == "rodando"
        assert meio["etapa"] == "renderizando o vídeo" and meio["formato"] == "ig-feed-1x1"
        assert meio["total"] == 2, "a tela não sabe por quanto dividir"
        assert meio["desde"], "sem relógio do vídeo a estimativa usa o da replicação"
        assert trabalhos.ler("conta-teste", "job-teste")["video"]["status"] == "pronto"

    def test_o_relogio_do_video_e_dele_e_nao_o_da_peca(self, tmp_path, monkeypatch):
        """A peça pode ter sido replicada ontem. Estimar o que falta pelo
        início dela dava "~4 h restando" num render de dois minutos."""
        from api import animacao, tarefas, trabalhos, uso
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(uso, "registrar", lambda *a, **k: {"gravado": True})
        trabalhos.gravar("conta-teste", "job-teste", {"inicio": 1.0})
        monkeypatch.setattr(animacao, "animar",
                            lambda *a, **k: ({"ig-feed-1x1": tmp_path}, {}))
        tarefas.processar_video("conta-teste", "job-teste", ["ig-feed-1x1"], "seco", 6.0)
        d = trabalhos.ler("conta-teste", "job-teste")
        assert d["video"]["desde"] > d["inicio"]


@pytest.mark.lento
class TestPecaEmCamadasNaoDesmonta:
    """Peça de PSD: a arte É as camadas.

    O vídeo tratava cada camada como um objeto que entra e sai. O resultado foi
    um vídeo de cinco segundos que passava dois deles em BRANCO: a prancheta do
    PSD no começo, antes de a arte chegar, e a prancheta de novo no fim, depois
    de a arte ir embora — com o maior "selo" voando para o centro e crescendo,
    que no Energiza era o algarismo zero de "2027".
    """

    def _quadro(self, mp4, segundo, destino):
        import subprocess
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(segundo),
                        "-i", str(mp4), "-frames:v", "1", str(destino)], check=True)
        return Image.open(destino).convert("RGB")

    def test_o_comeco_e_o_fim_mostram_a_arte_e_nao_a_prancheta(self, tmp_path):
        import shutil
        if not animacao.instalado():
            pytest.skip("o projeto de vídeo não está instalado")

        pasta = tmp_path / "trab"
        (pasta / "pecas").mkdir(parents=True)
        Image.new("RGB", (200, 200), "#ffffff").save(pasta / "prancheta.png")
        Image.new("RGB", (200, 200), "#0b1030").save(pasta / "arte.png")
        Image.new("RGB", (12, 16), "#ffffff").save(pasta / "selo.png")
        (pasta / "pecas" / "quadrado.json").write_text(json.dumps({
            "canvas": {"w": 200, "h": 200},
            "fundo": {"tipo": "imagem", "src": "prancheta.png", "fit": "cover"},
            "elementos": [
                {"tipo": "imagem", "papel": "figura", "ancorado": True, "ordem": 0,
                 "src": "arte.png", "fit": "fill",
                 "box": {"x": 0, "y": 0, "w": 200, "h": 200}},
                {"tipo": "imagem", "papel": "selo", "ancorado": True, "ordem": 1,
                 "letra": 0, "src": "selo.png", "fit": "fill",
                 "box": {"x": 90, "y": 150, "w": 12, "h": 16}},
            ]}), encoding="utf-8")

        props, slug = preparar(pasta, "quadrado", preset="lettering", segundos=2.0)
        try:
            mp4 = animacao.renderizar(props, tmp_path / "saida.mp4")
            primeiro = self._quadro(mp4, 0.05, tmp_path / "a.png")
            ultimo = self._quadro(mp4, 1.90, tmp_path / "b.png")
        finally:
            shutil.rmtree(animacao.VIDEO / "public" / "peca" / slug, ignore_errors=True)
            props.unlink(missing_ok=True)

        # no centro só pode estar a arte: branco ali é a prancheta aparecendo
        # — ou o selo que voou para o meio e cresceu
        for quando, q in (("no primeiro quadro", primeiro), ("no último quadro", ultimo)):
            r, g, b = q.getpixel((100, 100))
            assert max(r, g, b) < 120, f"a prancheta está à mostra {quando}: {(r, g, b)}"
        assert ultimo.getpixel((96, 158))[0] > 200, "o selo sumiu no fim: a peça se desmontou"
