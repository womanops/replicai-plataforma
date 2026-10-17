""""Minha preocupação é que não está sendo vista uma direção de arte na hora
de replicar a peça."

Ela estava certa, e o defeito aparecia inteiro na faixa extrema: para caber num
728x90 o KV de 1920x1080 era encolhido a 8% do tamanho, virava um carimbo de
160 px com o logo do cliente ilegível, e o que sobrava da peça era tratado como
"resto". Continuar o resto, esticar o resto, chapar o resto — tudo maquiagem,
porque o erro aconteceu antes, na decisão de encolher.

O que estes testes travam é a decisão que não existia: cada proporção pede
composição própria.
"""
import json

import pytest
from PIL import Image

from api import direcao
from motor.replica import formato_by_id


def medidas(fid, W=1920, H=1080):
    return direcao.medir(W, H, formato_by_id(fid))


class TestAConta:
    def test_a_escala_e_o_que_diz_se_a_mae_ainda_se_le(self):
        """Por escala e não por área que ela ocupa: o que decide é
        legibilidade. Numa story a arte entra a 56% e tudo nela se lê, ocupando
        um terço da peça; num 728x90 ela entraria a 8%."""
        assert round(medidas("ig-stories")[0], 2) == 0.56
        assert round(medidas("gdn-728x90")[0], 2) == 0.08

    def test_inventar_e_medido_no_eixo_que_cresce(self):
        """Por eixo e não por área: o que faz o generativo repetir é a
        distância que ele tem de preencher numa direção só."""
        _, inventaria, comprido = medidas("gdn-728x90")
        assert comprido is True
        assert round(inventaria, 1) == 3.5
        assert round(medidas("ig-feed-1x1")[1], 1) == 0.8

    def test_mesma_proporcao_nao_inventa_nada(self):
        escala, inventaria, _ = medidas("li-feed-16x9")
        assert escala == 1.0 and inventaria == 0.0


class TestARegua:
    """A rede, para quando não há credencial. Ela erra para o lado seguro."""

    def _fundo(self, fid):
        escala, inventaria, comprido = medidas(fid)
        return direcao.na_regua(True, escala, inventaria, comprido)["fundo"]

    def test_a_faixa_extrema_enche_a_peca_recortando(self):
        assert self._fundo("gdn-728x90") == "encher-recortando"
        assert self._fundo("gdn-320x50") == "encher-recortando"

    def test_a_proporcao_de_perto_continua_como_sempre(self):
        """A regra é para a faixa extrema. Onde a arte ainda se lê inteira,
        reenquadrar mantém o desenho como ele foi feito."""
        for fid in ("gdn-970x250", "ig-feed-1x1", "ig-stories"):
            assert self._fundo(fid) == "continuar", fid

    def test_sem_camadas_nunca_recorta(self):
        """Num arquivo achatado a tinta está dentro do fundo: recortar comeria
        a marca. A regra da casa não é afrouxada, é lida direito."""
        escala, inventaria, comprido = medidas("gdn-728x90")
        assert direcao.na_regua(False, escala, inventaria, comprido)["fundo"] == "continuar"

    def test_a_regua_nao_escolhe_campo_de_cor(self):
        """Ela não olha a peça, e bloco de cor é a decisão mais fácil de tomar
        errado: arte pequena num campo liso lê como peça mal montada."""
        for fid in ("gdn-728x90", "gdn-320x50", "gdn-970x250", "ig-stories"):
            assert self._fundo(fid) != "campo", fid

    def test_a_assinatura_segue_a_leitura(self):
        """Medida comprida: assinatura à esquerda e assunto à direita, que é
        como se lê. Medida alta: assunto em cima, assinatura embaixo."""
        esc, inv, comp = medidas("gdn-728x90")
        assert direcao.na_regua(True, esc, inv, comp)["assinatura"] == "esquerda"
        esc, inv, comp = medidas("ig-stories")
        assert direcao.na_regua(True, esc, inv, comp)["assinatura"] == "rodape"


class TestOQueARegaRecusa:
    """Decisão que não passa é recusada inteira, e a peça volta para o
    determinístico dizendo que voltou. Remendar a escolha do modelo com a régua
    foi o que entregou peça de régua com cara de peça do modelo."""

    PARTES = [{"papel": "marca", "box": {"x": 0, "y": 0, "w": 100, "h": 50}},
              {"papel": "headline", "box": {"x": 0, "y": 60, "w": 300, "h": 80}}]

    def _ok(self, **extra):
        return {"fundo": "continuar", "assinatura": "esquerda", "marca": 0,
                "sai": [], "porque": "porque sim", **extra}

    def test_a_decisao_inteira_passa(self):
        boa, desvios = direcao.conferir(self._ok(), True, self.PARTES)
        assert boa and not desvios

    def test_recortar_sem_camadas_e_recusado(self):
        boa, desvios = direcao.conferir(self._ok(fundo="encher-recortando"),
                                        False, self.PARTES)
        assert boa is None
        assert "comeria a marca" in desvios[0]

    def test_zona_inventada_e_recusada(self):
        boa, desvios = direcao.conferir(self._ok(assinatura="diagonal"),
                                        True, self.PARTES)
        assert boa is None and desvios

    def test_tirar_a_marca_e_deixar_o_resto_e_recusado(self):
        """Sair é hierarquia: o acessório sai primeiro, a marca fica por
        último."""
        boa, desvios = direcao.conferir(self._ok(sai=["marca"]), True, self.PARTES)
        assert boa is None
        assert "hierarquia saiu ao contrário" in desvios[0]

    def test_tirar_o_acessorio_e_decisao_valida(self):
        """O que sai primeiro é o acessório — e isso não é desvio nenhum."""
        partes = self.PARTES + [{"papel": "selo",
                                 "box": {"x": 0, "y": 0, "w": 40, "h": 20}}]
        boa, desvios = direcao.conferir(self._ok(sai=["selo"]), True, partes)
        assert boa is not None and not desvios

    def test_tirar_tudo_menos_o_acessorio_e_recusado(self):
        partes = self.PARTES + [{"papel": "selo",
                                 "box": {"x": 0, "y": 0, "w": 40, "h": 20}}]
        boa, desvios = direcao.conferir(self._ok(sai=["marca", "headline"]),
                                        True, partes)
        assert boa is None and "hierarquia" in desvios[0]

    def test_tirar_o_que_a_peca_nao_tem_e_recusado(self):
        boa, desvios = direcao.conferir(self._ok(sai=["mascote"]), True, self.PARTES)
        assert boa is None and "mascote" in desvios[0]

    def test_apontar_marca_que_nao_existe_e_recusado(self):
        boa, desvios = direcao.conferir(self._ok(marca=9), True, self.PARTES)
        assert boa is None and desvios

    def test_sem_marca_nenhuma_e_resposta_valida(self):
        """Nem toda peça tem logotipo solto: -1 é resposta, não erro."""
        boa, _ = direcao.conferir(self._ok(marca=-1), True, self.PARTES)
        assert boa is not None

    def test_sem_decisao_nao_ha_desvio(self):
        """Não haver credencial não é desvio: é a plataforma funcionando com
        menos qualidade, que é o combinado."""
        assert direcao.conferir(None, True, self.PARTES) == (None, [])


class TestAChamada:
    """O modelo decide a estrutura; a máquina calcula as caixas. Mesma divisão
    do resto da casa — e nenhuma falha dele derruba a peça."""

    class Resposta:
        def __init__(self, texto, stop=None):
            self.content = [type("B", (), {"type": "text", "text": texto})()]
            self.stop_reason = stop
            self.usage = None

    class Cliente:
        def __init__(self, resposta):
            self.resposta = resposta
            self.pedidos = []

        @property
        def messages(self):
            return self

        def create(self, **k):
            self.pedidos.append(k)
            return self.resposta

    @pytest.fixture
    def arte(self, tmp_path):
        p = tmp_path / "arte.png"
        Image.new("RGB", (1920, 1080), "#0a1a55").save(p)
        return p

    def _chamar(self, arte, monkeypatch, resposta):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "de-mentira")
        monkeypatch.delenv("REPLICAI_SEM_DIRECAO", raising=False)
        cliente = self.Cliente(resposta)
        d, calou = direcao.decidir(
            arte, formato_by_id("gdn-728x90"),
            [{"papel": "marca", "box": {"x": 1, "y": 2, "w": 3, "h": 4}}],
            True, 0.08, 3.5, cliente=cliente)
        return (d, calou), cliente

    def test_a_decisao_do_modelo_chega_inteira(self, arte, monkeypatch):
        escolha = {"fundo": "encher-recortando", "assinatura": "esquerda",
                   "marca": 0, "sai": ["selo"], "porque": "a faixa pede"}
        (d, calou), _ = self._chamar(arte, monkeypatch,
                                     self.Resposta(json.dumps(escolha)))
        assert d == escolha and calou == ""

    def test_o_pedido_leva_a_medida_e_as_contas(self, arte, monkeypatch):
        """Sem elas o modelo chutaria o que a máquina já sabe medir."""
        _, cliente = self._chamar(arte, monkeypatch,
                                  self.Resposta('{"fundo":"continuar","assinatura":'
                                                '"esquerda","marca":-1,"sai":[],'
                                                '"porque":"x"}'))
        texto = " ".join(b["text"] for b in cliente.pedidos[0]["messages"][0]["content"]
                         if b.get("type") == "text")
        assert "728x90" in texto
        assert "8%" in texto, "não disse a que tamanho a arte entraria"
        assert "3.5x" in texto, "não disse quanto teria de ser inventado"
        assert "CAMADA SEPARADA: sim" in texto

    def test_recusa_do_modelo_nao_derruba_a_peca(self, arte, monkeypatch):
        (d, calou), _ = self._chamar(arte, monkeypatch,
                                     self.Resposta("{}", stop="refusal"))
        assert d is None and "recusou" in calou

    def test_resposta_torta_nao_derruba_a_peca(self, arte, monkeypatch):
        (d, calou), _ = self._chamar(arte, monkeypatch,
                                     self.Resposta("isto não é json"))
        assert d is None and "fora do contrato" in calou

    def test_sem_credencial_nao_chama(self, arte, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        assert direcao.decidir(arte, formato_by_id("gdn-728x90"), [], True,
                               0.08, 3.5) == (None, "")

    def test_chave_sem_credito_nao_derruba_a_peca(self, arte, monkeypatch):
        """Chave válida sem crédito, rede fora, limite de uso: a peça sai pela
        régua e DIZ que saiu. Uma chave assim já entregou peça de régua com
        cara de peça do modelo durante dias, calada."""
        class Explode:
            @property
            def messages(self):
                return self

            def create(self, **k):
                raise RuntimeError("401 authentication_error")

        monkeypatch.setenv("ANTHROPIC_API_KEY", "de-mentira")
        monkeypatch.delenv("REPLICAI_SEM_DIRECAO", raising=False)
        d, calou = direcao.decidir(arte, formato_by_id("gdn-728x90"), [],
                                   True, 0.08, 3.5, cliente=Explode())
        assert d is None
        assert "não respondeu" in calou and "RuntimeError" in calou

    def test_da_para_desligar_a_direcao(self, arte, monkeypatch):
        """Para rodar a esteira sem gastar chamada — e para provar, em teste,
        que a régua sozinha entrega peça."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "de-mentira")
        monkeypatch.setenv("REPLICAI_SEM_DIRECAO", "1")
        assert direcao.disponivel() is False


class TestAComposicaoSobreAArte:
    """A composição que faltava para a faixa extrema: o desenho enche a peça e
    a assinatura se apoia nele, na zona quieta. Nas outras medidas a arte cabe
    inteira e a assinatura mora na sobra; aqui não há sobra — a imagem É a
    peça, que é como se monta um leaderboard."""

    def _leitura(self, tmp_path, com_figura=True):
        from api.psd import Camada, Leitura
        from PIL import ImageDraw
        im = Image.new("RGB", (1920, 1080), (9, 60, 180))
        # um canto agitado, para o sossego ter o que recusar
        d = ImageDraw.Draw(im)
        for i in range(0, 1080, 18):
            d.line((1400, i, 1920, i), fill=(250, 250, 250), width=6)
        im.save(tmp_path / "fundo.png")
        for nome in ("a.png", "b.png", "c.png"):
            Image.new("RGBA", (40, 40), (255, 255, 255, 255)).save(tmp_path / nome)
        camadas = [
            Camada("energiza", "texto", "a.png",
                   {"x": 300, "y": 480, "w": 900, "h": 200}, texto="energiza"),
            Camada("assinatura", "texto", "c.png",
                   {"x": 300, "y": 700, "w": 500, "h": 80}, texto="Energia que vem."),
        ]
        if com_figura:
            camadas.append(Camada("Objeto Inteligente de Vetor", "imagem", "b.png",
                                  {"x": 1300, "y": 200, "w": 400, "h": 400}))
        return Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=camadas)

    def _peca(self, tmp_path, monkeypatch, fid="gdn-728x90"):
        monkeypatch.setenv("REPLICAI_SEM_DIRECAO", "1")
        monkeypatch.setenv("REPLICAI_FUNDO", "solid")
        from api.psd import recompor
        return recompor(self._leitura(tmp_path), formato_by_id(fid), tmp_path)

    def test_a_faixa_extrema_sai_pela_composicao_nova(self, tmp_path, monkeypatch):
        peca = self._peca(tmp_path, monkeypatch)
        assert peca["via"] == "psd-sobre-a-arte"

    def test_o_fundo_enche_a_peca(self, tmp_path, monkeypatch):
        """Sem faixa vazia nenhuma: a arte É a peça. Era aqui que o KV virava
        carimbo de 160 px num quadro de 728."""
        peca = self._peca(tmp_path, monkeypatch)
        f = formato_by_id("gdn-728x90")
        assert peca["_fundo"]["base_box"] == [0, 0, f["w"], f["h"]]

    def test_nada_da_tinta_foi_cortado(self, tmp_path, monkeypatch):
        """Recortar o fundo é recortar cenário. A regra da casa protege a
        TINTA, e ela continua inteira — remontada por cima."""
        peca = self._peca(tmp_path, monkeypatch)
        f = formato_by_id("gdn-728x90")
        escritos = [e for e in peca["elementos"] if e.get("papel") != "figura"]
        assert escritos
        for e in escritos:
            b = e["box"]
            assert b["x"] >= 0 and b["y"] >= 0
            assert b["x"] + b["w"] <= f["w"] and b["y"] + b["h"] <= f["h"]

    def test_a_assinatura_foge_do_desenho_agitado(self, tmp_path, monkeypatch):
        """Texto sobre o ponto agitado do fundo some. A zona é aparada ao
        pedaço quieto antes de qualquer caixa ser calculada."""
        from api.psd import _zona_da_assinatura
        f = formato_by_id("gdn-728x90")
        self._leitura(tmp_path)
        fundo = tmp_path / "chapado.png"
        im = Image.open(tmp_path / "fundo.png").resize((f["w"], f["h"]))
        im.save(fundo)
        zona = _zona_da_assinatura(fundo, f, [], "esquerda")
        assert zona is not None
        assert zona[2] <= f["w"] * 0.60, "a zona invadiu a metade agitada"

    def test_a_assinatura_nao_entra_onde_a_figura_esta(self, tmp_path, monkeypatch):
        """Foi assim que o logo do cliente caiu em cima da chamada na primeira
        tentativa: a figura acompanha o fundo e a assinatura entrou por cima."""
        from api.psd import _zona_da_assinatura
        f = formato_by_id("gdn-728x90")
        self._leitura(tmp_path)
        fundo = tmp_path / "chapado.png"
        Image.new("RGB", (f["w"], f["h"]), (9, 60, 180)).save(fundo)
        figura = [{"box": {"x": 200, "y": 0, "w": 200, "h": f["h"] - 2}}]
        zona = _zona_da_assinatura(fundo, f, figura, "esquerda")
        assert zona is not None and zona[2] <= 200

    def test_sem_zona_a_peca_volta_para_o_caminho_de_sempre(self, tmp_path, monkeypatch):
        """Nenhuma composição é melhor do que uma com a chamada em cima do
        assunto."""
        from api.psd import _zona_da_assinatura
        f = formato_by_id("gdn-728x90")
        self._leitura(tmp_path)
        fundo = tmp_path / "chapado.png"
        Image.new("RGB", (f["w"], f["h"]), (9, 60, 180)).save(fundo)
        tapando = [{"box": {"x": 0, "y": 0, "w": f["w"], "h": f["h"]}}]
        assert _zona_da_assinatura(fundo, f, tapando, "esquerda") is None

    def test_o_cenario_que_atravessa_a_peca_nao_tira_a_zona(self, tmp_path):
        """O brilho do KV atravessa a peça inteira: se ele contasse como coisa
        posta, não sobraria zona nenhuma e a composição nova nunca aconteceria.
        Quem decide se dá para ler sobre ele é o sossego."""
        from api.psd import _zona_da_assinatura
        f = formato_by_id("gdn-728x90")
        fundo = tmp_path / "chapado.png"
        Image.new("RGB", (f["w"], f["h"]), (9, 60, 180)).save(fundo)
        cenario = [{"box": {"x": 0, "y": -160, "w": 387, "h": 410}}]
        assert _zona_da_assinatura(fundo, f, cenario, "esquerda") is not None

    def test_a_figura_que_a_mae_mostrava_inteira_nao_sai_cortada(self, tmp_path, monkeypatch):
        """O logotipo do cliente saía pela metade no alto do banner: ele
        acompanha o recorte do fundo, e o recorte é de cenário."""
        peca = self._peca(tmp_path, monkeypatch)
        f = formato_by_id("gdn-728x90")
        for e in peca["elementos"]:
            if e.get("papel") != "figura" or e.get("plantado"):
                continue
            b = e["box"]
            if b["w"] <= f["w"] and b["h"] <= f["h"]:
                assert b["x"] >= 0 and b["x"] + b["w"] <= f["w"], e.get("camada")
                assert b["y"] >= 0 and b["y"] + b["h"] <= f["h"], e.get("camada")

    def test_a_medida_de_perto_nao_muda(self, tmp_path, monkeypatch):
        """A composição nova é para a faixa extrema. Onde a arte ainda se lê,
        a peça sai como sempre saiu."""
        peca = self._peca(tmp_path, monkeypatch, fid="ig-stories")
        assert peca["via"] == "psd-recompor"
