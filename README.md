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

Credentials and defaults are read from environment variables (or flags). **Minimal setup is 3 values** — `HWCLOUD_PROJECT_ID`, `HWCLOUD_OIDC_ISSUER`, `HWCLOUD_OIDC_CLIENT_ID`; everything else has defaults.

| Variable | Required | Default | How to obtain |
|---|---|---|---|
| `HWCLOUD_PROJECT_ID` | yes | — | Console **My Credentials → API Credentials** project list. |
| `HWCLOUD_OIDC_ISSUER` | yes* | — | OIDC app / IdP **issuer URL**; endpoints auto-discovered from `<issuer>/.well-known/openid-configuration`. |
| `HWCLOUD_OIDC_CLIENT_ID` | yes | — | OIDC application's **Client ID** (IAM Identity Center app details). |
| `HWCLOUD_OIDC_CLIENT_SECRET` | no | empty | Only for a **confidential** client; omit for public/PKCE clients. |
| `HWCLOUD_OIDC_AUTHORIZE_URL` / `HWCLOUD_OIDC_TOKEN_URL` | no | from issuer | Only if issuer discovery is unavailable — copy `authorization_endpoint` / `token_endpoint` from the discovery doc. |
| `HWCLOUD_IDP_ID` | no* | — | Identity provider id, needed to exchange `id_token` for an IAM token (to call MaaS). |
| `HWCLOUD_IAM_EXCHANGE_URL` | no | `https://iam.{region}.myhuaweicloud.com/v3.0/OS-AUTH/id-token/tokens` | Override only if different. |
| `HWCLOUD_REGION` | no | `ap-southeast-1` | Region of your MaaS service. |
| `HWCLOUD_TIMEZONE` | no | detected user tz | e.g. `Asia/Shanghai`. |
| `HWCLOUD_OIDC_SCOPE` | no | `openid profile` | — |
| `HWCLOUD_OIDC_PORT` | no | `8765` | Local callback port; the redirect URI must match. |
| `HWCLOUD_TOKEN` / `HWCLOUD_AK`+`HWCLOUD_SK` / `MAAS_ENDPOINT` | no | — | Temporary-token override / optional AK-SK fallback / endpoint override. |

`*` `HWCLOUD_IDP_ID` is required in the common federated setup where MaaS calls need an IAM token.

### Authentication (OIDC login)

Recommended: **OIDC Authorization Code + PKCE**. The user logs in through the browser; the skill receives the authorization code on a local callback (`http://127.0.0.1:<port>/callback`), exchanges it for tokens, and stores only a temporary token — **no AK/SK is stored**.

```bash
python scripts/maas_statistics.py login     # opens the browser, waits for the callback
python scripts/maas_statistics.py status    # show auth source / expiry
python scripts/maas_statistics.py logout    # remove the saved token
```

Configure the OIDC client with the env vars above (or matching `login` flags). With **`HWCLOUD_OIDC_ISSUER` + `HWCLOUD_OIDC_CLIENT_ID`** the endpoints are auto-discovered, so you usually don't set the authorization/token URLs. The token is saved to `~/.config/huaweicloud-maas/token.json` with mode `0600` and used automatically by every command. `HWCLOUD_TOKEN` overrides it; `HWCLOUD_AK`+`HWCLOUD_SK` signing remains an optional fallback.

#### One-time OIDC app registration (admin)

The OIDC application is created **once by an administrator of the Huawei Cloud tenant** (in IAM Identity Center). End users do **not** create it — they only run `login` with the provided configuration.

1. Sign in to **Huawei Cloud IAM Identity Center** as an administrator.
2. Create an **OIDC application**. Prefer a **public/native client with PKCE** (no `client_secret`), so the `client_id` can be shared safely.
3. Set the **redirect URI** exactly to `http://127.0.0.1:8765/callback` (or match your `HWCLOUD_OIDC_PORT`).
4. Enable grant type **authorization_code** with **PKCE (S256)**; scopes `openid profile`.
5. Copy the `client_id` (and `client_secret` only for a confidential client — keep it out of source control).
6. To call MaaS, an **IAM token** is required: configure an identity provider / trust and set `HWCLOUD_IDP_ID` so the skill can exchange the OIDC `id_token` for an IAM `X-Auth-Token`. `HWCLOUD_IAM_EXCHANGE_URL` overrides the default `https://iam.{region}.myhuaweicloud.com/v3.0/OS-AUTH/id-token/tokens`.

Distribution model: the tenant admin creates the app once and shares `client_id` (+ issuer/endpoints) with users; each user fills the env vars (or ships a `.env`) and runs `login`. A ready template is provided in [`.env.example`](.env.example).

#### How to obtain the values

1. **Project ID** — Huawei Cloud console → account menu (top-right) → **My Credentials → API Credentials**; find the Project ID for the target region (or pass `--project-id`).
2. **Issuer / authorize / token endpoints** — open the OIDC application details, or visit `https://<issuer>/.well-known/openid-configuration`; use its `issuer`, `authorization_endpoint`, `token_endpoint`. Usually you only need to give the skill the **issuer** — endpoints are auto-discovered.
3. **Client ID / Client Secret** — from **IAM Identity Center → Applications → (your OIDC app) → Credentials**. Public/native clients (PKCE) have no secret.
4. **IDP_ID** — from **IAM → Identity Providers**; the IdP used for federated login (needed to exchange the `id_token` for an IAM token).
5. **Region** — the region where your MaaS service runs (default `ap-southeast-1`).

When registering the OIDC app, set the **Redirect URI** to `http://127.0.0.1:8765/callback` (must match `HWCLOUD_OIDC_PORT`).

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
| `.env.example` | Environment template for OIDC / region / timezone. |
