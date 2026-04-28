from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Deque, Dict, List, Optional, Tuple


class SlidingWindowTracker:
    """
    Tracks request timestamps over a true sliding 60-second window:
    - one global deque
    - one deque per source IP
    """

    def __init__(self, window_seconds: int = 60) -> None:
        self.window_seconds = window_seconds
        self.global_window: Deque[datetime] = deque()
        self.ip_windows: Dict[str, Deque[datetime]] = defaultdict(deque)

    def _evict_old(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.window_seconds)

        # Evict old global timestamps
        while self.global_window and self.global_window[0] < cutoff:
            self.global_window.popleft()

        # Evict old per-IP timestamps
        empty_ips: List[str] = []
        for ip, dq in self.ip_windows.items():
            while dq and dq[0] < cutoff:
                dq.popleft()
            if not dq:
                empty_ips.append(ip)

        # Cleanup empty IP deques to control memory
        for ip in empty_ips:
            del self.ip_windows[ip]

    def add_request(self, source_ip: str, timestamp: datetime) -> None:
        self.global_window.append(timestamp)
        self.ip_windows[source_ip].append(timestamp)
        self._evict_old(timestamp)

    def global_count_60s(self, now: datetime) -> int:
        self._evict_old(now)
        return len(self.global_window)

    def global_rps(self, now: datetime) -> float:
        return self.global_count_60s(now) / float(self.window_seconds)

    def ip_count_60s(self, source_ip: str, now: datetime) -> int:
        self._evict_old(now)
        return len(self.ip_windows.get(source_ip, deque()))

    def ip_rps(self, source_ip: str, now: datetime) -> float:
        return self.ip_count_60s(source_ip, now) / float(self.window_seconds)

    def top_n_ips(self, now: datetime, n: int = 10) -> List[Tuple[str, int]]:
        self._evict_old(now)
        counts = [(ip, len(dq)) for ip, dq in self.ip_windows.items()]
        counts.sort(key=lambda x: x[1], reverse=True)
        return counts[:n]


class RollingBaseline:
    """
    Learns "normal" request volume from recent per-second counts.
    Recalculates effective mean/stddev every interval (default 60s)
    using a rolling 30-minute window.
    """

    def __init__(
        self,
        rolling_window_minutes: int = 30,
        recalculation_interval_seconds: int = 60,
        min_samples_current_hour: int = 300,
        floor_mean: float = 0.1,
        floor_stddev: float = 0.1,
    ) -> None:
        self.rolling_window_seconds = rolling_window_minutes * 60
        self.recalculation_interval_seconds = recalculation_interval_seconds
        self.min_samples_current_hour = min_samples_current_hour
        self.floor_mean = floor_mean
        self.floor_stddev = floor_stddev

        self.per_second_counts: Dict[int, int] = defaultdict(int)
        self.hour_slots: Dict[str, List[int]] = defaultdict(list)

        self.last_recalculation_at: Optional[datetime] = None
        self.effective_mean = floor_mean
        self.effective_stddev = floor_stddev
        self.effective_source = "floor"

    @staticmethod
    def _to_epoch_second(dt: datetime) -> int:
        return int(dt.timestamp())

    @staticmethod
    def _hour_key(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")

    def add_observation(self, timestamp: datetime) -> None:
        sec = self._to_epoch_second(timestamp)
        self.per_second_counts[sec] += 1

    def _collect_rolling_values(self, now: datetime) -> List[int]:
        now_sec = self._to_epoch_second(now)
        start_sec = now_sec - self.rolling_window_seconds + 1
        return [self.per_second_counts.get(sec, 0) for sec in range(start_sec, now_sec + 1)]

    def _rebuild_hour_slots(self, now: datetime, rolling_values: List[int]) -> None:
        self.hour_slots.clear()
        now_sec = self._to_epoch_second(now)
        start_sec = now_sec - self.rolling_window_seconds + 1
        for idx, value in enumerate(rolling_values):
            sec = start_sec + idx
            dt = datetime.fromtimestamp(sec, tz=timezone.utc)
            self.hour_slots[self._hour_key(dt)].append(value)

    def recalculate_if_due(self, now: datetime) -> bool:
        if self.last_recalculation_at is not None:
            elapsed = (now - self.last_recalculation_at).total_seconds()
            if elapsed < self.recalculation_interval_seconds:
                return False

        rolling_values = self._collect_rolling_values(now)
        self._rebuild_hour_slots(now, rolling_values)

        current_hour_values = self.hour_slots.get(self._hour_key(now), [])
        if len(current_hour_values) >= self.min_samples_current_hour:
            source_values = current_hour_values
            self.effective_source = "current_hour"
        else:
            source_values = rolling_values
            self.effective_source = "rolling_30m"

        raw_mean = mean(source_values) if source_values else 0.0
        raw_stddev = pstdev(source_values) if len(source_values) > 1 else 0.0

        self.effective_mean = max(raw_mean, self.floor_mean)
        self.effective_stddev = max(raw_stddev, self.floor_stddev)
        self.last_recalculation_at = now
        return True

    def snapshot(self) -> Tuple[float, float, str]:
        return self.effective_mean, self.effective_stddev, self.effective_source