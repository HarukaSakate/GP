FROM python:3.12-slim

WORKDIR /app
COPY scripts/ scripts/
COPY tests/ tests/
COPY web/ web/
COPY docs/ docs/
COPY README.md .

EXPOSE 8000 8765

HEALTHCHECK --interval=5s --timeout=2s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/web/player.html', timeout=1)"

CMD ["python", "scripts/tcp_info_signal_server.py", "--host", "0.0.0.0", "--serve-dir", "/app"]
