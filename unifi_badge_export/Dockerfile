FROM python:3.13-alpine
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY exporter.py /app/exporter.py
CMD ["python3", "/app/exporter.py"]
