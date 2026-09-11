FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install -r requirements.txt

COPY app.py backtest.py test_backtest.py ./
COPY .streamlit/config.toml .streamlit/config.toml
RUN python -m unittest -q test_backtest.py \
    && useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8501
CMD ["sh", "-c", "exec python -m streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT:-8501} --server.fileWatcherType=none"]
