FROM python:3.12.11-alpine3.22

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup -S asfbot \
    && adduser -S -G asfbot -h /app asfbot

COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes --requirement requirements.lock

COPY bot.py ./bot.py
COPY ASFConnector.py ./ASFConnector.py
COPY logger.py ./logger.py
COPY IPCProtocol/ ./IPCProtocol/

USER asfbot

# Keep health independent from Telegram, ASF availability, and credentials.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import pathlib,sys; sys.exit(0 if b'bot.py' in pathlib.Path('/proc/1/cmdline').read_bytes() else 1)"]

ENTRYPOINT ["python", "bot.py"]
