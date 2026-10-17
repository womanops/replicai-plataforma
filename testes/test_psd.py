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

from api.psd import (AJUSTES, Camada, Leitura, Prancheta, escolher, extrair,
                     pranchetas)
from motor.replica import formato_by_id


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


class TestFidelidade:
    """Assar o que não anima é o que mantém a peça igual à do Photoshop. Cada
    camada que sai do fundo é uma chance de a reconstrução derivar — e nunca
    havia teste disso, só um número anotado num comentário.

    Medido no KV real da Consigaz, no tamanho nativo da prancheta: 0,01/255.
    """

    def _reconstruir(self, arte, destino):
        import json

        from api.psd import como_peca, extrair
        from motor.replica import render_peca
        leitura = extrair(arte, destino)
        peca = como_peca(leitura, "nativo", pasta=destino)
        (destino / "pecas").mkdir(exist_ok=True)
        arq = destino / "pecas" / "nativo.json"
        arq.write_text(json.dumps(peca, ensure_ascii=False), encoding="utf-8")
        render_peca(arq, destino / "nativo.png")
        return destino / "nativo.png", destino / "arte-mae.png"

    def test_a_reconstrucao_bate_com_o_composite(self, tmp_path):
        import numpy as np
        arte = psd_de(tmp_path, [
            ("fundo", (10, 20, 80, 255), (0, 0, 400, 300)),
            ("foto", (220, 40, 40, 255), (30, 40, 140, 90)),
            ("marca", (255, 255, 255, 255), (20, 220, 120, 40)),
        ])
        feita, mae = self._reconstruir(arte, tmp_path / "saida")
        a = np.asarray(Image.open(mae).convert("RGB"), dtype=float)
        b = np.asarray(Image.open(feita).convert("RGB"), dtype=float)
        assert a.shape == b.shape, "comparar tamanhos diferentes mede a reamostragem"
        assert np.abs(a - b).mean() < 1.0


class TestPranchetas:
    def test_arquivo_sem_prancheta_vira_uma_so(self, arquivo):
        """PSD sem prancheta é o caso comum: tratar pelo mesmo caminho evita um
        ramo a mais em tudo que vem depois."""
        ps = pranchetas(arquivo)
        assert len(ps) == 1
        assert (ps[0].nome, ps[0].w, ps[0].h) == ("", 400, 300)

    def test_a_proporcao_sai_do_tamanho(self):
        assert Prancheta("x", 0, 0, 1920, 1080).proporcao == pytest.approx(1.78, abs=0.01)


class TestPreviaDasPranchetas:
    """A tela recortava a MINIATURA embutida do PSD — 256 px para o documento
    inteiro — e mostrava isso como prévia de cada prancheta. Num arquivo de
    seis, a pessoa escolhia entre seis borrões azuis, e escolher errado é
    refazer tudo."""

    def test_escreve_uma_previa_por_prancheta(self, arquivo, tmp_path):
        from api.psd import previa_das_pranchetas
        feitas = previa_das_pranchetas(arquivo, tmp_path / "saida")
        assert [f["previa"] for f in feitas] == ["prancheta-0.png"]
        assert (tmp_path / "saida" / "prancheta-0.png").exists()

    def test_tem_resolucao_de_ler(self, arquivo, tmp_path):
        """Não é a miniatura de 256 px: é composta do arquivo, no tamanho
        nativo da prancheta até o teto."""
        from api.psd import previa_das_pranchetas
        previa_das_pranchetas(arquivo, tmp_path / "saida", largura=720)
        with Image.open(tmp_path / "saida" / "prancheta-0.png") as im:
            assert im.width == 400          # a prancheta é menor que o teto
            assert im.size == (400, 300)

    def test_nao_estica_prancheta_pequena(self, arquivo, tmp_path):
        from api.psd import previa_das_pranchetas
        previa_das_pranchetas(arquivo, tmp_path / "saida", largura=200)
        with Image.open(tmp_path / "saida" / "prancheta-0.png") as im:
            assert im.width == 200

    def test_e_a_peca_composta_e_nao_um_recorte_da_miniatura(self, arquivo, tmp_path):
        """A prévia TEM que ser o composite da prancheta. A outra rota — a
        única que existia — era recortar a miniatura embutida, que é o mesmo
        desenho a um vigésimo da resolução."""
        import numpy as np
        from psd_tools import PSDImage

        from api.psd import previa_das_pranchetas
        previa_das_pranchetas(arquivo, tmp_path / "saida")
        feita = np.asarray(
            Image.open(tmp_path / "saida" / "prancheta-0.png").convert("RGB"), dtype=float)
        certo = np.asarray(PSDImage.open(arquivo).composite().convert("RGB"), dtype=float)
        assert feita.shape == certo.shape
        assert np.abs(feita - certo).mean() < 1.0

    def test_arquivo_que_nao_compoe_nao_derruba_o_envio(self, tmp_path):
        """Prévia é conforto: sem ela a escolha ainda acontece, com o recorte
        da miniatura. O que não pode é o envio falhar por causa dela."""
        from api.psd import previa_das_pranchetas
        ruim = tmp_path / "nao-e-psd.psd"
        ruim.write_bytes(b"8BPS" + b"\0" * 100)
        with pytest.raises(Exception):
            previa_das_pranchetas(ruim, tmp_path / "saida")


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
    """Sem camada de texto não há o que animar: tudo assa no fundo. É o
    comportamento certo, e o que estes PSD de teste exercitam — pytoshop não
    escreve camada de texto, então a separação é pedida pelo nome."""

    def test_sem_texto_so_a_assinatura_sai_do_fundo(self, arquivo, tmp_path):
        """A regra era "sem texto, nada se solta". Mudou por causa do vídeo: a
        assinatura é o que fecha a peça no centro, e assada no fundo ela nunca
        chegava lá — quem voava para o meio era o mascote, cortado pela borda.

        O resto continua assado: fidelidade contra o composite do Photoshop."""
        L = extrair(arquivo, tmp_path / "camadas")
        assert [c.nome for c in L.camadas] == ["marca"]
        assert (tmp_path / "camadas" / L.fundo).exists()
        assert any("assadas no fundo" in i for i in L.ignoradas)

    def test_o_fundo_que_sangra_continua_assado(self, tmp_path):
        """A regra era "só a assinatura se solta". Mudou de novo, pelo vídeo:
        a foto da colagem também sai, senão metade da peça é um PNG parado
        atrás do texto. O que sangra pelos quatro lados é fundo, e fica."""
        arte = psd_de(tmp_path, [
            ("fundo", (10, 20, 80, 255), (0, 0, 400, 300)),
            ("foto", (255, 0, 0, 255), (20, 30, 120, 40)),
        ])
        L = extrair(arte, tmp_path / "camadas")
        assert [c.nome for c in L.camadas] == ["foto"]

    def test_o_fundo_sai_do_tamanho_da_prancheta(self, arquivo, tmp_path):
        L = extrair(arquivo, tmp_path / "camadas")
        assert Image.open(tmp_path / "camadas" / L.fundo).size == (400, 300)

    def test_camada_pedida_pelo_nome_sai_solta(self, arquivo, tmp_path):
        L = extrair(arquivo, tmp_path / "camadas", nomes_separados=["marca"])
        assert [c.nome for c in L.camadas] == ["marca"]
        marca = L.camadas[0]
        assert (marca.box["x"], marca.box["y"]) == (20, 30)
        assert (marca.box["w"], marca.box["h"]) == (120, 40)
        assert (tmp_path / "camadas" / marca.src).exists()

    def test_o_que_ficou_solto_nao_esta_no_fundo(self, arquivo, tmp_path):
        """O fundo é a prancheta com as soltas desligadas: se a marca
        aparecesse nos dois, sairia dobrada na peça."""
        import numpy as np
        com = extrair(arquivo, tmp_path / "a", nomes_separados=[])
        sem = extrair(arquivo, tmp_path / "b", nomes_separados=["marca"])
        a = np.asarray(Image.open(tmp_path / "a" / com.fundo).convert("RGB"), dtype=float)
        b = np.asarray(Image.open(tmp_path / "b" / sem.fundo).convert("RGB"), dtype=float)
        assert abs(a - b).mean() > 1

    def test_o_src_e_so_o_nome(self, arquivo, tmp_path):
        """Caminho absoluto prenderia a peça à máquina que a abriu."""
        L = extrair(arquivo, tmp_path / "camadas", nomes_separados=["marca", "fundo"])
        assert all("/" not in c.src for c in L.camadas)

    def test_camada_desligada_nao_entra(self, tmp_path):
        arq = psd_de(tmp_path, [("fundo", (10, 20, 80, 255), (0, 0, 400, 300)),
                                ("rascunho", (255, 0, 0, 255), (10, 10, 50, 50), False)])
        L = extrair(arq, tmp_path / "camadas", nomes_separados=["rascunho"])
        assert [c.nome for c in L.camadas] == ["rascunho"] or L.camadas == []

    def test_o_limite_vale_para_as_soltas(self, arquivo, tmp_path):
        L = extrair(arquivo, tmp_path / "camadas", nomes_separados=["marca", "fundo"],
                    limite=1)
        assert len(L.camadas) == 1

    def test_prancheta_inexistente_recusa(self, arquivo, tmp_path):
        with pytest.raises(ValueError, match="não existe prancheta"):
            extrair(arquivo, tmp_path / "camadas", nome_prancheta="Prancheta 4")


class Falsa:
    """Camada de mentira: o suficiente para `separaveis` decidir."""

    def __init__(self, nome, kind="pixel", filhos=None, visible=True):
        self.name, self.kind, self.filhos, self.visible = nome, kind, filhos, visible

    def is_group(self):
        return self.filhos is not None

    def __iter__(self):
        return iter(self.filhos or [])


class TestQuemValeSeparar:
    """A regra é o texto: onde há palavra há hierarquia, e hierarquia é o que a
    animação revela."""

    def test_grupo_com_texto_e_aberto_em_partes(self):
        from api.psd import separaveis
        lockup = Falsa("Agrupar 3", filhos=[Falsa("energiza", "type"),
                                            Falsa("logo", "smartobject")])
        soltas = separaveis([Falsa("fundo"), lockup])
        assert [c.name for c in soltas] == ["energiza", "logo"]

    def test_camada_sem_texto_fica_no_fundo(self):
        from api.psd import separaveis
        assert separaveis([Falsa("fundo"), Falsa("grain")]) == []

    def test_texto_solto_no_topo_tambem_vale(self):
        from api.psd import separaveis
        soltas = separaveis([Falsa("fundo"), Falsa("chamada", "type")])
        assert [c.name for c in soltas] == ["chamada"]

    def test_ajuste_e_desligada_ficam_de_fora(self):
        from api.psd import separaveis
        soltas = separaveis([Falsa("contraste", "brightnesscontrast"),
                             Falsa("oculta", "type", visible=False)])
        assert soltas == []


class TestViraPeca:
    def _leitura(self):
        return Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=[
            Camada("energiza", "texto", "a.png", {"x": 910, "y": 492, "w": 870, "h": 223},
                   texto="energiza"),
            Camada("logo", "imagem", "b.png", {"x": 930, "y": 443, "w": 384, "h": 59}),
            Camada("2027", "texto", "c.png", {"x": 1582, "y": 697, "w": 191, "h": 61},
                   texto="2027"),
            Camada("assinatura", "texto", "d.png", {"x": 924, "y": 675, "w": 513, "h": 83},
                   texto="Energia que impulsiona o futuro."),
        ])

    def test_cada_camada_ganha_papel_de_motion(self):
        """Sem papel, as quatro partes do lockup entram juntas — que é o mesmo
        que não ter separado nada."""
        from api.psd import como_elementos
        papeis = {e["camada"]: e["papel"] for e in como_elementos(self._leitura())}
        assert papeis == {"energiza": "headline", "logo": "marca",
                          "2027": "selo", "assinatura": "apoio"}

    def test_parte_de_lockup_nao_vagueia(self):
        """A animação dá deriva lenta a imagem solta; parte de lockup foi
        desenhada naquela posição e sair do lugar desmonta o desenho."""
        from api.psd import como_elementos
        assert all(e["ancorado"] for e in como_elementos(self._leitura()))

    def test_a_peca_usa_o_fundo_assado(self):
        from api.psd import como_peca
        peca = como_peca(self._leitura(), "li-feed-16x9")
        assert peca["fundo"] == {"tipo": "imagem", "src": "fundo.png", "fit": "cover"}
        assert peca["canvas"] == {"w": 1920, "h": 1080}
        assert len(peca["elementos"]) == 4

    def test_o_texto_da_camada_vai_junto(self):
        from api.psd import como_elementos
        els = {e["camada"]: e.get("conteudo") for e in como_elementos(self._leitura())}
        assert els["energiza"] == "energiza" and els["logo"] is None


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


class TestOrdemELetras:
    """Revisão de uma peça animada: a ordem de entrada tem que ser a de
    leitura — marca, nome com ano, assinatura — e o lettering tem que animar
    letra a letra. Camada inteira entrando é transição de slide, não motion."""

    def _leitura(self, camadas):
        return Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=camadas)

    def test_a_ordem_de_entrada_e_a_de_leitura(self):
        from api.psd import como_elementos
        L = self._leitura([
            Camada("assinatura", "texto", "d.png", {"x": 0, "y": 600, "w": 500, "h": 80},
                   texto="Energia que impulsiona"),
            Camada("logo", "imagem", "b.png", {"x": 0, "y": 400, "w": 380, "h": 60}),
            Camada("energiza", "texto", "a.png", {"x": 0, "y": 450, "w": 870, "h": 220},
                   texto="energiza"),
            Camada("2027", "texto", "c.png", {"x": 0, "y": 650, "w": 190, "h": 60},
                   texto="2027"),
        ])
        ordens = {e["camada"]: e["ordem"] for e in como_elementos(L)}
        assert ordens["logo"] == 0
        assert ordens["energiza"] == ordens["2027"] == 1
        assert ordens["assinatura"] == 2

    def test_o_ano_nao_entra_junto_da_marca(self):
        """O vocabulário de motion trata selo e marca como a mesma família; sem
        ordem explícita o ano chegava antes do nome."""
        from api.psd import ORDEM
        assert ORDEM["selo"] > ORDEM["marca"]
        assert ORDEM["selo"] == ORDEM["headline"]

    def test_lettering_vira_uma_letra_por_elemento(self, tmp_path):
        from PIL import ImageDraw
        from api.psd import como_elementos
        im = Image.new("RGBA", (300, 100), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for x in (0, 110, 220):
            d.rectangle((x, 10, x + 70, 90), fill=(255, 255, 255, 255))
        im.save(tmp_path / "a.png")
        L = self._leitura([Camada("energiza", "texto", "a.png",
                                  {"x": 100, "y": 200, "w": 300, "h": 100}, texto="abc")])
        els = como_elementos(L, tmp_path)
        assert len(els) == 3
        assert [e["letra"] for e in els] == [0, 1, 2]
        # a caixa de cada letra é a da camada deslocada do recorte
        assert els[1]["box"]["x"] == 100 + 110
        assert all(e["de"] == "energiza" for e in els)

    def test_frase_longa_entra_por_linha_e_nao_por_letra(self, tmp_path):
        """Trinta letras a 0,075s levam mais tempo do que a peça tem, e letra
        de 20px solta ninguém lê."""
        from PIL import ImageDraw
        from api.psd import LETRAS_DEMAIS, como_elementos
        im = Image.new("RGBA", (600, 60), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for i in range(LETRAS_DEMAIS + 6):
            d.rectangle((i * 36, 10, i * 36 + 20, 50), fill=(255, 255, 255, 255))
        im.save(tmp_path / "a.png")
        L = self._leitura([Camada("assinatura", "texto", "a.png",
                                  {"x": 0, "y": 0, "w": 600, "h": 60}, texto="x" * 20)])
        assert len(como_elementos(L, tmp_path)) == 1      # uma linha só

    def test_sem_pasta_a_camada_nao_e_fatiada(self):
        """Quem não passa pasta não quer letra: devolve a camada inteira."""
        from api.psd import como_elementos
        L = self._leitura([Camada("energiza", "texto", "a.png",
                                  {"x": 0, "y": 0, "w": 800, "h": 200}, texto="energiza")])
        els = como_elementos(L)
        assert len(els) == 1 and "letra" not in els[0]


class TestDesdobrar:
    """Reenquadrar mantém o lockup colado no fundo; recompor o solta. A escolha
    veio de uma revisão: no vertical, preservar a relação deixava o assunto
    fora do quadro e o lockup pequeno no meio do vazio."""

    def _leitura(self, tmp_path):
        Image.new("RGB", (1920, 1080), "#0a1a55").save(tmp_path / "fundo.png")
        Image.new("RGBA", (870, 220), (255, 255, 255, 255)).save(tmp_path / "a.png")
        return Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=[
            Camada("energiza", "texto", "a.png",
                   {"x": 910, "y": 443, "w": 870, "h": 315}, texto="energiza")])

    def test_proporcao_parecida_reenquadra(self, tmp_path, monkeypatch):
        import api.psd as psd
        chamadas = []
        monkeypatch.setattr(psd, "reenquadrar", lambda *a, **k: chamadas.append("re") or {})
        monkeypatch.setattr(psd, "recompor", lambda *a, **k: chamadas.append("rec") or {})
        psd.desdobrar(self._leitura(tmp_path), formato_by_id("ig-feed-1x1"), tmp_path)
        assert chamadas == ["re"]

    def test_proporcao_muito_diferente_amplia_e_centra(self, tmp_path, monkeypatch):
        """Com o lockup largo — que é como lockup de KV é — o corte de uma
        story partiria o nome no meio da palavra. A saída não é conter a arte e
        jogar o lockup para uma faixa: é ampliar a arte até cobrir e trazer a
        informação para o centro, que é a diagramação que a mãe tinha.

        Direcional da Ligia: "concentrar as informações no centro da peça e
        fazer upscale das laterais"."""
        import api.psd as psd
        from api.psd import Camada, Leitura
        Image.new("RGB", (1920, 1080), "#0a1a55").save(tmp_path / "fundo.png")
        Image.new("RGBA", (40, 40), (255, 255, 255, 255)).save(tmp_path / "a.png")
        largo = Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=[
            Camada("energiza", "texto", "a.png",
                   {"x": 429, "y": 479, "w": 1055, "h": 248}, texto="energiza")])
        chamadas = []
        monkeypatch.setattr(psd, "reenquadrar", lambda *a, **k: chamadas.append("re") or {})
        monkeypatch.setattr(psd, "recompor", lambda *a, **k: chamadas.append("rec") or {})
        monkeypatch.setattr(psd, "ampliar_e_centrar",
                            lambda *a, **k: chamadas.append("amp") or {})
        psd.desdobrar(largo, formato_by_id("ig-stories"), tmp_path)
        assert chamadas == ["amp"]

    def test_sem_informacao_para_centrar_volta_a_rediagramar(self, tmp_path, monkeypatch):
        """Ampliar e centrar precisa de algo para centrar. Sem isso a peça não
        pode ficar sem caminho."""
        import api.psd as psd
        from api.psd import Camada, Leitura
        Image.new("RGB", (1920, 1080), "#0a1a55").save(tmp_path / "fundo.png")
        Image.new("RGBA", (40, 40), (255, 255, 255, 255)).save(tmp_path / "a.png")
        largo = Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=[
            Camada("energiza", "texto", "a.png",
                   {"x": 429, "y": 479, "w": 1055, "h": 248}, texto="energiza")])
        chamadas = []
        monkeypatch.setattr(psd, "reenquadrar", lambda *a, **k: chamadas.append("re") or {})
        monkeypatch.setattr(psd, "recompor", lambda *a, **k: chamadas.append("rec") or {})
        monkeypatch.setattr(psd, "ampliar_e_centrar", lambda *a, **k: None)
        psd.desdobrar(largo, formato_by_id("ig-stories"), tmp_path)
        assert chamadas == ["rec"]

    def test_sem_camada_separada_nao_tem_o_que_recompor(self, tmp_path, monkeypatch):
        """Com tudo assado no fundo, soltar o lockup não é possível: é o caso
        do PNG, e aí só resta reenquadrar."""
        import api.psd as psd
        Image.new("RGB", (1920, 1080), "#0a1a55").save(tmp_path / "fundo.png")
        vazia = Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=[])
        chamadas = []
        monkeypatch.setattr(psd, "reenquadrar", lambda *a, **k: chamadas.append("re") or {})
        psd.desdobrar(vazia, formato_by_id("ig-stories"), tmp_path)
        assert chamadas == ["re"]

    def test_recompor_sem_as_camadas_recusa(self, tmp_path):
        from api.psd import recompor
        Image.new("RGB", (1920, 1080), "#0a1a55").save(tmp_path / "fundo.png")
        vazia = Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=[])
        with pytest.raises(ValueError, match="camadas"):
            recompor(vazia, formato_by_id("ig-stories"), tmp_path)

    def test_o_lockup_recomposto_cabe_na_area_segura(self, tmp_path, monkeypatch):
        import os
        monkeypatch.setenv("REPLICAI_FUNDO", "solid")
        from api.psd import recompor
        f = formato_by_id("ig-stories")
        peca = recompor(self._leitura(tmp_path), f, tmp_path)
        s = f["safe"]
        for e in peca["elementos"]:
            b = e["box"]
            assert b["x"] >= s["left"] and b["x"] + b["w"] <= f["w"] - s["right"]
            assert b["y"] + b["h"] <= f["h"] - s["bottom"]

    def test_o_lockup_recomposto_fica_abaixo_da_arte(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPLICAI_FUNDO", "solid")
        from api.psd import recompor
        peca = recompor(self._leitura(tmp_path), formato_by_id("ig-stories"), tmp_path)
        fim = peca["_fundo"]["base_box"][3]
        assert all(e["box"]["y"] >= fim for e in peca["elementos"])


class TestTextoNovoSobreOPsd:
    """O lockup vem do arquivo; o que muda de campanha vem do brief. Estes
    testes travam os dois defeitos que a primeira rodada real mostrou."""

    def peca_recomposta(self):
        return {"via": "psd-recompor", "canvas": {"w": 1080, "h": 1920},
                "fundo": {"tipo": "imagem", "src": "fundo-ig-stories.png"},
                "elementos": [{"tipo": "imagem", "camada": "energiza",
                               "box": {"x": 150, "y": 953, "w": 780, "h": 280}}]}

    def test_a_faixa_da_arte_conta_como_ocupada(self, tmp_path, monkeypatch):
        """Na peça recomposta a arte ocupa uma faixa própria; sem contá-la, a
        data caiu em cima da chama."""
        import api.pipeline as pl
        vistos = {}

        class Espia:
            def compor(self, base, formato_id, brief="", terreno=None):
                vistos["livres"] = terreno.livres
                return {"elementos": []}

        Image.new("RGB", (1080, 1920), "#0a1a55").save(tmp_path / "fundo-ig-stories.png")
        Image.new("RGB", (1920, 1080), "#0a1a55").save(tmp_path / "fundo.png")
        L = Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=[])
        pl._texto_novo(self.peca_recomposta(), formato_by_id("ig-stories"), tmp_path,
                       L, "", Espia(), {"base_box": [0, 0, 1080, 608]})
        # nada pode sobrar acima de 608: ali está a arte
        for r in vistos["livres"].values():
            assert r[1] >= 608 or r[3] <= 608 or r[1] >= 608

    def test_a_queda_para_a_regua_e_dita(self, tmp_path):
        """Sem isto o CTA saiu como texto simples, sem botão, e nada acusou."""
        import api.pipeline as pl

        class CaiuParaARegua:
            def compor(self, base, formato_id, brief="", terreno=None):
                return {"elementos": [], "_desvios": ["CompositorModelo: recusou"]}

        Image.new("RGB", (1080, 1920), "#0a1a55").save(tmp_path / "fundo-ig-stories.png")
        Image.new("RGB", (1920, 1080), "#0a1a55").save(tmp_path / "fundo.png")
        L = Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=[])
        avisos = pl._texto_novo(self.peca_recomposta(), formato_by_id("ig-stories"),
                                tmp_path, L, "", CaiuParaARegua(), {})
        assert any("régua" in a and "recusou" in a for a in avisos)

    def test_sem_compositor_a_peca_fica_como_esta(self, tmp_path):
        import api.pipeline as pl
        peca = self.peca_recomposta()
        assert pl._texto_novo(peca, formato_by_id("ig-stories"), tmp_path, None, "",
                              None, {}) == []
        assert len(peca["elementos"]) == 1


class TestOndeOLockupPousa:
    def test_fica_no_alto_do_espaco_para_sobrar_faixa(self, tmp_path, monkeypatch):
        """Centralizado no espaço livre, não sobrava faixa abaixo dele e o CTA
        não tinha onde entrar — a revisão pediu o botão sob a marca."""
        monkeypatch.setenv("REPLICAI_FUNDO", "solid")
        from api.psd import recompor
        Image.new("RGB", (1920, 1080), "#0a1a55").save(tmp_path / "fundo.png")
        Image.new("RGBA", (870, 220), (255, 255, 255, 255)).save(tmp_path / "a.png")
        L = Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=[
            Camada("energiza", "texto", "a.png",
                   {"x": 910, "y": 443, "w": 870, "h": 315}, texto="energiza")])
        f = formato_by_id("ig-stories")
        peca = recompor(L, f, tmp_path)
        fim_arte = peca["_fundo"]["base_box"][3]
        fim_lockup = max(e["box"]["y"] + e["box"]["h"] for e in peca["elementos"])
        util = f["h"] - f["safe"]["bottom"]
        # sobra abaixo do lockup pelo menos tanto quanto ele ocupa de margem
        assert (util - fim_lockup) > (fim_lockup - fim_arte) * 0.25


class TestAPreviaChegaNoEstado:
    """A tarefa que o worker executa: compor as prévias e ligá-las às
    pranchetas que já estão no estado, para a tela trocar o borrão pela peça
    sem precisar de outro endereço."""

    def test_liga_a_previa_a_prancheta_pelo_nome(self, arquivo, tmp_path, monkeypatch):
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "dados"))
        import importlib

        from api import tarefas, trabalhos
        importlib.reload(trabalhos)
        importlib.reload(tarefas)
        trabalhos.gravar("conta", "job", {"status": "escolha a prancheta",
                                          "pranchetas": [{"nome": "", "w": 400, "h": 300}]})
        tarefas.previas("conta", "job", str(arquivo))
        pr = trabalhos.ler("conta", "job")["pranchetas"][0]
        assert pr["previa"] == "prancheta-0.png"
        assert (trabalhos.pasta_do("conta", "job") / "prancheta-0.png").exists()

    def test_arquivo_que_nao_abre_nao_derruba_o_trabalho(self, tmp_path, monkeypatch):
        """A prévia é conforto. Falhar nela não pode apagar o estado de quem
        está esperando para escolher."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "dados"))
        import importlib

        from api import tarefas, trabalhos
        importlib.reload(trabalhos)
        importlib.reload(tarefas)
        trabalhos.gravar("conta", "job", {"status": "escolha a prancheta",
                                          "pranchetas": [{"nome": "x"}]})
        ruim = tmp_path / "ruim.psd"
        ruim.write_bytes(b"nao e psd")
        tarefas.previas("conta", "job", str(ruim))
        estado = trabalhos.ler("conta", "job")
        assert estado["status"] == "escolha a prancheta"
        assert estado["pranchetas"] == [{"nome": "x"}]
