# How I Built a Real-Time Anomaly Detector for Web Traffic (Beginner Friendly)

If you’ve ever wondered how websites defend themselves when traffic suddenly spikes—or when one IP keeps hammering login—you’re in the right place. This post walks through a small project I built: a **Python daemon** that watches **Nginx access logs**, learns what “normal” traffic looks like, and reacts when things look wrong. No security jargon gatekeeping—just plain concepts.

---

## Why this project matters

Imagine a Nextcloud server open on the internet. Most traffic is normal browsing and uploads. Sometimes:

- One IP sends thousands of requests per minute (abuse or an attack).
- Total traffic suddenly doubles everywhere at once (a spike).

Operators want:

1. **Detection** that adapts to real traffic—not fixed magic numbers.
2. **Response** that stops abusive IPs without shutting down the whole service for everyone.
3. **Visibility**: dashboards and alerts so humans notice quickly.

This project does exactly that in a teaching-sized package.

---

## What we built (big picture)

Stack:

1. **Nextcloud** behind **Nginx**, writing **JSON access logs** to a shared Docker volume.
2. A **detector** service that:
   - tails the log continuously,
   - tracks rates with sliding windows,
   - learns a rolling baseline,
   - flags anomalies,
   - optionally adds **iptables** rules to drop abusive IPs,
   - sends **Slack** alerts,
   - serves a small **live dashboard**.

Think of it as: **eyes on logs + math + firewall hooks**.

---

## Sliding windows (60 seconds): intuition first

We care about “how busy is it **right now**, compared to recent history?”

### What we store

For each **source IP**, we keep a **deque** (double-ended queue) of **timestamps**—only for requests that happened in the **last 60 seconds**.

We also keep one deque for **global** traffic.

### Eviction (the important part)

When a new request arrives:

1. Append its timestamp.
2. Remove timestamps older than 60 seconds from the **front** of the deque.

That’s “sliding”: the window always covers “now minus 60 seconds,” not “this calendar minute.”

### Rate

After eviction:

- **Requests in last 60s** ≈ `len(deque)`.
- **Rough requests/sec** can be shown as that count divided by 60 (average over the window).

No special rate-limit library—we implemented the window ourselves.

---

## Rolling baseline: teaching the machine “normal”

Fixed thresholds like “ban above 1000 req/s” fail in real life because “normal” differs per server and time of day.

### Per-second counts

Every second, we increment a counter for “how many requests arrived this second.” That builds a time series.

### 30-minute rolling window

We look back **30 minutes** of those per-second values.

### Recalculate every 60 seconds

Every minute we compute:

- **mean** (average requests per second-ish behavior),
- **spread** (standard deviation),

from that window.

### Hour preference

Traffic often differs by hour (morning vs night). We bucket samples by hour and, when enough data exists for the **current hour**, we prefer that slice for the baseline; otherwise we fall back to the wider 30-minute window.

### Floors

When traffic is tiny, mean/stddev can hit zero and math blows up. Small **floor** values keep statistics stable.

Net effect: **baseline tracks reality**, not a hardcoded guess.

---

## How detection decides “something is wrong”

For both **per-IP rate** and **global rate**, we compare current behavior to the baseline.

Two parallel triggers (whichever fires first):

1. **Z-score**: how many standard deviations above mean is the current rate? If it crosses a threshold (e.g. 3), flag anomaly.
2. **Multiplier**: if current rate is way above baseline mean (e.g. more than 5×), flag anomaly.

There’s also an **error surge** idea: if one IP produces far more 4xx/5xx responses than the baseline error rate, we **tighten** thresholds for that IP—like turning sensitivity up when someone looks “scan-y.”

---

## Global vs per-IP response

- **Per-IP anomaly**: block that IP with **iptables** (and alert Slack).
- **Global anomaly**: alert Slack only—because blocking “the whole internet” isn’t meaningful.

That matches how operators think: spike everywhere ≠ automatically ban everyone.

---

## iptables in plain English

**iptables** is Linux’s firewall rule engine. A simple mental model:

- Traffic arrives at the server.
- Rules decide **allow** or **drop**.

For Docker setups, traffic to published ports often flows through Docker’s chains. In practice, inserting a **DROP** rule for a bad source IP in the right chain stops that client from reaching your published ports.

Important operational detail: running `iptables` inside a normal container often wouldn’t affect the host. We used **host networking** and appropriate capabilities so rules apply where they matter for grading and real blocking.

---

## What I learned

- **Deque windows** are small code with big clarity—you always know what “last 60 seconds” means.
- **Rolling baselines** make detection feel fair: it adapts if your traffic grows legitimately.
- **Docker + logs + host networking** is powerful but easy to footgun—always verify where firewall rules actually apply.

---

## Closing

If you’re new to security tooling, start with **good logs**, **simple math**, and **visible alerts**. Fancy ML can come later—understanding windows, baselines, and firewalls already puts you ahead of “magic black box” thinking.

---

### Tags you can use on Dev.to

`beginners` `python` `docker` `devops` `security` `nginx` `iptables` `monitoring`

---

*Replace this line with your live repo link and dashboard URL when you publish.*
