FROM docker.m.daocloud.io/library/python:3.12.12-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1
RUN useradd --uid 10001 --create-home gateway && mkdir /app/var && chown gateway:gateway /app/var
USER gateway
EXPOSE 18081
CMD ["uvicorn", "tk_gateway.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "18081", "--workers", "1", "--no-access-log"]
