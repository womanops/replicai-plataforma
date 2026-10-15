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
    """O armazenamento, sem rede e sem credencial."""

    def __init__(self, quebrar=False):
        self.objetos: dict[str, int] = {}
        self.quebrar = quebrar

    def upload_file(self, caminho, balde, chave):
        if self.quebrar:
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
        copia, _, base = plataforma
        d = copia.montar()
        with tarfile.open(d["arquivo"]) as t:
            nomes = t.getnames()
        assert "agencia-1/campanha-1/ig-feed-1x1.png" in nomes
        assert "_contas/agencia-1.json" in nomes
        assert "agencia-1/campanha-1/pecas/ig-feed-1x1.json" in nomes

    def test_nao_leva_o_bruto(self, plataforma):
        """O bruto tem prazo de validade de 30 dias e é 85% do disco. Copiar o
        que vai ser apagado é pagar armazenamento para guardar lixo."""
        copia, _, _ = plataforma
        d = copia.montar()
        with tarfile.open(d["arquivo"]) as t:
            nomes = t.getnames()
        assert not any(n.endswith((".psd", ".psb")) for n in nomes), nomes
        assert "agencia-1/campanha-1/00-camada.png" not in nomes

    def test_leva_o_mesmo_que_a_faxina_guarda(self, plataforma):
        """Uma regra só, nos dois lugares: se a faxina passar a guardar mais
        coisa, a cópia leva junto sem ninguém lembrar."""
        import inspect
        copia, _, _ = plataforma
        assert "faxina._guardar(estado)" in inspect.getsource(copia.o_que_vai)

    def test_os_caminhos_sao_relativos_a_pasta_de_dados(self, plataforma):
        """Restaurar é `tar xzf` em cima dela — sem adivinhação na pior hora."""
        copia, _, _ = plataforma
        d = copia.montar()
        with tarfile.open(d["arquivo"]) as t:
            nomes = t.getnames()
        assert not any(n.startswith("/") or n.startswith("..") for n in nomes)


class TestACopiaSaiDoServidor:
    def test_sobe_e_apaga_o_pacote_local(self, plataforma, monkeypatch):
        """Cópia que fica no mesmo disco ocupa espaço e não protege contra a
        máquina morrer, que é o caso que importa. O pacote é montado numa
        pasta temporária, então olhar só a pasta de dados não prova nada:
        este teste segue o arquivo que foi de fato criado."""
        copia, falso, base = plataforma
        feitos = []
        de_verdade = copia.montar
        monkeypatch.setattr(copia, "montar",
                            lambda *a, **k: feitos.append(de_verdade(*a, **k))
                            or feitos[-1])
        d = copia.fazer()
        assert d["ok"] is True
        assert len(falso.objetos) == 1
        assert feitos and not feitos[0]["arquivo"].exists(), feitos
        assert not list(base.glob("**/replicai-*.tar.gz"))

    def test_a_chave_leva_prefixo_e_data(self, plataforma):
        copia, falso, _ = plataforma
        copia.fazer()
        chave = next(iter(falso.objetos))
        assert chave.startswith("replicai/replicai-")
        assert chave.endswith(".tar.gz")

    def test_guarda_so_as_ultimas(self, plataforma):
        """Sem girar, o armazenamento cresce para sempre."""
        copia, falso, _ = plataforma
        for dia in range(1, 21):
            falso.objetos[f"replicai/replicai-2026-09-{dia:02d}.tar.gz"] = 10
        apagadas = copia.girar(manter=14)
        assert len(falso.objetos) == 14
        assert "replicai/replicai-2026-09-01.tar.gz" in apagadas
        assert "replicai/replicai-2026-09-20.tar.gz" in falso.objetos


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
    def test_copia_em_dia_aparece_com_tamanho(self, plataforma):
        copia, _, _ = plataforma
        copia.fazer()
        d = copia.em_json()
        assert d["estado"] == "em dia"
        assert d["tamanho_mb"] > 0
        assert d["arquivos"] >= 3

    def test_copia_velha_aparece_como_atrasada(self, plataforma):
        copia, _, base = plataforma
        copia.fazer()
        registro = json.loads(copia._registro().read_text(encoding="utf-8"))
        registro["quando"] = "2026-01-01T03:00:00+00:00"
        copia._registro().write_text(json.dumps(registro), encoding="utf-8")
        assert copia.em_json()["estado"] == "ATRASADA"

    def test_falha_aparece_com_o_motivo(self, plataforma, monkeypatch):
        copia, _, _ = plataforma
        monkeypatch.setattr(copia, "_cliente", lambda: S3Falso(quebrar=True))
        copia.fazer()
        d = copia.em_json()
        assert d["estado"] == "FALHOU"
        assert "recusou" in d["porque"]


class TestOConteinerRodaTodoDia:
    def test_o_compose_tem_o_serviço_de_copia(self):
        compose = Path("infra/docker-compose.yml").read_text(encoding="utf-8")
        assert "python -m api.copia" in compose
        assert "sleep 86400" in compose.split("copia:")[1][:400]

    def test_a_copia_nao_mora_dentro_da_faxina(self):
        """Uma apaga e a outra guarda: parar uma não pode parar a outra."""
        compose = Path("infra/docker-compose.yml").read_text(encoding="utf-8")
        bloco = compose.split("  faxina:")[1].split("\n  copia:")[0]
        assert "api.copia" not in bloco
