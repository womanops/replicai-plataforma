"""O adaptador que fala com a API da Anthropic.

Sem chave não dá para testar a chamada de verdade — e nem deveria: teste que
gasta dinheiro não é rodado. O que se testa aqui é tudo em volta dela: o que é
enviado, o que é feito com a resposta, e o que acontece quando ela não vem.
"""
import base64
import json

import pytest
from PIL import Image

from api.modelo import ESQUEMA, MODELO, _imagem, disponivel, responder_anthropic


class RespostaFalsa:
    def __init__(self, texto, stop_reason="end_turn", categoria=None):
        self.content = [type("B", (), {"type": "text", "text": texto})()]
        self.stop_reason = stop_reason
        self.stop_details = type("D", (), {"category": categoria})() if categoria else None


class ClienteFalso:
    def __init__(self, resposta):
        self.resposta = resposta
        self.pedidos = []
        self.messages = type("M", (), {"create": self._create})()

    def _create(self, **kw):
        self.pedidos.append(kw)
        return self.resposta


BRUTO = json.dumps({
    "elementos": [{"papel": "headline", "zona": "meio-esquerda",
                   "texto": "Chegamos", "origem": ""}],
    "descartados": [{"o_que": "apoio", "por_que": "não cabe"}],
})


@pytest.fixture
def arte(tmp_path):
    p = tmp_path / "arte.png"
    Image.new("RGB", (80, 60), (10, 40, 110)).save(p)
    return p


class TestAImagemVaiJunto:
    def test_png_vira_bloco_de_imagem(self, arte):
        b = _imagem(arte)
        assert b["type"] == "image"
        assert b["source"]["media_type"] == "image/png"
        base64.standard_b64decode(b["source"]["data"])      # decodifica

    def test_psd_nao_vai(self, tmp_path):
        """O modelo não abre PSD. Mandar bytes que ele não entende é pior do
        que compor só pelo brief."""
        p = tmp_path / "arte.psd"
        p.write_bytes(b"8BPS" + b"\0" * 100)
        assert _imagem(p) is None

    def test_arquivo_que_nao_existe_nao_derruba(self, tmp_path):
        assert _imagem(tmp_path / "sumiu.png") is None


class TestOQueEEnviado:
    def test_manda_a_arte_e_a_instrucao(self, arte):
        c = ClienteFalso(RespostaFalsa(BRUTO))
        responder_anthropic("componha isto", arte, cliente=c)
        conteudo = c.pedidos[0]["messages"][0]["content"]
        assert conteudo[0]["type"] == "image"
        assert conteudo[1]["text"] == "componha isto"

    def test_usa_o_modelo_atual_e_forca_o_esquema(self, arte):
        c = ClienteFalso(RespostaFalsa(BRUTO))
        responder_anthropic("x", arte, cliente=c)
        p = c.pedidos[0]
        assert p["model"] == MODELO
        assert p["output_config"]["format"]["schema"] == ESQUEMA

    def test_sem_imagem_manda_so_o_texto(self, tmp_path):
        c = ClienteFalso(RespostaFalsa(BRUTO))
        responder_anthropic("x", tmp_path / "arte.psd", cliente=c)
        conteudo = c.pedidos[0]["messages"][0]["content"]
        assert len(conteudo) == 1 and conteudo[0]["type"] == "text"


class TestOQueVolta:
    def test_descartados_viram_o_formato_da_conferencia(self, arte):
        """O esquema estrito não aceita chave livre, então o modelo responde
        lista; quem converte é o adaptador, não o prompt."""
        r = responder_anthropic("x", arte, cliente=ClienteFalso(RespostaFalsa(BRUTO)))
        assert r["descartados"] == {"apoio": "não cabe"}
        assert r["elementos"][0]["papel"] == "headline"

    def test_recusa_do_modelo_vira_erro_com_motivo(self, arte):
        c = ClienteFalso(RespostaFalsa("", stop_reason="refusal", categoria="general_harms"))
        with pytest.raises(RuntimeError, match="recusou"):
            responder_anthropic("x", arte, cliente=c)

    def test_resposta_vazia_nao_passa_calada(self, arte):
        c = ClienteFalso(RespostaFalsa(""))
        with pytest.raises(json.JSONDecodeError):
            responder_anthropic("x", arte, cliente=c)


class TestDisponivel:
    def test_sem_credencial_diz_que_nao(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        assert disponivel() is False

    def test_com_credencial_diz_que_sim(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
        assert disponivel() is True
