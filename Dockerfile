FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir uv==0.12.23 && uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" \
    SPECPROBE_DATABASE_URL="sqlite:////data/specprobe.db" \
    SPECPROBE_VECTOR_PATH="/data/chroma"
RUN useradd --create-home --uid 10001 specprobe && mkdir -p /data && chown specprobe /data
USER specprobe
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health',timeout=3)"
EXPOSE 8000 8501
CMD ["uvicorn", "specprobe.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
