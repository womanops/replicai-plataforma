"""A faxina apaga o bruto e não encosta no que foi entregue.

Sem ela nenhum disco serve: pelos volumes dos planos, quarenta clientes geram
94 GB por mês e um disco de 640 GB enche em quatro meses. Com ela o acúmulo
permanente cai para 8 GB.

É código que apaga arquivo do cliente. Os testes aqui são principalmente
sobre o que ele **não** pode apagar.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from api import faxina, trabalhos
from testes.conftest import assinatura_valendo


@pytest.fixture
def cliente_limitado(tmp_path, monkeypatch):
    """A plataforma com um teto pequeno, para o teste não mover 250 MB."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("REPLICAI_SEGREDO", "segredo-de-teste")
    monkeypatch.setenv("REPLICAI_MAX_ARTE_MB", "2")
    monkeypatch.delenv("REDIS_URL", raising=False)
    import importlib

    from fastapi.testclient import TestClient

    from api import contas, main, trabalhos
    importlib.reload(trabalhos)
    importlib.reload(main)

    class FilaQuieta:
        def enfileirar(self, fn, *a, **k):
            return "espiado"

    main.FILA = FilaQuieta()
    c = assinatura_valendo(contas.criar("Teto", "teto@exemplo.com", "senha-bem-comprida"))
    chave = contas.nova_chave(c, "teto")
    return TestClient(main.app, headers={"Authorization": f"Bearer {chave}"}), main.LIMITE_ARTE


@pytest.fixture
def conta(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    import importlib
    importlib.reload(trabalhos)
    importlib.reload(faxina)
    return "conta-de-teste"


def montar(conta, job, dias_atras=60, status="pronto", prontas=("ig-stories",)):
    """Um trabalho como a esteira o deixa: bruto, peças, vídeo e apresentação."""
    pasta = trabalhos.pasta_do(conta, job)
    (pasta / "pecas").mkdir(parents=True, exist_ok=True)
    (pasta / "video").mkdir(parents=True, exist_ok=True)
    bruto = {"arte.psd": 60_000, "fundo.png": 5_000, "arte-mae.png": 4_000,
             "fundo-ig-stories.png": 3_000, "00-chegamos-0001.png": 200,
             "grotesk.ttf": 900, "apresentacao.html": 400}
    for nome, tam in bruto.items():
        (pasta / nome).write_bytes(b"x" * tam)
    # a arte é ligada, não copiada: os dois nomes, um arquivo só
    import os
    os.link(pasta / "arte.psd", pasta / "base.psd")
    for fid in prontas:
        (pasta / f"{fid}.png").write_bytes(b"peca")
        (pasta / "pecas" / f"{fid}.json").write_text("{}")
        (pasta / "video" / f"{fid}-lettering.mp4").write_bytes(b"filme")
    (pasta / "apresentacao.pdf").write_bytes(b"pdf")
    quando = datetime.now(timezone.utc) - timedelta(days=dias_atras)
    trabalhos.gravar(conta, job, {"status": status, "prontas": list(prontas)})
    estado = json.loads((pasta / "trabalho.json").read_text())
    estado["atualizado"] = quando.isoformat(timespec="seconds")
    (pasta / "trabalho.json").write_text(json.dumps(estado))
    return pasta


class TestOQueFica:
    def test_a_peca_entregue_fica(self, conta):
        pasta = montar(conta, "antigo")
        faxina.varrer_trabalho(conta, "antigo")
        assert (pasta / "ig-stories.png").exists()

    def test_o_video_fica(self, conta):
        pasta = montar(conta, "antigo")
        faxina.varrer_trabalho(conta, "antigo")
        assert (pasta / "video" / "ig-stories-lettering.mp4").exists()

    def test_a_apresentacao_fica(self, conta):
        """É o que se manda para o cliente aprovar."""
        pasta = montar(conta, "antigo")
        faxina.varrer_trabalho(conta, "antigo")
        assert (pasta / "apresentacao.pdf").exists()

    def test_o_estado_e_a_montagem_ficam(self, conta):
        pasta = montar(conta, "antigo")
        faxina.varrer_trabalho(conta, "antigo")
        assert (pasta / "trabalho.json").exists()
        assert (pasta / "pecas" / "ig-stories.json").exists()

    def test_peca_de_formato_livre_tambem_fica(self, conta):
        """O nome vem do estado, não de uma lista de formatos conhecidos."""
        pasta = montar(conta, "antigo", prontas=("livre-1200x1600",))
        faxina.varrer_trabalho(conta, "antigo")
        assert (pasta / "livre-1200x1600.png").exists()


class TestOQueSai:
    def test_o_psd_sai(self, conta):
        pasta = montar(conta, "antigo")
        faxina.varrer_trabalho(conta, "antigo")
        assert not (pasta / "arte.psd").exists()

    def test_as_duas_pontas_da_ligacao_saem(self, conta):
        """`arte.psd` e `base.psd` são o mesmo arquivo em disco: apagar só um
        não libera nada."""
        pasta = montar(conta, "antigo")
        faxina.varrer_trabalho(conta, "antigo")
        assert not (pasta / "base.psd").exists()

    def test_o_tamanho_ligado_conta_uma_vez(self, conta):
        """Senão a faxina relata o dobro do que liberou. Em bytes, porque
        arredondado para MB os dois números empatam e o erro passaria."""
        montar(conta, "antigo")
        r = faxina.varrer_trabalho(conta, "antigo")
        bruto = 60_000 + 5_000 + 4_000 + 3_000 + 200 + 900 + 400
        assert r["liberou"] == bruto, "a arte ligada foi contada duas vezes"

    def test_recortes_e_fundos_saem(self, conta):
        pasta = montar(conta, "antigo")
        faxina.varrer_trabalho(conta, "antigo")
        assert not (pasta / "00-chegamos-0001.png").exists()
        assert not (pasta / "fundo-ig-stories.png").exists()
        assert not (pasta / "arte-mae.png").exists()


class TestQuandoNaoMexe:
    def test_trabalho_novo_fica_inteiro(self, conta):
        pasta = montar(conta, "novo", dias_atras=3)
        r = faxina.varrer_trabalho(conta, "novo")
        assert "ainda não" in r["pulou"]
        assert (pasta / "arte.psd").exists()

    def test_trabalho_rodando_nao_e_tocado(self, conta):
        """Apagar o bruto de um trabalho em andamento é apagar debaixo dele."""
        pasta = montar(conta, "rodando", status="rodando")
        r = faxina.varrer_trabalho(conta, "rodando")
        assert "rodando" in r["pulou"]
        assert (pasta / "arte.psd").exists()

    def test_na_fila_nao_e_tocado(self, conta):
        pasta = montar(conta, "fila", status="na fila")
        assert faxina.varrer_trabalho(conta, "fila")["pulou"]
        assert (pasta / "arte.psd").exists()

    def test_nao_varre_duas_vezes(self, conta):
        montar(conta, "antigo")
        faxina.varrer_trabalho(conta, "antigo")
        assert "já foi varrido" in faxina.varrer_trabalho(conta, "antigo")["pulou"]

    def test_de_mentira_nao_apaga_nada(self, conta):
        """O primeiro uso de qualquer mudança aqui é de mentira."""
        pasta = montar(conta, "antigo")
        r = faxina.varrer_trabalho(conta, "antigo", de_verdade=False)
        assert r["apagados"] > 0 and r["liberou_mb"] > 0
        assert (pasta / "arte.psd").exists()
        assert not trabalhos.ler(conta, "antigo").get("arquivado")


class TestAMarca:
    def test_o_trabalho_varrido_diz_que_foi(self, conta):
        """A tela precisa saber: sem a arte não dá para refazer nem remontar,
        e oferecer o botão que vai falhar é pior do que não oferecer."""
        montar(conta, "antigo")
        faxina.varrer_trabalho(conta, "antigo")
        marca = trabalhos.ler(conta, "antigo")["arquivado"]
        assert marca["liberou_mb"] > 0
        assert "30 dias" in marca["porque"]


class TestOLimiteDaArte:
    """O PSD é 85% do disco de um trabalho. Sem teto, uma arte de 2 GB enche
    o disco do servidor antes de qualquer conferência."""

    def test_arte_grande_demais_e_recusada(self, cliente_limitado):
        c, limite = cliente_limitado
        import io
        grande = io.BytesIO(b"8BPS" + b"x" * (limite + 1000))
        r = c.post("/jobs", files={"arte": ("arte.psd", grande, "image/vnd.adobe.photoshop")},
                   data={"formatos": "gdn-300x250", "modo": "sem"})
        assert r.status_code == 413
        assert "MB" in r.json()["detail"]

    def test_o_que_passou_do_teto_nao_fica_no_disco(self, cliente_limitado):
        """Upload recusado não pode deixar meio arquivo ocupando lugar."""
        import io
        from api import trabalhos
        c, limite = cliente_limitado
        antes = sum(f.stat().st_size for f in trabalhos.pasta_base().rglob("*")
                    if f.is_file())
        grande = io.BytesIO(b"8BPS" + b"x" * (limite * 3))
        c.post("/jobs", files={"arte": ("arte.psd", grande, "image/vnd.adobe.photoshop")},
               data={"formatos": "gdn-300x250", "modo": "sem"})
        depois = sum(f.stat().st_size for f in trabalhos.pasta_base().rglob("*")
                     if f.is_file())
        assert depois - antes < limite, "sobrou arquivo pela metade"

    def test_arte_dentro_do_teto_passa(self, cliente_limitado):
        import io
        c, limite = cliente_limitado
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (400, 400), (10, 20, 80)).save(buf, "PNG")
        buf.seek(0)
        r = c.post("/jobs", files={"arte": ("arte.png", buf, "image/png")},
                   data={"formatos": "gdn-300x250", "modo": "sem"})
        assert r.status_code == 202

    def test_a_tela_sabe_o_limite_antes_de_subir(self, cliente_limitado):
        """Recusar só no fim de uma subida longa é a pior hora de avisar."""
        c, limite = cliente_limitado
        assert c.get("/saude").json()["limite_arte_mb"] == limite // 1_000_000
