# Huawei Cloud MaaS Statistics

A command-line skill that reports **Huawei Cloud MaaS (Model as a Service)** online-inference usage and cost — aggregate statistics, per-model requests / error rate / tokens / cost, caller source IPs, and per-model real cost from the official bill. It talks directly to the Huawei Cloud monitoring APIs (and the OCE billing API), handles `SDK-HMAC-SHA256` AK/SK signing itself, and needs **only the Python 3 standard library** (no `pip install`).

## Features

- **Aggregate summary** — total requests, errors, error rate, input/output/total tokens.
- **Per-model table** — requests, error rate, input/output/total (millions of tokens), cache hit ratio, cost (USD).
- **Optional latency** — avg/max end-to-end latency, avg/max TTFT, avg/max TPOT, plus avg/max input/output tokens per request.
- **Cost from the official bill** — per-model actual charged amount, aligned to the same local-time window.
- **Two donut charts** (PNG) — token total share and cost share, auto-generated under `maas_charts/`.
- **Caller source IPs** — list source IPs hitting MaaS, with IP-prefix search.
- **Flexible time windows** — last N hours/days, `today`/`yesterday`, or an arbitrary start/end (≤ 30 days).
- **Local-time aware** — uses the user's current timezone by default and says so in the output.
- **Dry-run** — print the signed request without sending it (and without exposing the SK).

## Requirements

- Python 3.9+ (standard library only).
- A Huawei Cloud account with MaaS enabled and the project ID. Authentication uses **OIDC login** (Authorization Code + PKCE); AK/SK remain an optional fallback.
- Network access to `modelarts.{region}.myhuaweicloud.com` and (for billing) `bss-intl.myhuaweicloud.com`.

## Installation

Copy the skill folder into your agent skills directory, or run the script in place:

```bash
python scripts/maas_statistics.py --help
```

## Configuration

Credentials and defaults are read from environment variables (or flags):

| Variable | Required | Description |
|---|---|---|
| `HWCLOUD_PROJECT_ID` | yes | Project ID (or `--project-id`) |
| `HWCLOUD_OIDC_AUTHORIZE_URL` | login | OIDC authorization endpoint |
| `HWCLOUD_OIDC_TOKEN_URL` | login | OIDC token endpoint |
| `HWCLOUD_OIDC_CLIENT_ID` | login | OIDC client id |
| `HWCLOUD_OIDC_CLIENT_SECRET` | no | OIDC client secret (confidential client) |
| `HWCLOUD_OIDC_SCOPE` | no | OIDC scope, default `openid profile` |
| `HWCLOUD_OIDC_PORT` | no | Local callback port, default `8765` |
| `HWCLOUD_IDP_ID` + `HWCLOUD_IAM_EXCHANGE_URL` | no | Exchange `id_token` for an IAM token |
| `HWCLOUD_REGION` | no | Region, default `ap-southeast-1` |
| `HWCLOUD_TIMEZONE` | no | User timezone, e.g. `Asia/Shanghai` |
| `HWCLOUD_TOKEN` | no | Override the saved token with a temporary `X-Auth-Token` |
| `HWCLOUD_AK` / `HWCLOUD_SK` | no | Optional fallback: AK/SK signing |
| `MAAS_ENDPOINT` | no | Override the MaaS endpoint host |

### Authentication (OIDC login)

Recommended: **OIDC Authorization Code + PKCE**. The user logs in through the browser; the skill receives the authorization code on a local callback (`http://127.0.0.1:<port>/callback`), exchanges it for tokens, and stores only a temporary token — **no AK/SK is stored**.

```bash
python scripts/maas_statistics.py login     # opens the browser, waits for the callback
python scripts/maas_statistics.py status    # show auth source / expiry
python scripts/maas_statistics.py logout    # remove the saved token
```

Configure the OIDC client with the env vars above (or matching `login` flags). The token is saved to `~/.config/huaweicloud-maas/token.json` with mode `0600` and used automatically by every command. `HWCLOUD_TOKEN` overrides it; `HWCLOUD_AK`+`HWCLOUD_SK` signing remains an optional fallback.

### Timezone

Times default to the **user's current timezone**, resolved in this order:

1. `--timezone`
2. `HWCLOUD_TIMEZONE`
3. saved user timezone file `~/.config/huaweicloud-maas/timezone`
4. OS detection (Windows registry / `/etc/timezone` / `/etc/localtime`)

When no timezone is given, the output explicitly states the detected user timezone that was used, for example:

```
Time range: 2026-10-27 00:00:00 ~ 2026-10-28 00:00:00 (Africa/Nairobi)
Note: no timezone specified; using detected user timezone Africa/Nairobi (UTC+03:00).
```

## Quick start

```bash
export HWCLOUD_PROJECT_ID=...
# OIDC config (for login):
export HWCLOUD_OIDC_AUTHORIZE_URL=... HWCLOUD_OIDC_TOKEN_URL=... HWCLOUD_OIDC_CLIENT_ID=...

# 1) Log in via OIDC Authorization Code + PKCE (no AK/SK stored)
python scripts/maas_statistics.py login
python scripts/maas_statistics.py status

# 2) Verify signing against the official example (no credentials needed)
python scripts/maas_statistics.py selftest

# 3) Aggregate summary for the last 24 hours
python scripts/maas_statistics.py summary --last 24h

# 4) Per-model table + cost + charts for yesterday (preset services)
python scripts/maas_statistics.py services --last 24h --service-type 2 --all

# 5) Per-model cost from the official bill for a single day
python scripts/maas_statistics.py billing --date 2026-10-27
```

## Subcommands

| Subcommand | What it does |
|---|---|
| `summary` | Aggregate total requests / errors / tokens for a window. |
| `services` | Per-model requests, error rate, tokens, cache hit ratio, cost, two donut charts (+ optional latency / token size). |
| `ips` | Caller source IP list. |
| `billing` | Per-model real cost from the official bill (OCE `res-fee-records`). |
| `login` | OIDC Authorization Code (+PKCE) browser login; stores a temporary token (`0600`). |
| `logout` | Remove the saved login token. |
| `status` | Show auth source / region / project / token expiry. |
| `selftest` | Verify AK/SK signing against the official example hash (no credentials needed). |

## Common parameters

- **Time**: `--last 24h|7d|30d`, `--days N`, or `--start` / `--end` (span ≤ 30 days). Accepts epoch ms, ISO 8601, `today`, `yesterday`.
- **Service type**: `--service-type 2` (preset) / `4` (custom) / `all`.
- **Inference type**: `--infer-type real_time|batch`.
- **Model type**: `--model-type "Text Generation" | "Image Generation" | ...`.
- **Filters**: `--service-names`, `--models`, `--api-keys`, `--ips`; for `ips`: `--ip-search`, `--service-id`.
- **Region / endpoint**: `--region`, `--endpoint`.

### `services` extras

- **Latency is hidden by default.** Add `--latency` to show avg/max end-to-end latency, avg/max TTFT, avg/max TPOT (uses per-service `show-detail-chart`, ~20 s rate limit).
- `--token-size` adds avg/max input/output tokens per request.
- `--no-cost`, `--no-chart`, `--no-max` skip the cost column, charts, or max-metric lookups.
- `--json` prints raw JSON.

## Example output

```
============================================================
Huawei Cloud MaaS per-model statistics (4 rows)
Time range: 2026-10-26 00:00:00 ~ 2026-10-27 00:00:00 (Africa/Nairobi)
Note: no timezone specified; using detected user timezone Africa/Nairobi (UTC+03:00).
============================================================
Model                       Requests    Error %    Input(M)     Output(M)    Total(M)     Cache Hit   Cost(USD)
----------------------------------------------------------------------------------------------------------------
GLM-5.2                     16          0.00%      0.382        0.011        0.392        68.40%      0.25
DeepSeek-V4.1-Flash         571         3.33%      19.288       1.261        20.550       71.17%      2.69
GLM-5.3                     102         8.82%      13.952       0.130        14.082       94.43%      6.17
DeepSeek-V4-Flash           247         2.43%      0.118        0.101        0.219        0.00%       0.03
```

Charts are written to `./maas_charts/` (`token_donut_*.png`, `cost_donut_*.png`) with English labels.

## How cost is computed

- `billing` reads **official resource consumption records** (`res-fee-records`), `statistic_type=3` (hourly detail).
- Each record carries `consume_time` (UTC hourly bucket); the skill keeps records falling inside the requested **user-timezone** window and aggregates `amount` (actual charged) and `official_amount` (list price) per model.
- Input usage excludes cached; tokens shown in **millions (M)**.
- The bill is same-calendar-month only and has hour-level latency.

## Rate limits & data retention

- Monitoring APIs: ~200 requests/min/user (HTTP 429 → wait 60 s).
- `show-detail-chart`: ~1 request / 20 s / user.
- Data retention: 30 days; `end - start` must be ≤ 30 days.

## Security

- Authentication is via a **temporary OIDC token** stored at `~/.config/huaweicloud-maas/token.json` with mode `0600`; the login flow stores no AK/SK.
- Tokens and any SK are **never printed**. `--dry-run` shows the request with `Authorization` / `X-Auth-Token` fully redacted (`***`).
- If you use the optional AK/SK fallback, keep them in environment variables or a secret manager — never commit them.

## Files

| File | Purpose |
|---|---|
| `scripts/maas_statistics.py` | The CLI implementation (stdlib only). |
| `SKILL.md` | Agent-facing skill metadata and usage. |
| `references/api-reference.md` | API request/response field reference. |
| `README.md` | This document. |
