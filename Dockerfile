FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"
CMD ["python", "-m", "specprobe.demo"]
