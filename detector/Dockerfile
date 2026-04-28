FROM python:3.11-slim

WORKDIR /app

COPY detector/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY detector /app

CMD ["python", "main.py"]
