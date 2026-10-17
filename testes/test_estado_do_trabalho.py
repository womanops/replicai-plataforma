"""O estado de um trabalho, gravado por mais de uma mão ao mesmo tempo.

Em 17/10/2026 a Ligia animou três peças e disse: "não apareceu na tela, nem
progresso; só quando baixei vi que havia sido feito, mas não veio a estática
junto". O `trabalho.json` dela tinha sobrado assim:

    {"status": "erro", "erro": "o estado do trabalho está corrompido",
     "video": {...}, "atualizado": "..."}

Sem `arte`, sem `formatos`, sem `prontas`. As peças estavam todas no disco.

Era `gravar` — ler, mudar, escrever — rodando em duas mãos ao mesmo tempo: a
esteira do vídeo gravando o passo de cada formato e a API gravando o número da
vaga na fila. `write_text` zera o arquivo antes de escrever, então a outra
mão lia um JSON pela metade, `ler` devolvia o estado de mentira
`{"status": "erro"}` — e esse estado de mentira era gravado por cima do
trabalho de verdade. O zip saía sem as peças porque ele monta a lista a partir
de `prontas`, que tinha virado vazia.
"""
import json
import threading

import pytest

from api import trabalhos


@pytest.fixture
def conta(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    trabalhos.gravar("c-teste", "job-teste", {
        "arte": "arte.psd", "formatos": ["a", "b"], "prontas": ["a", "b"],
        "titulo": "Energiza"})
    return "c-teste", "job-teste"


class TestDuasMaosAoMesmoTempo:
    def test_o_trabalho_sobrevive_a_escrita_simultanea(self, conta):
        """Quatro gravando e quatro lendo. Nada do que já estava lá pode
        sumir, e ninguém pode ler um arquivo pela metade."""
        c, job = conta
        achados = []

        def escrever(quem):
            for i in range(60):
                trabalhos.gravar(c, job, {"video": {"feito": i, "quem": quem}})

        def ler():
            for _ in range(400):
                if (trabalhos.ler(c, job) or {}).get("erro"):
                    achados.append("leu o arquivo pela metade")
                    return

        fios = ([threading.Thread(target=escrever, args=(n,)) for n in range(4)]
                + [threading.Thread(target=ler) for _ in range(4)])
        for f in fios:
            f.start()
        for f in fios:
            f.join()

        assert not achados, achados[0]
        d = trabalhos.ler(c, job)
        for campo in ("arte", "formatos", "prontas", "titulo"):
            assert campo in d, f"`{campo}` foi apagado por uma gravação paralela"
        assert d["prontas"] == ["a", "b"]

    def test_o_passo_de_quem_escreveu_por_ultimo_fica(self, conta):
        """A tranca não pode engolir a gravação: ela serializa, não descarta."""
        c, job = conta
        trabalhos.gravar(c, job, {"video": {"feito": 3}})
        assert (trabalhos.ler(c, job))["video"] == {"feito": 3}


class TestArquivoIlegivel:
    """Mesmo com a troca atômica, um arquivo pode chegar ilegível — disco
    cheio, cópia feita na mão. O que não pode é a gravação seguinte tratar o
    estado de mentira como se fosse o trabalho."""

    def test_ler_avisa_sem_fingir_que_e_estado(self, conta):
        c, job = conta
        (trabalhos.pasta_do(c, job) / "trabalho.json").write_text("{isso não é json",
                                                                  encoding="utf-8")
        d = trabalhos.ler(c, job)
        assert d["status"] == "erro" and d["erro"] == trabalhos.QUEBRADO

    def test_gravar_nao_empilha_por_cima_do_lixo(self, conta):
        """O defeito que apagou o trabalho dela: `gravar` lia pelo `ler`,
        recebia `{"status": "erro"}` e gravava ISSO como se fosse o estado."""
        c, job = conta
        (trabalhos.pasta_do(c, job) / "trabalho.json").write_text("{isso não é json",
                                                                  encoding="utf-8")
        trabalhos.gravar(c, job, {"video": {"status": "pronto"}})
        d = trabalhos.ler(c, job)
        assert d.get("erro") is None, "gravou o estado de mentira como estado"
        assert d["video"] == {"status": "pronto"}

    def test_o_arquivo_quebrado_fica_guardado(self, conta):
        """Apagar em silêncio o que não se conseguiu ler tira a única pista
        de quem for investigar depois."""
        c, job = conta
        (trabalhos.pasta_do(c, job) / "trabalho.json").write_text("{quebrado",
                                                                  encoding="utf-8")
        trabalhos.gravar(c, job, {"status": "pronto"})
        guardado = trabalhos.pasta_do(c, job) / "trabalho.quebrado.json"
        assert guardado.exists() and "{quebrado" in guardado.read_text(encoding="utf-8")


class TestATrancaNaoViraEntrega:
    def test_a_tranca_e_o_parcial_ficam_fora_do_pacote(self, conta):
        """A pasta do trabalho é o que o cliente baixa: arquivo de controle
        não pode aparecer no zip."""
        c, job = conta
        p = trabalhos.pasta_do(c, job)
        (p / "gdn-728x90.png").write_bytes(b"peca")
        (p / "trabalho.123.parcial").write_text("{}", encoding="utf-8")
        nomes = {e["nome"] for e in trabalhos.entregas(c, job)}
        assert "gdn-728x90.png" in nomes
        assert not [n for n in nomes if "tranca" in n or n.endswith(".parcial")]


class TestOZipLevaAPecaParada:
    """"Só quando baixei vi que havia sido feito, mas não veio a estática
    junto." O pacote monta a lista a partir de `prontas` — com o estado
    apagado, sobravam só os vídeos e o PDF."""

    def test_o_pacote_tem_a_peca_e_o_video(self, conta):
        from api.main import para_entregar
        c, job = conta
        estado = trabalhos.ler(c, job)
        itens = [{"nome": "a.png", "kb": 1}, {"nome": "b.png", "kb": 1},
                 {"nome": "video/a-lettering.mp4", "kb": 9},
                 {"nome": "arte.psd", "kb": 999}]
        nomes = {it["nome"] for it in para_entregar(estado, itens)}
        assert nomes == {"a.png", "b.png", "video/a-lettering.mp4"}
