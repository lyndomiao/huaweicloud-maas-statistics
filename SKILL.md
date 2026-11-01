---
name: huaweicloud-maas-statistics
description: Query Huawei Cloud MaaS (Model as a Service) model invocation metrics and cost — aggregate stats, per-model requests/error rate/tokens/cost, caller source IPs, and per-model cost from the official bill. Use for Huawei Cloud MaaS traffic, token usage, error rate, latency, caller IPs, or per-model cost/billing.
whenToUse: The user has Huawei Cloud MaaS (Model as a Service) services (preset or custom endpoint) and wants requests, errors, token usage, latency for a time window, caller IPs, or per-model cost.
---

# Huawei Cloud MaaS Statistics

Query online-inference model usage via Huawei Cloud **MaaS (Model as a Service) monitoring APIs**. Ships `scripts/maas_statistics.py` (Python 3 stdlib only; handles AK/SK `SDK-HMAC-SHA256` signing automatically).

## Subcommands
| Subcommand | Purpose |
|---|---|
| `summary` | Aggregate total requests / errors / tokens |
| `services` | Per-model requests, error rate, tokens, cache hit ratio, cost (+ optional latency / token size) |
| `ips` | Caller source IP list |
| `billing` | Per-model real cost from the official bill (OCE `res-fee-records`) |
| `status` | Show configured region / project / auth source |

## Setup
Auth: **AK/SK** (`SDK-HMAC-SHA256`). Required env: `HWCLOUD_AK`, `HWCLOUD_SK`, `HWCLOUD_PROJECT_ID` (or `--project-id`).
**Important security notice** — for account safety, do NOT use your primary account keys. Create a **dedicated IAM user used only for MaaS and bill queries**:
1. Sign in to the console → **IAM → Permissions → Permission management → Create custom policy → JSON view**, paste the policy below, and create it (only billing needs this policy):
   `{"Version":"1.1","Statement":[{"Effect":"Allow","Action":["bss:billDetail:view"]}]}`
2. **IAM → User groups → Create user group**, then attach the custom policy from step 1.
3. **IAM → Users → Create User**: add the user to the group from step 2, set **Access type = Programmatic access only** (no console password), then generate its **access key (AK/SK)**.
4. Configure `HWCLOUD_AK` / `HWCLOUD_SK` / `HWCLOUD_PROJECT_ID` with that user's key.
Keep the SK in env or a local secret manager — never commit it or paste it into chats/logs; rotate periodically.
Optional: `HWCLOUD_REGION` (default `ap-southeast-1`), `HWCLOUD_TIMEZONE` (default = detected user timezone), `MAAS_ENDPOINT`.

## First run / security notice
On the **first use after install — even if credentials are already configured — show the user a one-time security notice** about using a **dedicated least-privilege READ-ONLY IAM user** for MaaS and bill queries. If credentials are missing, include the full creation steps below and do not just error out:
1. IAM → Permissions → Permission management → Create custom policy → JSON view (only billing needs this):
   `{"Version":"1.1","Statement":[{"Effect":"Allow","Action":["bss:billDetail:view"]}]}`
2. IAM → User groups → Create user group; attach the policy.
3. IAM → Users → Create User; add to the group; Access type = **Programmatic access only**; generate the **access key (AK/SK)**.
4. Configure `HWCLOUD_AK` / `HWCLOUD_SK` / `HWCLOUD_PROJECT_ID` (environment variables or `~/.config/huaweicloud-maas/credentials.json`, mode 0600).
Then run `selftest` and `status` to confirm connectivity.

## Usage
```bash
python scripts/maas_statistics.py selftest                 # verify signing (no creds)
python scripts/maas_statistics.py status                   # show region / project / auth source
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

## Result footer (always)
Always append this security reminder to **every** result you return to the user, after the data, and render it in **bold**:
> **Important security tip:** 1) create a dedicated IAM user for queries; querying bills requires the `bss:billDetail:view` permission; 2) never paste or send AK/SK or any secret in the chat window — configure credentials locally via environment variables or a protected credentials file; keep the AK/SK secret and rotate it periodically.

## Notes
- Region defaults to `ap-southeast-1`; pass `--region` if your resources are elsewhere. Rate limit ~200 req/min/user (HTTP 429 → wait 60s).
- Times use the **user's current timezone**, resolved in order: `--timezone` → `HWCLOUD_TIMEZONE` → saved `~/.config/huaweicloud-maas/timezone` → OS detection. When timezone is omitted, the output explicitly notes the detected user timezone used. Do not assume the server/machine timezone.
- `cost(USD)` = billed `amount` aligned to the same local-time window (hourly detail). Bill has hour-level latency and is same-calendar-month only.
- Token unit is million tokens. Never expose any SK; use `--dry-run` to inspect requests (auth headers redacted).
- Full request/response fields: `references/api-reference.md`.
- Security model & credential handling: see `SECURITY.md`.
