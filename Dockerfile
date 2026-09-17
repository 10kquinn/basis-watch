FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install -r requirements.txt

COPY app.py backtest.py market_filters.py bend_api.py research.py execution.py storage.py paper.py lab.py research_ui.py recorder.py test_backtest.py test_market_filters.py test_bend_api.py test_research.py test_research_ui.py ./
COPY .streamlit/config.toml .streamlit/config.toml
COPY serve.py test_serve.py ./
RUN python -m unittest discover -q \
    && useradd --create-home --uid 10001 appuser \
    && mkdir /app/data && chown appuser:appuser /app/data
USER appuser

EXPOSE 8501
CMD ["python", "serve.py"]
