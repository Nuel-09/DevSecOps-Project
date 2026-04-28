from datetime import datetime, timedelta, timezone
from typing import Dict, List

from blocker import IPBlocker


class UnbanScheduler:
    """
    Backoff schedule:
    1st release: 10m
    2nd release: 30m
    3rd release: 2h
    4th: permanent (no auto-unban)
    """

    def __init__(self, blocker: IPBlocker) -> None:
        self.blocker = blocker
        self.backoff_seconds: List[int] = [10 * 60, 30 * 60, 2 * 60 * 60]
        self.ban_attempts: Dict[str, int] = {}

    def next_duration_for_ip(self, ip: str) -> int | None:
        attempts = self.ban_attempts.get(ip, 0)
        if attempts >= len(self.backoff_seconds):
            return None
        return self.backoff_seconds[attempts]

    def register_new_ban(self, ip: str) -> int | None:
        duration = self.next_duration_for_ip(ip)
        attempts = self.ban_attempts.get(ip, 0)
        self.ban_attempts[ip] = attempts + 1
        return duration

    def due_unbans(self, now: datetime | None = None) -> List[str]:
        now = now or datetime.now(timezone.utc)
        due_ips: List[str] = []
        for ip, meta in self.blocker.active_bans.items():
            expires_at = meta.get("expires_at")
            if expires_at is not None and isinstance(expires_at, datetime) and expires_at <= now:
                due_ips.append(ip)
        return due_ips