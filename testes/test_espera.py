"""Quem espera precisa saber que está esperando, e quanto.

A tela dizia "Replicando" tanto para o trabalho em andamento quanto para o que
estava atrás de outros três — indistinguível, com nada acontecendo. Esperar sem
saber quanto é o que faz a pessoa recarregar a página e subir a arte de novo,
que piora a fila que ela está esperando.
"""
import pytest

from api.fila import ABRIR_ARTE, POR_FORMATO, POR_VIDEO, FilaRQ, _custo


class TestOCustoDoQueEstaNaFrente:
    def test_peca_soma_abertura_mais_formatos(self):
        args = ("conta", "job", "/arte.psd", ["a", "b", "c"], "", "", "", "", False, "com")
        assert _custo("api.tarefas.processar", args) == ABRIR_ARTE + 3 * POR_FORMATO

    def test_video_custa_por_formato(self):
        args = ("conta", "job", ["a", "b"], "lettering", 5.0)
        assert _custo("api.tarefas.processar_video", args) == 2 * POR_VIDEO

    def test_trabalho_desconhecido_nao_derruba_a_conta(self):
        """Estimativa ruim é melhor do que tela sem estimativa."""
        assert _custo("outra.coisa", ()) > 0


class TestAEsperaNaFila:
    @pytest.fixture
    def fila(self):
        fakeredis = pytest.importorskip("fakeredis")
        return FilaRQ(conexao=fakeredis.FakeStrictRedis())

    def test_o_primeiro_nao_tem_ninguem_na_frente(self, fila):
        from api.tarefas import processar
        ident = fila.enfileirar(processar, "c", "j", "/a.psd", ["x"], "", "", "", "", False, "com")
        assert fila.espera(ident) == {"a_frente": 0, "segundos": 0}

    def test_o_terceiro_sabe_quantos_e_quanto(self, fila):
        from api.tarefas import processar
        for i in range(2):
            fila.enfileirar(processar, "c", f"j{i}", "/a.psd", ["x", "y"], "", "", "", "", False, "com")
        meu = fila.enfileirar(processar, "c", "meu", "/a.psd", ["x"], "", "", "", "", False, "com")
        r = fila.espera(meu)
        assert r["a_frente"] == 2
        assert r["segundos"] == 2 * (ABRIR_ARTE + 2 * POR_FORMATO)

    def test_trabalho_que_nao_esta_na_fila_nao_inventa_espera(self, fila):
        assert fila.espera("nunca-existiu") is None


class TestATelaMostra:
    def test_o_estado_leva_a_fila_para_a_tela(self):
        import inspect

        from api import main
        assert "FILA.espera" in inspect.getsource(main.ver)

    def test_a_tela_separa_esperar_de_estar_sendo_feito(self):
        from pathlib import Path
        tela = Path("web/index.html").read_text(encoding="utf-8")
        assert "'Na fila'" in tela
        assert "na frente" in tela

    def test_esperar_nao_depende_de_saber_a_posicao(self):
        """Exigir a posição para dizer "na fila" trazia de volta o
        "Replicando" com nada acontecendo sempre que a fila não soubesse
        responder — que é o defeito inteiro."""
        from pathlib import Path
        tela = Path("web/index.html").read_text(encoding="utf-8")
        assert "const esperando = d.status === 'na fila';" in tela
        assert "esperando uma vaga de processamento" in tela
