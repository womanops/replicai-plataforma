"""A esteira de um job.

O comportamento que mais importa aqui não é o caminho feliz: é o que acontece
quando um formato falha. Entregar seis de oito com a lista do que faltou é
melhor do que não entregar nada, e muito melhor do que entregar oito com duas
erradas.
"""
import json

import pytest
from PIL import Image

from api.compositor import ComposicaoImpossivel, CompositorSimples
from api.pipeline import desdobrar
from motor.replica import find_chrome

# Dois motivos para separar: sem navegador não dá para rodar, e com navegador
# leva mais de um minuto. A suíte do dia a dia precisa ser rápida o bastante
# para ser rodada sempre.
precisa_de_chrome = pytest.mark.skipif(
    find_chrome() is None,
    reason="sem navegador nesta máquina; o render é coberto pela prova do contêiner")
lento = pytest.mark.lento


class CompositorQueRecusa:
    """Compositor que nunca dá conta: serve para testar o caminho da falha sem
    depender de navegador."""

    def compor(self, base, formato_id, brief="", terreno=None):
        raise ComposicaoImpossivel(f"não sei compor {formato_id}")


@pytest.fixture
def arte(tmp_path):
    p = tmp_path / "arte.png"
    Image.new("RGB", (1200, 1200), (12, 42, 102)).save(p)
    return p


class TestQuandoTudoFalha:
    def test_status_erro_e_motivo_por_formato(self, arte, tmp_path):
        r = desdobrar(arte, ["ig-feed-4x5", "ig-stories"], CompositorQueRecusa(), tmp_path / "job")
        assert r.status == "erro"
        assert not r.prontas
        assert set(r.falhas) == {"ig-feed-4x5", "ig-stories"}
        assert "não sei compor" in r.falhas["ig-feed-4x5"]

    def test_grava_o_resultado_em_disco(self, arte, tmp_path):
        """Quem for buscar o job depois precisa achar o que aconteceu, mesmo que
        o processo que rodou já tenha morrido."""
        r = desdobrar(arte, ["ig-feed-4x5"], CompositorQueRecusa(), tmp_path / "job")
        gravado = json.loads((r.pasta / "resultado.json").read_text(encoding="utf-8"))
        assert gravado["status"] == "erro"
        assert "ig-feed-4x5" in gravado["falhas"]


class TestEntregaParcial:
    @lento
    @precisa_de_chrome
    def test_um_formato_ruim_nao_derruba_os_bons(self, arte, tmp_path):
        # yt-thumb não leva CTA: o compositor recusa esse e entrega os outros
        r = desdobrar(arte, ["ig-feed-4x5", "yt-thumb"],
                      CompositorSimples("Chegamos a Porto Belo", cta="Candidate-se"),
                      tmp_path / "job")
        assert r.status == "parcial"
        assert "ig-feed-4x5" in r.prontas
        assert "yt-thumb" in r.falhas
        assert r.prontas["ig-feed-4x5"].exists()


@lento
@precisa_de_chrome
class TestCaminhoFeliz:
    def test_entrega_as_pecas_na_medida_do_formato(self, arte, tmp_path):
        r = desdobrar(arte, ["ig-feed-4x5", "gdn-300x250"],
                      CompositorSimples("Chegamos a Porto Belo"), tmp_path / "job")
        assert r.status == "pronto"
        assert Image.open(r.prontas["ig-feed-4x5"]).size == (1080, 1350)
        assert Image.open(r.prontas["gdn-300x250"]).size == (300, 250)

    def test_a_peca_nao_sai_lisa(self, arte, tmp_path):
        """Fundo chapado sem texto quer dizer que a tipografia não desenhou —
        falha silenciosa que só aparece quando alguém olha a peça."""
        r = desdobrar(arte, ["ig-feed-4x5"], CompositorSimples("Chegamos a Porto Belo"),
                      tmp_path / "job")
        cores = Image.open(r.prontas["ig-feed-4x5"]).convert("RGB").getcolors(maxcolors=500_000)
        assert cores and len(cores) > 5, "a peça saiu lisa: o texto não desenhou"

    def test_guarda_a_peca_json_usada(self, arte, tmp_path):
        """Sem o JSON não dá para reabrir, ajustar e regravar a peça depois."""
        r = desdobrar(arte, ["ig-feed-4x5"], CompositorSimples("Chamada"), tmp_path / "job")
        assert (r.pasta / "pecas" / "ig-feed-4x5.json").is_file()

    def test_a_arte_vai_junto_para_a_pasta_do_job(self, arte, tmp_path):
        """O job tem que ser auto-contido: copiado para outra máquina, abre."""
        r = desdobrar(arte, ["gdn-300x250"], CompositorSimples("Chamada"), tmp_path / "job")
        assert (r.pasta / "base.png").is_file()
        peca = json.loads((r.pasta / "pecas" / "gdn-300x250.json").read_text(encoding="utf-8"))
        assert peca["fundo"]["src"] == "base.png", "caminho absoluto quebra ao mudar de máquina"


class TestAsVerificacoesRodam:
    """Escrever a verificação e não chamá-la foi o erro que deixou o lettering
    fantasma passar hoje. Estes testes existem para que ela continue sendo
    chamada, e não só existindo."""

    def peca_com_fundo(self, pasta, nome_fundo):
        return {"formato": "gdn-300x250", "canvas": {"w": 300, "h": 250},
                "saida": "x.png", "fundo": {"tipo": "imagem", "src": nome_fundo},
                "elementos": []}

    def test_acusa_fundo_que_perdeu_o_grafismo(self, tmp_path):
        from api.pipeline import conferir_peca
        import numpy as np
        arte = tmp_path / "arte.png"
        a = np.full((300, 400, 3), (12, 30, 110), dtype=np.uint8)
        a[::16, :] = (60, 100, 200); a[:, ::16] = (60, 100, 200)
        Image.fromarray(a).save(arte)
        liso = tmp_path / "fundo.png"
        Image.new("RGB", (300, 250), (12, 30, 110)).save(liso)

        avisos = conferir_peca(self.peca_com_fundo(tmp_path, "fundo.png"), tmp_path, arte)
        assert any("grafismo" in a for a in avisos), avisos

    def test_fundo_fiel_nao_gera_aviso(self, tmp_path):
        from api.pipeline import conferir_peca
        import numpy as np
        a = np.full((300, 400, 3), (12, 30, 110), dtype=np.uint8)
        a[::16, :] = (60, 100, 200); a[:, ::16] = (60, 100, 200)
        arte = tmp_path / "arte.png"; Image.fromarray(a).save(arte)
        bom = tmp_path / "fundo.png"; Image.fromarray(a[:250, :300]).save(bom)
        assert conferir_peca(self.peca_com_fundo(tmp_path, "fundo.png"), tmp_path, arte) == []

    def test_acusa_marca_colada_como_bloco(self, tmp_path):
        from api.pipeline import conferir_peca
        arte = tmp_path / "arte.png"
        Image.new("RGB", (400, 300), (12, 30, 110)).save(arte)
        logo = tmp_path / "logo.png"
        Image.new("RGBA", (80, 40), (255, 255, 255, 255)).save(logo)
        peca = {"fundo": {}, "elementos": [
            {"tipo": "imagem", "papel": "marca", "src": "logo.png", "box": {}}]}
        avisos = conferir_peca(peca, tmp_path, arte)
        assert any("bloco opaco" in a for a in avisos), avisos

    def test_marca_com_alfa_passa(self, tmp_path):
        from api.pipeline import conferir_peca
        arte = tmp_path / "arte.png"
        Image.new("RGB", (400, 300), (12, 30, 110)).save(arte)
        logo = tmp_path / "logo.png"
        im = Image.new("RGBA", (80, 40), (0, 0, 0, 0))
        im.paste((255, 255, 255, 255), (20, 10, 60, 30))
        im.save(logo)
        peca = {"fundo": {}, "elementos": [
            {"tipo": "imagem", "papel": "marca", "src": "logo.png", "box": {}}]}
        assert conferir_peca(peca, tmp_path, arte) == []

    def test_arquivo_sumido_nao_derruba_a_entrega(self, tmp_path):
        """Conferência é ressalva, não barreira: ela não pode ser o motivo de
        uma peça pronta não ser entregue."""
        from api.pipeline import conferir_peca
        arte = tmp_path / "arte.png"
        Image.new("RGB", (400, 300), (12, 30, 110)).save(arte)
        peca = {"fundo": {"src": "nao-existe.png"}, "elementos": [
            {"tipo": "imagem", "papel": "marca", "src": "sumiu.png", "box": {}}]}
        assert conferir_peca(peca, tmp_path, arte) == []

    @pytest.mark.lento
    @precisa_de_chrome
    def test_o_aviso_viaja_no_resultado(self, arte, tmp_path):
        r = desdobrar(arte, ["gdn-300x250"], CompositorSimples("Chegamos"), tmp_path / "job")
        gravado = json.loads((r.pasta / "resultado.json").read_text(encoding="utf-8"))
        assert "avisos" in gravado


class TestOQueFoiPedidoENaoEntrou:
    """Entregar diferente do que foi pedido sem dizer é o pior jeito de errar:
    parece que funcionou.

    Caso real, 12/10/2026: modo "novos textos", chamada "Chegamos a São
    Paulo!", ajuste "elimina o boneco da peça". A peça saiu com o "Chegamos a
    Porto Belo" impresso na arte e com o mascote no lugar. O modelo tinha
    explicado as duas coisas em `descartados` — e `descartados` era gravado no
    JSON da montagem e não chegava a lugar nenhum.
    """

    class Compositor:
        headline = "Chegamos a São Paulo!"
        cta = ""

    def _peca(self):
        return {"elementos": [{"tipo": "texto", "texto": "CANDIDATE-SE"}],
                "descartados": {
                    "a Porto Belo! / Chegamos":
                        "Já vêm impressos na arte. Atenção: a arte diz 'Chegamos a "
                        "Porto Belo!' e a headline diz 'São Paulo'.",
                    "elimina o boneco da peça":
                        "É um ajuste pedido, não texto da peça: a composição só "
                        "posiciona texto e não edita a arte.",
                }}

    def test_a_chamada_que_nao_entrou_vira_aviso(self):
        from api.pipeline import ficou_de_fora
        avisos = ficou_de_fora(self._peca(), self.Compositor(), "")
        assert any("São Paulo" in a and "não entrou" in a for a in avisos)

    def test_o_aviso_leva_o_motivo_do_modelo(self):
        """Dizer "não entrou" sem dizer por quê devolve a pessoa ao escuro."""
        from api.pipeline import ficou_de_fora
        avisos = ficou_de_fora(self._peca(), self.Compositor(), "")
        assert "Porto Belo" in avisos[0]

    def test_o_ajuste_que_nao_pode_ser_feito_vira_aviso(self):
        from api.pipeline import ficou_de_fora
        avisos = ficou_de_fora(self._peca(), self.Compositor(), "elimina o boneco da peça")
        assert any("ajuste que você pediu" in a for a in avisos)

    def test_chamada_que_entrou_nao_vira_aviso(self):
        """Senão todo trabalho sai com ressalva e a ressalva perde o sentido."""
        from api.pipeline import ficou_de_fora
        peca = {"elementos": [{"tipo": "texto", "texto": "Chegamos a São Paulo!"}]}
        assert ficou_de_fora(peca, self.Compositor(), "") == []

    def test_pontuacao_e_acento_nao_enganam_a_comparacao(self):
        from api.pipeline import ficou_de_fora
        peca = {"elementos": [{"tipo": "texto", "texto": "CHEGAMOS A SAO PAULO"}]}
        assert ficou_de_fora(peca, self.Compositor(), "") == []

    def test_sem_nada_pedido_nao_inventa_ressalva(self):
        from api.pipeline import ficou_de_fora

        class Vazio:
            headline = ""
            cta = ""
        assert ficou_de_fora(self._peca(), Vazio(), "") == []

    def test_o_caminho_do_psd_guarda_o_que_ficou_de_fora(self):
        """No caminho do PSD nem ao estado do trabalho isso chegava."""
        import inspect

        from api import pipeline
        fonte = inspect.getsource(pipeline._psd_e_render)
        assert 'r.descartados[fid] = peca["descartados"]' in fonte
        assert "ficou_de_fora(peca, compositor, brief)" in fonte


class TestARessalvaNaoSeRepete:
    """A esteira passa por várias réguas e mais de uma chega à mesma conclusão
    sobre a mesma peça. Repetida, a ressalva vira parede de texto e some o que
    de fato tem que ser olhado — foi o que a Ligia viu: treze linhas idênticas
    numa peça só."""

    def test_a_mesma_linha_entra_uma_vez(self, tmp_path):
        from api.pipeline import Resultado
        r = Resultado(pasta=tmp_path)
        r.avisar("gdn-728x90", "o título não se lê sobre o fundo")
        r.avisar("gdn-728x90", "o título não se lê sobre o fundo")
        r.avisar("gdn-728x90", "o selo não se lê sobre o fundo")
        assert r.avisos["gdn-728x90"] == ["o título não se lê sobre o fundo",
                                          "o selo não se lê sobre o fundo"]

    def test_cada_formato_tem_a_sua(self, tmp_path):
        """Juntar demais esconde: a mesma ressalva em dois formatos é duas
        peças para olhar, não uma."""
        from api.pipeline import Resultado
        r = Resultado(pasta=tmp_path)
        r.avisar("gdn-728x90", "o título não se lê sobre o fundo")
        r.avisar("gdn-300x600", "o título não se lê sobre o fundo")
        assert len(r.avisos) == 2
