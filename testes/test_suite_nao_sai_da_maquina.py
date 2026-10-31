"""A suíte testa o produto, não a máquina de quem está desenvolvendo.

Três vezes o mesmo defeito já apareceu com cara diferente: franquia desligada
no `.env` fazia todo teste de plano passar à toa; outpaint de verdade rodando
dentro da suíte gastava crédito; e a chave do modelo, que entra no ambiente na
importação de `api.main`, fazia a direção de arte ser decidida pelo modelo em
cada peça recomposta — dinheiro gasto e resultado que muda de uma rodada para
a outra.

O que trava aqui não é o sintoma de nenhuma das três. É a regra: credencial que
sai da máquina chega vazia no teste, e credencial nova tem que ser declarada.
"""
import os
import re
from pathlib import Path

from testes.conftest import FORA_DA_MAQUINA

RAIZ = Path(__file__).resolve().parent.parent

# Variável de credencial que NÃO sai da máquina: fica aqui declarada para a
# varredura abaixo não acusar, e com o motivo de ser de dentro.
DENTRO_DA_MAQUINA = {
    "REPLICAI_SEGREDO": "assina o cookie de sessão; não fala com ninguém",
    "REPLICAI_ADMIN_TOKEN": "porta do painel desta instalação",
    "ASAAS_AREIA": "liga a areia do Asaas; é interruptor, não credencial",
}

# O que parece credencial num nome de variável de ambiente.
PARECE_CREDENCIAL = re.compile(r"_(KEY|TOKEN|SEGREDO|CHAVE|URL)$")


def nomes_lidos_pelo_motor() -> set[str]:
    """Toda variável de ambiente que api/ e motor/ leem, do jeito que leem."""
    padrao = re.compile(r"""environ\.get\(["']([A-Z_]+)["']|"""
                        r"""environ\[["']([A-Z_]+)["']|"""
                        r"""getenv\(["']([A-Z_]+)["']""")
    achados = set()
    for pasta in ("api", "motor"):
        for arq in sorted((RAIZ / pasta).glob("*.py")):
            for m in padrao.finditer(arq.read_text(encoding="utf-8")):
                achados.add(next(g for g in m.groups() if g))
    return achados


def tentar_vazar(tmp_path, nomes=FORA_DA_MAQUINA) -> None:
    """Faz pelo caminho de verdade o que a importação de `api.main` faz.

    Um `.env` ao lado com as credenciais dentro, e `carregar()` em cima. É
    assim que a chave da máquina entrava na suíte; o teste que usa isto está
    perguntando se ela ainda entra.
    """
    from api.ambiente import carregar
    arq = tmp_path / ".env"
    arq.write_text("".join(f"{n}=valor-do-arquivo\n" for n in nomes),
                   encoding="utf-8")
    carregar(arq)


class TestAChaveNaoChegaNoTeste:
    def test_toda_credencial_de_fora_chega_vazia(self, tmp_path):
        """Nem de saída, nem depois de um `.env` tentar repor."""
        for nome in FORA_DA_MAQUINA:
            assert not os.environ.get(nome), f"{nome} chegou com valor no teste"
        tentar_vazar(tmp_path)
        for nome in FORA_DA_MAQUINA:
            assert not os.environ.get(nome), (
                f"{nome} entrou pelo `.env` no meio do teste: a trava precisa "
                f"pôr vazio, não apagar — `carregar()` só escreve o que falta")

    def test_o_modelo_fica_indisponivel_por_padrao(self, tmp_path):
        """A consequência que importa: sem credencial a esteira decide pela
        régua, de graça e igual em toda rodada. Com credencial, a direção de
        arte de CADA peça recomposta é uma chamada paga, e a peça muda de uma
        rodada para a outra."""
        from api import direcao, modelo
        tentar_vazar(tmp_path)
        assert modelo.disponivel() is False
        assert direcao.disponivel() is False

    def test_importar_a_api_nao_destrava_a_chave(self):
        """O caminho exato do defeito: dois testes só liam a tela e o
        Dockerfile, mas cada um importava `api.main` para conferir uma
        constante — e `api.main` carrega o `.env` na importação. Dali em diante
        a suíte inteira compunha com o modelo."""
        import api.main                                      # noqa: F401
        from api import direcao
        assert not os.environ.get("ANTHROPIC_API_KEY")
        assert direcao.disponivel() is False

    def test_quem_quer_a_credencial_poe_a_sua(self, monkeypatch):
        """A trava não pode atrapalhar o teste que precisa do caminho com
        credencial: a do teste vem depois e vence."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "de-mentira")
        monkeypatch.delenv("REPLICAI_SEM_DIRECAO", raising=False)
        from api import direcao, modelo
        assert modelo.disponivel() is True
        assert direcao.disponivel() is True


class TestCredencialNovaTemQueSerDeclarada:
    def test_nenhuma_credencial_do_motor_ficou_de_fora_da_trava(self):
        """A trava é uma lista escrita à mão, e lista escrita à mão envelhece.

        Quando entrar a chave de produção do Asaas, ou o Resend, ou qualquer
        serviço novo, este teste quebra até alguém dizer se aquilo sai da
        máquina ou não. Sem isto a trava protege só o que existia no dia em
        que foi escrita.
        """
        suspeitas = {n for n in nomes_lidos_pelo_motor() if PARECE_CREDENCIAL.search(n)}
        orfas = suspeitas - set(FORA_DA_MAQUINA) - set(DENTRO_DA_MAQUINA)
        assert not orfas, (
            f"credencial lida pelo motor e não classificada: {sorted(orfas)}. "
            f"Se ela sai da máquina, entre em FORA_DA_MAQUINA no conftest; se "
            f"é de dentro, declare em DENTRO_DA_MAQUINA com o motivo.")

    def test_a_trava_nao_lista_variavel_que_ninguem_le(self):
        """Lista com nome morto dá falsa sensação de cobertura."""
        lidas = nomes_lidos_pelo_motor()
        mortas = [n for n in FORA_DA_MAQUINA if n not in lidas]
        assert not mortas, f"na trava e ninguém lê: {mortas}"
