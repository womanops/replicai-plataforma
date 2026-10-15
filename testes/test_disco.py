"""O aviso de disco: o único recurso que a plataforma gasta e não devolve.

Disco cheio não deixa a plataforma lenta — para a produção: a peça não grava e
o trabalho morre no meio. E chega sem avisar, porque ninguém abre `/saude` todo
dia. Os testes aqui são sobre as duas coisas que fazem o aviso servir: ele
precisa dizer **em quanto tempo** enche, e precisa **calar** enquanto nada piora.
"""
import json
from datetime import date, timedelta

import pytest


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("REPLICAI_AVISO_PARA", "operacao@exemplo.teste")
    import importlib
    from api import disco, trabalhos
    importlib.reload(trabalhos)
    return disco


def medida(dia_atras: int, usado: float, total: float = 200.0) -> dict:
    quando = (date.today() - timedelta(days=dia_atras)).isoformat()
    return {"quando": f"{quando}T12:00:00+00:00", "total_gb": total,
            "usado_gb": usado, "livre_gb": round(total - usado, 2),
            "cheio": round(usado / total, 4)}


class TestOsTresNiveis:
    def test_folga_atencao_e_aperto(self, servidor):
        assert servidor.nivel(0.10) == "folga"
        assert servidor.nivel(0.6999) == "folga"
        assert servidor.nivel(0.70) == "atenção"
        assert servidor.nivel(0.8499) == "atenção"
        assert servidor.nivel(0.85) == "aperto"
        assert servidor.nivel(1.0) == "aperto"

    def test_a_medida_de_verdade_responde(self, servidor):
        m = servidor.medir()
        assert m["total_gb"] > 0
        assert 0 <= m["cheio"] <= 1
        assert round(m["usado_gb"] + m["livre_gb"]) <= round(m["total_gb"]) + 1


class TestOHistorico:
    def test_uma_medida_por_dia(self, servidor):
        """A faxina pode rodar duas vezes no mesmo dia; o histórico não dobra."""
        servidor.registrar(medida(0, 100))
        guardadas = servidor.registrar(medida(0, 101))
        hoje = [m for m in guardadas if m["quando"][:10] == date.today().isoformat()]
        assert len(hoje) == 1
        assert hoje[0]["usado_gb"] == 101

    def test_o_historico_nao_cresce_para_sempre(self, servidor):
        for d in range(servidor.GUARDA_DIAS + 20, 0, -1):
            servidor.registrar(medida(d, 100))
        assert len(servidor._historico()) <= servidor.GUARDA_DIAS

    def test_arquivo_torto_nao_derruba(self, servidor):
        servidor._arquivo().write_text("isto não é json", encoding="utf-8")
        assert servidor._historico() == []
        assert servidor.registrar(medida(0, 10))


class TestAPrevisao:
    """"72% cheio" não move ninguém. "Enche em cinco semanas" move."""

    def test_sem_historico_nao_inventa(self, servidor):
        assert servidor.previsao([])["sabe"] is False
        assert servidor.previsao([medida(0, 100)])["sabe"] is False

    def test_diz_em_quantos_dias_enche(self, servidor):
        # 10 dias, 20 GB a mais: 2 GB/dia, com 80 GB livres → 40 dias
        prev = servidor.previsao([medida(10, 100), medida(0, 120)])
        assert prev["por_dia_gb"] == 2.0
        assert prev["enche_em_dias"] == 40
        assert prev["medido_em_dias"] == 10

    def test_disco_que_nao_cresce_nao_enche(self, servidor):
        prev = servidor.previsao([medida(10, 120), medida(0, 100)])
        assert prev["enche_em_dias"] is None
        assert "não está crescendo" in prev["porque"]

    def test_duas_medidas_no_mesmo_dia_nao_viram_previsao(self, servidor):
        """Dividir por zero dia daria um número absurdo e assustaria à toa."""
        assert servidor.previsao([medida(0, 100), medida(0, 103)])["sabe"] is False


class TestOAvisoSoFalaQuandoPiora:
    def _conferir(self, servidor, monkeypatch, cheio):
        monkeypatch.setattr(servidor, "medir",
                            lambda caminho=None: medida(0, 200 * cheio))
        return servidor.conferir()

    def test_folga_nao_avisa(self, servidor, monkeypatch):
        r = self._conferir(servidor, monkeypatch, 0.30)
        assert r["nivel"] == "folga"
        assert r["carta"]["enviado"] is False

    def test_a_primeira_atencao_avisa(self, servidor, monkeypatch):
        from api import correio
        cartas = []
        monkeypatch.setattr(correio, "enviar",
                            lambda *a, **k: cartas.append(a) or {"enviado": True})
        r = self._conferir(servidor, monkeypatch, 0.72)
        assert r["nivel"] == "atenção"
        assert r["carta"]["enviado"] is True
        assert len(cartas) == 1

    def test_o_mesmo_nivel_no_dia_seguinte_cala(self, servidor, monkeypatch):
        """Aviso que chega todo dia vira aviso que ninguém lê."""
        from api import correio
        cartas = []
        monkeypatch.setattr(correio, "enviar",
                            lambda *a, **k: cartas.append(a) or {"enviado": True})
        self._conferir(servidor, monkeypatch, 0.72)
        r = self._conferir(servidor, monkeypatch, 0.75)
        assert r["carta"]["enviado"] is False
        assert len(cartas) == 1

    def test_piorar_de_atencao_para_aperto_avisa_de_novo(self, servidor, monkeypatch):
        from api import correio
        cartas = []
        monkeypatch.setattr(correio, "enviar",
                            lambda *a, **k: cartas.append(a) or {"enviado": True})
        self._conferir(servidor, monkeypatch, 0.72)
        r = self._conferir(servidor, monkeypatch, 0.90)
        assert r["nivel"] == "aperto"
        assert r["carta"]["enviado"] is True
        assert len(cartas) == 2

    def test_melhorar_e_apertar_de_novo_volta_a_avisar(self, servidor, monkeypatch):
        """A faxina liberou espaço; se encher outra vez, tem que falar."""
        from api import correio
        cartas = []
        monkeypatch.setattr(correio, "enviar",
                            lambda *a, **k: cartas.append(a) or {"enviado": True})
        self._conferir(servidor, monkeypatch, 0.72)
        self._conferir(servidor, monkeypatch, 0.40)      # a faxina passou
        r = self._conferir(servidor, monkeypatch, 0.72)
        assert r["carta"]["enviado"] is True
        assert len(cartas) == 2


class TestACarta:
    def test_sem_destinatario_configurado_ela_diz_isso(self, servidor, monkeypatch):
        monkeypatch.delenv("REPLICAI_AVISO_PARA", raising=False)
        from api import correio
        r = correio.disco_apertando(medida(0, 150), "atenção", {"sabe": False})
        assert r["enviado"] is False
        assert "REPLICAI_AVISO_PARA" in r["porque"]

    def test_a_carta_leva_a_previsao_e_a_saida(self, servidor, monkeypatch):
        from api import correio
        escrito = {}
        monkeypatch.setattr(correio, "enviar",
                            lambda para, assunto, texto: escrito.update(
                                para=para, assunto=assunto, texto=texto)
                            or {"enviado": True})
        correio.disco_apertando(medida(0, 150), "atenção",
                                {"sabe": True, "por_dia_gb": 2.0,
                                 "enche_em_dias": 25, "medido_em_dias": 10})
        assert escrito["para"] == "operacao@exemplo.teste"
        assert "25 dias" in escrito["texto"]
        assert "aumentar o disco" in escrito["texto"]
        assert "REPLICAI_FAXINA_DIAS" in escrito["texto"]
        assert "75%" in escrito["assunto"]

    def test_sem_previsao_ela_nao_inventa_prazo(self, servidor, monkeypatch):
        from api import correio
        escrito = {}
        monkeypatch.setattr(correio, "enviar",
                            lambda para, assunto, texto: escrito.update(texto=texto)
                            or {"enviado": True})
        correio.disco_apertando(medida(0, 150), "atenção", {"sabe": False})
        assert "falta histórico" in escrito["texto"]


class TestAFaxinaConfere:
    def test_a_faxina_olha_o_disco_depois_de_varrer(self):
        """Antes de varrer, a medida contaria o que está prestes a sair."""
        import inspect
        from api import faxina
        fonte = inspect.getsource(faxina.main)
        assert fonte.index("varrer(") < fonte.index("disco.conferir()")

    def test_a_faxina_denuncia_aviso_que_nao_saiu(self):
        import inspect
        from api import faxina
        assert "aviso NÃO saiu" in inspect.getsource(faxina.main)


class TestASaudeMostra:
    def test_a_saude_traz_o_disco_e_quem_recebe_o_aviso(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.delenv("REPLICAI_AVISO_PARA", raising=False)
        import importlib
        from api import main, trabalhos
        importlib.reload(trabalhos)
        importlib.reload(main)
        from fastapi.testclient import TestClient
        d = TestClient(main.app).get("/saude").json()["disco"]
        assert d["nivel"] in ("folga", "atenção", "aperto")
        assert d["cheio"].endswith("%")
        assert "ninguém" in d["avisa"]
