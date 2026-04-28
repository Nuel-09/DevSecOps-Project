import subprocess
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional


class IPBlocker:
    def __init__(self, use_iptables: bool = False) -> None:
        self.use_iptables = use_iptables
        self.active_bans: Dict[str, Dict[str, object]] = {}

    def ban_ip(self, ip: str, duration_seconds: Optional[int], condition: str) -> bool:
        if ip in self.active_bans:
            return False

        if self.use_iptables:
            subprocess.run(
                ["iptables", "-I", "INPUT", "-s", ip, "-j", "DROP"],
                check=True,
                capture_output=True,
                text=True,
            )

        now = datetime.now(timezone.utc)
        expires_at = None if duration_seconds is None else now + timedelta(seconds=duration_seconds)
        self.active_bans[ip] = {
            "banned_at": now,
            "expires_at": expires_at,
            "duration_seconds": duration_seconds,
            "condition": condition,
            "attempts": 0,
        }
        return True

    def unban_ip(self, ip: str) -> bool:
        if ip not in self.active_bans:
            return False

        if self.use_iptables:
            subprocess.run(
                ["iptables", "-D", "INPUT", "-s", ip, "-j", "DROP"],
                check=True,
                capture_output=True,
                text=True,
            )

        del self.active_bans[ip]
        return True