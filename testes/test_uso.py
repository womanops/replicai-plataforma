"""O que cada cliente consumiu.

O custo é por peça: uma conta que roda mil peças custa cem vezes mais do que
uma que roda dez. Contar é o que permite cobrar por volume — e barrar antes de
gastar é o que impede renderizar de graça.
"""
import json

import pytest

from api import uso


@pytest.fixture(autouse=True)
def disco(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    import importlib
    from api import trabalhos
    importlib.reload(trabalhos)


CONTA = "cliente-um"


class TestRegistro:
    def test_uma_linha_por_consumo(self, tmp_path):
        uso.registrar(CONTA, uso.PECA, job="j1", formato="ig-stories")
        uso.registrar(CONTA, uso.PECA, job="j1", formato="ig-feed-1x1")
        linhas = uso.arquivo(CONTA).read_text().strip().splitlines()
        assert len(linhas) == 2
        assert json.loads(linhas[0])["formato"] == "ig-stories"

    def test_o_registro_diz_se_gravou(self):
        """Faturamento que some calado é a pior queda calada: o cliente usa,
        ninguém cobra, e nada denuncia."""
        assert uso.registrar(CONTA, uso.PECA)["gravado"] is True
        ruim = uso.registrar("c1", uso.PECA)       # identificador curto demais
        assert ruim["gravado"] is False and "porque" in ruim

    def test_linha_quebrada_nao_derruba_o_relatorio(self):
        uso.registrar(CONTA, uso.PECA, job="j1")
        with open(uso.arquivo(CONTA), "a") as f:
            f.write("{isto não é json\n")
        uso.registrar(CONTA, uso.PECA, job="j2")
        assert len(uso.eventos(CONTA)) == 2


class TestResumo:
    def test_soma_por_tipo(self):
        uso.registrar(CONTA, uso.PECA, job="j1", dolares=0.04)
        uso.registrar(CONTA, uso.PECA, job="j2", dolares=0.04)
        uso.registrar(CONTA, uso.VIDEO, job="j1")
        uso.registrar(CONTA, uso.FUNDO, job="j1", quantas=3)
        r = uso.resumo(CONTA)
        assert (r["pecas"], r["videos"], r["fundos_generativos"]) == (2, 1, 3)
        assert r["custo_dolares"] == pytest.approx(0.08)
        assert r["trabalhos"] == 2

    def test_mes_sem_nada_e_zero(self):
        assert uso.resumo(CONTA, "2020-01")["pecas"] == 0

    def test_cada_mes_no_seu_arquivo(self):
        uso.registrar(CONTA, uso.PECA)
        assert uso.meses(CONTA) == [uso._mes()]


class TestPlano:
    def test_cabe_enquanto_nao_estoura(self):
        for _ in range(10):
            uso.registrar(CONTA, uso.PECA)
        assert uso.cabe(CONTA, "basic", pecas=5)[0] is True

    def test_nao_cabe_e_diz_o_numero(self):
        for _ in range(78):
            uso.registrar(CONTA, uso.PECA)
        pode, porque = uso.cabe(CONTA, "basic", pecas=5)
        assert pode is False
        assert "80 peças" in porque and "83" in porque

    def test_video_tem_limite_proprio(self):
        for _ in range(8):
            uso.registrar(CONTA, uso.VIDEO)
        assert uso.cabe(CONTA, "basic", videos=1)[0] is False
        assert uso.cabe(CONTA, "basic", pecas=1)[0] is True

    def test_plano_maior_cabe_mais(self):
        for _ in range(100):
            uso.registrar(CONTA, uso.PECA)
        assert uso.cabe(CONTA, "basic", pecas=1)[0] is False
        assert uso.cabe(CONTA, "freelancer", pecas=1)[0] is True

    def test_sem_plano_nao_cabe_nada(self):
        """Não é franquia pequena: é sem sistema."""
        pode, porque = uso.cabe(CONTA, uso.PLANO_PADRAO, pecas=1)
        assert pode is False
        assert "não tem plano ativo" in porque

    def test_plano_desconhecido_cai_no_mais_apertado(self):
        """Plano torto não pode virar uso ilimitado."""
        assert uso.limites("inventado") == uso.limites(uso.PLANO_PADRAO)


class TestNaEsteira:
    """Contar e não ser chamado é o defeito recorrente deste projeto. Aqui ele
    custaria faturamento: o cliente usa, ninguém cobra, nada denuncia."""

    @pytest.fixture
    def esteira(self, tmp_path, monkeypatch):
        from PIL import Image
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        import importlib
        from api import tarefas, trabalhos
        importlib.reload(trabalhos)
        monkeypatch.setattr(tarefas, "trabalhos", trabalhos)

        class Serve:
            def compor(self, base, formato_id, brief="", terreno=None):
                return {"canvas": {"w": 100, "h": 100},
                        "fundo": {"tipo": "cor", "cor": "#000"},
                        "elementos": [], "saida": f"{formato_id}.png"}

        import api.pipeline as pl
        monkeypatch.setattr(pl, "render_peca", lambda a, d: d.write_bytes(b"x"))
        monkeypatch.setattr(tarefas, "compositor", lambda *a: Serve())
        monkeypatch.setattr(tarefas, "leitor", lambda: None)

        arte = tmp_path / "arte.png"
        Image.new("RGB", (1920, 1080), "#0a1a55").save(arte)
        return tarefas, trabalhos, arte

    def test_cada_peca_entregue_vira_consumo(self, esteira):
        tarefas, trabalhos, arte = esteira
        job = trabalhos.novo_id("x")
        tarefas.processar(CONTA, job, str(arte), ["ig-feed-1x1", "ig-stories"],
                          "Oi", "", "")
        r = uso.resumo(CONTA)
        assert r["pecas"] == 2
        formatos = {e.get("formato") for e in uso.eventos(CONTA)
                    if e["tipo"] == uso.PECA}
        assert formatos == {"ig-feed-1x1", "ig-stories"}

    def test_o_consumo_e_da_conta_certa(self, esteira):
        tarefas, trabalhos, arte = esteira
        tarefas.processar("cliente-dois", trabalhos.novo_id("x"), str(arte),
                          ["ig-feed-1x1"], "Oi", "", "")
        assert uso.resumo(CONTA)["pecas"] == 0
        assert uso.resumo("cliente-dois")["pecas"] == 1

    def test_formato_que_falhou_nao_e_cobrado(self, esteira, monkeypatch):
        """Cobrar por peça que não saiu é cobrar por nada."""
        tarefas, trabalhos, arte = esteira
        import api.pipeline as pl

        def so_um(arq, destino):
            if "stories" in str(destino):
                raise RuntimeError("o Chrome não abriu")
            destino.write_bytes(b"x")

        monkeypatch.setattr(pl, "render_peca", so_um)
        tarefas.processar(CONTA, trabalhos.novo_id("x"), str(arte),
                          ["ig-feed-1x1", "ig-stories"], "Oi", "", "")
        assert uso.resumo(CONTA)["pecas"] == 1


class TestOCicloDaFranquia:
    """Mês de calendário estaria errado: quem assina dia 20 teria a franquia
    zerada no dia 1º, nove dias depois de pagar."""

    def test_o_ciclo_vai_de_dia_a_dia(self):
        from datetime import date
        i, f = uso.ciclo(20, date(2026, 10, 25))
        assert (i, f) == (date(2026, 10, 20), date(2026, 11, 20))

    def test_antes_do_dia_o_ciclo_e_o_anterior(self):
        from datetime import date
        i, f = uso.ciclo(20, date(2026, 10, 11))
        assert (i, f) == (date(2026, 9, 20), date(2026, 10, 20))

    def test_dia_29_30_31_viram_28(self):
        """Fevereiro não tem 30: a franquia não pode pular um mês."""
        from datetime import date
        i, _ = uso.ciclo(31, date(2026, 3, 15))
        assert i.day == 28

    def test_o_consumo_do_ciclo_anterior_nao_conta(self, monkeypatch):
        from datetime import datetime, timedelta, timezone
        antigo = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        with open(uso.arquivo(CONTA, (datetime.now(timezone.utc)
                                      - timedelta(days=45)).strftime("%Y-%m")), "a") as f:
            import json
            f.write(json.dumps({"quando": antigo, "tipo": uso.PECA}) + "\n")
        uso.registrar(CONTA, uso.PECA)
        hoje = uso.resumo(CONTA, dia_do_ciclo=1)
        assert hoje["pecas"] == 1          # só o deste ciclo

    def test_sem_dia_do_ciclo_continua_por_mes(self):
        uso.registrar(CONTA, uso.PECA)
        assert uso.resumo(CONTA)["pecas"] == 1


class TestInstalacaoDeTeste:
    """Quem está construindo a plataforma precisa rodar a mesma peça vinte
    vezes para olhar um detalhe. Bater no limite do plano no meio disso não
    prova nada — só gasta a tarde. Mas ambiente que não cobra tem que DIZER
    que não cobra: senão alguém testa aqui e promete lá fora."""

    def test_desligado_por_padrao(self, monkeypatch):
        from api import uso
        monkeypatch.delenv("REPLICAI_SEM_LIMITE", raising=False)
        assert uso.sem_limite() is False

    def test_ligado_a_franquia_nao_barra(self, monkeypatch, tmp_path):
        from api import uso
        monkeypatch.setenv("REPLICAI_SEM_LIMITE", "1")
        pode, porque = uso.cabe("conta-qualquer", uso.PLANO_PADRAO, pecas=10_000)
        assert pode and porque == ""

    def test_zero_e_nao_contam_como_desligado(self, monkeypatch):
        """`REPLICAI_SEM_LIMITE=0` tem que significar o que diz."""
        from api import uso
        for valor in ("0", "", "nao", "não"):
            monkeypatch.setenv("REPLICAI_SEM_LIMITE", valor)
            assert uso.sem_limite() is False, valor

    def test_a_saude_denuncia_o_ambiente_sem_franquia(self, monkeypatch):
        import inspect

        from api import main
        fonte = inspect.getsource(main.saude)
        assert "franquia" in fonte and "REPLICAI_SEM_LIMITE" in fonte


class TestAEscadaDePlanos:
    """Basic 80, Freelancer 250, e daí para cima. Vídeo é 10% das peças em
    todos: ele anima uma peça que já existe e não chama serviço nenhum, então
    o limite protege a fila, não o caixa — e proporção fixa se explica."""

    def test_a_escada_que_a_ligia_pediu(self):
        from api import uso
        assert uso.PLANOS["basic"]["pecas"] == 80
        assert uso.PLANOS["freelancer"]["pecas"] == 250
        assert [uso.PLANOS[p]["pecas"] for p in uso.A_VENDA] == sorted(
            uso.PLANOS[p]["pecas"] for p in uso.A_VENDA)

    def test_video_e_dez_por_cento_em_todos(self):
        from api import uso
        for p in uso.A_VENDA:
            lim = uso.PLANOS[p]
            assert lim["videos"] == round(lim["pecas"] * 0.10), p

    def test_nao_se_vende_o_sem_plano(self):
        from api import uso
        assert "sem" not in uso.A_VENDA
        assert uso.PLANOS[uso.PLANO_PADRAO]["pecas"] == 0

    def test_subir_de_plano_baixa_o_preco_da_peca(self):
        """É o que faz a escada ser escada: quem produz mais paga menos por
        peça. Se o preço por peça subisse com o volume, o plano de cima seria
        punição — e ninguém sobe."""
        from api import cobranca, uso
        por_peca = [cobranca.PRECO(p) / uso.PLANOS[p]["pecas"] for p in uso.A_VENDA]
        assert por_peca == sorted(por_peca, reverse=True), por_peca
        assert len(set(por_peca)) == len(por_peca), "dois planos com o mesmo preço por peça"

    def test_a_escada_sobe(self):
        from api import cobranca, uso
        precos_ = [cobranca.PRECO(p) for p in uso.A_VENDA]
        assert precos_ == sorted(precos_) and len(set(precos_)) == len(precos_), precos_
        franquias = [uso.PLANOS[p]["pecas"] for p in uso.A_VENDA]
        assert franquias == sorted(franquias), franquias

    def test_nenhum_preco_de_tabela_fura_o_piso(self):
        """O piso é o preço derivado do custo medido. Tabela abaixo dele é
        margem comida em silêncio — e é a esteira que tem que gritar, não o
        extrato no fim do mês."""
        from api import precos, uso
        assert precos.abaixo_do_piso(uso.PLANOS) == []


def test_a_conta_nasce_no_mesmo_estado_que_o_uso_conhece():
    """A conta nascia com `plano="demo"`, que saiu da escada: um degrau
    fantasma, que `limites()` só não transformava em acesso de graça porque cai
    no padrão. Os dois lados têm que dizer a mesma palavra."""
    from api import contas, uso
    assert contas.Conta(id="x", nome="x", email="x@y.z").plano == uso.PLANO_PADRAO
    import inspect
    assinatura = inspect.signature(contas.criar).parameters["plano"]
    assert assinatura.default == uso.PLANO_PADRAO
