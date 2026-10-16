"""A arte sobe primeiro; os formatos vêm depois de ver o que tem dentro dela.

A ordem antiga pedia os formatos antes de abrir o arquivo — e num PSD de várias
pranchetas isso é perguntar na ordem errada: a prancheta decide o que cada
formato vai recortar. Pior: o upload de um PSD de 190 MB só começava no clique
final, então a escolha da prancheta chegava depois de uma espera longa, quando
a pessoa já tinha decidido tudo.

Agora são dois passos. O primeiro sobe a arte e devolve o que achou; o segundo
manda rodar. Quem integra pelo programa continua podendo mandar tudo de uma vez
— esse caminho não foi tirado, e há teste disso aqui.
"""
import io
import json

import pytest
from PIL import Image

from testes.test_api import FilaEspia, arte_png, cliente  # noqa: F401


def subir(cliente, **extra):
    """Sobe a arte sem formato nenhum: o rascunho."""
    return cliente.post("/jobs", files={"arte": ("arte.png", arte_png(), "image/png")},
                        data={"titulo": "prova", **extra})


class TestOEnvioEmDoisPassos:
    def test_sem_formatos_nasce_rascunho_e_nao_vai_para_a_fila(self, cliente):
        r = subir(cliente)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "rascunho"
        assert d["rascunho"] is True
        assert cliente.fila.pedidos == []

    def test_o_rascunho_diz_como_seguir(self, cliente):
        d = subir(cliente).json()
        assert f"/jobs/{d['job']}/rodar" in d["como"]

    def test_rodar_poe_na_fila_com_os_formatos_escolhidos(self, cliente):
        job = subir(cliente).json()["job"]
        r = cliente.post(f"/jobs/{job}/rodar",
                         data={"formatos": "ig-feed-1x1,ig-stories", "modo": "com"})
        assert r.status_code == 202, r.text
        assert r.json()["formatos"] == ["ig-feed-1x1", "ig-stories"]
        assert cliente.fila.pedidos[-1][0] == "processar"
        estado = cliente.get(f"/jobs/{job}").json()
        assert estado["status"] == "na fila"
        assert estado["formatos"] == ["ig-feed-1x1", "ig-stories"]

    def test_a_arte_nao_sobe_de_novo(self, cliente):
        """É o motivo de existir o rascunho: num PSD de 190 MB, subir duas
        vezes é esperar duas vezes."""
        job = subir(cliente).json()["job"]
        cliente.post(f"/jobs/{job}/rodar", data={"formatos": "ig-feed-1x1"})
        from api import trabalhos
        pasta = trabalhos.pasta_do(cliente.conta.id, job)
        assert len(list(pasta.glob("arte.*"))) == 1

    def test_o_texto_e_o_modo_vem_no_segundo_passo(self, cliente):
        job = subir(cliente).json()["job"]
        cliente.post(f"/jobs/{job}/rodar", data={
            "formatos": "ig-feed-1x1", "modo": "novo",
            "headline": "Chegamos a Porto Belo", "cta": "Saiba mais",
            "brief": "sem travessão"})
        d = cliente.get(f"/jobs/{job}").json()
        assert d["modo"] == "novo"
        assert d["headline"] == "Chegamos a Porto Belo"
        assert d["brief"] == "sem travessão"

    def test_o_titulo_pode_mudar_depois_de_subir(self, cliente):
        """Ela digita o nome da campanha enquanto a arte sobe."""
        job = subir(cliente).json()["job"]
        cliente.post(f"/jobs/{job}/rodar",
                     data={"formatos": "ig-feed-1x1", "titulo": "Energiza 2027"})
        assert cliente.get(f"/jobs/{job}").json()["titulo"] == "Energiza 2027"


class TestOQueRodarRecusa:
    def test_rodar_duas_vezes_nao_duplica_o_trabalho(self, cliente):
        job = subir(cliente).json()["job"]
        cliente.post(f"/jobs/{job}/rodar", data={"formatos": "ig-feed-1x1"})
        r = cliente.post(f"/jobs/{job}/rodar", data={"formatos": "ig-feed-1x1"})
        assert r.status_code == 409
        assert "rascunho" in r.json()["detail"]

    def test_sem_formato_nao_roda(self, cliente):
        job = subir(cliente).json()["job"]
        r = cliente.post(f"/jobs/{job}/rodar", data={"formatos": "  "})
        assert r.status_code == 422

    def test_formato_inventado_nao_roda(self, cliente):
        job = subir(cliente).json()["job"]
        r = cliente.post(f"/jobs/{job}/rodar", data={"formatos": "nao-existe"})
        assert r.status_code == 422
        assert "formato desconhecido" in r.json()["detail"]

    def test_texto_novo_sem_chamada_e_recusado(self, cliente):
        job = subir(cliente).json()["job"]
        r = cliente.post(f"/jobs/{job}/rodar",
                         data={"formatos": "ig-feed-1x1", "modo": "novo"})
        assert r.status_code == 422
        assert "chamada" in r.json()["detail"]

    def test_trabalho_de_outra_conta_nao_roda(self, cliente, tmp_path):
        job = subir(cliente).json()["job"]
        from fastapi.testclient import TestClient
        from api import contas, main
        outra = contas.criar("Outra", "outra@exemplo.com", "senha-bem-comprida")
        from testes.conftest import assinatura_valendo
        assinatura_valendo(outra)
        chave = contas.nova_chave(outra, "outra")
        c2 = TestClient(main.app, headers={"Authorization": f"Bearer {chave}"})
        assert c2.post(f"/jobs/{job}/rodar",
                       data={"formatos": "ig-feed-1x1"}).status_code == 404

    def test_a_franquia_e_conferida_no_rodar_e_nao_no_envio(self, cliente):
        """Subir a arte não produz nada: barrar ali seria barrar antes de
        existir pedido. O que conta peça é o rodar."""
        from api import uso
        job = subir(cliente).json()["job"]          # passa, mesmo estourado
        for _ in range(uso.limites("agency")["pecas"]):
            uso.registrar(cliente.conta.id, uso.PECA)
        r = cliente.post(f"/jobs/{job}/rodar", data={"formatos": "ig-feed-1x1"})
        assert r.status_code == 402
        assert "peças por ciclo" in r.json()["detail"]


class TestPSDComVariasPranchetas:
    def _psd_falso(self, cliente, monkeypatch, quantas=3):
        """Um PSD de mentira: o que importa é o que `psd.pranchetas` devolve."""
        from api import psd

        class P:
            def __init__(self, i):
                self.nome, self.x, self.y, self.w, self.h = f"Prancheta {i}", i*100, 0, 800, 600
        monkeypatch.setattr(psd, "pranchetas", lambda caminho: [P(i) for i in range(1, quantas+1)])
        return cliente.post("/jobs", files={"arte": ("arte.psd", io.BytesIO(b"8BPS" + b"\0"*64), "image/vnd.adobe.photoshop")},
                            data={"titulo": "psd"})

    def test_o_rascunho_ja_devolve_as_pranchetas(self, cliente, monkeypatch):
        """É o ponto da mudança: a pergunta vem logo depois de ler a arte, e
        não depois de escolher os formatos."""
        r = self._psd_falso(cliente, monkeypatch)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "escolha a prancheta"
        assert d["rascunho"] is True
        assert [p["nome"] for p in d["pranchetas"]] == ["Prancheta 1", "Prancheta 2",
                                                        "Prancheta 3"]
        assert cliente.fila.pedidos[-1][0] == "previas"   # só as prévias

    def test_escolher_a_prancheta_num_rascunho_nao_roda_nada(self, cliente, monkeypatch):
        job = self._psd_falso(cliente, monkeypatch).json()["job"]
        cliente.fila.pedidos.clear()
        r = cliente.post(f"/jobs/{job}/prancheta", data={"nome": "Prancheta 2"})
        assert r.status_code == 200
        assert r.json()["status"] == "rascunho"
        assert cliente.fila.pedidos == []
        assert cliente.get(f"/jobs/{job}").json()["prancheta"] == "Prancheta 2"

    def test_rodar_sem_escolher_a_prancheta_e_recusado(self, cliente, monkeypatch):
        job = self._psd_falso(cliente, monkeypatch).json()["job"]
        r = cliente.post(f"/jobs/{job}/rodar", data={"formatos": "ig-feed-1x1"})
        assert r.status_code == 409
        assert "prancheta" in r.json()["detail"]

    def test_o_caminho_inteiro_do_psd(self, cliente, monkeypatch):
        job = self._psd_falso(cliente, monkeypatch).json()["job"]
        cliente.post(f"/jobs/{job}/prancheta", data={"nome": "Prancheta 3"})
        r = cliente.post(f"/jobs/{job}/rodar", data={"formatos": "ig-feed-1x1"})
        assert r.status_code == 202
        pedido = cliente.fila.pedidos[-1]
        assert pedido[0] == "processar"
        assert "Prancheta 3" in pedido[1]        # a escolha chega ao motor


class TestOCaminhoDeUmaTacadaContinua:
    """Quem integra pelo programa manda tudo de uma vez. Tirar isso seria
    quebrar a API de quem já usa — e não há motivo."""

    def test_com_formatos_vai_direto_para_a_fila(self, cliente):
        r = cliente.post("/jobs", files={"arte": ("arte.png", arte_png(), "image/png")},
                         data={"formatos": "ig-feed-1x1", "titulo": "direto"})
        assert r.status_code == 202
        assert r.json()["status"] == "na fila"
        assert cliente.fila.pedidos[-1][0] == "processar"

    def test_psd_de_uma_tacada_ainda_pergunta_a_prancheta(self, cliente, monkeypatch):
        from api import psd

        class P:
            def __init__(self, i):
                self.nome, self.x, self.y, self.w, self.h = f"Prancheta {i}", 0, 0, 800, 600
        monkeypatch.setattr(psd, "pranchetas", lambda caminho: [P(1), P(2)])
        r = cliente.post("/jobs",
                         files={"arte": ("arte.psd", io.BytesIO(b"8BPS"), "image/vnd.adobe.photoshop")},
                         data={"formatos": "ig-feed-1x1"})
        assert r.json()["status"] == "escolha a prancheta"
        assert r.json()["rascunho"] is False
        # e aí a escolha JÁ manda rodar, porque os formatos vieram junto
        job = r.json()["job"]
        cliente.fila.pedidos.clear()
        cliente.post(f"/jobs/{job}/prancheta", data={"nome": "Prancheta 2"})
        assert cliente.fila.pedidos[-1][0] == "processar"


class TestRascunhoAbandonadoNaoFicaNoDisco:
    """Ela trocou a arte três vezes e cada tentativa guardou 194 MB do PSD.
    Rascunho é arte que subiu e nunca rodou: não tem peça a preservar."""

    def test_da_para_jogar_fora_um_rascunho(self, cliente):
        job = subir(cliente).json()["job"]
        from api import trabalhos
        pasta = trabalhos.pasta_do(cliente.conta.id, job)
        assert pasta.exists()
        r = cliente.delete(f"/jobs/{job}")
        assert r.status_code == 200
        assert r.json()["liberou_mb"] >= 0
        assert not pasta.exists()

    def test_trabalho_que_rodou_nao_se_apaga_por_ai(self, cliente):
        """A peça é dela: some pela faxina quando envelhece, não num clique."""
        job = subir(cliente).json()["job"]
        cliente.post(f"/jobs/{job}/rodar", data={"formatos": "ig-feed-1x1"})
        r = cliente.delete(f"/jobs/{job}")
        assert r.status_code == 409

    def test_o_rascunho_do_outro_nao_existe_para_mim(self, cliente):
        job = subir(cliente).json()["job"]
        from fastapi.testclient import TestClient
        from api import contas, main
        from testes.conftest import assinatura_valendo
        outra = assinatura_valendo(
            contas.criar("Outra", "outra2@exemplo.com", "senha-bem-comprida"))
        c2 = TestClient(main.app,
                        headers={"Authorization": f"Bearer {contas.nova_chave(outra)}"})
        assert c2.delete(f"/jobs/{job}").status_code == 404

    def test_a_faxina_varre_rascunho_de_ontem_inteiro(self, cliente):
        from datetime import datetime, timedelta, timezone
        from api import faxina, trabalhos
        job = subir(cliente).json()["job"]
        pasta = trabalhos.pasta_do(cliente.conta.id, job)
        amanha = datetime.now(timezone.utc) + timedelta(days=faxina.DIAS_RASCUNHO + 1)
        r = faxina.varrer_trabalho(cliente.conta.id, job, agora=amanha)
        assert r.get("rascunho") is True
        assert not pasta.exists()

    def test_a_faxina_nao_varre_o_rascunho_de_hoje(self, cliente):
        """Ela pode estar com a janela aberta, decidindo os formatos."""
        from api import faxina, trabalhos
        job = subir(cliente).json()["job"]
        r = faxina.varrer_trabalho(cliente.conta.id, job)
        assert "rascunho de hoje" in r.get("pulou", "")
        assert trabalhos.pasta_do(cliente.conta.id, job).exists()

    def test_a_tela_joga_fora_o_anterior_ao_trocar_de_arte(self):
        from pathlib import Path
        tela = Path("web/index.html").read_text(encoding="utf-8")
        assert "fetch(`/jobs/${rascunho}`, { method:'DELETE' })" in tela
