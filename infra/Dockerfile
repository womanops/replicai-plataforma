# ReplicAI — imagem da plataforma
#
# Esta imagem é a resposta ao problema de portabilidade: ela carrega DENTRO dela
# o Python, as bibliotecas, o Chromium e o ffmpeg. Onde esta imagem roda, o
# ReplicAI roda igual — Mac, Windows, Linux, qualquer servidor ou nuvem.
# O cliente final nunca instala nada: ele usa o navegador.

FROM python:3.14-slim

# --- dependências de sistema -------------------------------------------------
# chromium  → renderiza assets/template.html e tira o screenshot da peça
# ffmpeg    → export de peça animada / trilha
# fontes    → sem elas o Chromium renderiza texto como caixas vazias
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium \
      ffmpeg \
      curl \
      fonts-dejavu-core \
      fontconfig \
    && rm -rf /var/lib/apt/lists/*

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

# --- código ------------------------------------------------------------------
COPY motor/ ./motor/
COPY api/ ./api/

# Fontes da marca entram aqui (montadas em volume ou copiadas no build).
# Sem isso, a tipografia da peça não bate com a da arte-mãe.
RUN mkdir -p /app/fontes && fc-cache -f

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
