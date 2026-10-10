"""A leitura do `.env`.

Existe porque exportar a chave num terminal não alcança o servidor já em pé:
a pessoa põe a chave, nada muda, e não há erro nenhum para explicar.
"""
import os

from api.ambiente import carregar


def test_le_o_que_esta_no_arquivo(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("ANTHROPIC_API_KEY=sk-ant-teste\nOUTRA=2\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OUTRA", raising=False)
    assert set(carregar(f)) == {"ANTHROPIC_API_KEY", "OUTRA"}
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-teste"


def test_o_ambiente_real_vence_o_arquivo(tmp_path, monkeypatch):
    """O Docker repassa a chave por variável; o arquivo não pode sobrescrever."""
    f = tmp_path / ".env"
    f.write_text("ANTHROPIC_API_KEY=do-arquivo\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-ambiente")
    carregar(f)
    assert os.environ["ANTHROPIC_API_KEY"] == "do-ambiente"


def test_ignora_comentario_linha_vazia_e_valor_vazio(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# comentário\n\nVAZIA=\nBOA=1\nsem_igual\n")
    monkeypatch.delenv("BOA", raising=False)
    assert carregar(f) == ["BOA"]


def test_tira_as_aspas(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('COM_ASPAS="valor"\n')
    monkeypatch.delenv("COM_ASPAS", raising=False)
    carregar(f)
    assert os.environ["COM_ASPAS"] == "valor"


def test_sem_arquivo_nao_reclama(tmp_path):
    assert carregar(tmp_path / "nao-existe") == []


def test_nao_devolve_os_valores(tmp_path, monkeypatch):
    """O retorno vai para log: só os nomes, nunca o segredo."""
    f = tmp_path / ".env"
    f.write_text("SEGREDO=nao-pode-vazar\n")
    monkeypatch.delenv("SEGREDO", raising=False)
    assert carregar(f) == ["SEGREDO"]
