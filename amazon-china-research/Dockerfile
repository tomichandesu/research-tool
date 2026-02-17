FROM python:3.11-slim

# Install system deps for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libatspi2.0-0 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libxshmfence1 libxfixes3 libx11-6 libx11-xcb1 libxcb1 libxext6 \
    libxrender1 libxtst6 libxi6 libglib2.0-0 libexpat1 \
    fonts-noto-cjk curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt web_requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r web_requirements.txt

# Install Playwright + Chromium
RUN pip install playwright && playwright install chromium

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p /app/data /app/output/jobs

EXPOSE 8000

CMD ["python", "run_web.py"]
