# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ffmpeg a kamera hangszóró formátumának konverziójához (MP3 → G.711 μ-law)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Függőségek külön rétegbe (jobb cache-elhetőség)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Alkalmazás kód
COPY main.py tapo_player.py server.py ./

# Music könyvtár – host volume-ból lesz feltöltve
RUN mkdir -p music

# API port
EXPOSE 8099

# Szerver indítása 0.0.0.0-n (network_mode: host esetén is kell)
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8099"]
