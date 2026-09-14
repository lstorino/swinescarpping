FROM python:3.12-slim

# scrapling pulls lxml + cssselect — that's the whole dependency surface.
# stdlib does fetch (urllib), FX, DB (sqlite3) and HTTP serving.
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scraper/pig333.py /app/scraper/pig333.py
COPY backend/server.py /app/server.py

ENV PIG_DB=/data/pigprices.db
RUN mkdir -p /data
VOLUME /data

EXPOSE 8902
CMD ["python", "server.py", "serve"]