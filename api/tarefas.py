"""O que o worker executa.

Separado do servidor web de propósito: o worker não precisa de FastAPI nem de
rotas para renderizar uma peça, e carregar o aplicativo inteiro num processo
que só desenha é peso sem motivo. Aqui ficam as funções que a fila guarda —
e o que vai para o Redis precisa ser importável do outro lado.
"""
from __future__ import annotations

from pathlib import Path

from api import trabalhos
from api.compositor import CompositorEmCadeia, CompositorModelo, CompositorSimples
from api.pipeline import desdobrar


def compositor(arte: str, headline: str, cta: str):
    """Quem compõe. Com credencial, o modelo decide a estrutura e a máquina
    calcula as caixas; a regra determinística fica atrás como rede. Sem
    credencial, só a regra — a plataforma funciona, com menos qualidade, em vez
    de recusar o trabalho.

    A ordem é essa e não o contrário: a regra dá conta do caso fácil, mas não
    sabe o que sacrificar quando o formato aperta, que é o que decide a peça.
    """
    from api import modelo
    simples = CompositorSimples(headline=headline, cta=cta)
    if not modelo.disponivel():
        return simples
    pelo_modelo = CompositorModelo(
        modelo.responder_anthropic,
        fundo={"tipo": "imagem", "src": Path(arte).name, "fit": "cover"},
        material=" ".join(x for x in (headline, cta) if x))
    return CompositorEmCadeia(pelo_modelo, simples)


def leitor():
    """Quem lê a arte antes de compor. Sem credencial não há leitura, e a
    esteira cai no comportamento antigo — com a arte crua de fundo."""
    from api import modelo
    if not modelo.disponivel():
        return None

    def ler(arte):
        from api.leitura import entender
        return entender(modelo.ler_arte(arte))
    return ler


def processar(job: str, arte: str, formatos: list[str], headline: str,
              cta: str, brief: str, prancheta: str = "") -> None:
    """O que o worker executa. Fora da API de propósito: é o pedaço pesado."""
    trabalhos.gravar(job, {"status": "rodando"})

    def contar(p: dict) -> None:
        # grava a cada passo: é o que distingue, de fora, um render demorado
        # de um travamento
        trabalhos.gravar(job, {"progresso": p})

    try:
        r = desdobrar(Path(arte), formatos, compositor(arte, headline, cta),
                      trabalhos.pasta_do(job), brief, leitor(), prancheta,
                      progresso=contar)
        trabalhos.gravar(job, {"status": r.status, "progresso": None,
                               "prontas": sorted(r.prontas),
                               "falhas": r.falhas,
                               "avisos": r.avisos,
                               "descartados": r.descartados,
                               "psd": r.psd,
                               "custo": r.custo})
    except Exception as e:
        # sem isto o trabalho fica "rodando" para sempre e ninguém sabe por quê
        trabalhos.gravar(job, {"status": "erro", "erro": str(e)})
        raise


def processar_video(job: str, formatos: list[str], preset: str, segundos: float) -> None:
    """O que o worker executa para animar. Separado de `processar` porque é
    outra ferramenta e outro tempo: a peça parada leva segundos, o vídeo leva
    minutos, e quem quer só a peça não deve esperar pelo vídeo."""
    from api import animacao
    trabalhos.gravar(job, {"video": {"status": "rodando", "preset": preset,
                                     "formatos": formatos}})
    try:
        prontos, falhas = animacao.animar(trabalhos.pasta_do(job), formatos, preset, segundos)
        estado = "pronto" if prontos and not falhas else ("parcial" if prontos else "erro")
        trabalhos.gravar(job, {"video": {"status": estado, "preset": preset,
                                         "prontos": sorted(prontos), "falhas": falhas}})
    except Exception as e:
        trabalhos.gravar(job, {"video": {"status": "erro", "erro": str(e)}})
        raise


