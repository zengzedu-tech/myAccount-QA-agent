FROM python:3.12-slim

# Install Chromium
RUN apt-get update && \
    apt-get install -y --no-install-recommends chromium && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HEADLESS=true

EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
