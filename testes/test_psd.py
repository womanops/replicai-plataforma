"""Leitura e escrita de PSD em camadas.

O `psd_io` já teve um bug caro: `size` do pytoshop é (largura, altura), e a
documentação sugere o contrário. Um PSD quadrado passa nos dois jeitos — por
isso o teste aqui é deliberadamente **retangular**.
"""
import json

import numpy as np
import pytest
from PIL import Image

from motor.psd_io import slug, texto_puro

pytoshop = pytest.importorskip("pytoshop", reason="pytoshop é a dependência da escrita de PSD")
from motor import psd_io  # noqa: E402


class TestSlug:
    @pytest.mark.parametrize("entrada,esperado", [
        ("CANDIDATE-SE", "candidate-se"),
        ("  Camada 1  ", "camada-1"),
        ("Foto/Capa (final)", "fotocapa-final"),
        ("", "camada"),
        ("///", "camada"),
    ])
    def test_vira_nome_de_arquivo_seguro(self, entrada, esperado):
        assert slug(entrada) == esperado

    def test_corta_nome_quilometrico(self):
        assert len(slug("x" * 200)) <= 40


class TestTextoPuro:
    @pytest.mark.parametrize("entrada,esperado", [
        ("texto\x00\x00", "texto"),          # o Photoshop deixa nulos no fim
        ("'CeraPro-Light'", "CeraPro-Light"),  # o psd-tools devolve com aspas
        ('"Bebas Neue"', "Bebas Neue"),
        (b"bytes", "bytes"),
        ("   ", None),
        (None, None),
    ])
    def test_limpa_o_que_o_photoshop_deixa(self, entrada, esperado):
        assert texto_puro(entrada) == esperado


class TestIdaEVolta:
    """Escreve um PSD e lê de volta. É o único jeito de pegar largura e altura
    trocadas: a conta fecha igual nos dois sentidos num arquivo quadrado."""

    LARGURA, ALTURA = 300, 200      # retangular de propósito

    def test_o_psd_sai_na_medida_pedida(self, tmp_path):
        camada = tmp_path / "bloco.png"
        Image.new("RGBA", (120, 60), (200, 30, 90, 255)).save(camada)
        spec = tmp_path / "camadas.json"
        spec.write_text(json.dumps({
            "w": self.LARGURA, "h": self.ALTURA,
            "camadas": [{"nome": "bloco", "png": str(camada), "x": 40, "y": 30}],
        }), encoding="utf-8")

        saida = tmp_path / "saida.psd"
        assert psd_io.cmd_write(str(saida), str(spec)) == 0
        assert saida.exists()

        from psd_tools import PSDImage
        lido = PSDImage.open(saida)
        assert (lido.width, lido.height) == (self.LARGURA, self.ALTURA), \
            f"largura e altura trocadas: saiu {lido.width}x{lido.height}"

    def test_a_camada_volta_na_posicao_certa(self, tmp_path):
        camada = tmp_path / "bloco.png"
        Image.new("RGBA", (120, 60), (200, 30, 90, 255)).save(camada)
        spec = tmp_path / "camadas.json"
        spec.write_text(json.dumps({
            "w": self.LARGURA, "h": self.ALTURA,
            "camadas": [{"nome": "bloco", "png": str(camada), "x": 40, "y": 30}],
        }), encoding="utf-8")
        saida = tmp_path / "saida.psd"
        psd_io.cmd_write(str(saida), str(spec))

        from psd_tools import PSDImage
        # a prévia achatada é gravada em RGB (sem alfa), então quem diz onde a
        # camada caiu é a cor, não a transparência
        achatada = np.asarray(PSDImage.open(saida).composite().convert("RGB"))
        dentro = achatada[60, 100]       # linha 60, coluna 100: miolo do bloco
        fora = achatada[5, 5]
        assert tuple(dentro) == (200, 30, 90), f"a camada não caiu em (40,30): achei {tuple(dentro)}"
        assert tuple(fora) != (200, 30, 90), "a camada vazou para o canto"

    def test_camada_maior_que_o_canvas_e_recortada(self, tmp_path):
        """Não recusa: recorta. O PSD continua na medida pedida e o que passou
        da borda some — melhor do que gravar um arquivo com medida errada."""
        camada = tmp_path / "grande.png"
        Image.new("RGBA", (500, 500), (10, 200, 60, 255)).save(camada)
        spec = tmp_path / "camadas.json"
        spec.write_text(json.dumps({
            "w": self.LARGURA, "h": self.ALTURA,
            "camadas": [{"nome": "grande", "png": str(camada), "x": 0, "y": 0}],
        }), encoding="utf-8")
        saida = tmp_path / "saida.psd"
        assert psd_io.cmd_write(str(saida), str(spec)) == 0

        from psd_tools import PSDImage
        lido = PSDImage.open(saida)
        assert (lido.width, lido.height) == (self.LARGURA, self.ALTURA)
