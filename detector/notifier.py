import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib import request


class SlackNotifier:
    def __init__(self, webhook_url: str = "") -> None:
        self.webhook_url = webhook_url.strip()

    def send(self, message: str) -> None:
        if not self.webhook_url:
            return
        payload = json.dumps({"text": message}).encode("utf-8")
        req = request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=5):
            pass


class AuditLogger:
    def __init__(self, path: str = "audit.log") -> None:
        self.path = Path(path)

    def write(
        self,
        action: str,
        ip: str,
        condition: str,
        rate: float,
        baseline: float,
        duration: str,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        line = (
            f"[{ts}] {action} {ip} | {condition} | "
            f"{rate:.4f} | {baseline:.4f} | {duration}\n"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)