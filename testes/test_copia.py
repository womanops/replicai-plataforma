"""A cópia diária do que é dos clientes.

O backup do provedor é semanal e salva a máquina. Isto salva o trabalho
entregue — o que o cliente pagou e não tem como ser refeito. Os testes aqui
são sobre as quatro coisas que fazem uma cópia prestar: ela leva o que
importa, **não** leva o que vai ser apagado de qualquer jeito, sai do
servidor, e avisa quando para de acontecer.
"""
import json
import tarfile
from pathlib import Path

import pytest


class S3Falso:
    """O armazenamento, sem rede e sem credencial.

    `quebrar_no` existe para o caso que mais importa e menos acontece em
    teste: cair NO MEIO de uma cópia grande.
    """

    def __init__(self, quebrar=False, quebrar_no=None):
        self.objetos: dict[str, int] = {}
        self.quebrar = quebrar
        self.quebrar_no = quebrar_no
        self.subidas = 0

    def upload_file(self, caminho, balde, chave):
        self.subidas += 1
        if self.quebrar or (self.quebrar_no and self.subidas >= self.quebrar_no):
            raise OSError("o armazenamento recusou")
        self.objetos[chave] = Path(caminho).stat().st_size

    def list_objects_v2(self, Bucket, Prefix=""):
        return {"Contents": [{"Key": k} for k in sorted(self.objetos)
                             if k.startswith(Prefix)]}

    def delete_object(self, Bucket, Key):
        self.objetos.pop(Key, None)


@pytest.fixture
def plataforma(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("REPLICAI_COPIA_BUCKET", "balde")
    monkeypatch.setenv("REPLICAI_COPIA_CHAVE", "chave")
    monkeypatch.setenv("REPLICAI_COPIA_SEGREDO", "segredo")
    monkeypatch.setenv("REPLICAI_AVISO_PARA", "operacao@exemplo.teste")
    import importlib
    from api import copia, trabalhos
    importlib.reload(trabalhos)

    # um trabalho entregue, com bruto e com peça
    conta = tmp_path / "agencia-1"
    job = conta / "campanha-1"
    (job / "pecas").mkdir(parents=True)
    (job / "trabalho.json").write_text(json.dumps(
        {"status": "pronto", "prontas": ["ig-feed-1x1"]}), encoding="utf-8")
    # peça do tamanho de uma peça de verdade (2,41 MB é a mediana medida), para
    # o teste do tamanho não passar por acaso com um arquivo de brinquedo
    (job / "ig-feed-1x1.png").write_bytes(bytes(range(256)) * 9400)
    (job / "pecas" / "ig-feed-1x1.json").write_text("{}", encoding="utf-8")
    (job / "arte.psd").write_bytes(b"o psd pesado" * 10_000)
    (job / "00-camada.png").write_bytes(b"recorte de camada" * 1000)
    (tmp_path / "_contas").mkdir()
    (tmp_path / "_contas" / "agencia-1.json").write_text("{}", encoding="utf-8")

    falso = S3Falso()
    monkeypatch.setattr(copia, "_cliente", lambda: falso)
    copia.s3 = falso
    return copia, falso, tmp_path


class TestOQueEntraNaCopia:
    def test_leva_a_peca_entregue_e_as_contas(self, plataforma):
        copia, falso, _ = plataforma
        copia.fazer()
        guardados = set(falso.objetos)
        assert "replicai/arquivos/agencia-1/campanha-1/ig-feed-1x1.png" in guardados
        assert "replicai/arquivos/_contas/agencia-1.json" in guardados
        assert "replicai/arquivos/agencia-1/campanha-1/pecas/ig-feed-1x1.json" in guardados

    def test_nao_leva_o_bruto(self, plataforma):
        """O bruto tem prazo de validade de 30 dias e é 85% do disco. Copiar o
        que vai ser apagado é pagar armazenamento para guardar lixo."""
        copia, falso, _ = plataforma
        copia.fazer()
        assert not any(k.endswith((".psd", ".psb")) for k in falso.objetos)
        assert not any("00-camada" in k for k in falso.objetos)

    def test_leva_o_mesmo_que_a_faxina_guarda(self, plataforma):
        """Uma regra só, nos dois lugares: se a faxina passar a guardar mais
        coisa, a cópia leva junto sem ninguém lembrar."""
        import inspect
        copia, _, _ = plataforma
        assert "faxina._guardar(estado)" in inspect.getsource(copia.o_que_vai)

    def test_o_caminho_la_dentro_espelha_o_daqui(self, plataforma):
        """Restaurar é descer os arquivos por cima da pasta de dados."""
        copia, falso, _ = plataforma
        copia.fazer()
        for chave in falso.objetos:
            if chave.startswith("replicai/arquivos/"):
                assert ".." not in chave


class TestEspelhoEmVezDePacote:
    """A primeira versão empacotava tudo todo dia e guardava catorze — catorze
    vezes o tamanho dos dados, porque peça entregue nunca muda. A R$ 0,10 o GB
    da Magalu, isso é R$ 102 contra R$ 7,29 por mês com dez clientes em um ano."""

    def test_o_que_ja_subiu_nao_sobe_de_novo(self, plataforma):
        copia, falso, _ = plataforma
        primeira = copia.fazer()
        quantos = len(falso.objetos)
        segunda = copia.fazer()
        assert primeira["novos"] >= 3
        assert segunda["novos"] == 0
        assert segunda["ja_estavam"] == primeira["novos"]
        # só a versão datada das contas é reescrita; o espelho fica igual
        assert len(falso.objetos) == quantos

    def test_peca_nova_sobe_no_dia_seguinte(self, plataforma):
        copia, falso, base = plataforma
        copia.fazer()
        job = base / "agencia-1" / "campanha-1"
        import json as _json
        (job / "trabalho.json").write_text(_json.dumps(
            {"status": "pronto", "prontas": ["ig-feed-1x1", "ig-stories"]}),
            encoding="utf-8")
        (job / "ig-stories.png").write_bytes(b"outra peca" * 1000)
        d = copia.fazer()
        assert d["novos"] == 2          # a peça nova e o trabalho.json que mudou
        assert "replicai/arquivos/agencia-1/campanha-1/ig-stories.png" in falso.objetos

    def test_conta_alterada_sobe_de_novo(self, plataforma):
        """Peça não muda; conta muda — plano, senha, medidas."""
        copia, falso, base = plataforma
        copia.fazer()
        (base / "_contas" / "agencia-1.json").write_text('{"plano": "studio"}',
                                                         encoding="utf-8")
        assert copia.fazer()["novos"] == 1

    def test_o_que_sumiu_daqui_nao_some_de_la(self, plataforma):
        """Backup que apaga o que foi apagado não protege do engano, que é
        metade do motivo de existir."""
        copia, falso, base = plataforma
        copia.fazer()
        antes = set(falso.objetos)
        import shutil
        shutil.rmtree(base / "agencia-1")
        copia.fazer()
        assert antes <= set(falso.objetos)


class TestAsContasGanhamVersao:
    def test_sobe_uma_versao_datada(self, plataforma):
        copia, falso, _ = plataforma
        d = copia.fazer()
        assert d["contas"].startswith("contas-")
        assert any(k.startswith("replicai/contas/contas-") for k in falso.objetos)

    def test_so_as_contas_giram(self, plataforma):
        copia, falso, _ = plataforma
        copia.fazer()
        for dia in range(1, 21):
            falso.objetos[f"replicai/contas/contas-2026-09-{dia:02d}.tar.gz"] = 10
        apagadas = copia.girar_contas(manter=14)
        versoes = [k for k in falso.objetos if k.startswith("replicai/contas/")]
        assert len(versoes) == 14
        assert any(k.startswith("replicai/arquivos/") for k in falso.objetos)
        assert "replicai/contas/contas-2026-09-01.tar.gz" in apagadas

    def test_a_versao_das_contas_nao_fica_no_disco(self, plataforma):
        copia, _, base = plataforma
        copia.fazer()
        assert not list(base.glob("**/contas-*.tar.gz"))


class TestQuandoFalha:
    def test_falhar_nao_derruba_e_fica_registrado(self, plataforma, monkeypatch):
        copia, _, _ = plataforma
        monkeypatch.setattr(copia, "_cliente", lambda: S3Falso(quebrar=True))
        d = copia.fazer()
        assert d["ok"] is False
        assert "recusou" in d["porque"]
        assert copia.ultima()["ok"] is False

    def test_sem_armazenamento_configurado_ela_diz_em_letras(self, plataforma, monkeypatch):
        copia, _, _ = plataforma
        monkeypatch.delenv("REPLICAI_COPIA_BUCKET")
        d = copia.fazer()
        assert d["ok"] is False
        assert "não configurado" in d["porque"]
        assert "desligada" in copia.em_json()["estado"]

    def test_avisa_quando_quebra_e_quando_volta(self, plataforma, monkeypatch):
        """Carta diária dizendo "falhou de novo" vira carta que ninguém lê."""
        from api import correio
        copia, falso, _ = plataforma
        cartas = []
        monkeypatch.setattr(correio, "enviar",
                            lambda para, assunto, texto: cartas.append(assunto)
                            or {"enviado": True})
        copia.fazer()                                   # primeira: ok
        monkeypatch.setattr(copia, "_cliente", lambda: S3Falso(quebrar=True))
        copia.fazer()                                   # quebrou: avisa
        copia.fazer()                                   # quebrou de novo: cala
        monkeypatch.setattr(copia, "_cliente", lambda: falso)
        copia.fazer()                                   # voltou: avisa
        assert len(cartas) == 3                         # ok inicial, falha, volta
        assert "falhou" in cartas[1]
        assert "voltou" in cartas[2]

    def test_o_que_falhou_no_meio_sobe_amanha(self, plataforma, monkeypatch):
        """Cair no meio é o caso que importa: o arquivo que NÃO subiu não pode
        ficar marcado como guardado — o buraco só apareceria na restauração."""
        copia, falso, _ = plataforma
        meio = S3Falso(quebrar_no=3)
        monkeypatch.setattr(copia, "_cliente", lambda: meio)
        assert copia.fazer()["ok"] is False
        subiram = set(meio.objetos)

        monkeypatch.setattr(copia, "_cliente", lambda: falso)
        d = copia.fazer()
        assert d["ok"] is True
        # tudo que faltava subiu, e o que já estava não subiu de novo
        guardados = {k for k in falso.objetos if k.startswith("replicai/arquivos/")}
        esperados = {k for k in copia._tudo()["enviados"]}
        assert len(guardados) + len(subiram) >= len(esperados)
        assert d["novos"] == len(esperados) - len(subiram)

    def test_o_progresso_vai_para_o_disco_durante_a_copia(self):
        """A primeira cópia de uma carteira grande leva horas: uma queda no
        fim não pode mandar tudo de volta para o começo."""
        import inspect
        from api import copia
        fonte = inspect.getsource(copia.espelhar)
        assert "len(novos) % 50 == 0" in fonte
        assert "finally:" in fonte

    def test_a_carta_de_falha_diz_o_que_esta_desprotegido(self, plataforma, monkeypatch):
        from api import correio
        escrito = {}
        monkeypatch.setattr(correio, "enviar",
                            lambda para, assunto, texto: escrito.update(texto=texto)
                            or {"enviado": True})
        correio.copia_mudou({"ok": False, "porque": "sem espaço",
                             "quando": "2026-10-16T03:00:00+00:00"})
        assert "semanal" in escrito["texto"]
        assert "REPLICAI_COPIA_" in escrito["texto"]


class TestASaudeConta:
    def test_copia_em_dia_aparece_com_o_que_guarda(self, plataforma):
        copia, _, _ = plataforma
        copia.fazer()
        d = copia.em_json()
        assert d["estado"] == "em dia"
        assert d["guardados"] >= 3
        assert d["contas"]

    def test_copia_velha_aparece_como_atrasada(self, plataforma):
        copia, _, _ = plataforma
        copia.fazer()
        tudo = json.loads(copia._registro().read_text(encoding="utf-8"))
        tudo["ultima"]["quando"] = "2026-01-01T03:00:00+00:00"
        copia._registro().write_text(json.dumps(tudo), encoding="utf-8")
        assert copia.em_json()["estado"] == "ATRASADA"

    def test_falha_aparece_com_o_motivo(self, plataforma, monkeypatch):
        copia, _, _ = plataforma
        monkeypatch.setattr(copia, "_cliente", lambda: S3Falso(quebrar=True))
        copia.fazer()
        d = copia.em_json()
        assert d["estado"] == "FALHOU"
        assert "recusou" in d["porque"]


class TestOConteinerRodaTodoDia:
    def test_o_compose_tem_o_servico_de_copia(self):
        compose = Path("infra/docker-compose.yml").read_text(encoding="utf-8")
        assert "python -m api.copia" in compose
        assert "sleep 86400" in compose.split("copia:")[1][:400]

    def test_a_copia_nao_mora_dentro_da_faxina(self):
        """Uma apaga e a outra guarda: parar uma não pode parar a outra."""
        compose = Path("infra/docker-compose.yml").read_text(encoding="utf-8")
        bloco = compose.split("  faxina:")[1].split("\n  copia:")[0]
        assert "api.copia" not in bloco
