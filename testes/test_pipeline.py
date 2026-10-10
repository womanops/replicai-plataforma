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

    def compor(self, base, formato_id, brief=""):
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
