from dataclasses import dataclass


@dataclass
class DetectionDecision:
    is_anomaly: bool
    condition: str
    current_rate: float
    baseline_mean: float
    baseline_stddev: float
    zscore: float
    scope: str
    tightened: bool


def compute_zscore(current_rate: float, mean_value: float, stddev_value: float) -> float:
    if stddev_value <= 0:
        return 0.0
    return (current_rate - mean_value) / stddev_value


def detect_rate_anomaly(
    *,
    current_rate: float,
    baseline_mean: float,
    baseline_stddev: float,
    scope: str,
    zscore_threshold: float,
    mean_multiplier_threshold: float,
    tightened: bool = False,
) -> DetectionDecision:
    zscore = compute_zscore(current_rate, baseline_mean, baseline_stddev)

    if zscore > zscore_threshold:
        return DetectionDecision(
            is_anomaly=True,
            condition=f"zscore>{zscore_threshold}",
            current_rate=current_rate,
            baseline_mean=baseline_mean,
            baseline_stddev=baseline_stddev,
            zscore=zscore,
            scope=scope,
            tightened=tightened,
        )

    if current_rate > (mean_multiplier_threshold * baseline_mean):
        return DetectionDecision(
            is_anomaly=True,
            condition=f"rate>{mean_multiplier_threshold}x_mean",
            current_rate=current_rate,
            baseline_mean=baseline_mean,
            baseline_stddev=baseline_stddev,
            zscore=zscore,
            scope=scope,
            tightened=tightened,
        )

    return DetectionDecision(
        is_anomaly=False,
        condition="normal",
        current_rate=current_rate,
        baseline_mean=baseline_mean,
        baseline_stddev=baseline_stddev,
        zscore=zscore,
        scope=scope,
        tightened=tightened,
    )