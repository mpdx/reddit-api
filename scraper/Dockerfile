FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium is already installed in the base image; just register it with this venv
RUN playwright install chromium

COPY . .

CMD ["python", "-u", "main.py"]
