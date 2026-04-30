# System architecture — HNG anomaly detection & Nextcloud stack

This document describes the full system: who talks to what, how data moves, and how the detector fits beside the prebuilt Nextcloud image. Use the Mermaid diagrams in [Mermaid Live](https://mermaid.live) or a VS Code Mermaid extension to export **`architecture.png`** for the brief.

---

## 1. Problem space (one paragraph)

Users reach **Nextcloud** over the public internet. **Nginx** terminates HTTP, logs every request as **JSON** to a shared volume. A **Python detector** tails that log, maintains **sliding windows** and a **rolling baseline**, flags **anomalies**, may add **host `iptables` rules** (per-IP), sends **Slack** alerts, writes an **audit log**, and serves a **live dashboard** (subdomain in production). The official Nextcloud image is **not** modified; all custom logic lives in Nginx config + the detector.

---

## 2. C4 Level 1 — System context

External actors and the system boundary.

```mermaid
flowchart TB
  subgraph internet["Public internet"]
    U[("End users / clients")]
    A[("Attack / load-test traffic")]
    G[("Graders / reviewers")]
  end

  subgraph hng["HNG cloud storage platform (this project)"]
    S["Nextcloud + Nginx + Detector stack\n(Linux VPS)"]
  end

  Slack[("Slack (webhook)")]
  DNS[("DuckDNS / DNS\nA record → VPS")]

  U -->|HTTPS/HTTP :8080| S
  A -->|:8080| S
  G -->|IP :8080 Nextcloud\nsubdomain :8090 dashboard| S
  S -->|Ban / unban / global alerts| Slack
  DNS -.->|resolves| S
```

**Notes**

- **:8080** = Nginx front door to Nextcloud (as in your compose).
- **:8090** = detector dashboard (host network in your design).
- Graders may hit **IP** for Nextcloud and a **hostname** for the dashboard per brief.

---

## 3. C4 Level 2 — Containers (Docker Compose)

Logical processes and data stores on one VPS.

```mermaid
flowchart TB
  subgraph host["Linux host (VPS)"]
    subgraph bridge["Docker bridge network (default)"]
      NC["nextcloud\nkefaslungu/hng-nextcloud"]
      NGX["nginx\nreverse proxy"]
    end

    subgraph hostnet["Host network namespace"]
      DET["detector\nPython daemon +\nFlask dashboard"]
    end

    VOL[("Named volume\nHNG-nginx-logs\n/var/log/nginx")]
    IPT[("Host netfilter\niptables DOCKER-USER")]

    U2[("Clients")] -->|:8080→80| NGX
    NGX -->|proxy_pass| NC
    NGX -->|append JSON lines| VOL

    DET -->|read-only tail\nhng-access.log| VOL
    DET -->|INSERT/DROP rules\nDOCKER-USER chain| IPT
    U2 -.->|blocked client traffic| IPT
  end
```

**Why two network modes?**

- **Nginx + Nextcloud** use normal bridge networking so port **8080:80** mapping works as expected.
- **Detector** uses **`network_mode: host`** plus **`NET_ADMIN`** so `iptables` commands affect the **real host** (rules visible in `iptables -L` for grading). The dashboard listens on **8090** on the host.

---

## 4. Request path vs observability path

Two orthogonal flows: **user data** vs **telemetry**.

```mermaid
flowchart LR
  subgraph data_plane["Data plane (user traffic)"]
    C[Client] -->|HTTP :8080| N[Nginx]
    N -->|HTTP| X[Nextcloud]
  end

  subgraph obs_plane["Observability plane"]
    N -->|JSON line per request| L[("/var/log/nginx/hng-access.log\non volume HNG-nginx-logs")]
    L --> M[Monitor: tail + parse]
    M --> W[Sliding windows]
    M --> B[Rolling baseline]
    W --> D[Detector logic]
    B --> D
    D --> F[Blocker / iptables]
    D --> SL[Slack notifier]
    D --> AU[Audit log]
    D --> DB[Dashboard API]
  end
```

---

## 5. Detector — internal components

Maps to your `detector/` modules.

```mermaid
flowchart TB
  subgraph detector["Detector process"]
    CFG["config.yaml\nthresholds, paths, webhook"]

    MON["monitor.py\nTail log, JSON → LogEvent"]

    SW["SlidingWindowTracker\n60s deques\nglobal + per-IP"]

    BL["RollingBaseline\n30m per-second series\n60s recalc, hourly slots\nfloor mean/stddev"]

    DET["detector.py\nz-score + N× mean\nerror-surge tighten"]

    BLK["blocker.py\niptables DOCKER-USER\nDROP per IP"]

    UNB["unbanner.py\n10m / 30m / 2h / permanent"]

    NOT["notifier.py\nSlack + audit file"]

    DASH["dashboard.py\nRuntimeState + Flask\n8090"]

    CFG --> MON
    CFG --> BL
    CFG --> DET
    MON --> SW
    MON --> BL
    SW --> DET
    BL --> DET
    DET --> BLK
    DET --> NOT
    BLK --> UNB
    UNB --> NOT
    SW --> DASH
    BL --> DASH
    BLK --> DASH
  end

  LOG[("Nginx access log")] --> MON
  BLK --> IPT[("Host iptables")]
```

---

## 6. Sequence — per-IP anomaly to ban

```mermaid
sequenceDiagram
  participant C as Client IP
  participant N as Nginx
  participant L as Access log
  participant D as Detector
  participant I as iptables / DOCKER-USER
  participant S as Slack
  participant A as Audit log

  C->>N: HTTP request
  N->>L: append JSON line
  D->>L: read new line
  D->>D: update deques + baseline
  D->>D: anomaly? z-score or 5× mean
  D->>I: iptables -I DOCKER-USER -s C -j DROP
  D->>S: webhook (condition, rate, baseline, duration)
  D->>A: BAN line
  Note over C,I: Subsequent packets from C dropped before reaching published ports
```

---

## 7. Sequence — global anomaly (alert only)

```mermaid
sequenceDiagram
  participant Many as Many clients
  participant N as Nginx
  participant L as Access log
  participant D as Detector
  participant S as Slack

  Many->>N: High aggregate rate
  N->>L: many JSON lines
  D->>D: global_rps vs baseline
  D->>S: Global anomaly alert
  Note over D: No mass iptables ban for "global" branch
```

---

## 8. Unban backoff

```mermaid
stateDiagram-v2
  [*] --> Banned: first ban
  Banned --> Try10: wait 10 min
  Try10 --> Released: unban + Slack + audit
  Try10 --> Banned2: still bad?
  Released --> [*]

  Banned2 --> Try30: wait 30 min
  Try30 --> Released2: unban
  Try30 --> Banned3: repeat offense

  Banned3 --> Try2h: wait 2 hours
  Try2h --> Released3: unban
  Try2h --> Permanent: no more auto-unban
```

(Exact timings match your `unbanner.py` config.)

---

## 9. Deployment & ports (reference)

| Surface | Port | Purpose |
|--------|------|--------|
| Host | **22** | SSH |
| Host | **8080** | Published **Nginx → Nextcloud** |
| Host | **8090** | **Detector dashboard** (Flask, host network) |
| Host | **80** | Optional host Nginx proxy to dashboard hostname |
| Internal | Nextcloud **expose 80** | Only reachable from Nginx on Docker network |

---

## 10. Shared volume contract

| Path in containers | Writer | Readers |
|-------------------|--------|---------|
| `/var/log/nginx/hng-access.log` | **nginx** | **detector** (tail, RO mount), **nextcloud** RO (per brief parity) |

Volume name: **`HNG-nginx-logs`**.

---

## 11. Security & trust boundaries

- **Real client IP**: Nginx trusts `X-Forwarded-For` (tune `set_real_ip_from` in production to known proxies only).
- **Blocking**: Only **per-IP** path adds host firewall rules; **global** anomaly does not blanket-ban.
- **Privilege**: Detector container is **privileged** + **NET_ADMIN** by design so host `iptables` matches grading expectations; minimize exposure (firewall only SSH + needed ports on cloud).

---

## 12. Exporting `architecture.png`

1. Open [Mermaid Live Editor](https://mermaid.live).
2. Paste **one** diagram at a time (Context or Container is best for a single poster image).
3. Export PNG.
4. Save as `docs/architecture.png` (or combine panels in any image editor).

Alternatively use **mermaid-cli** (`mmdc`) in CI to render from this file.

---

## 13. Diagram checklist for reviewers

- [ ] External users → Nginx :8080 → Nextcloud
- [ ] Nginx → JSON log → shared volume
- [ ] Detector tails log, updates windows/baseline, decides anomalies
- [ ] Per-IP → `iptables` + Slack + audit
- [ ] Global → Slack only
- [ ] Dashboard on :8090 (and optional hostname on :80)

This matches the HNG brief and your Compose layout.
