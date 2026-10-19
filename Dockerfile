FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && useradd --create-home app \
 && mkdir /data && chown app /data
USER app
ENV MAINTDESK_DB_PATH=/data/maintdesk.sqlite3
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["uvicorn", "maintdesk.api:app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]
