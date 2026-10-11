FROM python:3.12-slim AS runtime

# Build once: docker build --target runtime -t vericoder-runtime:local .
# Verification containers run offline; dependencies are installed at build time.
RUN pip install --no-cache-dir pytest Flask
WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "--version"]

FROM runtime AS application

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "vericoder.py"]
CMD ["demo"]
