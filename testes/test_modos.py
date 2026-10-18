"""Os três modos de desdobrar, e o ajuste na mão.

Quem sobe uma peça escolhe o quanto a plataforma pode mexer nela: só o quadro,
o quadro e a diagramação, ou também o texto. Essa escolha não existia, e a
plataforma escrevia sempre — foi assim que o Stories real saiu com a chamada e
o CTA duplicados por cima do lettering que a arte já trazia, nas mesmas
palavras, porque ninguém tinha pedido texto novo.
"""
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from testes.test_api import FilaEspia, arte_png, cliente, enviar      # noqa: F401


def enviar_psd(cliente, monkeypatch, **extra):
    """O mesmo envio, em camadas. É o arquivo que comporta os três modos: numa
    imagem achatada a arte decide e sobra um só."""
    from api import psd
    monkeypatch.setattr(psd, "pranchetas",
                        lambda a: [psd.Prancheta("Prancheta 1", 0, 0, 1920, 1080)])
    campos = {"formatos": "gdn-300x250", "headline": "Chegamos a Porto Belo"}
    campos.update(extra)
    return cliente.post("/jobs",
                        files={"arte": ("arte.psd", b"8BPS" + b"\0" * 60,
                                        "image/vnd.adobe.photoshop")},
                        data=campos)


class TestEscolhaDoModo:
    def test_sem_modo_a_plataforma_nao_escreve(self, cliente, monkeypatch):
        """O padrão é conservador. Entre inventar texto e não inventar, o
        erro barato é não inventar: dá para pedir de novo pedindo texto."""
        r = enviar_psd(cliente, monkeypatch)
        assert r.status_code == 202
        assert cliente.fila.pedidos[-1][1][-1] == "com"

    def test_so_formato_nao_exige_chamada(self, cliente):
        """Quem quer a mesma peça noutro formato não tem chamada a escrever,
        e a tela travava o começo do trabalho pedindo uma."""
        r = cliente.post("/jobs", files={"arte": ("arte.png", arte_png(), "image/png")},
                         data={"formatos": "gdn-300x250", "modo": "sem"})
        assert r.status_code == 202

    def test_texto_novo_sem_chamada_e_recusado(self, cliente, monkeypatch):
        r = enviar_psd(cliente, monkeypatch, modo="novo", headline="")
        assert r.status_code == 422
        assert "chamada" in r.json()["detail"]

    def test_modo_inventado_e_recusado(self, cliente):
        r = enviar(cliente, modo="turbo")
        assert r.status_code == 422
        assert "turbo" in r.json()["detail"]

    def test_o_modo_chega_ate_a_fila(self, cliente, monkeypatch):
        enviar_psd(cliente, monkeypatch, modo="novo")
        nome, args = cliente.fila.pedidos[-1]
        assert nome == "processar"
        assert args[-1] == "novo"

    def test_na_imagem_achatada_a_arte_decide(self, cliente):
        """"Se ele não possibilita ajuste de diagramação de logo, de fonte,
        porque é uma peça estática, não deveria ter as outras opções."

        Sem camadas não há o que mover nem como corrigir o que for escrito:
        a peça é 100% do formato dela, e os outros dois modos não existem."""
        for pedido in ("com", "novo"):
            enviar(cliente, modo=pedido)
            assert cliente.fila.pedidos[-1][1][-1] == "sem", pedido

    def test_o_modo_sobrevive_a_exportacao_final(self, cliente):
        """Finalizar refaz o trabalho. Refazer com outro modo entregaria uma
        peça diferente da que foi aprovada no rascunho."""
        from api import trabalhos
        job = enviar(cliente, modo="sem").json()["job"]
        trabalhos.gravar(cliente.conta.id, job,
                         {"status": "pronto", "prontas": ["gdn-300x250"]})
        cliente.post(f"/jobs/{job}/finalizar")
        assert cliente.fila.pedidos[-1][1][-1] == "sem"


class TestQuemPreservaNaoEscreve:
    def test_a_peca_sai_sem_elemento_nenhum(self, tmp_path):
        """A peça do modo conservador é a arte reenquadrada, e só. Qualquer
        elemento aqui é texto repetido por cima do que a arte já diz."""
        from api.compositor import CompositorPreserva
        from api.pipeline import desdobrar
        base = tmp_path / "arte.png"
        Image.new("RGB", (1200, 1200), (12, 42, 102)).save(base)
        r = desdobrar(base, ["gdn-300x250"], CompositorPreserva(), tmp_path / "saida")
        montada = json.loads(
            (tmp_path / "saida" / "pecas" / "gdn-300x250.json").read_text(encoding="utf-8"))
        assert montada["elementos"] == []
        assert montada["via"] == "reenquadra"

    def test_nao_gasta_chamada_de_modelo(self, tmp_path):
        """Sem texto a escrever não há o que perguntar: nem para ler a arte.
        É o que faz este modo custar zero por peça."""
        from api.compositor import CompositorPreserva
        from api.pipeline import desdobrar
        chamou = []

        def leitor(arte):
            chamou.append(arte)
            raise AssertionError("ninguém deveria ler a arte neste modo")

        base = tmp_path / "arte.png"
        Image.new("RGB", (1200, 1200), (12, 42, 102)).save(base)
        desdobrar(base, ["gdn-300x250"], CompositorPreserva(), tmp_path / "saida",
                  leitor=leitor)
        assert chamou == []

    def test_o_fundo_nao_corta_a_arte(self, tmp_path):
        """Preservar 100% é a promessa do modo. Com `cover` a peça 1:1 vinda
        de uma 16:9 perdia as pontas — foi o "energiza" virando "energ"."""
        from api.compositor import CompositorPreserva
        from api.pipeline import desdobrar
        base = tmp_path / "arte.png"
        Image.new("RGB", (1600, 900), (12, 42, 102)).save(base)
        desdobrar(base, ["ig-feed-1x1"], CompositorPreserva(), tmp_path / "saida")
        montada = json.loads(
            (tmp_path / "saida" / "pecas" / "ig-feed-1x1.json").read_text(encoding="utf-8"))
        # o fundo é o preparado, não a arte crua servida em cover
        assert montada["fundo"]["src"] == "fundo-ig-feed-1x1.png"


class TestAjusteNaMao:
    def _com_peca(self, cliente):
        from api import trabalhos
        job = enviar(cliente, modo="com").json()["job"]
        pasta = trabalhos.pasta_do(cliente.conta.id, job)
        (pasta / "pecas").mkdir(parents=True, exist_ok=True)
        (pasta / "pecas" / "gdn-300x250.json").write_text(json.dumps({
            "formato": "gdn-300x250", "canvas": {"w": 300, "h": 250},
            "safe": {"top": 0, "bottom": 0, "left": 8, "right": 8},
            "saida": "gdn-300x250.png", "fundo": {"tipo": "cor", "cor": "#000"},
            "elementos": [{"tipo": "texto", "papel": "headline", "texto": "Oi",
                           "box": {"x": 10, "y": 10, "w": 100, "h": 40}}],
        }), encoding="utf-8")
        return job

    def test_mover_grava_a_caixa_nova_e_manda_desenhar(self, cliente):
        job = self._com_peca(cliente)
        r = cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={
            "elementos": [{"i": 0, "box": {"x": 40, "y": 90, "w": 120, "h": 50}}]})
        assert r.status_code == 202
        d = cliente.get(f"/jobs/{job}/pecas/gdn-300x250").json()
        assert d["elementos"][0]["box"] == {"x": 40, "y": 90, "w": 120, "h": 50}
        assert d["elementos"][0]["texto"] == "Oi"      # o resto do elemento fica
        assert cliente.fila.pedidos[-1][0] == "redesenhar"

    def test_elemento_que_nao_volta_sai_da_peca(self, cliente):
        job = self._com_peca(cliente)
        cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={"elementos": []})
        d = cliente.get(f"/jobs/{job}/pecas/gdn-300x250").json()
        assert d["elementos"] == []

    def test_a_tela_nao_escolhe_que_arquivo_o_motor_desenha(self, cliente):
        """`src` não está na lista do que se pode ajustar. Sem isso um pedido
        forjado faria o motor desenhar — e devolver dentro do PNG — qualquer
        arquivo que a máquina conseguisse abrir."""
        job = self._com_peca(cliente)
        cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={"elementos": [
            {"i": 0, "src": "../../../etc/passwd", "tipo": "imagem",
             "box": {"x": 0, "y": 0, "w": 10, "h": 10}}]})
        d = cliente.get(f"/jobs/{job}/pecas/gdn-300x250").json()
        assert "src" not in d["elementos"][0]
        assert d["elementos"][0]["tipo"] == "texto"

    def test_indice_fora_da_peca_e_recusado(self, cliente):
        job = self._com_peca(cliente)
        r = cliente.post(f"/jobs/{job}/pecas/gdn-300x250",
                         json={"elementos": [{"i": 7, "box": {"x": 0, "y": 0, "w": 1, "h": 1}}]})
        assert r.status_code == 422

    def test_formato_sem_peca_montada_nao_abre(self, cliente):
        job = self._com_peca(cliente)
        assert cliente.get(f"/jobs/{job}/pecas/ig-stories").status_code == 404

    def test_ajustar_nao_conta_peca_de_novo(self, cliente):
        """A franquia é por peça produzida. Cobrar de novo porque a pessoa
        discordou da diagramação é cobrar por discordar."""
        from api import uso
        job = self._com_peca(cliente)
        antes = uso.resumo(cliente.conta.id)["pecas"]
        cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={
            "elementos": [{"i": 0, "box": {"x": 1, "y": 1, "w": 10, "h": 10}}]})
        assert uso.resumo(cliente.conta.id)["pecas"] == antes


class TestMedidaLivre:
    def test_a_api_aceita_medida_fora_do_catalogo(self, cliente):
        """O catálogo cobre os destinos conhecidos. Fora deles havia só o
        impasse: ou o formato existia na lista, ou a peça não saía."""
        r = enviar(cliente, formatos="livre-1080x1350", modo="sem")
        assert r.status_code == 202

    def test_medida_absurda_continua_recusada(self, cliente):
        for fid in ("livre-10x10", "livre-99999x200", "livre-abcxdef"):
            r = enviar(cliente, formatos=fid, modo="sem")
            assert r.status_code == 422, fid

    def test_a_margem_e_proporcional_e_o_lado_maior_nao_manda_nela(self):
        """Margem calculada sobre o lado maior esmagaria a faixa de um banner
        3000x500 até sobrar menos do que o texto precisa."""
        from motor.replica import formato_by_id
        f = formato_by_id("livre-3000x500")
        assert f["safe"]["top"] == f["safe"]["left"]
        assert 0 < f["safe"]["top"] < 500 * 0.1

    def test_a_proporcao_vem_simplificada(self):
        from motor.replica import formato_by_id
        assert formato_by_id("livre-1920x1080")["ratio"] == "16:9"

    def test_a_peca_sai_na_medida_pedida(self, tmp_path):
        from api.compositor import CompositorPreserva
        from api.pipeline import desdobrar
        base = tmp_path / "arte.png"
        Image.new("RGB", (1200, 1200), (12, 42, 102)).save(base)
        desdobrar(base, ["livre-900x1600"], CompositorPreserva(), tmp_path / "saida")
        with Image.open(tmp_path / "saida" / "livre-900x1600.png") as im:
            assert im.size == (900, 1600)


class TestOMotivoDoFundo:
    """O aviso da queda do generativo tem que dizer o que houve de verdade."""

    def test_recusa_rapida_nao_e_relatada_como_demora(self, monkeypatch, tmp_path):
        """Dizer "não respondeu em 180s" quando a recusa voltou em dois
        segundos manda quem lê procurar lentidão onde o problema é crédito."""
        from api import fundo
        monkeypatch.setattr(fundo, "_outpaint_higgsfield",
                            lambda *a, **k: (None, {"erro": "sem URL de resultado"}))
        relogio = iter([0.0, 2.0])
        import time as _t
        monkeypatch.setattr(_t, "monotonic", lambda: next(relogio))
        base = Image.new("RGB", (100, 100), (0, 0, 0))
        _, motivo = fundo._continuar(base, {"left": 0, "right": 0, "top": 0, "bottom": 10}, 180)
        assert "180s" not in motivo
        assert "crédito" in motivo

    def test_demora_de_verdade_continua_sendo_demora(self, monkeypatch):
        from api import fundo
        monkeypatch.setattr(fundo, "_outpaint_higgsfield",
                            lambda *a, **k: (None, {"erro": "sem resposta"}))
        relogio = iter([0.0, 180.0])
        import time as _t
        monkeypatch.setattr(_t, "monotonic", lambda: next(relogio))
        base = Image.new("RGB", (100, 100), (0, 0, 0))
        _, motivo = fundo._continuar(base, {"left": 0, "right": 0, "top": 0, "bottom": 10}, 180)
        assert "não respondeu em 180s" in motivo


class TestOAjusteSobreviveAExportacao:
    """A exportação final refaz o trabalho inteiro — é assim que ela insiste
    no fundo generativo. Refazendo, ela reescrevia a peça por cima do ajuste:
    a pessoa movia o CTA, clicava em exportar e o CTA voltava sozinho."""

    def _peca(self, pasta, via, x):
        import json as _j
        (pasta / "pecas").mkdir(parents=True, exist_ok=True)
        (pasta / "pecas" / "gdn-300x250.json").write_text(_j.dumps({
            "formato": "gdn-300x250", "via": via,
            "elementos": [{"tipo": "texto", "papel": "cta", "texto": "Oi",
                           "box": {"x": x, "y": 5, "w": 50, "h": 20}}]}), encoding="utf-8")

    def test_a_montagem_feita_a_mao_volta_para_a_peca(self, tmp_path):
        from api.pipeline import manter_a_mao
        self._peca(tmp_path, "psd-reenquadra+mao", 99)
        nova = {"via": "psd-reenquadra", "elementos": [{"tipo": "texto", "papel": "cta",
                                                        "box": {"x": 5, "y": 5, "w": 50, "h": 20}}]}
        avisos = manter_a_mao(nova, tmp_path, "gdn-300x250")
        assert nova["elementos"][0]["box"]["x"] == 99
        assert "+mao" in nova["via"]
        assert avisos and "à mão" in avisos[0]

    def test_peca_que_ninguem_ajustou_e_recomposta_normalmente(self, tmp_path):
        from api.pipeline import manter_a_mao
        self._peca(tmp_path, "psd-reenquadra", 99)
        nova = {"via": "psd-reenquadra", "elementos": [{"box": {"x": 5, "y": 5, "w": 1, "h": 1}}]}
        assert manter_a_mao(nova, tmp_path, "gdn-300x250") == []
        assert nova["elementos"][0]["box"]["x"] == 5

    def test_so_a_montagem_volta_o_fundo_novo_fica(self, tmp_path):
        """O fundo refeito é justamente o que a exportação final foi buscar."""
        from api.pipeline import manter_a_mao
        self._peca(tmp_path, "psd-reenquadra+mao", 99)
        nova = {"via": "psd-reenquadra", "elementos": [],
                "fundo": {"tipo": "imagem", "src": "fundo-novo.png"}}
        manter_a_mao(nova, tmp_path, "gdn-300x250")
        assert nova["fundo"]["src"] == "fundo-novo.png"


class TestOTempoEstimado:
    """Abrir um PSD de 60 MB em camadas leva quase um minuto, e esse minuto
    não se repete por formato. Contado como ritmo, ele anunciava catorze
    minutos restantes num trabalho de um."""

    def test_o_relogio_so_comeca_no_primeiro_formato(self):
        from api.pipeline import _passo
        vistos = []
        avisar = _passo(vistos.append, 3)
        avisar("abrindo o PSD em camadas", 0)
        assert vistos[-1]["desde"] is None
        avisar("preparando o fundo", 0, "ig-stories")
        assert vistos[-1]["desde"] is not None

    def test_o_relogio_nao_reinicia_a_cada_formato(self):
        from api.pipeline import _passo
        vistos = []
        avisar = _passo(vistos.append, 2)
        avisar("preparando o fundo", 0, "a")
        primeiro = vistos[-1]["desde"]
        avisar("preparando o fundo", 1, "b")
        assert vistos[-1]["desde"] == primeiro


class TestAsPecasAparecemUmaAUma:
    def test_o_passo_leva_o_que_ja_ficou_pronto(self):
        """Sem isso o estado só ganhava `prontas` no fim, e quem pediu oito
        formatos ficava minutos olhando quadro vazio com a primeira peça já
        desenhada no disco."""
        from api.pipeline import Resultado, _passo
        from pathlib import Path
        r = Resultado(pasta=Path("."))
        vistos = []
        avisar = _passo(vistos.append, 3, r)
        avisar("preparando o fundo", 0, "a")
        assert vistos[-1]["prontas"] == []
        r.prontas["a"] = Path("a.png")
        avisar("pronta", 1, "a")
        assert vistos[-1]["prontas"] == ["a"]

    def test_a_esteira_grava_prontas_antes_de_terminar(self, tmp_path):
        from api.compositor import CompositorPreserva
        from api.pipeline import desdobrar
        base = tmp_path / "arte.png"
        Image.new("RGB", (1200, 1200), (12, 42, 102)).save(base)
        passos = []
        desdobrar(base, ["gdn-300x250", "gdn-320x50"], CompositorPreserva(),
                  tmp_path / "saida", progresso=passos.append)
        # houve pelo menos um passo anunciando a primeira peça com a segunda
        # ainda por fazer
        parciais = [p for p in passos if len(p["prontas"]) == 1 and p["total"] == 2]
        assert parciais, [p.get("prontas") for p in passos]


class TestCorDeFora:
    """Um bloco chapado não inventa traço nenhum e passava na conferência,
    mesmo sendo magenta num fundo azul. Aconteceu de verdade: o generativo
    devolveu faixas magenta num KV da Consigaz, com `limpo: true` e sem aviso,
    e a peça foi entregue assim."""

    def _peca(self, cor_da_faixa):
        """Arte azul no meio, faixa da cor dada em cima e embaixo."""
        import numpy as np
        alto = Image.new("RGB", (200, 400), cor_da_faixa)
        arte = Image.new("RGB", (200, 200))
        px = arte.load()
        for y in range(200):          # um degradê azul, com variação
            for x in range(200):
                px[x, y] = (20 + x // 4, 90 + y // 3, 200)
        alto.paste(arte, (0, 100))
        return alto, arte

    def test_faixa_magenta_num_fundo_azul_e_acusada(self, tmp_path):
        from api.fundo import cor_estranha
        peca, arte = self._peca((236, 24, 244))
        peca.save(tmp_path / "f.png")
        avisos = cor_estranha(tmp_path / "f.png", [0, 100, 200, 300], arte)
        assert len(avisos) == 2
        assert "não existe na arte" in avisos[0]

    def test_faixa_tirada_da_propria_paleta_passa(self, tmp_path):
        from api.fundo import cor_estranha
        peca, arte = self._peca((30, 120, 200))
        peca.save(tmp_path / "f.png")
        assert cor_estranha(tmp_path / "f.png", [0, 100, 200, 300], arte) == []

    def test_sem_extensao_nao_ha_o_que_conferir(self, tmp_path):
        from api.fundo import cor_estranha
        peca, arte = self._peca((236, 24, 244))
        peca.save(tmp_path / "f.png")
        assert cor_estranha(tmp_path / "f.png", [0, 0, 200, 400], arte) == []

    def test_a_esteira_nao_entrega_a_faixa_magenta(self, tmp_path, monkeypatch):
        """Primeiro ela entregava calada. Depois passou a entregar com aviso —
        e ninguém publica um KV azul com tarja magenta, então entregar com
        ressalva é empurrar o problema para quem está com pressa. Agora o
        generativo absurdo é descartado e o determinístico assume."""
        from api import fundo as pf
        from motor.replica import formato_by_id
        arte = tmp_path / "arte.png"
        base = Image.new("RGB", (200, 200))
        px = base.load()
        for y in range(200):
            for x in range(200):
                px[x, y] = (20 + x // 4, 90 + y // 3, 200)
        base.save(arte)

        def magenta(b, ex, espera):
            alvo = (b.width + ex["left"] + ex["right"], b.height + ex["top"] + ex["bottom"])
            tela = Image.new("RGB", alvo, (236, 24, 244))
            tela.paste(b, (ex["left"], ex["top"]))
            return tela, ""

        monkeypatch.setattr(pf, "_continuar", magenta)
        info = pf.preparar(arte, formato_by_id("ig-stories"), None,
                           tmp_path / "fundo.png", modo="outpaint")
        assert info["modo"] == "stretch", "a faixa magenta foi entregue"
        assert "descartado" in info["caiu_para"]
        # e o que ficou em disco é o determinístico, que pode ser reaproveitado
        import json as _j
        assinatura = _j.loads((tmp_path / "fundo.png.origem.json").read_text())
        assert assinatura["modo"] == "stretch"


class TestOPacoteSoLevaAsPecas:
    """A pasta do trabalho guarda a arte original, o fundo preparado e cada
    recorte de letra do PSD. Num PSD de 60 MB o pacote saía com 118 MB e 88
    arquivos, e quem pediu duas peças tinha de garimpar as duas no meio."""

    def test_deixa_de_fora_a_oficina(self):
        from api.main import para_entregar
        itens = [{"nome": n} for n in (
            "arte.psd", "base.psd", "fundo.png", "fundo-ig-stories.png",
            "fundo-ig-stories.png.origem.json", "00-chegamos-0003.png",
            "grotesk.ttf", "ig-stories.png", "gdn-300x250.png",
            "video/ig-stories.mp4")]
        fica = {i["nome"] for i in para_entregar(
            {"prontas": ["ig-stories", "gdn-300x250"]}, itens)}
        assert fica == {"ig-stories.png", "gdn-300x250.png", "video/ig-stories.mp4"}

    def test_formato_que_nao_saiu_nao_entra(self):
        from api.main import para_entregar
        itens = [{"nome": "ig-stories.png"}, {"nome": "gdn-300x250.png"}]
        fica = {i["nome"] for i in para_entregar({"prontas": ["ig-stories"]}, itens)}
        assert fica == {"ig-stories.png"}

    def test_sem_nada_reconhecido_manda_tudo(self):
        """Melhor um pacote gordo do que um pacote vazio."""
        from api.main import para_entregar
        itens = [{"nome": "coisa.png"}]
        assert para_entregar({"prontas": []}, itens) == itens


class TestDuasPessoasNaMesmaPeca:
    """No Agency são até três pessoas na mesma conta. Duas podem abrir a mesma
    peça, e a última a salvar apagaria o trabalho da primeira em silêncio."""

    def _com_peca(self, cliente):
        return TestAjusteNaMao()._com_peca(cliente)

    def test_salvar_sem_dizer_a_versao_continua_valendo(self, cliente):
        """Quem integra pelo programa não tem editor aberto: exigir versão
        quebraria a chave de API de quem já usa."""
        job = self._com_peca(cliente)
        r = cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={
            "elementos": [{"i": 0, "box": {"x": 1, "y": 1, "w": 10, "h": 10}}]})
        assert r.status_code == 202

    def test_a_versao_sobe_a_cada_ajuste(self, cliente):
        job = self._com_peca(cliente)
        primeira = cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={
            "elementos": [{"i": 0, "box": {"x": 1, "y": 1, "w": 10, "h": 10}}]}).json()
        assert primeira["versao"] == 1
        segunda = cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={
            "elementos": [{"i": 0, "box": {"x": 2, "y": 2, "w": 10, "h": 10}}],
            "versao": 1}).json()
        assert segunda["versao"] == 2

    def test_quem_abriu_antes_nao_apaga_o_trabalho_de_quem_salvou(self, cliente):
        job = self._com_peca(cliente)
        # as duas abrem a peça na versão 0
        aberta = cliente.get(f"/jobs/{job}/pecas/gdn-300x250").json()
        assert aberta.get("versao", 0) == 0
        # a primeira salva
        cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={
            "elementos": [{"i": 0, "box": {"x": 40, "y": 90, "w": 120, "h": 50}}],
            "versao": 0})
        # a segunda tenta salvar com a versão que abriu
        r = cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={
            "elementos": [{"i": 0, "box": {"x": 5, "y": 5, "w": 20, "h": 20}}],
            "versao": 0})
        assert r.status_code == 409
        assert "abra de novo" in r.json()["detail"].lower()
        # e o ajuste da primeira continua lá
        d = cliente.get(f"/jobs/{job}/pecas/gdn-300x250").json()
        assert d["elementos"][0]["box"] == {"x": 40, "y": 90, "w": 120, "h": 50}

    def test_a_peca_guarda_quem_ajustou(self, cliente):
        job = self._com_peca(cliente)
        cliente.post(f"/jobs/{job}/pecas/gdn-300x250", json={
            "elementos": [{"i": 0, "box": {"x": 1, "y": 1, "w": 10, "h": 10}}]})
        mao = cliente.get(f"/jobs/{job}/pecas/gdn-300x250").json()["mao"]
        assert mao["nome"]
        assert mao["quando"]


class TestAChamadaTrocaADaArte:
    """"Selecionei a opção de trocar texto, ele vem na ressalva que não foi
    possível pois já havia um texto lá, mas não faz sentido, uma vez que a
    opção é pra trocar o texto."

    A chamada escrita era entregue ao modelo como texto a ACRESCENTAR num
    espaço livre. Numa arte que ocupa a peça inteira não há espaço livre, e
    ele recusava: "não há zona livre na arte para posicioná-la; além disso,
    repetiria a ideia de 'Energia que impulsiona o futuro'". Ou seja:
    recusava porque já havia ali exatamente o texto que era para ser trocado.
    """

    def peca(self, tmp_path):
        """Uma peça de PSD com a chamada em três letras recortadas."""
        from PIL import Image
        els = []
        for i, x in enumerate((10, 40, 70)):
            Image.new("RGBA", (28, 30), (255, 255, 255, 255)).save(tmp_path / f"l{i}.png")
            els.append({"tipo": "imagem", "papel": "headline", "de": "energiza",
                        "camada": "energiza", "letra": i, "fonte_mae": "FuturaICG-Bold",
                        "src": f"l{i}.png", "box": {"x": x, "y": 50, "w": 28, "h": 30}})
        els.insert(0, {"tipo": "imagem", "papel": "figura", "src": "arte.png",
                       "box": {"x": 0, "y": 0, "w": 300, "h": 250}})
        els.append({"tipo": "imagem", "papel": "apoio", "src": "a.png",
                    "box": {"x": 10, "y": 90, "w": 100, "h": 10}})
        return {"canvas": {"w": 300, "h": 250}, "elementos": els, "fontes": []}

    def test_a_chamada_nova_entra_no_lugar_da_antiga(self, tmp_path):
        from api.pipeline import trocar_a_chamada
        p = self.peca(tmp_path)
        trocar_a_chamada(p, tmp_path, "A sua energia para o futuro")
        chamadas = [e for e in p["elementos"] if e.get("papel") == "headline"]
        assert len(chamadas) == 1, "os recortes antigos continuaram na peça"
        assert chamadas[0]["tipo"] == "texto"
        assert chamadas[0]["texto"] == "A sua energia para o futuro"

    def test_ocupa_a_caixa_da_linha_inteira(self, tmp_path):
        """A frase nova mora onde a antiga morava: é o que preserva a
        diagramação da arte-mãe."""
        from api.pipeline import trocar_a_chamada
        p = self.peca(tmp_path)
        trocar_a_chamada(p, tmp_path, "Outra chamada")
        caixa = next(e for e in p["elementos"] if e.get("papel") == "headline")["box"]
        assert caixa == {"x": 10, "y": 50, "w": 88, "h": 30}

    def test_sai_na_cor_que_a_linha_tinha(self, tmp_path):
        from api.pipeline import trocar_a_chamada
        p = self.peca(tmp_path)
        trocar_a_chamada(p, tmp_path, "Outra")
        assert next(e for e in p["elementos"]
                    if e.get("papel") == "headline")["cor"] == "#FFFFFF"

    def test_o_resto_da_peca_fica_onde_estava(self, tmp_path):
        """Trocar a chamada não é refazer a peça: figura e apoio continuam."""
        from api.pipeline import trocar_a_chamada
        p = self.peca(tmp_path)
        trocar_a_chamada(p, tmp_path, "Outra")
        papeis = [e.get("papel") for e in p["elementos"]]
        assert papeis == ["figura", "headline", "apoio"], papeis

    def test_sem_a_fonte_da_marca_o_aviso_vem(self, tmp_path):
        """O PSD diz o nome da fonte e não leva o arquivo. Sair noutra letra
        em silêncio é o erro mais difícil de ver no olho."""
        from api.pipeline import trocar_a_chamada
        p = self.peca(tmp_path)
        avisos = trocar_a_chamada(p, tmp_path, "Outra",
                                  lambda f: ("PecaSans", "", f"a chamada da arte é {f}"))
        assert avisos and "FuturaICG-Bold" in avisos[0]

    def test_com_a_fonte_da_marca_ela_vai_declarada_com_arquivo(self, tmp_path):
        """Família declarada sem arquivo faz o navegador cair numa fonte do
        sistema, calado."""
        from api.pipeline import trocar_a_chamada
        p = self.peca(tmp_path)
        avisos = trocar_a_chamada(p, tmp_path, "Outra",
                                  lambda f: (f, "futura.ttf", ""))
        linha = next(e for e in p["elementos"] if e.get("papel") == "headline")
        assert linha["fonte"] == "FuturaICG-Bold"
        assert {"familia": "FuturaICG-Bold", "arquivo": "futura.ttf",
                "peso": "100 900"} in p["fontes"]
        assert not avisos

    def test_peca_sem_chamada_na_arte_nao_muda(self, tmp_path):
        """Nem toda arte tem camada de chamada: aí o texto novo continua
        sendo trabalho do modelo, em espaço livre."""
        from api.pipeline import trocar_a_chamada
        p = {"canvas": {"w": 300, "h": 250}, "elementos": [
            {"tipo": "imagem", "papel": "figura", "src": "a.png",
             "box": {"x": 0, "y": 0, "w": 300, "h": 250}}]}
        assert trocar_a_chamada(p, tmp_path, "Chamada") == []
        assert len(p["elementos"]) == 1

    def test_chamada_vazia_nao_mexe_na_arte(self, tmp_path):
        from api.pipeline import trocar_a_chamada
        p = self.peca(tmp_path)
        assert trocar_a_chamada(p, tmp_path, "   ") == []
        assert len([e for e in p["elementos"] if e.get("papel") == "headline"]) == 3


class TestOModeloOlhaAArte:
    """O modelo decidia olhando a PRANCHETA, não a arte.

    Num PSD cujas camadas vêm todas soltas, o fundo assado é a prancheta
    vazia. Ele recebia uma imagem branca e escreveu isso na própria resposta:
    "a imagem recebida aparece totalmente branca, sem texto nem logo visível".
    Toda decisão dele naquela peça foi tomada sobre uma imagem em branco.
    """

    def test_a_arte_mae_e_o_que_vai_para_o_modelo(self, tmp_path):
        assert "arte-mae.png" in open("api/pipeline.py", encoding="utf-8").read()
        from pathlib import Path
        import inspect
        from api import pipeline
        fonte = inspect.getsource(pipeline._texto_novo)
        assert 'olha = pasta / "arte-mae.png"' in fonte
        assert "compositor.compor(olha," in fonte
        # e segue valendo o fundo assado quando a arte-mãe não saiu
        assert "if not olha.exists():" in fonte


class TestACadeiaResponderPeloConjunto:
    """"Coloquei a versão de inserir texto e de novo ela ignorou."

    A esteira lê `getattr(compositor, "headline", "")` para trocar o texto da
    arte e para conferir se ele entrou. COM credencial o compositor é uma
    cadeia (modelo, e a régua atrás), que não tinha o atributo: a troca nunca
    acontecia e a conferência achava que não havia nada a conferir. SEM
    credencial o compositor é o simples, que tem o atributo — por isso o
    defeito não aparecia na máquina de quem desenvolve.
    """

    def test_a_cadeia_sabe_a_chamada_dos_seus_compositores(self):
        from api.compositor import CompositorEmCadeia, CompositorSimples

        class SoCompoe:
            def compor(self, *a, **k): return {}

        c = CompositorEmCadeia(SoCompoe(), CompositorSimples(headline="Oi", cta="Vem"))
        assert c.headline == "Oi" and c.cta == "Vem"

    def test_atributo_que_ninguem_tem_continua_não_existindo(self):
        """`getattr(compositor, "preserva", False)` precisa poder dar o
        padrão: inventar o atributo faria a esteira escrever sem ser pedido."""
        import pytest
        from api.compositor import CompositorEmCadeia, CompositorSimples
        c = CompositorEmCadeia(CompositorSimples(headline="Oi"))
        assert getattr(c, "preserva", False) is False
        with pytest.raises(AttributeError):
            c.coisa_que_ninguem_tem

    def test_com_o_modelo_disponivel_a_chamada_chega_a_esteira(self, monkeypatch):
        """O caminho exato da máquina dela: credencial presente."""
        from api import modelo, tarefas
        monkeypatch.setattr(modelo, "disponivel", lambda: True)
        c = tarefas.compositor("arte.psd", "Teste energia", "", "novo")
        assert type(c).__name__ == "CompositorEmCadeia"
        assert getattr(c, "headline", "") == "Teste energia"


class TestRessalvaQueNaoEhNoticia:
    """"Nada foi acrescentado à peça", logo abaixo de uma troca que deu
    certo, lê-se como "ignorei o seu texto"."""

    def _peca_trocada(self):
        return {"canvas": {"w": 300, "h": 300}, "fundo": {"src": "f.png"},
                "elementos": [{"tipo": "texto", "papel": "headline",
                               "texto": "Nova", "trocado": True,
                               "box": {"x": 0, "y": 0, "w": 100, "h": 20}}]}

    def test_sem_nada_pendente_a_recusa_nao_vira_ressalva(self, tmp_path, monkeypatch):
        from api import pipeline
        from api.compositor import ComposicaoImpossivel

        class Recusa:
            headline, cta, preserva = "Nova", "", False
            def compor(self, *a, **k): raise ComposicaoImpossivel("a arte já traz o texto")

        monkeypatch.setattr(pipeline.prep_fundo, "espaco_livre", lambda *a, **k: [])
        monkeypatch.setattr(pipeline.sossego, "acalmar", lambda *a, **k: ([], None))
        from PIL import Image
        Image.new("RGB", (300, 300), "#123").save(tmp_path / "f.png")

        class Leitura:
            camadas, fundo = [], "f.png"
        assert pipeline._texto_novo(self._peca_trocada(), {"id": "x", "w": 300, "h": 300},
                                    tmp_path, Leitura(), "", Recusa(), {}) == []

    def test_com_botao_pedido_a_recusa_continua_sendo_dita(self, tmp_path, monkeypatch):
        """Aí havia material pendente de verdade: o botão não entrou."""
        from api import pipeline
        from api.compositor import ComposicaoImpossivel

        class Recusa:
            headline, cta, preserva = "Nova", "Compre agora", False
            def compor(self, *a, **k): raise ComposicaoImpossivel("não cabe")

        monkeypatch.setattr(pipeline.prep_fundo, "espaco_livre", lambda *a, **k: [])
        monkeypatch.setattr(pipeline.sossego, "acalmar", lambda *a, **k: ([], None))
        from PIL import Image
        Image.new("RGB", (300, 300), "#123").save(tmp_path / "f.png")

        class Leitura:
            camadas, fundo = [], "f.png"
        avisos = pipeline._texto_novo(self._peca_trocada(), {"id": "x", "w": 300, "h": 300},
                                      tmp_path, Leitura(), "", Recusa(), {})
        assert avisos and "não cabe" in avisos[0]
