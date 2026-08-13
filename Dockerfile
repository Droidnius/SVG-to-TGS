FROM python:3.11-slim

# Dependencias de sistema necesarias para renderizar SVG (usadas por
# cairosvg, que instala lottie[all]) y para compilar algunas libs de Python.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libcairo2-dev \
    libxml2-dev \
    libxslt1-dev \
    pkg-config \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# El bot no expone ningún puerto: usa polling saliente hacia Telegram.
CMD ["python", "bot.py"]
