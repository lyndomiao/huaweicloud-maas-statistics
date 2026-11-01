# Huawei Cloud MaaS Monitoring API Reference

MaaS monitoring APIs. Auth: `X-Auth-Token` or AK/SK `SDK-HMAC-SHA256`. Endpoint `modelarts.{region}.myhuaweicloud.com`, path prefix `/v1/{project_id}/maas/monitoring/`.

- Region: default `ap-southeast-1` (pass `--region` for others). Rate limit ~200 req/min/user (HTTP 429 → wait 60s). Data retained 30 days; `end_time - start_time` ≤ 30 days.
- Token units in responses are **thousand tokens** (the skill converts to million for display).

## 1. ShowStatistics — aggregate
`POST /v1/{project_id}/maas/monitoring/show-statistics`

Body: `service_type`(2 preset /4 custom), `start_time`,`end_time` (epoch ms), `infer_type`(`real_time`/`batch`); optional `timezone` (the skill passes your local timezone by default), `model_type`, `api_keys[]`, `ips[]`.

Response: `total_request_count`, `total_error_count`, `total_token`, `total_prompt_token`, `total_completion_token`, `total_completion_tasks`, `total_infer_count`, `video_generate_duration`, `image_generate_nums`.

## 2. ListServiceStatistics — per service
`POST /v1/{project_id}/maas/monitoring/list-service-statistics`

Body: `service_type`, `start_time`, `end_time`, `infer_type`; optional `service_names[]`, `api_keys[]`, `ips[]`, `limit`(0 = all), `offset`, `timezone`, `model_type`.

Response `{total, count, items[]}`; key `items[]` fields:
`service_id, service_name, generation_type, request_count, error_count, error_rate(0–1), total_token, prompt_token, completion_token, avg_latency(ms), avg_ttft(ms), avg_tpot(ms), cache_token, cache_hit_ratio` (batch: `infer_times, completion_tasks_count, avg_consume_time, scc_count`).

## 3. ListSourceIps — caller IPs
`POST /v1/{project_id}/maas/monitoring/source-ips`

Body: `service_type`, `start_time`, `end_time`, `limit`(>0); optional `offset`, `ip_search` (prefix), `service_id`, `api_keys[]`, `timezone`.

Response: `{total, items[ips], count}`.

## 4. ListCustomerselfResourceRecords — real cost (OCE)
`GET /v2/bills/customer-bills/res-fee-records`
Endpoint: intl `bss-intl.myhuaweicloud.com`, China `bss.myhuaweicloud.com`.

Query: `cycle`(YYYY-MM, required), `statistic_type`(1 cycle /2 day /3 detail, default 3), `bill_date_begin/end`, `cloud_service_type=hws.service.type.modelarts`, `region`, `limit/offset`.
Bill is split by Beijing time (UTC+8); hourly latency; same calendar month only. With `statistic_type=3`, each record's `consume_time` is a UTC hourly bucket (e.g. `2026-10-27T15:00:00Z-2026-10-27T16:00:00Z`) — used to align an arbitrary local-time window.

Response `fee_records[]`: `region, cloud_service_type, product_spec_desc`(→model), `usage_type`(`input`/`output`/`cached_input_tokens`), `usage`, `unit`(`USD/thousand tokens`), `official_amount`(before discount), `amount`(actual payable), `bill_date`, `consume_time/effective_time`, `trade_time`.

## 5. ShowDetailChart — max/percentile metrics
`POST /v1/{project_id}/maas/monitoring/{service_id}/show-detail-chart`

Region: China-Hong Kong (`ap-southeast-1`). **Rate limit: 1 request / 20s / user.**
Body: `service_type`, `start_time`, `end_time`, `time_granularity`(1 minute /2 hour /3 day; ≤2d minute/hour, 3–7d hour/day, 8–30d day), `timezone`, `infer_type`.

Per-bucket `items[]` (excerpt): `time, request_count, error_count, error_rate, total_token, prompt_token, completion_token, cache_token, cache_hit_ratio, avg_latency, max_latency, p50/p80/p90/p99_latency, avg_ttft, max_ttft, ..., avg_tpot, max_tpot, ..., avg_prompt_token, max_prompt_token, ..., avg_completion_token, max_completion_token, rpm, tpm`.

- `*_latency/ttft/tpot` = ms; `*_token` (incl. `max_*_token`) = thousand tokens.
- Window max = max over buckets of `max_*`; average uses `list-service-statistics` `avg_*`.
- Per-request tokens: avg = `prompt_token*1000/request_count`; max = `max_prompt_token*1000`.

## Auth & signing (SDK-HMAC-SHA256)
`StringToSign = "SDK-HMAC-SHA256\n" + X-Sdk-Date + "\n" + HexEncode(SHA256(CanonicalRequest))`; `Signature = HexEncode(HMAC-SHA256(SK, StringToSign))`; header `Authorization: SDK-HMAC-SHA256 Access=<AK>, SignedHeaders=<content-type;host;x-sdk-date>, Signature=<...>`.
`X-Sdk-Date` = `YYYYMMDD'T'HHMMSS'Z'` (UTC, skew < 15 min). `scripts/maas_statistics.py` implements this; `selftest` verifies against the official example hash `b25362e603ee30f4f25e7858e8a7160fd36e803bb2dfe206278659d71a9bcd7a`.

## Error codes
`400 ModelArts.0104` invalid parameter · `401 APIGW.0301` bad auth (AK/SK/project/region) · `404` unsupported/no resource · `429` rate limited (retry after 60s).
