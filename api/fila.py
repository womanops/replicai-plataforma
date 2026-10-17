"""A fila de trabalhos.

Renderizar uma peça abre o Chromium e leva minutos. Sem fila, a requisição
estoura por timeout e o cliente vê erro num trabalho que está indo bem. Com
fila, ele recebe um identificador na hora e acompanha.

Duas implementações atrás da mesma interface:

- `FilaRQ` é a de produção: Redis guarda, o worker executa em outro processo, e
  derrubar a API não perde trabalho. São duas filas — peça e vídeo — porque a
  peça sai em segundos e o vídeo leva minutos: numa fila só, o vídeo de um
  cliente segura a peça do outro.
- `FilaDireta` roda na hora, no mesmo processo. É o que os testes usam — montar
  Redis para testar endpoint é atrito que faz ninguém rodar teste.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Protocol


class Fila(Protocol):
    def enfileirar(self, fn: Callable[..., Any], *args, fila: str = "", **kwargs) -> str:
        """Devolve o identificador do trabalho na fila."""


class FilaDireta:
    """Executa na hora, dentro de quem chamou. É a fila dos testes: eles
    precisam do resultado pronto na linha seguinte.

    Para rodar a plataforma sem Redis quem serve é `FilaEmFio` — aqui o
    trabalho acabaria antes de a tela poder mostrar que ele existiu."""

    def __init__(self, porque: str = ""):
        self.feitos: list[str] = []
        self.porque = porque          # aparece em /saude: queda calada engana

    def enfileirar(self, fn, *args, fila: str = "", **kwargs) -> str:
        fn(*args, **kwargs)
        nome = getattr(fn, "__name__", "trabalho")
        self.feitos.append(nome)
        return f"direto-{len(self.feitos)}"


class FilaEmFio:
    """Executa num fio próprio e devolve na hora. É a fila de quem roda sem
    Redis — a máquina de quem desenvolve, e o servidor quando o Redis cai.

    `FilaDireta` roda DENTRO da requisição: oito formatos, oito renders, e a
    resposta só sai no fim. A tela pergunta o andamento depois de receber a
    resposta, então encontrava tudo pronto e a barra de progresso nunca tinha
    o que mostrar. Não faltava barra: faltava o trabalho ainda estar
    acontecendo quando alguém pudesse olhar.

    Um fio por fila, e não um por trabalho: a peça e o vídeo correm em
    paralelo entre si, mas duas peças seguem uma de cada vez — é o mesmo
    comportamento do worker lá fora, com `REPLICAI_WORKERS=1`.
    """

    def __init__(self, porque: str = ""):
        from concurrent.futures import ThreadPoolExecutor
        self.porque = porque
        self.feitos: list[str] = []
        self._fios: dict[str, ThreadPoolExecutor] = {}
        self._fabrica = ThreadPoolExecutor

    def _fio(self, fila: str):
        if fila not in self._fios:
            self._fios[fila] = self._fabrica(
                max_workers=1, thread_name_prefix=f"replicai-{fila or 'peca'}")
        return self._fios[fila]

    def enfileirar(self, fn, *args, fila: str = "", **kwargs) -> str:
        nome = getattr(fn, "__name__", "trabalho")
        self.feitos.append(nome)
        # o erro não pode sumir dentro do fio: cada tarefa já grava o próprio
        # estado de erro, mas um estouro fora disso ficaria invisível
        self._fio(fila).submit(_a_salvo, fn, *args, **kwargs)
        return f"fio-{len(self.feitos)}"


def _a_salvo(fn, *args, **kwargs) -> None:
    import traceback
    try:
        fn(*args, **kwargs)
    except Exception:
        traceback.print_exc()


# a peça sai em segundos, o vídeo leva minutos. Numa fila só, o vídeo de um
# cliente segura a peça do outro — e peça é o que a pessoa está esperando
# para ver.
FILA_PECA = "replicai"
FILA_VIDEO = "replicai-video"

LIMITES = {FILA_PECA: 1800, FILA_VIDEO: 3600}


# quanto custa cada coisa, medido no PSD de 60 MB da Consigaz. Serve para
# dizer a quem espera quanto falta — e esperar sem saber quanto é a diferença
# entre uma fila e um travamento.
ABRIR_ARTE = 7        # segundos, uma vez por trabalho
POR_FORMATO = 7
POR_VIDEO = 21


def _custo(nome: str, args) -> int:
    """Quanto tempo um trabalho parado na fila vai tomar quando começar."""
    try:
        if nome.endswith("processar_video"):
            return POR_VIDEO * max(1, len(args[2]))
        if nome.endswith("processar"):
            return ABRIR_ARTE + POR_FORMATO * max(1, len(args[3]))
    except Exception:
        pass
    return ABRIR_ARTE + POR_FORMATO


class FilaRQ:
    """Redis + RQ. O worker é outro processo: `rq worker replicai`."""

    def __init__(self, url: str | None = None, conexao=None):
        from redis import Redis
        from rq import Queue
        conn = conexao or Redis.from_url(url or os.environ["REDIS_URL"])
        conn.ping()                   # falhar aqui é melhor do que na primeira peça
        self.filas = {nome: Queue(nome, connection=conn, default_timeout=limite)
                      for nome, limite in LIMITES.items()}

    def enfileirar(self, fn, *args, fila: str = FILA_PECA, **kwargs) -> str:
        return self.filas.get(fila, self.filas[FILA_PECA]).enqueue(fn, *args, **kwargs).id

    def espera(self, ident: str) -> dict | None:
        """Quantos trabalhos estão na frente deste, e quanto tempo somam.

        A tela dizia "Replicando" para quem só estava esperando: indistinguível
        de trabalho em andamento, com nada acontecendo na frente. Esperar sem
        saber quanto é o que faz a pessoa recarregar a página e subir de novo.
        """
        for q in self.filas.values():
            try:
                ids = q.get_job_ids()
            except Exception:
                continue
            if ident not in ids:
                continue
            antes = ids[:ids.index(ident)]
            segundos = 0
            for outro in antes:
                try:
                    from rq.job import Job
                    j = Job.fetch(outro, connection=q.connection)
                    segundos += _custo(j.func_name or "", j.args)
                except Exception:
                    segundos += ABRIR_ARTE + POR_FORMATO
            return {"a_frente": len(antes), "segundos": segundos}
        return None


def fila_do_ambiente() -> Fila:
    """Redis quando há REDIS_URL configurado; senão roda na hora.

    Cair para execução direta é melhor do que recusar a subir: em máquina de
    desenvolvimento a plataforma funciona inteira, só sem paralelismo.
    """
    url = os.environ.get("REDIS_URL")
    if not url:
        return FilaEmFio("sem REDIS_URL configurado")
    try:
        return FilaRQ(url)
    except Exception as e:
        # cair é melhor do que recusar a subir, mas cair calado é o defeito que
        # já entregou peça de régua com cara de peça do modelo. O motivo sobe
        # até /saude, onde quem opera consegue ver.
        return FilaEmFio(f"o Redis em {url} não respondeu: {type(e).__name__}")
