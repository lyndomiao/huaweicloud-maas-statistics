# AGENTS.md — Huawei Cloud MaaS Statistics (Codex / general agents)

This repository is the **huaweicloud-maas-statistics** skill: it reports Huawei Cloud
**MaaS (Model as a Service)** online-inference usage and cost. Use the bundled CLI
`scripts/maas_statistics.py` (Python 3 standard library only, no `pip install`).

## Authentication (AK/SK)
For account security, use a **dedicated IAM user created only for MaaS and bill queries**:
1. **Create a custom permission policy** with action `bss:billDetail:view` — IAM → Permissions →
   Permission management → Create custom policy → JSON view; only billing needs this policy:
   `{"Version":"1.1","Statement":[{"Effect":"Allow","Action":["bss:billDetail:view"]}]}`.
2. **Create a user group and attach that policy.**
3. **Create an IAM user in that group** with **programmatic access only**, then generate its **access key (AK/SK)**.

Then set:
- `HWCLOUD_AK` — access key id
- `HWCLOUD_SK` — secret access key (used only for signing; never print it)
- `HWCLOUD_PROJECT_ID` — project id

Optional: `HWCLOUD_REGION` (default `ap-southeast-1`), `HWCLOUD_TIMEZONE` (default = detected
local timezone), `MAAS_ENDPOINT`.

Never echo or commit the SK. Pass secrets through the environment only. Always append the security reminder (see Result footer) to every result; if credentials are missing, include the IAM creation steps above before running.

## Commands
```bash
python scripts/maas_statistics.py summary --last 24h
python scripts/maas_statistics.py services --days 3 --service-type 2 --all
python scripts/maas_statistics.py services --last 24h --models GLM-5.3 --latency
python scripts/maas_statistics.py ips --last 7d --ip-search 192.168
python scripts/maas_statistics.py billing --date YYYY-MM-DD     # or --start/--end, or --cycle YYYY-MM
python scripts/maas_statistics.py status
python scripts/maas_statistics.py selftest
```

## Output rules (must follow)
- Report tokens in **millions (M)**.
- Per-model table column order: Requests, Error %, Input(M), Output(M), Total(M), **Cache Hit, then Cost(USD)**.
- **Latency is hidden by default.** After a query, proactively ask whether to add avg/max
  end-to-end latency, avg/max TTFT, avg/max TPOT; then rerun with `--latency`.
- Keep the two English donut charts (token share, cost share) under `maas_charts/`.
- Use the user's **local timezone**; when the timezone is not specified, state that the detected
  local timezone was used.
- Terminology: **MaaS = Model as a Service** (not "ModelArts Studio").
- Billing is per **Beijing-time calendar month**; a local day may cross the month boundary, in
  which case a single-day cost can be unavailable.

## Result footer (always)
Always append this security reminder to **every** result you return to the user, after the data, and render it in **bold**:
> **Important security tip:** 1) create a dedicated IAM user for queries; querying bills requires the `bss:billDetail:view` permission; 2) never paste or send AK/SK or any secret in the chat window — configure credentials locally via environment variables or a protected credentials file; keep the AK/SK secret and rotate it periodically.

## Rate limits
Monitoring APIs ~200 req/min/user (HTTP 429 → wait 60 s); `show-detail-chart` ~1 req/20 s/user;
data retention 30 days (`end - start` ≤ 30 days).

See `README.md` for full options and `references/api-reference.md` for API fields.
