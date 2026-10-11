# ReplicAI — imagem da plataforma
#
# Esta imagem é a resposta ao problema de portabilidade: ela carrega DENTRO dela
# o Python, as bibliotecas, o Chromium e o ffmpeg. Onde esta imagem roda, o
# ReplicAI roda igual — Mac, Windows, Linux, qualquer servidor ou nuvem.
# O cliente final nunca instala nada: ele usa o navegador.

# Imagem base presa por digest: `3.14-slim` é uma etiqueta móvel e um rebuild
# amanhã traria outro sistema por baixo. Para atualizar, troque o digest de
# propósito e deixe a esteira renderizar a peça de prova antes de confiar.
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

# --- dependências de sistema -------------------------------------------------
# chromium  → renderiza assets/template.html e tira o screenshot da peça
# ffmpeg    → export de peça animada / trilha
# fontes    → sem elas o Chromium renderiza texto como caixas vazias
# O Chromium vai preso na versão. Ele não é só um detalhe de infraestrutura:
# é quem mede o texto. O motor descobre o corpo da fonte por busca binária
# perguntando ao navegador se a frase cabe na caixa — uma mudança de métrica
# muda o tamanho do texto em toda peça, caladamente, sem erro nenhum.
#
# Quando o Debian publicar outra versão, o build falha aqui. É de propósito:
# atualizar é decisão, não acidente. Para subir, troque o número abaixo e deixe
# a esteira renderizar a peça de prova antes de confiar.
ARG CHROMIUM_VERSAO=154.0.8037.92-1~deb13u1

RUN set -eux; \
    apt-get update; \
    if ! apt-get install -y --no-install-recommends "chromium=${CHROMIUM_VERSAO}"; then \
      echo "=== o Chromium ${CHROMIUM_VERSAO} não está mais no repositório ==="; \
      apt-cache policy chromium; \
      echo "Troque CHROMIUM_VERSAO para a versão acima, reconstrua, e confira a"; \
      echo "peça de prova antes de aceitar: o texto pode ter mudado de tamanho."; \
      exit 1; \
    fi; \
    apt-get install -y --no-install-recommends ffmpeg curl ca-certificates gnupg \
      fonts-dejavu-core fontconfig; \
    rm -rf /var/lib/apt/lists/*

# --- Node ---------------------------------------------------------------------
# Duas coisas precisam dele: o Remotion, que anima a peça, e a CLI do
# Higgsfield, que continua o desenho do fundo. Sem Node a plataforma entrega
# peça parada com fundo em bloco de cor — funciona, e é metade do produto.
ARG NODE_MAJOR=22
RUN set -eux; \
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -; \
    apt-get install -y --no-install-recommends nodejs; \
    npm install -g @higgsfield/cli; \
    node --version; npm --version; \
    rm -rf /var/lib/apt/lists/* /root/.npm

# As versões ficam gravadas na imagem: assim o sistema em pé sabe dizer com o
# que está desenhando, e a diferença entre duas máquinas aparece na hora.
RUN set -eux; \
    printf '{"chromium":"%s","fontes_dejavu":"%s","ffmpeg":"%s","node":"%s"}\n' \
      "$(dpkg-query -W -f='${Version}' chromium)" \
      "$(dpkg-query -W -f='${Version}' fonts-dejavu-core)" \
      "$(dpkg-query -W -f='${Version}' ffmpeg)" \
      "$(node --version)" > /app-versoes.json; \
    cat /app-versoes.json

# O motor procura o binário por nome; garante que "chrome" resolva.
RUN ln -sf /usr/bin/chromium /usr/local/bin/chrome

# CHROME_FLAGS: dentro do contêiner o processo roda como root, e o Chromium se
# recusa a abrir sem --no-sandbox. O --disable-dev-shm-usage evita o /dev/shm
# pequeno que o Docker dá por padrão, que trava o render de peça grande.
# As bandeiras vêm por ambiente para o motor continuar igual no Mac.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHROME_BIN=/usr/bin/chromium \
    CHROME_FLAGS="--no-sandbox --disable-dev-shm-usage"

WORKDIR /app

# --- dependências Python -----------------------------------------------------
# Copiadas antes do código: o cache do Docker só invalida quando elas mudam.
COPY requirements.txt requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt

# --- projeto de vídeo ---------------------------------------------------------
# Antes do código da aplicação: `npm ci` é o passo caro, e só deve refazer
# quando o lock mudar. O Remotion usa o Chromium que já está na imagem —
# `CHROME_BIN` diz isso a ele —, senão ele baixa um navegador próprio na
# primeira peça e passa a medir texto com outra métrica.
COPY video/package.json video/package-lock.json* ./video/
RUN set -eux; cd video; npm ci --omit=dev || npm install --omit=dev
COPY video/ ./video/

# --- código ------------------------------------------------------------------
COPY motor/ ./motor/
COPY api/ ./api/
COPY web/ ./web/
COPY worker.py ./

# Fontes da marca entram aqui (montadas em volume ou copiadas no build).
# Sem isso, a tipografia da peça não bate com a da arte-mãe.
RUN mkdir -p /app/fontes && fc-cache -f

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
