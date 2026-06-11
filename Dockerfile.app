FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg libass9 fonts-noto fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-app.txt ./requirements-app.txt
RUN pip install --no-cache-dir -r requirements-app.txt

COPY app ./app
COPY prompts ./prompts

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
