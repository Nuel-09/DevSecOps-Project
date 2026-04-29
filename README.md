# Anomaly Detection Engine (DDOS-style detection)

Real-time HTTP anomaly detection for a Nextcloud stack behind Nginx: tail JSON access logs, sliding-window rates, rolling statistical baseline, z-score and spike rules, per-IP `iptables` bans with Slack + audit trail, auto-unban backoff, and a live metrics dashboard.

## Live endpoints (update during grading window)


| Item                               | Value                           |
| ---------------------------------- | ------------------------------- |
| **Server IP**                      | `129.212.222.41`                |
| **Metrics dashboard**              | `http://mydetector.duckdns.org` |
| **Nextcloud (IP only, per brief)** | `http://129.212.222.41:8080`    |


Both the server and dashboard URL must stay reachable for the full grading period. If your Reserved IP or DuckDNS hostname changes, update this table and your submission.

---

## Language choice

**Python 3.11**

- Clear standard library + small deps (`PyYAML`, `Flask`, `psutil`) for a learning-focused implementation.
- Fast iteration on parsing, statistics, and concurrency (tail loop + dashboard thread).
- Straightforward to document deque sliding windows and rolling baselines for reviewers.

---

## Sliding window (60 seconds)

**Structure**

- **Global:** one `collections.deque` of request **timestamps** for all traffic.
- **Per IP:** a **dictionary** mapping each `source_ip` to its own deque of timestamps.

**Eviction logic**

- Each deque only keeps timestamps **newer than** `now - 60 seconds`.
- On every new request, we append the event time, then **pop from the left** while the oldest timestamp is before the cutoff (lazy eviction when events arrive).
- Empty per-IP deques are removed to limit memory.

**Rates**

- **Counts in window:** `len(deque)` after eviction.
- **Requests per second (display):** count / 60 (average rate over the last 60 seconds).

No third-party rate-limiting libraries; this is explicit deque math.

---

## Rolling baseline

**What we model**

- **Per-second global counts:** every second bucket gets `+1` for each request observed in that second (UTC epoch second).

**Window**

- **Rolling length:** last **30 minutes** of per-second counts (`baseline.rolling_window_minutes` in `detector/config.yaml`, default `30`).

**Recalculation**

- **Every 60 seconds** (`recalculation_interval_seconds`), if enough time has passed since the last run, we recompute **mean** and **population stddev** (`statistics.mean` / `statistics.pstdev`) over that rolling slice.

**Hourly slots**

- Within that same 30-minute slice, counts are grouped into **hour buckets** (`YYYY-MM-DDTHH` UTC).
- If the **current hour** has at least `**min_samples_current_hour`** samples (default `300`), the effective baseline uses **only that hour’s** values; otherwise it falls back to the **full 30-minute** rolling list.

**Floors**

- `**floor_mean`** and `**floor_stddev`** (defaults `0.1`) clamp tiny values so z-scores stay stable when traffic is near zero.

Effective mean/stddev are **never hardcoded** to a fixed “normal traffic” constant; they come from recent observed counts plus floors.

---

## Setup: fresh VPS → running stack

Example: **Ubuntu 22.04** on DigitalOcean, **2 vCPU / 2 GB RAM**, **Reserved IP** attached.

### 1) OS and Docker

SSH into the VPS, then:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-plugin git ufw
sudo systemctl enable docker --now
```

(Optional non-root Docker user: `sudo usermod -aG docker $USER` and re-login.)

Verify:

```bash
docker --version
docker compose version
docker run --rm hello-world
```

### 2) Firewall (UFW)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 8080/tcp
sudo ufw allow 8090/tcp
sudo ufw allow 80/tcp
sudo ufw enable
sudo ufw status
```

Also open the same ports on **DigitalOcean → Networking → Firewalls** and attach the firewall to your Droplet.

### 3) Clone this repository

```bash
sudo mkdir -p /opt/hng && sudo chown "$USER:$USER" /opt/hng
cd /opt/hng
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
```

Replace with your **public** GitHub URL.

### 4) Configure the detector

Edit `detector/config.yaml`:


| Setting                      | Production (VPS)                                                                         |
| ---------------------------- | ---------------------------------------------------------------------------------------- |
| `log_file`                   | `/var/log/nginx/hng-access.log`                                                          |
| `blocking.use_iptables`      | `true`                                                                                   |
| `notifier.slack_webhook_url` | Your Slack incoming webhook (keep secret; avoid committing real tokens to a public repo) |
| `audit.log_path`             | e.g. `./audit.log` (container-local unless you add a bind mount)                         |


The Compose file sets `DETECTOR_LOG_FILE=/var/log/nginx/hng-access.log` for the detector container; keeping `log_file` aligned avoids confusion.

### 5) Start the stack

From the repo root (where `docker-compose.yml` lives):

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f detector
```

### 6) Verify services

- Nextcloud via Nginx: `http://YOUR_RESERVED_IP:8080`
- Dashboard: `http://YOUR_RESERVED_IP:8090` and `http://YOUR_RESERVED_IP:8090/api/metrics`

### 7) Dashboard on a free hostname (DuckDNS)

1. Create `yourname.duckdns.org` at [DuckDNS](https://www.duckdns.org) and point it to your **Reserved IP**.
2. Allow **8090** on cloud firewall + UFW.
3. Use `http://yourname.duckdns.org:8090` as the public metrics URL.

(Optional) Put **Nginx on the host** on port **80** reverse-proxying to `http://127.0.0.1:8090` so the dashboard has no port in the URL.

### 8) IP bans and iptables (grading)

The detector service uses `**network_mode: host`**, `**privileged: true`**, and `**cap_add: NET_ADMIN**` so `iptables` applies on the real host. Bans insert into the `**DOCKER-USER**` chain (traffic to published container ports).

After a ban:

```bash
sudo iptables -L DOCKER-USER -n -v
```

---

## Repository structure (high level)

```
detector/          Python daemon + dashboard
nginx/nginx.conf   Reverse proxy + JSON access log
docker-compose.yml Nextcloud + Nginx + detector + HNG-nginx-logs volume
docs/              Architecture diagram (architecture.png)
screenshots/       Required submission screenshots
```

---

## GitHub repository (public)

**Repository:** [https://github.com/Nuel-09/DevSecOps-Project.git](https://github.com/Nuel-09/DevSecOps-Project.git)

---

## Blog post

A beginner-friendly write-up of this project is linked here once published: **(add your Hashnode / Dev.to / Medium URL)**.