"""O que protege a plataforma de quem está do outro lado.

Não é teste de funcionalidade: é teste do que **não** pode acontecer. Cada um
aqui nasceu de uma pergunta concreta — o que um robô consegue tentando senha, o
que uma pessoa com conta consegue escrever na tela da colega, o que atravessa a
rede sem proteção, e o que o navegador deveria recusar.

A regra que vale em todos: muro de fora **e** muro de dentro. O e-mail torto é
recusado na entrada e escapado na saída; quem passar por um encontra o outro.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("REPLICAI_SEGREDO", "segredo-de-teste")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DOMINIO", raising=False)
    import importlib
    from api import contas, main, tranca, trabalhos
    importlib.reload(trabalhos)
    importlib.reload(main)
    tranca.esquecer_tudo()
    return main, contas


class TestOReboqueDeSenha:
    """Senha de dez caracteres não resiste a um robô tentando sem parar. O que
    faz resistir é a tentativa custar tempo."""

    def test_errar_demais_tranca_a_porta(self, servidor):
        main, contas = servidor
        contas.criar("Dona", "dona@exemplo.com", "senha-bem-comprida")
        c = TestClient(main.app)
        from api import tranca
        for _ in range(tranca.LIMITE):
            r = c.post("/entrar", data={"email": "dona@exemplo.com", "senha": "chute"})
            assert r.status_code == 401
        r = c.post("/entrar", data={"email": "dona@exemplo.com", "senha": "chute"})
        assert r.status_code == 429
        assert r.headers.get("Retry-After")

    def test_a_tranca_nao_entrega_quais_e_mails_existem(self, servidor):
        """"Esta conta está trancada" contaria metade do trabalho de quem tenta."""
        main, contas = servidor
        contas.criar("Dona", "dona@exemplo.com", "senha-bem-comprida")
        c = TestClient(main.app)
        from api import tranca
        for _ in range(tranca.LIMITE + 1):
            c.post("/entrar", data={"email": "dona@exemplo.com", "senha": "chute"})
        trancada = c.post("/entrar", data={"email": "dona@exemplo.com", "senha": "x"})
        errada = TestClient(main.app).post(
            "/entrar", data={"email": "ninguem@exemplo.com", "senha": "x"})
        assert trancada.json()["detail"] == errada.json()["detail"]

    def test_a_senha_certa_destranca_a_contagem(self, servidor):
        """Quem sabe a senha não paga pelo robô que errou antes dela."""
        main, contas = servidor
        contas.criar("Dona", "dona@exemplo.com", "senha-bem-comprida")
        c = TestClient(main.app)
        from api import tranca
        for _ in range(tranca.LIMITE - 1):
            c.post("/entrar", data={"email": "dona@exemplo.com", "senha": "chute"})
        assert c.post("/entrar", data={"email": "dona@exemplo.com",
                                       "senha": "senha-bem-comprida"}).status_code == 200
        for _ in range(tranca.LIMITE - 1):
            assert c.post("/entrar", data={"email": "dona@exemplo.com",
                                           "senha": "chute"}).status_code == 401

    def test_conta_por_e_mail_tambem_e_nao_so_por_maquina(self, servidor):
        """Mil máquinas varrendo a senha de uma conta só é o mesmo ataque."""
        main, contas = servidor
        contas.criar("Dona", "dona@exemplo.com", "senha-bem-comprida")
        from api import tranca
        for i in range(tranca.LIMITE):
            TestClient(main.app).post(
                "/entrar", data={"email": "dona@exemplo.com", "senha": "chute"},
                headers={"x-forwarded-for": f"10.0.0.{i}"})
        r = TestClient(main.app).post(
            "/entrar", data={"email": "dona@exemplo.com", "senha": "chute"},
            headers={"x-forwarded-for": "10.0.0.99"})
        assert r.status_code == 429

    def test_a_tranca_de_uma_conta_nao_tranca_a_outra(self, servidor):
        main, contas = servidor
        contas.criar("Uma", "uma@exemplo.com", "senha-bem-comprida")
        contas.criar("Outra", "outra@exemplo.com", "senha-bem-comprida")
        from api import tranca
        c = TestClient(main.app)
        for _ in range(tranca.LIMITE + 1):
            c.post("/entrar", data={"email": "uma@exemplo.com", "senha": "chute"},
                   headers={"x-forwarded-for": "10.0.0.1"})
        r = TestClient(main.app).post(
            "/entrar", data={"email": "outra@exemplo.com", "senha": "senha-bem-comprida"},
            headers={"x-forwarded-for": "10.0.0.2"})
        assert r.status_code == 200

    def test_adivinhar_convite_tambem_cansa(self, servidor):
        """O convite é sorteado com entropia de sobra, mas tentar sai de graça."""
        main, _ = servidor
        from api import tranca
        c = TestClient(main.app)
        for _ in range(tranca.LIMITE):
            assert c.post("/senha", data={"convite": "x" * 43,
                                          "senha": "senha-bem-comprida"}).status_code == 410
        assert c.post("/senha", data={"convite": "x" * 43,
                                      "senha": "senha-bem-comprida"}).status_code == 429


class TestOQueOClienteEscreveNaoViraHTML:
    def test_o_e_mail_torto_nao_entra(self, servidor):
        """`a<img src=x onerror=...>@b.co` passava no teste de "tem arroba"."""
        _, contas = servidor
        for ruim in ('a<img src=x>@b.co', 'a"b@c.co', "a'b@c.co", "a&b@c.co",
                     "a/b@c.co", "a\\b@c.co"):
            with pytest.raises(contas.ContaInvalida):
                contas.criar("X", ruim, "senha-bem-comprida")

    def test_o_e_mail_de_verdade_continua_entrando(self, servidor):
        _, contas = servidor
        for bom in ("ligia@exemplo.com", "a.b-c+d@sub.dominio.com.br",
                    "nome_sobrenome@agencia.com"):
            assert contas.criar("X", bom, "senha-bem-comprida")

    def test_a_tela_escapa_tudo_que_o_cliente_escreve(self):
        """O nome da fonte vem de dentro do arquivo que o cliente sobe, e o da
        prancheta vem do PSD: nenhum dos dois é texto nosso."""
        from pathlib import Path
        tela = Path("web/index.html").read_text(encoding="utf-8")
        assert "const esc = v =>" in tela
        for perigoso in ("${esc(f.nome)}", "${esc(f.familia)}", "${esc(p.email)}",
                         "${esc(p.nome)}", "${esc(pr.nome || 'a arte')}",
                         "${esc(t.titulo || t.job)}"):
            assert perigoso in tela, perigoso

    def test_nenhum_nome_de_cliente_entra_cru(self):
        from pathlib import Path
        tela = Path("web/index.html").read_text(encoding="utf-8")
        for cru in ("${f.nome}", "${f.familia}", "${p.email}", "${pr.nome"):
            assert cru not in tela, cru


class TestOQueONavegadorDeveRecusar:
    def test_a_resposta_vem_com_as_regras(self, servidor):
        main, _ = servidor
        r = TestClient(main.app).get("/saude")
        assert "default-src 'self'" in r.headers["Content-Security-Policy"]
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Referrer-Policy"] == "same-origin"

    def test_script_e_conexao_so_do_proprio_servidor(self, servidor):
        """Injeção que não alcança a internet não leva nada embora."""
        main, _ = servidor
        regra = TestClient(main.app).get("/").headers["Content-Security-Policy"]
        assert "connect-src 'self'" in regra
        assert "script-src 'self' 'unsafe-inline'" in regra
        assert "frame-ancestors 'none'" in regra

    def test_sem_dominio_o_cookie_nao_exige_https(self, servidor):
        """Em localhost não há certificado: exigir `Secure` impediria de entrar."""
        main, contas = servidor
        contas.criar("Dona", "dona@exemplo.com", "senha-bem-comprida")
        r = TestClient(main.app).post("/entrar", data={"email": "dona@exemplo.com",
                                                       "senha": "senha-bem-comprida"})
        assert "secure" not in r.headers["set-cookie"].lower()

    def test_com_dominio_o_cookie_so_viaja_em_https(self, tmp_path, monkeypatch):
        """Sem isto o selo volta em HTTP puro para quem estiver no caminho."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setenv("REPLICAI_SEGREDO", "segredo-de-teste")
        monkeypatch.setenv("DOMINIO", "app.exemplo.com.br")
        monkeypatch.delenv("REDIS_URL", raising=False)
        import importlib
        from api import contas, main, trabalhos
        importlib.reload(trabalhos)
        importlib.reload(main)
        contas.criar("Dona", "dona@exemplo.com", "senha-bem-comprida")
        r = TestClient(main.app).post("/entrar", data={"email": "dona@exemplo.com",
                                                       "senha": "senha-bem-comprida"})
        biscoito = r.headers["set-cookie"].lower()
        assert "secure" in biscoito
        assert "httponly" in biscoito
        assert r.headers["Strict-Transport-Security"]


class TestOSegredoNaoSaiDaquiEmClaro:
    def test_a_conta_em_json_nao_leva_senha(self, servidor):
        _, contas = servidor
        c = contas.criar("Dona", "dona@exemplo.com", "senha-bem-comprida")
        bruto = str(c.em_json())
        assert "scrypt" not in bruto
        assert "senha" not in bruto

    def test_a_senha_guardada_e_irreconhecivel(self, servidor):
        _, contas = servidor
        c = contas.criar("Dona", "dona@exemplo.com", "senha-bem-comprida")
        assert "senha-bem-comprida" not in c.senha
        assert c.senha.startswith("scrypt$")

    def test_o_convite_guardado_nao_serve_para_entrar(self, servidor):
        """Guarda-se o resumo: arquivo roubado não abre conta de ninguém."""
        _, contas = servidor
        c, convite = contas.nascer_da_assinatura("Agência", "dona@exemplo.com", "basic")
        guardado = contas.por_id(c.id).convite
        assert convite not in guardado
        assert contas.dono_do_convite(guardado) is None


class TestATrancaExigeUmaApiSo:
    """A contagem vive na memória do processo. Duas apis contariam cada uma
    por si, e oito tentativas virariam dezesseis — quem subir réplica precisa
    saber disso, e o roteiro de subida precisa dizer."""

    def test_o_roteiro_avisa_para_nao_replicar_a_api(self):
        from pathlib import Path
        roteiro = Path("infra/SUBIR.md").read_text(encoding="utf-8")
        assert "não na `api`" in roteiro

    def test_o_compose_sobe_uma_api_so(self):
        from pathlib import Path
        linhas = Path("infra/docker-compose.yml").read_text(encoding="utf-8").splitlines()
        dentro, achou = False, []
        for linha in linhas:
            crua = linha.strip()
            if linha.startswith("  ") and linha[2:3] not in (" ", "#") and crua.endswith(":"):
                dentro = crua == "api:"           # trocou de serviço
                continue
            if dentro and crua and not crua.startswith("#"):
                achou.append(crua)
        assert achou, "não achei o serviço api no compose"
        assert not any("replicas" in l for l in achou), achou
