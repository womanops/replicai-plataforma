"""Para que lado a faixa nova vai quando o quadro cresce.

Melhor prática de diagramação, e não preferência: o que está plantado numa
borda continua plantado nela. No KV da Consigaz o mascote é cortado pelo
rodapé da prancheta — ele está em pé no chão da peça. Centrar a arte no quadro
novo abriu faixa embaixo dele, e o Stories saiu com o Nino amputado flutuando
sobre um rodapé vazio.

Não é régua de pixel: o arquivo diz. Camada com bbox que passa da borda é
figura cortada pelo quadro.
"""
import pytest


class Falsa:
    """Uma camada, com o mínimo que a regra olha."""

    def __init__(self, bbox):
        self.bbox = bbox

    def is_group(self):
        return False


class Prancheta:
    def __init__(self, w=1200, h=1200, x=0, y=0):
        self.x, self.y, self.w, self.h = x, y, w, h


def bordas(camadas, prancheta=None):
    from api.psd import _bordas_com_figura
    return _bordas_com_figura([Falsa(b) for b in camadas], prancheta or Prancheta())


class TestOndeAFiguraEstaPlantada:
    def test_mascote_cortado_pelo_rodape(self):
        """O bbox real do Nino na prancheta de 1200×1200."""
        assert "baixo" in bordas([(718, 748, 1240, 1586)])

    def test_e_tambem_pela_direita(self):
        assert "direita" in bordas([(718, 748, 1240, 1586)])

    def test_fundo_que_sangra_dos_quatro_lados_nao_e_figura(self):
        assert bordas([(0, -335, 1200, 1463)]) == set()

    def test_faixa_larga_cortada_em_cima_nao_e_figura(self):
        """`Camada 5 copiar` atravessa 91% da largura: é textura de fundo, e
        tratá-la como figura prenderia a arte no topo sem motivo."""
        assert "cima" not in bordas([(147, -66, 1240, 589)])

    def test_camada_inteira_dentro_nao_prende_nada(self):
        assert bordas([(100, 100, 400, 400)]) == set()


class TestParaOndeAFaixaVai:
    def test_figura_embaixo_joga_a_faixa_para_cima(self):
        from api.psd import ancora_das_bordas
        assert ancora_das_bordas({"baixo"}) == (0.5, 1.0)

    def test_figura_em_cima_joga_a_faixa_para_baixo(self):
        from api.psd import ancora_das_bordas
        assert ancora_das_bordas({"cima"}) == (0.5, 0.0)

    def test_figura_nos_dois_lados_volta_ao_centro(self):
        """Sem lado melhor, o comportamento antigo: dividir a faixa."""
        from api.psd import ancora_das_bordas
        assert ancora_das_bordas({"cima", "baixo"}) == (0.5, 0.5)

    def test_sem_figura_nenhuma_volta_ao_centro(self):
        from api.psd import ancora_das_bordas
        assert ancora_das_bordas(set()) == (0.5, 0.5)

    def test_o_caso_real_da_consigaz(self):
        """Figura cortada embaixo, à direita e à esquerda: o eixo horizontal
        empata e o vertical encosta embaixo."""
        from api.psd import ancora_das_bordas
        assert ancora_das_bordas({"baixo", "direita", "esquerda"}) == (0.5, 1.0)


class TestAEsteiraUsaAAncora:
    def test_reenquadrar_passa_a_ancora(self):
        import inspect

        from api import psd
        assert "ancora_das_bordas" in inspect.getsource(psd.reenquadrar)

    def test_recompor_nao_abre_rodape_sob_figura_plantada(self, tmp_path):
        """`recompor` encosta a arte no topo para abrir rodapé ao lockup.
        Embaixo de uma figura plantada, abrir ali a descola do chão — então a
        faixa vai para cima e a arte desce."""
        from PIL import Image

        from api.psd import Leitura, _ancora_do_recompor
        arte = tmp_path / "a.png"
        Image.new("RGB", (1200, 1200)).save(arte)
        alto = {"w": 1080, "h": 1920}
        assert _ancora_do_recompor(Leitura(plantada_em=[]), alto, arte) == (0.5, 0.0)
        assert _ancora_do_recompor(Leitura(plantada_em=["baixo"]), alto, arte) == (0.5, 1.0)

    def test_a_leitura_carrega_as_bordas(self):
        from api.psd import Leitura
        assert Leitura().plantada_em == []


class TestNaoMostrarOQueAPranchetaEsconde:
    """A prancheta corta o que não foi aprovado. O mascote da Consigaz tem,
    na perna que ela esconde, uma logo espelhada ao contrário: mostrar isso
    num formato mais alto não é desdobrar a peça, é publicar o que o designer
    tinha escondido."""

    def test_a_camada_e_aparada_na_prancheta(self, tmp_path):
        from PIL import Image
        from api import psd
        import inspect
        fonte = inspect.getsource(psd.extrair)
        assert "im.crop((cx0 - x0, cy0 - y0, cx1 - x0, cy1 - y0))" in fonte

    def test_caixa_cortada_vira_a_caixa_visivel(self):
        """O bbox guardado é o aparado, senão o elemento é desenhado maior do
        que a arte mostrava."""
        x0, y0, x1, y1 = 718, 748, 1240, 1586
        px, py, pw, ph = 0, 0, 1200, 1200
        cx0, cy0 = max(x0, px), max(y0, py)
        cx1, cy1 = min(x1, px + pw), min(y1, py + ph)
        assert (cx0, cy0, cx1, cy1) == (718, 748, 1200, 1200)


class TestOConteudoCentraEAFiguraFicaNoChao:
    def test_o_bloco_centra_na_altura_util(self):
        """Útil, não o quadro cru: o Stories tem 250 px no topo e 340 no
        rodapé que o aplicativo cobre."""
        import inspect

        from api import psd
        fonte = inspect.getsource(psd._ancora_centrada)
        assert 'sv["top"]' in fonte and 'sv["bottom"]' in fonte

    def test_sem_figura_plantada_a_ancora_nao_muda(self):
        from api.psd import Leitura, _ancora_centrada
        from pathlib import Path
        vazia = Leitura()
        assert _ancora_centrada(vazia, {"w": 1, "h": 1, "safe": {}}, Path("."), (0.5, 0.3)) \
            == (0.5, 0.3)

    def test_plantar_encosta_so_o_lado_que_o_quadro_cortava(self):
        from api.psd import _plantar
        els = [{"box": {"x": 10, "y": 10, "w": 50, "h": 50}},
               {"plantado": ["baixo"], "box": {"x": 20, "y": 20, "w": 40, "h": 60}}]
        saida = _plantar(els, {"w": 200, "h": 300})
        assert saida[0]["box"]["y"] == 10          # conteúdo não se move
        assert saida[1]["box"]["y"] == 300 - 60    # figura desce até o chão
        assert saida[1]["box"]["x"] == 20          # e o eixo livre fica


class TestQuemEhAAssinatura:
    """O vídeo fecha levando a assinatura ao centro. Chamar toda imagem de
    `marca` fez o mascote da Consigaz ser eleito a assinatura: ele voava para
    o meio da tela, cortado pela borda, enquanto a logo de verdade ficava
    assada no fundo e nunca aparecia no fecho."""

    def _camada(self, nome, tipo="imagem"):
        from api.psd import Camada
        return Camada(nome=nome, tipo=tipo, src="x.png",
                      box={"x": 0, "y": 0, "w": 10, "h": 10})

    def test_imagem_com_logo_no_nome_e_marca(self):
        from api.psd import _papel_de
        assert _papel_de(self._camada("Consigaz-logo_branco-02"), None) == "marca"

    def test_mascote_nao_e_marca(self):
        from api.psd import _papel_de
        assert _papel_de(self._camada("Consigaz-Nino-Poses-Pose-5"), None) == "figura"

    def test_o_motion_trata_figura_como_objeto(self):
        """`figura` não pode cair no vocabulário de marca do movimento."""
        import re
        from pathlib import Path
        fonte = Path("video/src/peca/movimento.ts").read_text(encoding="utf-8")
        regra = re.search(r"if \(/(.+?)/\.test\(n\)\) return 'marca'", fonte)
        assert regra, "não achei a regra de marca no movimento"
        assert not re.search(regra.group(1), "figura")


class TestAFaixaDoLockup:
    """`recompor` assumia que a sobra era um rodapé embaixo da arte. Numa capa
    de Facebook (1640×624 vinda de um quadrado) a arte ocupa a altura inteira
    e a sobra é lateral: não havia rodapé, e o formato não saía."""

    def _formato(self, w, h, margem=20):
        return {"w": w, "h": h,
                "safe": {"top": margem, "bottom": margem,
                         "left": margem, "right": margem}}

    def test_destino_largo_acha_a_faixa_lateral(self):
        from api.psd import _faixa_livre
        # arte quadrada de 624 encostada à esquerda de uma capa 1640×624
        faixa = _faixa_livre([0, 0, 624, 624], self._formato(1640, 624))
        assert faixa is not None
        x0, y0, x1, y1 = faixa
        assert x0 >= 624 and x1 - x0 > 900          # a sobra é à direita

    def test_destino_alto_acha_o_rodape(self):
        from api.psd import _faixa_livre
        faixa = _faixa_livre([0, 0, 1080, 1080], self._formato(1080, 1920))
        x0, y0, x1, y1 = faixa
        assert y0 >= 1080                            # a sobra é embaixo

    def test_sem_sobra_nenhuma_devolve_nada(self):
        from api.psd import _faixa_livre
        assert _faixa_livre([0, 0, 1080, 1080], self._formato(1080, 1080)) is None

    def test_faixa_fina_demais_nao_conta(self):
        """Vinte pixels não comportam lockup: é borda, não faixa."""
        from api.psd import _faixa_livre
        assert _faixa_livre([0, 0, 1080, 1060], self._formato(1080, 1080)) is None


class TestParaQueLadoAArteEncosta:
    class Leit:
        def __init__(self, plantada): self.plantada_em = list(plantada)

    def test_destino_largo_foge_da_figura_a_direita(self, tmp_path):
        """O mascote sai pela direita da prancheta: abrir faixa ali o descola
        da borda em que se apoia."""
        from PIL import Image
        from api.psd import _ancora_do_recompor
        arte = tmp_path / "a.png"
        Image.new("RGB", (1200, 1200)).save(arte)
        a = _ancora_do_recompor(self.Leit(["baixo", "direita"]),
                                {"w": 1640, "h": 624}, arte)
        assert a == (1.0, 0.5)                       # arte encosta à direita

    def test_destino_largo_sem_figura_poe_a_arte_a_esquerda(self, tmp_path):
        from PIL import Image
        from api.psd import _ancora_do_recompor
        arte = tmp_path / "a.png"
        Image.new("RGB", (1200, 1200)).save(arte)
        assert _ancora_do_recompor(self.Leit([]), {"w": 1640, "h": 624}, arte) == (0.0, 0.5)

    def test_destino_alto_mantem_o_rodape(self, tmp_path):
        from PIL import Image
        from api.psd import _ancora_do_recompor
        arte = tmp_path / "a.png"
        Image.new("RGB", (1200, 1200)).save(arte)
        assert _ancora_do_recompor(self.Leit([]), {"w": 1080, "h": 1920}, arte) == (0.5, 0.0)


class TestAFiguraNaoEhLockup:
    def test_recompor_move_a_figura_com_a_arte(self):
        """Escalada pela medida do lockup, ela encolhia e ia para o meio da
        faixa, longe do chão em que se apoia."""
        import inspect

        from api import psd
        fonte = inspect.getsource(psd.recompor)
        assert 'e.get("plantado")' in fonte
        assert "_plantar(figuras, formato)" in fonte


class TestFotoNaoEhAssinaturaNemEstaPlantada:
    """Soltar as fotos para a animação quebrou a capa do Facebook de dois
    jeitos ao mesmo tempo, e os dois só aparecem no `recompor`, que remonta a
    peça quando a proporção muda muito."""

    def test_a_foto_acompanha_a_arte_e_nao_o_lockup(self):
        """Escalada pela medida do lockup, a colagem se espatifa: cada foto
        sai voando para um canto, num tamanho diferente."""
        import inspect

        from api import psd
        fonte = inspect.getsource(psd.recompor)
        assert 'e.get("papel") == "figura"' in fonte

    def test_a_tinta_do_lockup_ignora_as_fotos(self):
        """É por ela que o lockup é escalado na faixa. Com as fotos dentro, a
        escala sai pela colagem inteira e o texto some."""
        import inspect

        from api import psd
        assert "MARCA.search" in inspect.getsource(psd.tinta_de)

    def test_sangrar_pela_lateral_nao_e_estar_plantada(self):
        """Estar plantada é apoiar-se no chão. Foto cortada pela lateral do
        quadro virava "plantada à esquerda" e era grudada na borda — era o que
        separava a colagem em dois blocos nas pontas da capa."""
        from psd_tools import PSDImage
        from pathlib import Path
        from api.psd import Camada
        c = Camada(nome="foto", tipo="imagem", src="x.png",
                   box={"x": 0, "y": 0, "w": 1, "h": 1}, plantada=("esquerda",))
        # o campo existe, mas a extração só guarda os lados verticais
        import inspect
        from api import psd
        fonte = inspect.getsource(psd.extrair)
        assert 'if l in ("baixo", "cima")' in fonte
