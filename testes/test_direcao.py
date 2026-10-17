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

    def test_o_cenario_e_cortado_como_a_mae_corta(self, tmp_path, monkeypatch):
        """Houve uma versão que ARRASTAVA para dentro do quadro a figura que a
        mãe mostrava inteira. Ela nasceu para salvar o logotipo do cliente — e
        o logotipo hoje anda com a assinatura. Sobre cenário ela quebrava a
        simetria: dos dois arcos iguais do stories, um ficava no lugar e o
        outro era puxado, e a peça perdia o eixo."""
        peca = self._peca(tmp_path, monkeypatch)
        f = formato_by_id("gdn-728x90")
        figuras = [e for e in peca["elementos"]
                   if e.get("papel") == "figura" and not e.get("plantado")]
        # o cenário pode sair do quadro: quem garante o que não pode sair é a
        # régua da assinatura, não um empurrão
        assert any(e["box"]["x"] < 0 or e["box"]["x"] + e["box"]["w"] > f["w"]
                   or e["box"]["y"] < 0 or e["box"]["y"] + e["box"]["h"] > f["h"]
                   for e in figuras), "nenhum cenário foi cortado pelo quadro"

    def test_a_medida_de_perto_nao_muda(self, tmp_path, monkeypatch):
        """A composição nova é para a faixa extrema. Onde a arte ainda se lê,
        a peça sai como sempre saiu."""
        peca = self._peca(tmp_path, monkeypatch, fid="ig-stories")
        assert peca["via"] == "psd-recompor"


class TestAMaeReenquadrada:
    """"O preview que aparece nas peças assim que o PSD é lido é exatamente o
    que deveria ser gerado. Por que o preview fica certo e a peça cheia de
    erros?"

    O preview da tela é um corte seco — `object-fit: cover` — e para vários
    destinos ele É a peça certa: a arte enche o formato e o que passa da borda
    fica de fora. O sistema nunca tentava isso, porque lia "nada é cortado"
    sobre a arte inteira. A regra protege a TINTA, e aqui ela é medida antes:
    se o lockup sobrevive ao corte, o corte é a melhor peça possível — não
    encolhe o desenho, não inventa fundo e não custa nada.

    Onde o preview mente também está medido: no 160x600 ele corta o nome do
    cliente no meio da palavra, e aí a peça NÃO sai por ele.
    """

    def _leitura(self, tmp_path, alto=248):
        from api.psd import Camada, Leitura
        Image.new("RGB", (1920, 1080), (9, 60, 180)).save(tmp_path / "fundo.png")
        for n in ("a.png", "b.png", "c.png"):
            Image.new("RGBA", (40, 40), (255, 255, 255, 255)).save(tmp_path / n)
        meio = 540
        return Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=[
            Camada("energiza", "texto", "a.png",
                   {"x": 429, "y": meio - alto // 2, "w": 1055, "h": alto},
                   texto="energiza"),
            Camada("apoio", "texto", "c.png",
                   {"x": 600, "y": meio + alto // 2 - 30, "w": 400, "h": 30},
                   texto="Energia que vem."),
        ])

    def test_onde_a_tinta_sobrevive_a_peca_sai_pelo_corte(self, tmp_path):
        from api.psd import ENCOLHER_ATE, cabe_cortando, como_elementos
        leitura = self._leitura(tmp_path)
        base = como_elementos(leitura, tmp_path)
        k = cabe_cortando(leitura, formato_by_id("gdn-970x250"), 1920, 1080, base)
        assert k is not None and k >= 1 - ENCOLHER_ATE

    def test_onde_ela_seria_cortada_no_meio_da_palavra_nao_sai(self, tmp_path):
        """O 160x600 é o caso: o corte seco parte o nome do cliente ao meio, e
        em miniatura isso passa despercebido."""
        from api.psd import ENCOLHER_ATE, cabe_cortando, como_elementos
        leitura = self._leitura(tmp_path)
        base = como_elementos(leitura, tmp_path)
        k = cabe_cortando(leitura, formato_by_id("gdn-160x600"), 1920, 1080, base)
        assert k is not None and k < 1 - ENCOLHER_ATE

    def test_o_corte_enche_a_peca(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPLICAI_FUNDO", "solid")
        from api.psd import desdobrar
        f = formato_by_id("gdn-970x250")
        peca = desdobrar(self._leitura(tmp_path), f, tmp_path)
        assert peca["via"] == "psd-reenquadra-cortando"
        assert peca["_fundo"]["base_box"] == [0, 0, f["w"], f["h"]]

    def test_nada_do_lockup_fica_de_fora(self, tmp_path, monkeypatch):
        """É a regra da casa, lida onde ela vale: a tinta."""
        monkeypatch.setenv("REPLICAI_FUNDO", "solid")
        from api.psd import desdobrar
        f = formato_by_id("gdn-728x90")
        peca = desdobrar(self._leitura(tmp_path), f, tmp_path)
        assert peca["via"] == "psd-reenquadra-cortando"
        for e in peca["elementos"]:
            if e.get("papel") == "figura" or e.get("plantado"):
                continue
            b = e["box"]
            assert b["x"] >= 0 and b["y"] >= 0, e.get("camada")
            assert b["x"] + b["w"] <= f["w"] and b["y"] + b["h"] <= f["h"], e.get("camada")

    def test_o_lockup_encolhe_junto_e_nao_se_desmonta(self, tmp_path, monkeypatch):
        """Encolher parte por parte espatifaria a colagem: a relação entre as
        linhas é o desenho."""
        monkeypatch.setenv("REPLICAI_FUNDO", "solid")
        from api.psd import desdobrar
        f = formato_by_id("gdn-728x90")
        peca = desdobrar(self._leitura(tmp_path), f, tmp_path)
        caixas = {e["camada"]: e["box"] for e in peca["elementos"] if e.get("camada")}
        assert caixas["energiza"]["y"] < caixas["apoio"]["y"], "o apoio subiu acima do nome"
        a = caixas["energiza"]["w"] / caixas["apoio"]["w"]
        assert round(a, 1) == round(1055 / 400, 1), "as partes encolheram em escalas diferentes"

    def test_a_marca_encostada_no_lockup_anda_com_ele(self, tmp_path):
        """O logotipo do cliente chega com nome genérico do Photoshop e, tratado
        como desenho de fundo, saía fora do corte — ou empurrado para cima do
        nome da campanha."""
        from api.psd import _da_assinatura, tinta_de, tinta_com_a_marca
        from api.psd import Camada, Leitura
        leitura = self._leitura(tmp_path)
        logo = {"tipo": "imagem", "papel": "figura",
                "box": {"x": 700, "y": 400, "w": 300, "h": 50}}
        cenario = {"tipo": "imagem", "papel": "figura",
                   "box": {"x": 0, "y": 0, "w": 1900, "h": 1000}}
        t = tinta_de(leitura)
        assert _da_assinatura(logo, t, 1920, 1080) is True
        assert _da_assinatura(cenario, t, 1920, 1080) is False
        ampliada = tinta_com_a_marca(leitura, [logo, cenario], 1920, 1080)
        assert ampliada[1] <= 400, "a caixa do lockup não subiu para incluir o logotipo"

    def test_sem_camadas_o_corte_nao_acontece(self, tmp_path, monkeypatch):
        """Num arquivo achatado a tinta está dentro do fundo e o corte a
        comeria — a regra não é afrouxada, é lida direito."""
        monkeypatch.setenv("REPLICAI_FUNDO", "solid")
        from api.psd import Leitura, desdobrar
        Image.new("RGB", (1920, 1080), (9, 60, 180)).save(tmp_path / "fundo.png")
        vazia = Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=[])
        peca = desdobrar(vazia, formato_by_id("gdn-970x250"), tmp_path)
        assert peca["via"] == "psd-reenquadra"


class TestOQueNaoVaiSerLidoNaoEntra:
    """Da skill de replicação da casa: "quando o formato é muito mais estreito
    que a arte-mãe, reduza a mensagem a uma headline e ao logo".

    O catálogo já dizia o mesmo pelo outro lado — o 728x90 e o 320x50 têm
    `apoio_max: 0` — e a reconstrução levava a linha de apoio assim mesmo, com
    7 px de altura: sujeira em cima da arte que ainda obrigava o resto do
    lockup a encolher para abrir espaço para ela.
    """

    def _elementos(self):
        return [
            {"papel": "headline", "box": {"x": 100, "y": 20, "w": 500, "h": 60},
             "camada": "nome"},
            # o "20" e o "27" ficam um de cada lado do nome, na altura dele
            {"papel": "selo", "box": {"x": 60, "y": 30, "w": 30, "h": 20},
             "camada": "20"},
            {"papel": "selo", "box": {"x": 610, "y": 30, "w": 30, "h": 20},
             "camada": "27"},
            # a linha de apoio mora numa faixa própria, abaixo
            {"papel": "apoio", "box": {"x": 300, "y": 95, "w": 300, "h": 14},
             "camada": "assinatura"},
        ]

    def test_a_linha_que_nao_se_le_sai(self):
        from api.psd import _so_o_que_se_le
        fica, fora = _so_o_que_se_le(self._elementos(), 0.5)   # 14 px * 0.5 = 7
        assert "apoio" in fora
        assert all(e["papel"] != "apoio" for e in fica)

    def test_e_a_peca_diz_qual_saiu_e_por_que(self):
        from api.psd import LETRA_MINIMA, _so_o_que_se_le
        _, fora = _so_o_que_se_le(self._elementos(), 0.5)
        assert f"{LETRA_MINIMA} px" in fora["apoio"]

    def test_o_que_esta_na_linha_da_chamada_e_a_chamada(self):
        """O "20" e o "27" são o ano da campanha, colados no nome. Tirá-los por
        serem pequenos deixa a marca sem o ano — e eles estão na mesma linha,
        que é quem divide lockup em toda a casa."""
        from api.psd import _so_o_que_se_le
        fica, fora = _so_o_que_se_le(self._elementos(), 0.5)
        assert "selo" not in fora
        assert sum(1 for e in fica if e["papel"] == "selo") == 2

    def test_a_chamada_nunca_sai(self):
        """Peça sem chamada não é a peça. Se ela não couber, o caminho é
        outro — não é tirar a chamada."""
        from api.psd import _so_o_que_se_le
        fica, fora = _so_o_que_se_le(self._elementos(), 0.05)
        assert "headline" not in fora
        assert any(e["papel"] == "headline" for e in fica)

    def test_o_que_se_le_fica_como_esta(self):
        from api.psd import _so_o_que_se_le
        fica, fora = _so_o_que_se_le(self._elementos(), 1.0)
        assert fora == {} and len(fica) == 4

    def test_sem_a_linha_o_resto_cabe_maior(self):
        """É o motivo de tirar antes de encolher, e não depois."""
        from api.psd import _quanto_cabe, _so_o_que_se_le
        f = formato_by_id("gdn-728x90")
        todos = self._elementos()
        com = _quanto_cabe(todos, f)
        fica, _ = _so_o_que_se_le(todos, 0.5)
        sem = _quanto_cabe(fica, f)
        assert sem > com

    def test_o_lockup_entra_no_quadro_mesmo_quando_ja_cabe(self):
        """O logotipo do cliente saía dois pixels acima da borda no 320x50: a
        peça cabia, e ninguém trazia o bloco para dentro."""
        from api.psd import _caber
        f = formato_by_id("gdn-320x50")
        fora = [{"papel": "headline", "assinatura": True,
                 "box": {"x": 40, "y": -2, "w": 200, "h": 30}}]
        dentro = _caber(fora, f, 1.0)[0]["box"]
        assert dentro["y"] >= 0
        assert dentro["y"] + dentro["h"] <= f["h"]


class TestOndeOLockupSeLe:
    """A plataforma escolhia lugar para o texto medindo se o fundo é LISO.
    Fundo liso e claro passa na régua, e letra branca some nele — foi o lockup
    fantasma do 970x250 e o do stories.

    Agora a escolha pergunta também se a letra se LÊ ali. E pergunta medindo
    onde a letra está, bloco a bloco: a média mente duas vezes, uma na caixa e
    outra no lockup inteiro.
    """

    def _camada(self, tmp_path, nome):
        from PIL import ImageDraw
        im = Image.new("RGBA", (300, 60), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle((10, 15, 290, 45), fill=(255, 255, 255, 255))
        im.save(tmp_path / nome)
        return {"tipo": "imagem", "papel": "headline", "src": nome,
                "box": {"x": 0, "y": 0, "w": 300, "h": 60}}

    def test_a_faixa_que_le_ganha_da_faixa_maior(self, tmp_path):
        """A maior era o único critério, e a maior era a branca."""
        from api.psd import _faixa_livre
        f = {"id": "x", "w": 1000, "h": 400,
             "safe": {"top": 10, "bottom": 10, "left": 10, "right": 10}}
        fundo = tmp_path / "fundo.png"
        im = Image.new("RGB", (1000, 400), (250, 250, 250))      # tudo claro
        im.paste(Image.new("RGB", (300, 400), (8, 10, 24)), (0, 0))  # faixa escura à esquerda
        im.save(fundo)
        # a arte no meio deixa duas faixas: a da direita é maior, a da esquerda lê
        base_box = [300, 0, 500, 400]
        sem_cor = _faixa_livre(base_box, f)
        com_cor = _faixa_livre(base_box, f, fundo, (255, 255, 255))
        assert sem_cor[0] >= 500, "sem a cor, a escolha é a faixa maior"
        assert com_cor[0] < 300, "com a cor, ganha a faixa em que a letra se lê"

    def test_sem_a_cor_da_tinta_a_conta_antiga_vale(self, tmp_path):
        """Arte sem camada separada não tem cor de tinta para medir, e a peça
        não pode parar por isso."""
        from api.psd import _faixa_livre
        f = {"id": "x", "w": 1000, "h": 400,
             "safe": {"top": 10, "bottom": 10, "left": 10, "right": 10}}
        assert _faixa_livre([300, 0, 500, 400], f) is not None

    def test_a_nota_da_posicao_e_a_do_pior_bloco(self, tmp_path):
        """Dois blocos bons e um que some dão uma média boa. Quem some é a
        palavra, não a média."""
        from PIL import Image as Im

        from api.psd import _nota_da_posicao
        bons = [self._camada(tmp_path, f"b{i}.png") for i in range(3)]
        for i, e in enumerate(bons):
            e["box"] = {"x": 0, "y": i * 60, "w": 300, "h": 60}
        fundo = Im.new("RGB", (300, 180), (8, 10, 24))
        fundo.paste(Im.new("RGB", (300, 60), (250, 250, 250)), (0, 120))  # o terceiro cai no claro
        caixa = (0, 0, 300, 180)
        nota = _nota_da_posicao(fundo, bons, tmp_path, caixa, 1.0, 150, 90)
        assert nota == 0.0, "a média dos três esconderia o bloco que some"

    def test_com_tudo_no_escuro_a_nota_e_alta(self, tmp_path):
        from PIL import Image as Im

        from api.psd import _nota_da_posicao
        bons = [self._camada(tmp_path, f"c{i}.png") for i in range(3)]
        for i, e in enumerate(bons):
            e["box"] = {"x": 0, "y": i * 60, "w": 300, "h": 60}
        fundo = Im.new("RGB", (300, 180), (8, 10, 24))
        assert _nota_da_posicao(fundo, bons, tmp_path, (0, 0, 300, 180), 1.0, 150, 90) > 10

    def test_o_bloco_desce_dentro_da_faixa_ate_onde_le(self, tmp_path):
        """Em vez de sair da composição, ele anda dentro da própria faixa."""
        from api.psd import _onde_le_na_faixa
        e = self._camada(tmp_path, "d.png")
        fundo = tmp_path / "f.png"
        im = Image.new("RGB", (400, 800), (250, 250, 250))
        im.paste(Image.new("RGB", (400, 300), (8, 10, 24)), (0, 500))   # o escuro está embaixo
        im.save(fundo)
        faixa = (0, 0, 400, 800)
        convencao = 100.0                       # a convenção manda para o alto, que é claro
        onde = _onde_le_na_faixa(fundo, faixa, 60, (255, 255, 255), convencao,
                                 [e], tmp_path, (0, 0, 300, 60), 1.0)
        assert onde > 500, "ficou no claro, onde a letra some"

    def test_quando_a_convencao_le_ela_e_mantida(self, tmp_path):
        """A régua corrige o que não lê; ela não redesenha a peça por gosto."""
        from api.psd import _onde_le_na_faixa
        e = self._camada(tmp_path, "e.png")
        fundo = tmp_path / "g.png"
        Image.new("RGB", (400, 800), (8, 10, 24)).save(fundo)
        onde = _onde_le_na_faixa(fundo, (0, 0, 400, 800), 60, (255, 255, 255), 100.0,
                                 [e], tmp_path, (0, 0, 300, 60), 1.0)
        assert abs(onde - 100.0) <= 50, "mexeu num lugar que já lia"


class TestInformacaoNoCentro:
    """Direcional da Ligia, depois de ver o stories sair com a arte em cima e
    o lockup numa faixa: *"precisamos sempre concentrar as informações no
    centro da peça e fazer upscale das laterais"*.

    A arte-mãe do Energiza é centrada — o lockup está a 49,8% da largura e
    52,5% da altura. Conter a arte e jogar a informação para uma borda preserva
    cada pixel do lockup e mesmo assim desmonta a diagramação dela.

    A saída separa as duas escalas: o desenho é AMPLIADO até cobrir a peça, a
    informação é REDUZIDA até caber, no centro. É o que permite preservar as
    duas coisas numa proporção que não comporta as duas na mesma escala.
    """

    def _leitura(self, tmp_path):
        from api.psd import Camada, Leitura
        Image.new("RGB", (1920, 1080), (9, 60, 180)).save(tmp_path / "fundo.png")
        for n in ("a.png", "b.png"):
            Image.new("RGBA", (40, 40), (255, 255, 255, 255)).save(tmp_path / n)
        return Leitura(canvas={"w": 1920, "h": 1080}, fundo="fundo.png", camadas=[
            # centrado na mãe, como a arte dela é
            Camada("energiza", "texto", "a.png",
                   {"x": 429, "y": 479, "w": 1055, "h": 248}, texto="energiza"),
            Camada("grafismo", "imagem", "b.png",
                   {"x": 0, "y": 0, "w": 500, "h": 1080}),
        ])

    def _peca(self, tmp_path, monkeypatch, fid="ig-stories"):
        monkeypatch.setenv("REPLICAI_FUNDO", "solid")
        monkeypatch.setenv("REPLICAI_SEM_DIRECAO", "1")
        from api.psd import desdobrar
        return desdobrar(self._leitura(tmp_path), formato_by_id(fid), tmp_path)

    def test_a_medida_que_nao_comporta_a_relacao_amplia_e_centra(self, tmp_path, monkeypatch):
        assert self._peca(tmp_path, monkeypatch)["via"] == "psd-ampliar-e-centrar"

    def test_a_arte_cobre_a_peca_inteira(self, tmp_path, monkeypatch):
        """Upscale das laterais: sem faixa vazia, sem fundo inventado."""
        peca = self._peca(tmp_path, monkeypatch)
        f = formato_by_id("ig-stories")
        x0, y0, x1, y1 = peca["_fundo"]["base_box"]
        # um pixel de arredondamento é a conta da escala, não faixa vazia
        assert x0 <= 1 and y0 <= 1
        assert x1 >= f["w"] - 1 and y1 >= f["h"] - 1

    def test_a_informacao_fica_no_centro(self, tmp_path, monkeypatch):
        from api.psd import _caixa
        peca = self._peca(tmp_path, monkeypatch)
        f = formato_by_id("ig-stories")
        escritos = [e for e in peca["elementos"]
                    if e.get("papel") in ("headline", "apoio", "selo", "marca")]
        x0, y0, x1, y1 = _caixa(escritos)
        assert abs((x0 + x1) / 2 - f["w"] / 2) <= 2, "saiu do centro na largura"
        assert abs((y0 + y1) / 2 - f["h"] / 2) <= 2, "saiu do centro na altura"

    def test_a_informacao_cabe_na_area_segura(self, tmp_path, monkeypatch):
        from api.psd import _caixa
        peca = self._peca(tmp_path, monkeypatch)
        f = formato_by_id("ig-stories")
        s = f["safe"]
        x0, y0, x1, y1 = _caixa([e for e in peca["elementos"]
                                 if e.get("papel") in ("headline", "apoio", "selo", "marca")])
        assert x0 >= s["left"] and x1 <= f["w"] - s["right"]
        assert y0 >= s["top"] and y1 <= f["h"] - s["bottom"]

    def test_desenho_e_informacao_tem_escalas_proprias(self, tmp_path, monkeypatch):
        """É o que permite preservar as duas coisas: o desenho cresce, a
        informação encolhe. Na mesma escala, uma das duas se perde."""
        peca = self._peca(tmp_path, monkeypatch)
        texto = next(e for e in peca["elementos"] if e.get("papel") == "headline")
        desenho = next(e for e in peca["elementos"] if e.get("papel") == "figura")
        k_texto = texto["box"]["w"] / 1055
        k_desenho = desenho["box"]["w"] / 500
        assert k_desenho > 1 > k_texto, (k_desenho, k_texto)
