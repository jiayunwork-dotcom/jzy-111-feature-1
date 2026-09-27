FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import json,urllib.request; req=urllib.request.Request('http://127.0.0.1:8000/nmo/point', data=json.dumps({'t0':2.0,'velocity':2000.0,'offset':0.0}).encode(), headers={'Content-Type':'application/json'}); urllib.request.urlopen(req, timeout=3).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
