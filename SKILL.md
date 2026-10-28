---
name: huaweicloud-maas-statistics
description: Query Huawei Cloud MaaS (Model as a Service) model invocation metrics and cost — aggregate stats, per-model requests/error rate/tokens/cost, caller source IPs, and per-model cost from the official bill. Use for Huawei Cloud MaaS traffic, token usage, error rate, latency, caller IPs, or per-model cost/billing.
whenToUse: The user has Huawei Cloud MaaS (Model as a Service) services (preset or custom endpoint) and wants requests, errors, token usage, latency for a time window, caller IPs, or per-model cost.
---

# Huawei Cloud MaaS Statistics

Query online-inference model usage via Huawei Cloud **MaaS (Model as a Service) monitoring APIs**. Ships `scripts/maas_statistics.py` (Python 3 stdlib only; supports OIDC browser login — Authorization Code + PKCE — and optional AK/SK `SDK-HMAC-SHA256` signing).

## Subcommands
| Subcommand | Purpose |
|---|---|
| `summary` | Aggregate total requests / errors / tokens |
| `services` | Per-model requests, error rate, tokens, cache hit ratio, cost (+ optional latency / token size) |
| `ips` | Caller source IP list |
| `billing` | Per-model real cost from the official bill (OCE `res-fee-records`) |
| `login` | OIDC Authorization Code (+PKCE) browser login; stores a temporary token (0600) |
| `logout` | Remove the saved login token |
| `status` | Show auth source / region / project / token expiry |

## Setup
Auth (recommended): run `login` (OIDC Authorization Code + PKCE). The temporary token is stored at `~/.config/huaweicloud-maas/token.json` (mode 0600) and used automatically; no AK/SK stored.
Required: `HWCLOUD_PROJECT_ID` (or `--project-id`).
OIDC config (minimal): `HWCLOUD_OIDC_ISSUER` + `HWCLOUD_OIDC_CLIENT_ID` (endpoints auto-discovered from `/.well-known/openid-configuration`; or set `HWCLOUD_OIDC_AUTHORIZE_URL`+`HWCLOUD_OIDC_TOKEN_URL` explicitly). Optional: `HWCLOUD_OIDC_CLIENT_SECRET` (confidential client), `HWCLOUD_OIDC_SCOPE`, `HWCLOUD_OIDC_PORT`; `HWCLOUD_IDP_ID` + `HWCLOUD_IAM_EXCHANGE_URL` to exchange `id_token` for an IAM token.
Optional: `HWCLOUD_REGION` (default `ap-southeast-1`), `HWCLOUD_TIMEZONE` (user timezone; default = saved/detected), `HWCLOUD_TOKEN` (override), `MAAS_ENDPOINT`. AK/SK (`HWCLOUD_AK`/`HWCLOUD_SK`) remain a fallback.

## Usage
```bash
python scripts/maas_statistics.py login                    # OIDC browser login (Authorization Code + PKCE)
python scripts/maas_statistics.py status                   # show auth source / expiry
python scripts/maas_statistics.py selftest                 # verify signing (no creds)
python scripts/maas_statistics.py summary --last 24h
python scripts/maas_statistics.py services --last 24h --service-type 2 --all
python scripts/maas_statistics.py services --days 3 --models GLM-5.3 --latency
python scripts/maas_statistics.py ips --last 7d --ip-search 192.168
python scripts/maas_statistics.py billing --date 2026-10-27 --timezone Africa/Nairobi --region ap-southeast-1
```

## Key parameters
- Time: `--last 24h|7d|30d`, `--days N`, or `--start/--end` (span ≤ 30 days).
- `--service-type 2`(preset)/`4`(custom)/`all`; `--infer-type real_time|batch`; `--model-type ...`.
- Filters: `--service-names`, `--models`, `--api-keys`, `--ips`; for `ips`: `--ip-search`, `--service-id`.
- `services` defaults: requests, error rate, **input/output/total (million tokens)**, **cache hit ratio**, **cost (USD)**, plus two donut charts under `maas_charts/`.
  - **Latency hidden by default**; add `--latency` to show avg/max end-to-end latency, avg/max TTFT, avg/max TPOT (per-service `show-detail-chart`, 20s rate limit).
  - `--token-size` adds avg/max input/output tokens (per request). `--no-cost`, `--no-chart`, `--no-max` to skip. `--json` for raw JSON.
- When latency is hidden, proactively ask the user whether to query avg/max end-to-end latency, avg/max TTFT, avg/max TPOT (then run with `--latency`).
- `summary` output uses million tokens; `billing` shows official price (before discount), no payable.

## Notes
- Region defaults to `ap-southeast-1`; pass `--region` if your resources are elsewhere. Rate limit ~200 req/min/user (HTTP 429 → wait 60s).
- Times use the **user's current timezone**, resolved in order: `--timezone` → `HWCLOUD_TIMEZONE` → saved `~/.config/huaweicloud-maas/timezone` → OS detection. When timezone is omitted, the output explicitly notes the detected user timezone used. Do not assume the server/machine timezone.
- `cost(USD)` = billed `amount` aligned to the same local-time window (hourly detail). Bill has hour-level latency and is same-calendar-month only.
- Token unit is million tokens. Never expose tokens or any SK; use `--dry-run` to inspect requests (auth headers redacted).
- Full request/response fields: `references/api-reference.md`.
