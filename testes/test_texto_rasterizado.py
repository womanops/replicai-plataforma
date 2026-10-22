"""PSD cujo texto veio rasterizado.

Defeito achado gravando o vídeo da landing, numa rodada real da Torra: a peça
saía SEM O TÍTULO e com `status: pronto`, `avisos: {}`. No yt-thumb a caixa do
título tinha ido parar em `y=-746`, inteira fora do quadro de 720 px.

A causa é de leitura, não de diagramação. Muito PSD de cliente chega com o
texto achatado em camada de pixel — e ali `tipo == "texto"` não existe para
ninguém. Duas contas tratavam essas camadas como DESENHO:

- `tinta_de`, que devolvia só a camada com cara de marca quando não havia
  camada de texto nenhuma: a tinta virava a caixa da logomarca sozinha, e
  título, apoio e botão passavam a ser "fundo";
- `_da_assinatura`, que manda qualquer `figura` maior que 2% da peça
  acompanhar o fundo.

Cortando o fundo, a frase da peça ia junto para fora.
"""
import pytest

from api.psd import (Camada, Leitura, _da_assinatura, o_que_saiu_do_quadro,
                     so_camadas_de_pixel, tinta_de)


def camada(nome, x, y, w, h, tipo="imagem", plantada=()):
    return Camada(nome=nome, tipo=tipo, src=f"{nome}.png",
                  box={"x": x, "y": y, "w": w, "h": h}, plantada=tuple(plantada))


def leitura_torra():
    """A arte da Torra, reduzida: quatro camadas de pixel, nenhuma de texto."""
    return Leitura(fundo="fundo.png", camadas=[
        camada("Título", 114, 167, 843, 270),
        camada("Apoio", 117, 511, 683, 36),
        camada("Logo", 111, 1760, 421, 117),
        camada("Botão", 1104, 1771, 384, 97)])


class TestOArquivoSemCamadaDeTexto:
    def test_e_reconhecido(self):
        assert so_camadas_de_pixel(leitura_torra())

    def test_com_uma_camada_de_texto_ja_nao_e(self):
        l = leitura_torra()
        l.camadas.append(camada("Chamada", 0, 0, 10, 10, tipo="texto"))
        assert not so_camadas_de_pixel(l)

    def test_a_tinta_e_todo_o_conteudo_e_nao_so_a_marca(self):
        """Era aqui que começava: `Logo` casa com a marca, a lista saía com
        um item só, e a tinta virava a caixa da logomarca."""
        x0, y0, x1, y1 = tinta_de(leitura_torra())
        assert (x0, y0) == (111, 167), "a tinta não começa no título"
        assert y1 >= 1877, f"a tinta termina em {y1}: o botão ficou de fora"
        assert y1 - y0 > 1000, "a tinta virou a caixa de uma camada só"

    def test_a_camada_solta_vira_conteudo_e_nao_desenho(self):
        """Um título de 843x270 passa de longe dos 2% que a régua de área
        deixa entrar — e era por isso que ele acompanhava o fundo."""
        titulo = {"papel": "figura", "box": {"x": 114, "y": 167, "w": 843, "h": 270}}
        tinta = (111, 167, 1488, 1877)
        assert not _da_assinatura(titulo, tinta, 1620, 2160, False)
        assert _da_assinatura(titulo, tinta, 1620, 2160, True)

    def test_desenho_plantado_na_borda_continua_sendo_fundo(self):
        """A foto sangra de propósito: ela não vira lockup por não haver
        camada de texto no arquivo."""
        foto = {"papel": "figura", "plantado": ["left", "top"],
                "box": {"x": 0, "y": 0, "w": 1620, "h": 2160}}
        assert not _da_assinatura(foto, (1, 1, 2, 2), 1620, 2160, True)


class TestNadaSaiDoQuadroCalado:
    """A rede de segurança: entregar a peça sem o que ela diz, e ainda dizer
    "pronto", é o pior jeito de errar."""

    def _formato(self):
        return {"id": "yt-thumb", "w": 1280, "h": 720,
                "safe": {"left": 0, "right": 0, "top": 0, "bottom": 0}}

    def test_o_que_ficou_fora_e_apontado(self):
        els = [{"camada": "Título", "box": {"x": 91, "y": -746, "w": 674, "h": 216}},
               {"camada": "Logo", "box": {"x": 89, "y": 528, "w": 337, "h": 94}}]
        assert o_que_saiu_do_quadro(els, self._formato()) == [0]

    def test_um_canto_sangrando_nao_e_estar_fora(self):
        """Peça de borda a borda é projeto, não defeito."""
        els = [{"camada": "Foto", "box": {"x": -20, "y": -10, "w": 1320, "h": 740}}]
        assert o_que_saiu_do_quadro(els, self._formato()) == []

    def test_desenho_plantado_sangra_a_vontade(self):
        els = [{"camada": "Faixa", "plantado": ["left"],
                "box": {"x": -900, "y": 0, "w": 1000, "h": 720}}]
        assert o_que_saiu_do_quadro(els, self._formato()) == []

    def test_metade_fora_ja_conta(self):
        els = [{"camada": "Título", "box": {"x": 0, "y": -200, "w": 600, "h": 300}}]
        assert o_que_saiu_do_quadro(els, self._formato()) == [0]


@pytest.mark.lento
class TestAPecaDaTorraSaiInteira:
    """A prova no arquivo de verdade, com as seis medidas da rodada."""

    def test_nenhum_elemento_fora_do_quadro(self, tmp_path):
        from pathlib import Path

        from api.psd import como_o_arquivo_pede, desdobrar, extrair
        from motor.replica import formato_by_id
        arte = Path("/Users/ligia/Desktop/OPERAÇÃO CLAUDE CODE/ReplicAI/entrada"
                    "/_torra-arte-mae/torra-arte-mae.psd")
        if not arte.exists():
            pytest.skip("a arte da Torra não está nesta máquina")
        leitura = como_o_arquivo_pede(extrair(arte, tmp_path))
        for fid in ("yt-thumb", "ads-meta-1x1", "gdn-728x90", "ig-stories",
                    "site-hero", "li-feed-16x9"):
            f = formato_by_id(fid)
            peca = desdobrar(leitura, f, tmp_path)
            peca.pop("_fundo", {})
            fora = o_que_saiu_do_quadro(peca["elementos"], f)
            assert not fora, f"{fid}: elemento {fora} fora do quadro"
            camadas = {e.get("camada") for e in peca["elementos"]}
            assert "Título" in camadas, f"{fid} saiu sem o título"
