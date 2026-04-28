from collections import defaultdict
from datetime import timezone
import os

import yaml

from baseline import RollingBaseline, SlidingWindowTracker
from blocker import IPBlocker
from dashboard import RuntimeState, start_dashboard
from detector import detect_rate_anomaly
from monitor import tail_log_file
from notifier import AuditLogger, SlackNotifier
from unbanner import UnbanScheduler


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    cfg = load_config()
    log_file = os.getenv("DETECTOR_LOG_FILE", cfg["log_file"])
    poll_interval = float(os.getenv("DETECTOR_POLL_INTERVAL", cfg.get("poll_interval_seconds", 0.2)))

    sliding = SlidingWindowTracker(window_seconds=60)
    baseline_cfg = cfg.get("baseline", {})
    baseline = RollingBaseline(
        rolling_window_minutes=int(baseline_cfg.get("rolling_window_minutes", 30)),
        recalculation_interval_seconds=int(baseline_cfg.get("recalculation_interval_seconds", 60)),
        min_samples_current_hour=int(baseline_cfg.get("min_samples_current_hour", 300)),
        floor_mean=float(baseline_cfg.get("floor_mean", 0.1)),
        floor_stddev=float(baseline_cfg.get("floor_stddev", 0.1)),
    )

    detection_cfg = cfg.get("detection", {})
    zscore_threshold = float(detection_cfg.get("zscore_threshold", 3.0))
    mean_multiplier_threshold = float(detection_cfg.get("mean_multiplier_threshold", 5.0))
    error_surge_multiplier = float(detection_cfg.get("error_surge_multiplier", 3.0))
    tightened_zscore_threshold = float(detection_cfg.get("tightened_zscore_threshold", 2.0))
    tightened_mean_multiplier_threshold = float(
        detection_cfg.get("tightened_mean_multiplier_threshold", 3.0)
    )

    blocker = IPBlocker(use_iptables=bool(cfg.get("blocking", {}).get("use_iptables", False)))
    unbanner = UnbanScheduler(blocker)
    notifier = SlackNotifier(cfg.get("notifier", {}).get("slack_webhook_url", ""))
    audit = AuditLogger(cfg.get("audit", {}).get("log_path", "./audit.log"))
    dashboard_cfg = cfg.get("dashboard", {})
    dashboard_host = os.getenv("DASHBOARD_HOST", str(dashboard_cfg.get("host", "0.0.0.0")))
    dashboard_port = int(os.getenv("DASHBOARD_PORT", str(dashboard_cfg.get("port", 5000))))
    state = RuntimeState()
    start_dashboard(state=state, host=dashboard_host, port=dashboard_port)

    ip_total_counts = defaultdict(int)
    ip_error_counts = defaultdict(int)
    global_total_count = 0
    global_error_count = 0

    print(f"[detector] starting monitor on {log_file}")
    print(f"[dashboard] running on {dashboard_host}:{dashboard_port}")

    for event in tail_log_file(log_file, poll_interval):
        event_ts = event.timestamp
        if event_ts.tzinfo is None:
            event_ts = event_ts.replace(tzinfo=timezone.utc)

        sliding.add_request(event.source_ip, event_ts)
        baseline.add_observation(event_ts)

        now = event_ts
        if baseline.recalculate_if_due(now):
            baseline_mean, baseline_stddev, baseline_source = baseline.snapshot()
            print(
                f"[baseline] source={baseline_source} "
                f"mean={baseline_mean:.4f} stddev={baseline_stddev:.4f}"
            )
            audit.write(
                action="BASELINE_RECALCULATED",
                ip="-",
                condition=baseline_source,
                rate=0.0,
                baseline=baseline_mean,
                duration="-",
            )

        baseline_mean, baseline_stddev, _ = baseline.snapshot()
        state.set_baseline(baseline_mean, baseline_stddev, baseline.effective_source)

        global_total_count += 1
        ip_total_counts[event.source_ip] += 1
        if 400 <= event.status <= 599:
            global_error_count += 1
            ip_error_counts[event.source_ip] += 1

        baseline_error_rate = global_error_count / global_total_count if global_total_count else 0.0
        ip_error_rate = (
            ip_error_counts[event.source_ip] / ip_total_counts[event.source_ip]
            if ip_total_counts[event.source_ip]
            else 0.0
        )
        tightened = (
            baseline_error_rate > 0.0
            and ip_error_rate >= (error_surge_multiplier * baseline_error_rate)
        )

        g_count = sliding.global_count_60s(now)
        g_rps = sliding.global_rps(now)
        ip_count = sliding.ip_count_60s(event.source_ip, now)
        ip_rps = sliding.ip_rps(event.source_ip, now)
        top3 = sliding.top_n_ips(now, n=3)

        print(
            f"[metrics] global_60s={g_count} global_rps={g_rps:.3f} "
            f"ip={event.source_ip} ip_60s={ip_count} ip_rps={ip_rps:.3f} top3={top3}"
        )
        state.set_metrics(g_rps, top3)
        state.set_banned_ips(blocker.active_bans)

        ip_decision = detect_rate_anomaly(
            current_rate=ip_rps,
            baseline_mean=baseline_mean,
            baseline_stddev=baseline_stddev,
            scope="ip",
            zscore_threshold=tightened_zscore_threshold if tightened else zscore_threshold,
            mean_multiplier_threshold=(
                tightened_mean_multiplier_threshold if tightened else mean_multiplier_threshold
            ),
            tightened=tightened,
        )
        global_decision = detect_rate_anomaly(
            current_rate=g_rps,
            baseline_mean=baseline_mean,
            baseline_stddev=baseline_stddev,
            scope="global",
            zscore_threshold=zscore_threshold,
            mean_multiplier_threshold=mean_multiplier_threshold,
            tightened=False,
        )

        if ip_decision.is_anomaly:
            duration_seconds = unbanner.register_new_ban(event.source_ip)
            duration_label = "permanent" if duration_seconds is None else f"{duration_seconds}s"
            if blocker.ban_ip(event.source_ip, duration_seconds, ip_decision.condition):
                print(
                    f"[anomaly][ip] ip={event.source_ip} condition={ip_decision.condition} "
                    f"rate={ip_decision.current_rate:.4f} baseline={ip_decision.baseline_mean:.4f} "
                    f"z={ip_decision.zscore:.4f} tightened={ip_decision.tightened}"
                )
                notifier.send(
                    "IP anomaly triggered | "
                    f"condition={ip_decision.condition} | rate={ip_decision.current_rate:.4f} | "
                    f"baseline={ip_decision.baseline_mean:.4f} | timestamp={now.isoformat()} | "
                    f"ban_duration={duration_label}"
                )
                audit.write(
                    action="BAN",
                    ip=event.source_ip,
                    condition=ip_decision.condition,
                    rate=ip_decision.current_rate,
                    baseline=ip_decision.baseline_mean,
                    duration=duration_label,
                )

        if global_decision.is_anomaly:
            print(
                f"[anomaly][global] condition={global_decision.condition} "
                f"rate={global_decision.current_rate:.4f} baseline={global_decision.baseline_mean:.4f} "
                f"z={global_decision.zscore:.4f}"
            )
            notifier.send(
                "Global anomaly triggered | "
                f"condition={global_decision.condition} | rate={global_decision.current_rate:.4f} | "
                f"baseline={global_decision.baseline_mean:.4f} | timestamp={now.isoformat()}"
            )

        for due_ip in unbanner.due_unbans(now):
            if blocker.unban_ip(due_ip):
                print(f"[unban] ip={due_ip}")
                notifier.send(
                    "IP unbanned | "
                    f"condition=backoff-expired | rate=0.0 | baseline={baseline_mean:.4f} | "
                    f"timestamp={now.isoformat()} | ban_duration=released"
                )
                audit.write(
                    action="UNBAN",
                    ip=due_ip,
                    condition="backoff-expired",
                    rate=0.0,
                    baseline=baseline_mean,
                    duration="released",
                )
                state.set_banned_ips(blocker.active_bans)


if __name__ == "__main__":
    main()