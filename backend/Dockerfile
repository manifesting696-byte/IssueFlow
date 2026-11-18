FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY README.md /app/README.md
COPY backend/ .
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m app.cli seed && uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
