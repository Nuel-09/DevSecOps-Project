FROM python:3.11-slim

WORKDIR /app

# Required at runtime when use_iptables is true (host netfilter from privileged + host network)
RUN apt-get update && apt-get install -y --no-install-recommends \
    iptables \
    && rm -rf /var/lib/apt/lists/*

COPY detector/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY detector /app

CMD ["python", "main.py"]
