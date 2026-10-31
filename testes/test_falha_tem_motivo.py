"""A falha que não deixa motivo.

Em 31/10/2026 ela subiu um PSD de 127 MB e disse "o upload não aparece
prévia, nem ao menos dos formatos". O arquivo tinha duas pranchetas e as duas
saíram com `previa` vazia. A causa era uma biblioteca que faltava — a que
desenha efeito de camada — e esse motivo **nunca chegou a lugar nenhum**:
dois `except` mudos, um em `psd.previa_das_pranchetas` e outro em
`tarefas.previas`, o engoliram. A tela ficou dizendo "compondo a prévia…"
para sempre, a extração logo depois esvaziou 96 das 99 camadas pelo MESMO
motivo, e a peça saiu com doze ressalvas que pareciam doze defeitos novos.

É o padrão que mais custou caro neste projeto: a falha calada não some, ela
reaparece noutro lugar com outra cara. Estes testes seguram as duas pontas —
o motivo nasce, e ele chega à tela.
"""
import json
from pathlib import Path

import pytest

from api import psd, tarefas

RAIZ = Path(__file__).resolve().parent.parent


class TestOMotivoNasce:
    """Quem não compôs diz por quê, na mesma lista de quem compôs."""

    def test_prancheta_que_explode_volta_com_motivo(self, tmp_path, monkeypatch):
        monkeypatch.setattr(psd, "_abrir", lambda _: [])
        monkeypatch.setattr(psd, "pranchetas",
                            lambda _: [psd.Prancheta("capa", 0, 0, 100, 100)])

        feitas = psd.previa_das_pranchetas(tmp_path / "x.psd", tmp_path / "saida")

        assert len(feitas) == 1, "a prancheta que falhou sumia da lista"
        assert feitas[0]["previa"] == ""
        assert feitas[0]["motivo"], "voltou sem prévia E sem motivo: é o bug"

    def test_o_motivo_da_biblioteca_manda_para_a_instalacao(self):
        """Faltar `scikit-image` não é limitação da ferramenta: é máquina
        montada pela metade. A frase tem que mandar para o lugar certo."""
        frase = psd._porque_falhou(ImportError("Layer effects require: scikit-image"))

        assert "scikit-image" in frase
        assert "requirements" in frase, "não disse o que fazer"
        assert "ImportError" not in frase

    @pytest.mark.parametrize("pacote", sorted(psd.POR_FORA))
    def test_toda_biblioteca_declarada_tem_frase_propria(self, pacote):
        frase = psd._porque_falhou(ImportError(f"requires: {pacote}"))
        assert pacote in frase and "requirements" in frase

    def test_falha_que_nao_e_import_leva_a_mensagem_junto(self):
        """`type(e).__name__` sozinho é "ImportError" com outro nome: diz a
        categoria e esconde o fato. "KeyError" não diz QUAL chave."""
        frase = psd._porque_falhou(KeyError("b'vstk'"))

        assert "KeyError" in frase
        assert "vstk" in frase, "a mensagem foi jogada fora; sobrou a classe"

    def test_sem_mensagem_sobra_a_classe_e_tudo_bem(self):
        assert psd._porque_falhou(RuntimeError()) == "RuntimeError"


class TestOMotivoChegaAoTrabalho:
    """O arquivo que não abre tem que deixar rastro no trabalho."""

    def test_arquivo_que_nao_abre_marca_todas_as_pranchetas(self, tmp_path, monkeypatch):
        gravado = {}
        monkeypatch.setattr(tarefas.trabalhos, "pasta_do", lambda c, j: tmp_path)
        monkeypatch.setattr(tarefas.trabalhos, "ler", lambda c, j: {
            "pranchetas": [{"nome": "capa", "previa": ""},
                           {"nome": "verso", "previa": ""}]})
        monkeypatch.setattr(tarefas.trabalhos, "gravar",
                            lambda c, j, d: gravado.update(d))
        monkeypatch.setattr(psd, "previa_das_pranchetas",
                            lambda *a, **k: (_ for _ in ()).throw(
                                ImportError("requires: aggdraw")))

        tarefas.previas("conta", "job", str(tmp_path / "x.psd"))

        assert gravado, "o `except` era mudo e `return`: nada era gravado"
        for p in gravado["pranchetas"]:
            assert "aggdraw" in p["motivo"]

    def test_prancheta_que_compoe_nao_fica_com_motivo_velho(self, tmp_path, monkeypatch):
        """Compôs na segunda tentativa: o motivo da primeira não pode ficar
        pendurado dizendo que deu errado."""
        gravado = {}
        monkeypatch.setattr(tarefas.trabalhos, "pasta_do", lambda c, j: tmp_path)
        monkeypatch.setattr(tarefas.trabalhos, "ler", lambda c, j: {
            "pranchetas": [{"nome": "capa", "previa": "", "motivo": "falhou antes"}]})
        monkeypatch.setattr(tarefas.trabalhos, "gravar",
                            lambda c, j, d: gravado.update(d))
        monkeypatch.setattr(psd, "previa_das_pranchetas",
                            lambda *a, **k: [{"nome": "capa", "previa": "p-0.png"}])

        tarefas.previas("conta", "job", str(tmp_path / "x.psd"))

        p = gravado["pranchetas"][0]
        assert p["previa"] == "p-0.png"
        assert "motivo" not in p

    def test_a_escolha_dela_nao_e_apagada(self, tmp_path, monkeypatch):
        """A prévia chega depois da escolha. Sobrescrever a lista inteira
        levava junto o que já tinha sido decidido."""
        gravado = {}
        monkeypatch.setattr(tarefas.trabalhos, "pasta_do", lambda c, j: tmp_path)
        monkeypatch.setattr(tarefas.trabalhos, "ler", lambda c, j: {
            "pranchetas": [{"nome": "capa", "previa": "", "x": 0, "w": 1080}]})
        monkeypatch.setattr(tarefas.trabalhos, "gravar",
                            lambda c, j, d: gravado.update(d))
        monkeypatch.setattr(psd, "previa_das_pranchetas",
                            lambda *a, **k: [{"nome": "capa", "previa": "p-0.png"}])

        tarefas.previas("conta", "job", str(tmp_path / "x.psd"))

        assert gravado["pranchetas"][0]["w"] == 1080


class TestATelaMostraOMotivo:
    """De nada adianta o motivo existir no servidor e morrer lá."""

    def tela(self):
        return (RAIZ / "web" / "index.html").read_text()

    def test_o_cartao_da_prancheta_troca_a_espera_pelo_motivo(self):
        tela = self.tela()
        assert "if (!pr.previa && pr.motivo){" in tela, (
            "sem isto o cartão diz 'compondo a prévia…' para sempre — que é a "
            "cara da falha calada na tela")
        assert "nao-saiu" in tela

    def test_o_motivo_sai_escapado(self):
        assert "esc(pr.motivo)" in self.tela(), (
            "motivo vem de nome de camada do arquivo do cliente: entra escapado")


class TestAMaquinaVemInteira:
    """As bibliotecas que faltavam na máquina dela têm de vir declaradas, ou
    o servidor de produção nasce com o defeito de 31/10."""

    def test_as_bibliotecas_do_psd_estao_na_lista(self):
        lista = (RAIZ / "requirements.txt").read_text()
        for pacote in ("psd-tools", "scipy", "scikit-image", "aggdraw"):
            assert f"{pacote}==" in lista, f"{pacote} não está travado na lista"

    def test_a_plataforma_herda_a_lista_do_motor(self):
        assert "-r requirements.txt" in (RAIZ / "requirements-api.txt").read_text()
