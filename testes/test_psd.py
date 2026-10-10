"""O PSD aberto em camadas.

Com PNG a arte chega achatada e só o que a plataforma acrescenta se mexe. Com
PSD cada camada tem posição própria, e a peça inteira pode animar.

Os testes montam um PSD de verdade na hora, com pytoshop. Depender do arquivo
do cliente seria teste que só roda numa máquina — e o Key Visual do Energiza
tem 200 MB, que não entra em repositório.
"""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from api.psd import (AJUSTES, Camada, Prancheta, escolher, extrair, pranchetas)


def psd_de(tmp_path, camadas, w=400, h=300) -> Path:
    """Escreve um PSD com as camadas pedidas.

    Cada uma é (nome, cor, (x, y, w, h)) ou (nome, cor, caixa, visivel).
    """
    from pytoshop import enums, image_data
    from pytoshop.user import nested_layers as nl

    feitas = []
    for item in reversed(camadas):
        nome, cor, (x, y, cw, ch) = item[0], item[1], item[2]
        visivel = item[3] if len(item) > 3 else True
        # cada camada com o tamanho dela e a posição dela: gravar tudo do
        # tamanho da tela esconderia justamente o que o módulo precisa ler
        a = np.asarray(Image.new("RGBA", (cw, ch), cor))
        feitas.append(nl.Image(name=nome, top=y, left=x, visible=visivel,
                               channels={0: a[:, :, 0], 1: a[:, :, 1],
                                         2: a[:, :, 2], -1: a[:, :, 3]}))
    psd = nl.nested_layers_to_psd(feitas, color_mode=enums.ColorMode.rgb,
                                  size=(w, h), compression=enums.Compression.raw)
    plana = np.asarray(Image.new("RGB", (w, h), (10, 10, 40)))
    psd.image_data = image_data.ImageData(
        channels=np.stack([plana[:, :, 0], plana[:, :, 1], plana[:, :, 2]]),
        compression=enums.Compression.raw)
    alvo = tmp_path / "arte.psd"
    with alvo.open("wb") as f:
        psd.write(f)
    return alvo


@pytest.fixture
def arquivo(tmp_path):
    return psd_de(tmp_path, [
        ("fundo", (10, 20, 80, 255), (0, 0, 400, 300)),
        ("marca", (255, 255, 255, 255), (20, 30, 120, 40)),
    ])


class TestPranchetas:
    def test_arquivo_sem_prancheta_vira_uma_so(self, arquivo):
        """PSD sem prancheta é o caso comum: tratar pelo mesmo caminho evita um
        ramo a mais em tudo que vem depois."""
        ps = pranchetas(arquivo)
        assert len(ps) == 1
        assert (ps[0].nome, ps[0].w, ps[0].h) == ("", 400, 300)

    def test_a_proporcao_sai_do_tamanho(self):
        assert Prancheta("x", 0, 0, 1920, 1080).proporcao == pytest.approx(1.78, abs=0.01)


class TestEscolher:
    def _seis(self):
        return [Prancheta(f"Prancheta {i}", i * 2000, 0, 1920, 1080) for i in range(1, 7)]

    def test_por_nome(self):
        achada, chute = escolher(self._seis(), "Prancheta 4")
        assert achada.nome == "Prancheta 4" and chute is False

    def test_nome_que_nao_existe_diz_quais_existem(self):
        with pytest.raises(ValueError, match="Prancheta 1"):
            escolher(self._seis(), "Prancheta 9")

    def test_uma_so_nao_e_chute(self):
        achada, chute = escolher([Prancheta("", 0, 0, 100, 100)])
        assert chute is False

    def test_proporcao_que_nao_desempata_avisa_que_e_chute(self):
        """No arquivo real as seis pranchetas têm a mesma proporção: escolher
        por formato pegaria a errada e ficaria calado."""
        _, chute = escolher(self._seis(), proporcao=1920 / 1080)
        assert chute is True

    def test_proporcao_que_desempata_nao_e_chute(self):
        lista = [Prancheta("larga", 0, 0, 1920, 1080), Prancheta("alta", 0, 0, 1080, 1920)]
        achada, chute = escolher(lista, proporcao=0.5625)
        assert achada.nome == "alta" and chute is False

    def test_sem_nada_escolhe_a_maior_mas_avisa(self):
        lista = [Prancheta("pequena", 0, 0, 100, 100), Prancheta("grande", 0, 0, 900, 900)]
        achada, chute = escolher(lista)
        assert achada.nome == "grande" and chute is True


class TestExtrair:
    def test_cada_camada_vira_arquivo_com_posicao(self, arquivo, tmp_path):
        L = extrair(arquivo, tmp_path / "camadas")
        assert L.canvas == {"w": 400, "h": 300}
        nomes = {c.nome for c in L.camadas}
        assert nomes == {"fundo", "marca"}
        marca = next(c for c in L.camadas if c.nome == "marca")
        assert (marca.box["x"], marca.box["y"]) == (20, 30)
        assert (marca.box["w"], marca.box["h"]) == (120, 40)
        assert (tmp_path / "camadas" / marca.src).exists()

    def test_o_src_e_so_o_nome(self, arquivo, tmp_path):
        """Caminho absoluto prenderia a peça à máquina que a abriu."""
        L = extrair(arquivo, tmp_path / "camadas")
        assert all("/" not in c.src for c in L.camadas)

    def test_camada_desligada_fica_de_fora_e_e_contada(self, tmp_path):
        """O Key Visual real tinha camadas desligadas: entram na peça só se
        quem desenhou as deixou ligadas, e o que ficou de fora é dito."""
        arq = psd_de(tmp_path, [("fundo", (10, 20, 80, 255), (0, 0, 400, 300)),
                                ("rascunho", (255, 0, 0, 255), (10, 10, 50, 50), False)])
        L = extrair(arq, tmp_path / "camadas")
        assert "rascunho" not in {c.nome for c in L.camadas}
        assert any("rascunho" in i and "desligada" in i for i in L.ignoradas)

    def test_o_nome_vem_sem_o_enchimento_do_arquivo(self, arquivo, tmp_path):
        """O PSD guarda `fundo\x00`; o nulo iria para o nome do arquivo e para
        o texto que o modelo lê."""
        L = extrair(arquivo, tmp_path / "camadas")
        assert all("\x00" not in c.nome for c in L.camadas)
        assert all("\x00" not in c.src for c in L.camadas)

    def test_o_limite_de_camadas_e_dito(self, arquivo, tmp_path):
        L = extrair(arquivo, tmp_path / "camadas", limite=1)
        assert len(L.camadas) == 1
        assert any("parou em 1 camadas" in i for i in L.ignoradas)

    def test_prancheta_inexistente_recusa(self, arquivo, tmp_path):
        with pytest.raises(ValueError, match="não existe prancheta"):
            extrair(arquivo, tmp_path / "camadas", nome_prancheta="Prancheta 4")


class TestOQueOArquivoRealEnsinou:
    def test_ajuste_nao_e_camada_de_imagem(self):
        """Matiz/Saturação e Brilho/Contraste mudam o que está abaixo: extrair
        como imagem devolve nada ou um quadrado vazio."""
        assert "huesaturation" in AJUSTES and "brightnesscontrast" in AJUSTES

    def test_camada_guarda_a_fonte_pedida(self):
        """Quando a fonte não está instalada o texto sai noutra letra e ninguém
        avisa — foi o que aconteceu na primeira prancheta lida."""
        c = Camada("energiza", "texto", "x.png", {"x": 0, "y": 0, "w": 1, "h": 1},
                   texto="energiza", fonte="Blanquotey")
        assert c.fonte == "Blanquotey"
