"""Quem é o cliente, e o que é dele.

Fronteira de segurança: estes testes existem para não deixar passar segredo em
claro, conta de um alcançando a de outro, ou chave revogada continuando a
valer.
"""
import json

import pytest

from api import contas
from api.contas import ContaInvalida


@pytest.fixture(autouse=True)
def disco(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    import importlib
    from api import trabalhos
    importlib.reload(trabalhos)


@pytest.fixture
def conta():
    return contas.criar("Operandi", "ligia@exemplo.com", "senha-bem-comprida")


class TestCriar:
    def test_cria_com_identificador_legivel_e_unico(self):
        a = contas.criar("Operandi", "a@exemplo.com", "senha-bem-comprida")
        b = contas.criar("Operandi", "b@exemplo.com", "senha-bem-comprida")
        assert a.id.startswith("operandi-") and b.id.startswith("operandi-")
        assert a.id != b.id

    def test_email_repetido_e_recusado(self, conta):
        with pytest.raises(ContaInvalida, match="já existe"):
            contas.criar("Outra", "LIGIA@exemplo.com", "senha-bem-comprida")

    def test_email_torto_e_recusado(self):
        for ruim in ("", "sem-arroba", "a@b", "a b@c.com"):
            with pytest.raises(ContaInvalida, match="e-mail"):
                contas.criar("x", ruim, "senha-bem-comprida")

    def test_senha_curta_e_recusada(self):
        with pytest.raises(ContaInvalida, match="10 caracteres"):
            contas.criar("x", "a@exemplo.com", "curta")


class TestSegredo:
    def test_a_senha_nao_fica_em_claro_no_disco(self, conta, tmp_path):
        bruto = (tmp_path / "_contas" / f"{conta.id}.json").read_text()
        assert "senha-bem-comprida" not in bruto
        assert json.loads(bruto)["senha"].startswith("scrypt$")

    def test_a_chave_nao_fica_em_claro_no_disco(self, conta, tmp_path):
        chave = contas.nova_chave(conta)
        for f in (tmp_path / "_contas").glob("*.json"):
            assert chave not in f.read_text()

    def test_o_que_sai_da_api_nao_tem_segredo(self, conta):
        contas.nova_chave(conta)
        saida = json.dumps(conta.em_json())
        assert "senha" not in saida and "resumo" not in saida

    def test_duas_contas_com_a_mesma_senha_tem_hashes_diferentes(self):
        a = contas.criar("a", "a@exemplo.com", "mesma-senha-aqui")
        b = contas.criar("b", "b@exemplo.com", "mesma-senha-aqui")
        assert a.senha != b.senha          # sal por conta


class TestAutenticar:
    def test_senha_certa_entra(self, conta):
        assert contas.autenticar("ligia@exemplo.com", "senha-bem-comprida").id == conta.id

    def test_maiuscula_no_email_nao_atrapalha(self, conta):
        assert contas.autenticar("LIGIA@Exemplo.com", "senha-bem-comprida")

    def test_senha_errada_nao_entra(self, conta):
        assert contas.autenticar("ligia@exemplo.com", "quase-a-senha") is None

    def test_conta_desligada_nao_entra(self, conta):
        conta.ativa = False
        contas._gravar(conta)
        assert contas.autenticar("ligia@exemplo.com", "senha-bem-comprida") is None

    def test_email_que_nao_existe_demora_o_mesmo(self, conta):
        """Responder rápido quando o e-mail não existe conta quais e-mails
        existem."""
        import time
        t0 = time.time(); contas.autenticar("ninguem@exemplo.com", "x" * 12)
        sem = time.time() - t0
        t0 = time.time(); contas.autenticar("ligia@exemplo.com", "x" * 12)
        com = time.time() - t0
        assert sem > com * 0.4            # mesma ordem de grandeza


class TestChaves:
    def test_a_chave_devolve_a_conta(self, conta):
        k = contas.nova_chave(conta, "servidor")
        assert contas.da_chave(k).id == conta.id

    def test_chave_inventada_nao_vale(self, conta):
        contas.nova_chave(conta)
        assert contas.da_chave("rpl_inventada") is None
        assert contas.da_chave("") is None
        assert contas.da_chave("sem-prefixo") is None

    def test_chave_revogada_para_de_valer(self, conta):
        k = contas.nova_chave(conta)
        assert contas.revogar(conta, conta.chaves[-1]["id"]) is True
        assert contas.da_chave(k) is None

    def test_revogar_uma_nao_derruba_a_outra(self, conta):
        k1 = contas.nova_chave(conta, "um")
        k2 = contas.nova_chave(conta, "dois")
        contas.revogar(conta, conta.chaves[0]["id"])
        assert contas.da_chave(k1) is None
        assert contas.da_chave(k2).id == conta.id

    def test_conta_desligada_invalida_as_chaves(self, conta):
        k = contas.nova_chave(conta)
        conta.ativa = False
        contas._gravar(conta)
        assert contas.da_chave(k) is None

    def test_duas_chaves_nunca_saem_iguais(self, conta):
        assert contas.nova_chave(conta) != contas.nova_chave(conta)


class TestIdentificador:
    def test_nao_da_para_sair_da_pasta_pelo_identificador(self):
        for ruim in ("../fora", "a/b", "..", "", "x" * 100):
            assert contas.por_id(ruim) is None


class TestSessao:
    def test_o_selo_volta_a_conta(self, conta, monkeypatch):
        monkeypatch.setenv("REPLICAI_SEGREDO", "um-segredo-qualquer")
        assert contas.abrir_selo(contas.selar(conta.id)) == conta.id

    def test_selo_mexido_nao_vale(self, conta, monkeypatch):
        monkeypatch.setenv("REPLICAI_SEGREDO", "um-segredo-qualquer")
        selo = contas.selar(conta.id)
        assert contas.abrir_selo(selo.replace(conta.id, "outra-conta")) is None

    def test_selo_de_outro_segredo_nao_vale(self, conta, monkeypatch):
        monkeypatch.setenv("REPLICAI_SEGREDO", "um-segredo")
        selo = contas.selar(conta.id)
        monkeypatch.setenv("REPLICAI_SEGREDO", "outro-segredo")
        assert contas.abrir_selo(selo) is None

    def test_selo_vencido_nao_vale(self, conta, monkeypatch):
        monkeypatch.setenv("REPLICAI_SEGREDO", "um-segredo")
        monkeypatch.setattr(contas, "SELO_VALE", -10)
        assert contas.abrir_selo(contas.selar(conta.id)) is None

    def test_lixo_nao_quebra(self, monkeypatch):
        monkeypatch.setenv("REPLICAI_SEGREDO", "um-segredo")
        for ruim in ("", "abc", "a:b", "a:b:c:d"):
            assert contas.abrir_selo(ruim) is None

    def test_sem_segredo_configurado_a_plataforma_avisa(self, monkeypatch):
        monkeypatch.delenv("REPLICAI_SEGREDO", raising=False)
        assert contas.segredo_configurado() is False


class TestAPastaTemMaisQueContas:
    """A pasta guarda também os índices — chaves e eventos de cobrança.
    Listar contas tentava lê-los como conta, e isso quebrava o login depois do
    primeiro pagamento: a pior hora possível."""

    def test_indice_de_chaves_nao_vira_conta(self, conta):
        contas.nova_chave(conta)
        assert [c.id for c in contas.todas()] == [conta.id]

    def test_arquivo_de_eventos_nao_vira_conta(self, conta):
        (contas.pasta() / "eventos.json").write_text('["evt_1","evt_2"]')
        assert [c.id for c in contas.todas()] == [conta.id]
        assert contas.autenticar("ligia@exemplo.com", "senha-bem-comprida")

    def test_json_de_outra_forma_nao_quebra(self, conta):
        (contas.pasta() / "lixo.json").write_text('{"algo": 1}')
        assert [c.id for c in contas.todas()] == [conta.id]

    def test_conta_com_campo_desconhecido_nao_derruba_a_lista(self, conta):
        import json as j
        f = contas.pasta() / "antiga-aaaaaa.json"
        f.write_text(j.dumps({"id": "antiga-aaaaaa", "nome": "x", "email": "a@b.co",
                              "campo_que_nao_existe_mais": 1}))
        assert conta.id in [c.id for c in contas.todas()]


class TestMedidasGuardadas:
    """Quem publica num destino fora do catálogo publica lá toda semana.
    Digitar a mesma medida a cada trabalho é trabalho que a plataforma devia
    lembrar — e é da CONTA, não do navegador: trocar de máquina não pode
    apagar a lista."""

    def test_guarda_e_devolve(self, conta):
        contas.guardar_medida(conta, 1200, 1600)
        assert contas.por_id(conta.id).medidas[0]["id"] == "livre-1200x1600"

    def test_sobrevive_ao_recarregar(self, conta):
        contas.guardar_medida(conta, 1200, 1600)
        assert contas.por_id(conta.id).medidas[0]["w"] == 1200

    def test_a_mesma_medida_nao_duplica(self, conta):
        contas.guardar_medida(conta, 1200, 1600)
        contas.guardar_medida(conta, 1200, 1600)
        assert len(contas.por_id(conta.id).medidas) == 1

    def test_medida_fora_do_limite_do_motor_e_recusada(self, conta):
        """O limite é o do motor, lido de lá: duas constantes iguais em
        arquivos diferentes é uma delas errada daqui a um mês."""
        from motor.replica import LIVRE_MAX
        with pytest.raises(ContaInvalida):
            contas.guardar_medida(conta, 10, 500)
        with pytest.raises(ContaInvalida):
            contas.guardar_medida(conta, LIVRE_MAX + 1, 500)
        assert contas.por_id(conta.id).medidas == []

    def test_o_que_nao_e_numero_nao_entra(self, conta):
        with pytest.raises(ContaInvalida):
            contas.guardar_medida(conta, "mil", 500)

    def test_tem_teto(self, conta):
        """É lista de atalho, não catálogo: passando disso a grade vira a
        lista enorme de que ela é o remédio."""
        for i in range(contas.MAX_MEDIDAS):
            contas.guardar_medida(conta, 100 + i, 500)
        with pytest.raises(ContaInvalida):
            contas.guardar_medida(conta, 999, 500)

    def test_esquecer_tira_da_conta(self, conta):
        contas.guardar_medida(conta, 1200, 1600)
        contas.esquecer_medida(conta, "livre-1200x1600")
        assert contas.por_id(conta.id).medidas == []

    def test_esquecer_o_que_nao_existe_nao_explode(self, conta):
        assert contas.esquecer_medida(conta, "livre-1x1") == []

    def test_a_medida_de_uma_conta_nao_aparece_na_outra(self, conta):
        outra = contas.criar("Outra", "outra@exemplo.com", "senha-bem-comprida")
        contas.guardar_medida(conta, 1200, 1600)
        assert contas.por_id(outra.id).medidas == []

    def test_sai_na_api_sem_levar_segredo_junto(self, conta):
        contas.guardar_medida(conta, 1200, 1600)
        pacote = contas.por_id(conta.id).em_json()
        assert pacote["medidas"][0]["id"] == "livre-1200x1600"
        assert "senha" not in pacote

    def test_conta_antiga_sem_o_campo_continua_abrindo(self, conta):
        """Conta gravada antes deste campo existir não pode parar de ler."""
        f = contas.pasta() / f"{conta.id}.json"
        d = json.loads(f.read_text())
        d.pop("medidas", None)
        f.write_text(json.dumps(d))
        assert contas.por_id(conta.id).medidas == []


class TestFontesDaMarca:
    """O PSD diz qual fonte cada linha usa — "FuturaICG-Bold" — e não leva o
    arquivo dentro dele. Sem o arquivo, trocar o texto de uma peça troca a
    letra junto, e família declarada sem arquivo faz o navegador cair numa
    fonte do sistema sem avisar."""

    def _arquivo(self):
        from pathlib import Path
        return Path("motor/assets/fontes/grotesk.ttf").read_bytes()

    def test_guarda_lendo_o_nome_de_dentro_do_arquivo(self, conta):
        """Do arquivo, e não do nome dele: `minha-fonte-final-v2.ttf` não diz
        nada sobre qual fonte é."""
        item = contas.guardar_fonte(conta, "qualquer-nome.ttf", self._arquivo())
        assert item["familia"]
        assert contas.por_id(conta.id).fontes[0]["familia"] == item["familia"]

    def test_acha_pela_forma_que_o_psd_pede(self, conta):
        """O PSD pede `FuturaICG-Bold`; o arquivo se apresenta como família
        "Futura ICG" e estilo "Bold". É a mesma fonte."""
        item = contas.guardar_fonte(conta, "f.ttf", self._arquivo())
        pedida = f"{item['familia'].replace(' ', '')}-{item['estilo']}"
        assert contas.fonte_de(conta, pedida)["id"] == item["id"]

    def test_fonte_que_nao_tem_nao_e_inventada(self, conta):
        assert contas.fonte_de(conta, "FuturaICG-Bold") is None

    def test_arquivo_que_nao_e_fonte_e_recusado(self, conta):
        with pytest.raises(ContaInvalida):
            contas.guardar_fonte(conta, "x.ttf", b"isto nao e uma fonte")
        assert contas.por_id(conta.id).fontes == []

    def test_extensao_estranha_e_recusada(self, conta):
        with pytest.raises(ContaInvalida):
            contas.guardar_fonte(conta, "x.exe", self._arquivo())

    def test_arquivo_grande_demais_e_recusado(self, conta):
        with pytest.raises(ContaInvalida):
            contas.guardar_fonte(conta, "x.ttf", b"0" * (contas.FONTE_MAX + 1))

    def test_a_mesma_fonte_duas_vezes_nao_duplica(self, conta):
        contas.guardar_fonte(conta, "a.ttf", self._arquivo())
        contas.guardar_fonte(conta, "b.ttf", self._arquivo())
        assert len(contas.por_id(conta.id).fontes) == 1

    def test_esquecer_tira_o_arquivo_do_disco(self, conta):
        item = contas.guardar_fonte(conta, "f.ttf", self._arquivo())
        alvo = contas.pasta_das_fontes(conta) / item["nome"]
        assert alvo.exists()
        contas.esquecer_fonte(conta, item["id"])
        assert not alvo.exists()
        assert contas.por_id(conta.id).fontes == []

    def test_a_fonte_de_uma_conta_nao_serve_a_outra(self, conta):
        contas.guardar_fonte(conta, "f.ttf", self._arquivo())
        outra = contas.criar("Outra", "o@exemplo.com", "senha-bem-comprida")
        assert contas.por_id(outra.id).fontes == []

    def test_o_nome_do_arquivo_nao_escapa_da_pasta(self, conta):
        item = contas.guardar_fonte(conta, "../../fora.ttf", self._arquivo())
        assert "/" not in item["nome"] and ".." not in item["nome"]
        assert (contas.pasta_das_fontes(conta) / item["nome"]).exists()
