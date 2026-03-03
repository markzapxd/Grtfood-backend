FROM python:3.11-slim

ENV TZ="America/Sao_Paulo"
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependências
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copia código fonte
COPY . .

# Cria diretório de dados
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
