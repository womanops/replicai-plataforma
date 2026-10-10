"""O que o motor precisa do ambiente para renderizar.

Estes três já quebraram de verdade, e nenhum deu mensagem que apontasse a causa:
o Chromium recusando abrir como root, os assets fora de alcance, e a peça saindo
sem o PNG. Teste aqui é memória do que custou caro.
"""
import subprocess

import pytest

from motor import replica


@pytest.fixture
def chrome_falso(monkeypatch):
    """Troca o Chrome por um espião: devolve os argumentos com que ele seria
    chamado, sem abrir navegador nenhum."""
    vistos = {}

    def espiar(args, **kw):
        vistos["args"] = list(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(replica, "find_chrome", lambda: "/falso/chrome")
    monkeypatch.setattr(subprocess, "run", espiar)
    return vistos


class TestBandeirasDoChrome:
    """Dentro de um contêiner o processo roda como root, e o Chromium se recusa
    a abrir sem --no-sandbox. A bandeira vem do ambiente: o Dockerfile define,
    o Mac não. Se o motor parar de ler CHROME_FLAGS, o contêiner quebra e o
    desenvolvimento local continua passando — regressão invisível."""

    def test_passa_as_bandeiras_do_ambiente(self, chrome_falso, monkeypatch):
        monkeypatch.setenv("CHROME_FLAGS", "--no-sandbox --disable-dev-shm-usage")
        replica.chrome_run("file:///x.html", ["--screenshot=/tmp/x.png"])
        assert "--no-sandbox" in chrome_falso["args"]
        assert "--disable-dev-shm-usage" in chrome_falso["args"]

    def test_sem_a_variavel_nao_inventa_bandeira(self, chrome_falso, monkeypatch):
        monkeypatch.delenv("CHROME_FLAGS", raising=False)
        replica.chrome_run("file:///x.html", [])
        assert "--no-sandbox" not in chrome_falso["args"]

    def test_a_url_vai_por_ultimo(self, chrome_falso, monkeypatch):
        """O Chrome trata o último argumento como a página. Se uma bandeira
        entrar depois da URL, ele abre aba em branco e o PNG sai vazio."""
        monkeypatch.setenv("CHROME_FLAGS", "--no-sandbox")
        replica.chrome_run("file:///pagina.html", ["--window-size=100,100"])
        assert chrome_falso["args"][-1] == "file:///pagina.html"

    def test_o_que_foi_pedido_chega_ao_chrome(self, chrome_falso, monkeypatch):
        monkeypatch.delenv("CHROME_FLAGS", raising=False)
        replica.chrome_run("file:///x.html", ["--screenshot=/tmp/peca.png"])
        assert "--screenshot=/tmp/peca.png" in chrome_falso["args"]
        assert "--headless=new" in chrome_falso["args"]

    def test_sem_navegador_o_erro_diz_o_que_fazer(self, monkeypatch):
        monkeypatch.setattr(replica, "find_chrome", lambda: None)
        with pytest.raises(RuntimeError, match="Chrome"):
            replica.chrome_run("file:///x.html", [])


class TestAssets:
    """Na skill os assets ficam um nível acima do script; na plataforma o motor
    é um pacote e eles ficam ao lado. Quando isso quebrou, o erro foi
    'formatos.json não existe' — que não diz nada sobre a causa."""

    def test_acha_a_pasta_de_assets(self):
        assert replica.ASSETS.is_dir(), f"assets não encontrada em {replica.ASSETS}"

    def test_o_template_de_composicao_existe(self):
        assert replica.TEMPLATE.is_file()
        assert "<html" in replica.TEMPLATE.read_text(encoding="utf-8").lower()

    def test_o_catalogo_existe_e_abre(self):
        assert replica.FORMATOS_JSON.is_file()
        assert replica.load_formatos()["formatos"]
