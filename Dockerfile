FROM node:20-bookworm-slim

WORKDIR /app

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv ffmpeg fluidsynth fluid-soundfont-gm \
    build-essential libsndfile1 && rm -rf /var/lib/apt/lists/*

COPY package*.json ./
RUN npm install --omit=dev

RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir \
    numpy==1.26.4 \
    librosa==0.10.2.post1 \
    pretty_midi==0.2.10 \
    soundfile==0.12.1

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

COPY . .

RUN mkdir -p /app/data/jobs

EXPOSE 3000

CMD ["node", "server.js"]
