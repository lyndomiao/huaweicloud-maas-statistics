#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Huawei Cloud MaaS (Model as a Service) invocation statistics and cost.

Auth: HWCLOUD_AK / HWCLOUD_SK (SDK-HMAC-SHA256 signing) or HWCLOUD_TOKEN.
Required: HWCLOUD_PROJECT_ID. Optional: HWCLOUD_REGION (default ap-southeast-1),
MAAS_ENDPOINT, HWCLOUD_AUTH_STYLE. Run `selftest` to verify signing.
"""

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

DEFAULT_REGION = "ap-southeast-1"
DEFAULT_TIMEZONE = "Etc/UTC"  # last-resort fallback; normally the local timezone is auto-detected

# Common Windows time zone IDs -> IANA (extend as needed)
_WIN_TZ_TO_IANA = {
    "E. Africa Standard Time": "Africa/Nairobi",
    "South Africa Standard Time": "Africa/Johannesburg",
    "Egypt Standard Time": "Africa/Cairo",
    "Morocco Standard Time": "Africa/Casablanca",
    "W. Europe Standard Time": "Europe/Berlin",
    "GMT Standard Time": "Europe/London",
    "Romance Standard Time": "Europe/Paris",
    "Central Europe Standard Time": "Europe/Budapest",
    "Russian Standard Time": "Europe/Moscow",
    "Turkey Standard Time": "Europe/Istanbul",
    "Arab Standard Time": "Asia/Riyadh",
    "Arabian Standard Time": "Asia/Dubai",
    "Iran Standard Time": "Asia/Tehran",
    "India Standard Time": "Asia/Kolkata",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "SE Asia Standard Time": "Asia/Bangkok",
    "Singapore Standard Time": "Asia/Singapore",
    "China Standard Time": "Asia/Shanghai",
    "Taipei Standard Time": "Asia/Taipei",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "New Zealand Standard Time": "Pacific/Auckland",
    "UTC": "Etc/UTC",
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
    "SA Pacific Standard Time": "America/Bogota",
    "E. South America Standard Time": "America/Sao_Paulo",
}


def _windows_tz_id():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation") as k:
            return winreg.QueryValueEx(k, "TimeZoneKeyName")[0]
    except Exception:
        return None


def _offset_etc_name():
    """Represent the local UTC offset as an IANA Etc/GMT+-h zone (sign is inverted)."""
    off = datetime.now().astimezone().utcoffset()
    if off is None:
        return "Etc/UTC"
    mins = int(off.total_seconds() // 60)
    if mins % 60:
        return "Etc/UTC"
    h = mins // 60
    return "Etc/UTC" if h == 0 else ("Etc/GMT%+d" % (-h))


def _user_tz_file():
    """Persisted user-timezone file (records the user's current timezone across runs)."""
    return os.environ.get("HWCLOUD_TZ_FILE") or os.path.expanduser(
        "~/.config/huaweicloud-maas/timezone")


def _local_tz_name():
    """Detect the user's current timezone (IANA) used when --timezone is omitted.
    Priority: --timezone/env -> saved user timezone -> OS detection -> UTC offset."""
    for var in ("HWCLOUD_TIMEZONE", "TZ"):
        v = os.environ.get(var)
        if v:
            return v
    fp = _user_tz_file()
    try:
        if fp and os.path.exists(fp):
            with open(fp, encoding="utf-8") as f:
                s = f.read().strip()
            if s:
                return s
    except Exception:
        pass
    try:
        if os.path.exists("/etc/timezone"):
            s = open("/etc/timezone", encoding="utf-8").read().strip()
            if s:
                return s
    except Exception:
        pass
    try:
        p = "/etc/localtime"
        if os.path.islink(p):
            tgt = os.readlink(p)
            if "zoneinfo/" in tgt:
                return tgt.split("zoneinfo/")[-1]
    except Exception:
        pass
    wid = _windows_tz_id()
    if wid and wid in _WIN_TZ_TO_IANA:
        return _WIN_TZ_TO_IANA[wid]
    return _offset_etc_name()

REGION_ENDPOINTS = {
    "ap-southeast-1": "modelarts.ap-southeast-1.myhuaweicloud.com",
    "cn-southwest-2": "modelarts.cn-southwest-2.myhuaweicloud.com",
    "cn-hongkong": "modelarts.cn-hongkong.myhuaweicloud.com",
    "cn-north-4": "modelarts.cn-north-4.myhuaweicloud.com",
    "cn-east-3": "modelarts.cn-east-3.myhuaweicloud.com",
    "cn-south-1": "modelarts.cn-south-1.myhuaweicloud.com",
}

MODEL_TYPES = ["Text Generation", "Video Generation", "Image Generation",
               "Vector Model", "Embedding", "Rerank"]

PIE_PALETTE = [
    (78, 121, 167), (242, 142, 43), (89, 161, 79), (225, 87, 89),
    (118, 183, 178), (237, 201, 72), (176, 122, 161), (255, 157, 167),
    (156, 117, 95), (186, 176, 172), (140, 209, 122), (127, 127, 229),
]


# ---------------------------------------------------------------------------
# Signing (SDK-HMAC-SHA256)
# ---------------------------------------------------------------------------
def _uri_encode(value, safe="~"):
    return urllib.parse.quote(str(value), safe=safe)


def canonical_uri(path):
    if not path:
        return "/"
    segments = urllib.parse.unquote(path).split("/")
    uri = "/".join(_uri_encode(seg) for seg in segments)
    return uri if uri.endswith("/") else uri + "/"


def canonical_query_string(query_params):
    if not query_params:
        return ""
    parts = []
    for key in sorted(query_params.keys()):
        value = query_params[key]
        parts.append(_uri_encode(key) + "=" + _uri_encode("" if value is None else value))
    return "&".join(parts)


def _canonical_and_string_to_sign(method, path, query_params, signed_header_values, payload_hash):
    lower = {k.lower(): str(v).strip() for k, v in signed_header_values.items()}
    signed_headers = ";".join(sorted(lower.keys()))
    canonical_headers = "".join("%s:%s\n" % (k, lower[k]) for k in sorted(lower.keys()))
    canonical_request = (
        method + "\n" + canonical_uri(path) + "\n" + canonical_query_string(query_params) + "\n"
        + canonical_headers + "\n" + signed_headers + "\n" + payload_hash
    )
    hashed = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = "SDK-HMAC-SHA256\n" + lower.get("x-sdk-date", "") + "\n" + hashed
    return canonical_request, string_to_sign, signed_headers


def sign_request(method, url, body_bytes, ak, sk, region=DEFAULT_REGION,
                 service="modelarts", auth_style="access"):
    parts = urllib.parse.urlsplit(url)
    x_sdk_date = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    header_params = {"Host": parts.netloc, "X-Sdk-Date": x_sdk_date}
    if body_bytes:
        header_params["Content-Type"] = "application/json"
    payload_hash = hashlib.sha256(body_bytes or b"").hexdigest()
    query = dict(urllib.parse.parse_qsl(parts.query))
    _, string_to_sign, signed_headers = _canonical_and_string_to_sign(
        method, parts.path, query, header_params, payload_hash)
    signature = hmac.new(sk.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    if str(auth_style).lower() == "credential":
        credential = "%s/%s/%s/%s/sdk_request" % (ak, x_sdk_date[:8], region, service)
        authorization = "SDK-HMAC-SHA256 Credential=%s, SignedHeaders=%s, Signature=%s" % (
            credential, signed_headers, signature)
    else:
        authorization = "SDK-HMAC-SHA256 Access=%s, SignedHeaders=%s, Signature=%s" % (
            ak, signed_headers, signature)
    headers = dict(header_params)
    headers["Authorization"] = authorization
    return headers, x_sdk_date


def _selftest():
    method, path = "GET", "/v1/77b6a44cba5143ab91d13ab9a8ff44fd/vpcs/"
    query = {"limit": "2", "marker": "13551d6b-755d-4757-b956-536f674975c0"}
    headers = {"Content-Type": "application/json", "Host": "service.region.example.com",
               "X-Sdk-Date": "20191115T033655Z"}
    cr, _, signed_headers = _canonical_and_string_to_sign(
        method, path, query, headers, hashlib.sha256(b"").hexdigest())
    got = hashlib.sha256(cr.encode("utf-8")).hexdigest()
    expected = "b25362e603ee30f4f25e7858e8a7160fd36e803bb2dfe206278659d71a9bcd7a"
    print("signed_headers:", signed_headers)
    print("canonical_request_hash:", got)
    print("expected:              ", expected)
    print("SELFTEST:", "PASS" if got == expected else "FAIL")
    return 0 if got == expected else 1


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def _now_ms():
    return int(time.time() * 1000)


def _user_tzinfo(tzname=None):
    if tzname and ZoneInfo is not None:
        try:
            return ZoneInfo(tzname)
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo


def parse_time_ms(value, is_end=False, tzname=None):
    if value is None or value == "":
        return _now_ms() if is_end else _now_ms() - 24 * 3600 * 1000
    s = str(value).strip()
    lower = s.lower()
    if s.isdigit():
        n = int(s)
        return n if n > 10 ** 12 else n * 1000
    m = re.fullmatch(r"(\d+)\s*([smhdw])", lower)
    if m:
        seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[m.group(2)] * int(m.group(1))
        return _now_ms() - seconds * 1000
    now = datetime.now(_user_tzinfo(tzname))
    if lower == "now":
        return _now_ms()
    if lower == "today":
        base = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(base.timestamp() * 1000) if not is_end else _now_ms()
    if lower == "yesterday":
        base = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = base + timedelta(days=1) - timedelta(milliseconds=1)
        return int((end if is_end else base).timestamp() * 1000)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo)
        return int(dt.timestamp() * 1000)
    except ValueError:
        raise SystemExit("Cannot parse time: %r (use epoch ms, ISO8601, 24h/7d, today/yesterday)" % value)


def _fmt_ms(ms, tzname=None):
    try:
        return datetime.fromtimestamp(ms / 1000, _user_tzinfo(tzname)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ms)


# ---------------------------------------------------------------------------
# HTTP / config
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status, code, msg, body=None):
        super().__init__("HTTP %s: %s %s" % (status, code, msg))
        self.status, self.code, self.msg, self.body = status, code, msg, body


class Config:
    def __init__(self, args):
        self.ak = os.environ.get("HWCLOUD_AK") or os.environ.get("HUAWEICLOUD_SDK_AK")
        self.sk = os.environ.get("HWCLOUD_SK") or os.environ.get("HUAWEICLOUD_SDK_SK")
        self.token = os.environ.get("HWCLOUD_TOKEN") or os.environ.get("MAAS_TOKEN")
        self.project_id = args.project_id or os.environ.get("HWCLOUD_PROJECT_ID")
        self.region = args.region or os.environ.get("HWCLOUD_REGION") or DEFAULT_REGION
        self.timezone = args.timezone or _local_tz_name()
        self.auth_style = os.environ.get("HWCLOUD_AUTH_STYLE", "access")
        self.endpoint = (args.endpoint or os.environ.get("MAAS_ENDPOINT")
                         or REGION_ENDPOINTS.get(self.region)
                         or ("modelarts.%s.myhuaweicloud.com" % self.region))
        self.dry_run = getattr(args, "dry_run", False)

    def require(self, need_project=True):
        if need_project and not self.project_id:
            raise SystemExit("Missing project ID: set HWCLOUD_PROJECT_ID or pass --project-id.")
        if not self.token and not (self.ak and self.sk):
            raise SystemExit("Missing credentials: set HWCLOUD_AK / HWCLOUD_SK, or HWCLOUD_TOKEN.")


def call_api(cfg, path, body, method="POST"):
    url = "https://%s%s" % (cfg.endpoint, path)
    body_bytes = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if body is not None else b""
    if cfg.token:
        headers = {"Host": urllib.parse.urlsplit(url).netloc, "X-Auth-Token": cfg.token}
        if body_bytes:
            headers["Content-Type"] = "application/json"
    else:
        headers, _ = sign_request(method, url, body_bytes, cfg.ak, cfg.sk,
                                  region=cfg.region, service="modelarts", auth_style=cfg.auth_style)
    if cfg.dry_run:
        print("[dry-run] %s %s" % (method, url))
        for k in ("Host", "X-Auth-Token", "X-Sdk-Date", "Content-Type", "Authorization"):
            if k in headers:
                v = headers[k]
                if k in ("X-Auth-Token", "Authorization") and len(v) > 20:
                    v = v[:20] + "..."
                print("  %s: %s" % (k, v))
        if body_bytes:
            print("  body: " + body_bytes.decode("utf-8"))
        return {"_dry_run": True}
    req = urllib.request.Request(url, data=body_bytes or None, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        code, msg = None, raw
        try:
            obj = json.loads(raw)
            code = obj.get("error_code")
            msg = obj.get("error_msg") or obj
        except Exception:
            pass
        hint = ""
        if e.code == 429:
            hint = " (rate limited: ~200 req/min/user, wait 60s and retry)"
        elif e.code in (401, 403):
            hint = " (auth failed: check AK/SK, project_id, region, or use HWCLOUD_TOKEN)"
        raise ApiError(e.code, code, "%s%s" % (msg, hint), raw)
    except urllib.error.URLError as e:
        raise ApiError(-1, "NetworkError",
                       "Cannot reach %s: %s (try --dry-run to inspect the request)" % (cfg.endpoint, e.reason))


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------
def _service_type_list(value):
    if str(value).lower() in ("all", "both"):
        return [2, 4]
    try:
        return [int(value)]
    except ValueError:
        raise SystemExit("--service-type supports only 2, 4, or all")


def _st_label(st):
    return {2: "Preset services (2)", 4: "Custom endpoints (4)"}.get(st, str(st))


def cmd_summary(cfg, args):
    start = parse_time_ms(args.start, False, cfg.timezone) if args.start else parse_time_ms(args.last, False, cfg.timezone)
    end = parse_time_ms(args.end, True, cfg.timezone) if args.end else _now_ms()
    _validate_range(start, end)
    all_json = []
    for st in _service_type_list(args.service_type):
        body = {"service_type": st, "start_time": start, "end_time": end,
                "timezone": cfg.timezone, "infer_type": args.infer_type}
        if args.api_keys:
            body["api_keys"] = args.api_keys
        if args.ips:
            body["ips"] = args.ips
        if args.model_type:
            body["model_type"] = args.model_type
        data = call_api(cfg, "/v1/%s/maas/monitoring/show-statistics" % cfg.project_id, body)
        if cfg.dry_run:
            return 0
        all_json.append({"service_type": st, "data": data})
        if args.json:
            continue
        _print_summary(st, data, start, end, cfg.timezone, _local_tz_note(args))
    if args.json:
        print(json.dumps(all_json if len(all_json) > 1 else all_json[0]["data"],
                         ensure_ascii=False, indent=2))
    return 0


def _print_summary(st, d, start, end, tz, tz_note=None):
    req = d.get("total_request_count", 0) or 0
    err = d.get("total_error_count", 0) or 0
    rate = (err / req * 100) if req else 0.0
    print("=" * 60)
    print("Huawei Cloud MaaS summary — %s" % _st_label(st))
    print("=" * 60)
    print("Time range: %s ~ %s (%s)" % (_fmt_ms(start, tz), _fmt_ms(end, tz), tz))
    if tz_note:
        print(tz_note)
    print("Total requests: %s" % req)
    print("Total errors: %s  (error rate %.2f%%)" % (err, rate))
    print("Total tokens : %s M" % _mtok(d.get("total_token")))
    print("  Input tokens : %s M" % _mtok(d.get("total_prompt_token")))
    print("  Output tokens: %s M" % _mtok(d.get("total_completion_token")))
    if d.get("total_infer_count"):
        print("Batch inference total: %s" % d.get("total_infer_count"))
    if d.get("total_completion_tasks"):
        print("Completed batch tasks: %s" % d.get("total_completion_tasks"))
    if d.get("video_generate_duration"):
        print("Video generation duration (s): %s" % _num(d.get("video_generate_duration")))
    if d.get("image_generate_nums"):
        print("Generated images: %s" % d.get("image_generate_nums"))
    print("")


def cmd_services(cfg, args):
    if args.start:
        start = parse_time_ms(args.start, False, cfg.timezone)
    elif getattr(args, "days", None):
        start = _now_ms() - int(float(args.days) * 86400000)
    else:
        start = parse_time_ms(args.last, False, cfg.timezone)
    end = parse_time_ms(args.end, True, cfg.timezone) if args.end else _now_ms()
    _validate_range(start, end)

    all_items = []
    for st in _service_type_list(args.service_type):
        offset = args.offset or 0
        page_limit = args.limit if args.limit is not None else 100
        page = 0
        while True:
            body = {"start_time": start, "end_time": end, "service_type": st,
                    "infer_type": args.infer_type, "limit": page_limit,
                    "offset": offset, "timezone": cfg.timezone}
            names = list(args.service_names or [])
            if getattr(args, "models", None):
                names += list(args.models)
            if names:
                body["service_names"] = names
            if args.api_keys:
                body["api_keys"] = args.api_keys
            if args.ips:
                body["ips"] = args.ips
            if args.model_type:
                body["model_type"] = args.model_type
            data = call_api(cfg, "/v1/%s/maas/monitoring/list-service-statistics" % cfg.project_id, body)
            if cfg.dry_run:
                return 0
            items = data.get("items") or []
            for it in items:
                it["_service_type"] = st
            all_items.extend(items)
            fetched = offset + len(items)
            need_more = args.all and items and data.get("total") is not None and fetched < data.get("total")
            page += 1
            if need_more and page < 100:
                offset = fetched
                if page_limit == 0:
                    break
                continue
            break

    if args.json:
        print(json.dumps(all_items, ensure_ascii=False, indent=2))
        return 0

    show_latency = getattr(args, "latency", False)
    if (show_latency or getattr(args, "token_size", False)) and not getattr(args, "no_max", False):
        _enrich_max(cfg, all_items, start, end, cfg.timezone, args.infer_type)

    cost_map = {}
    if not getattr(args, "no_cost", False) and all_items:
        try:
            cost_map = _billing_costs_for_window(cfg, getattr(args, "region", None), start, end)
        except Exception as e:  # noqa
            print("(cost lookup failed: %s)" % e, file=sys.stderr)

    print("=" * 60)
    print("Huawei Cloud MaaS per-model statistics (%d rows)" % len(all_items))
    print("Time range: %s ~ %s (%s)" % (_fmt_ms(start, cfg.timezone), _fmt_ms(end, cfg.timezone), cfg.timezone))
    _tznote = _local_tz_note(args)
    if _tznote:
        print(_tznote)
    print("=" * 60)
    if not all_items:
        print("(No data. Check the time range, service_type and region, or that traffic exists.)")
        return 0
    _print_services_table(all_items, token_size=getattr(args, "token_size", False),
                          cost_map=cost_map, show_latency=show_latency)
    print("")
    print("Note: tokens are in millions (M); cost (USD) = actual charged amount for the same window.")
    if not show_latency:
        print("Hint: query average/max end-to-end latency, average/max TTFT and average/max TPOT too? "
              "(add --latency)")

    if not getattr(args, "no_chart", False) and all_items:
        try:
            for p in _render_two_pies(all_items, cost_map):
                print("Chart saved: %s" % p)
        except Exception as e:  # noqa
            print("(chart generation failed: %s)" % e, file=sys.stderr)
    return 0


def _billing_costs_for_window(cfg, region, start_ms, end_ms):
    """Return {model_lower: {"amount":x,"official":y}} for [start_ms,end_ms) using hourly detail."""
    bss = default_bss_endpoint()
    bj = timezone(timedelta(hours=8))
    bstart = datetime.fromtimestamp(start_ms / 1000.0, timezone.utc).astimezone(bj)
    bend = datetime.fromtimestamp(end_ms / 1000.0, timezone.utc).astimezone(bj)
    cycle = bstart.strftime("%Y-%m")
    if bend.strftime("%Y-%m") != cycle:
        return {}
    base = {"cycle": cycle, "statistic_type": 3, "cloud_service_type": "hws.service.type.modelarts",
            "bill_date_begin": bstart.strftime("%Y-%m-%d"), "bill_date_end": bend.strftime("%Y-%m-%d")}
    if region:
        base["region"] = region
    recs, _ = _fetch_fee_records(cfg, bss, base)
    agg = {}
    for r in recs or []:
        if not _is_token_record(r):
            continue
        hs = _hour_start(r)
        if hs is None:
            continue
        ms = hs.timestamp() * 1000.0
        if ms < start_ms or ms >= end_ms:
            continue
        name = _extract_model_name(r).lower()
        a = agg.setdefault(name, {"amount": 0.0, "official": 0.0})
        a["amount"] += float(r.get("amount") or 0)
        a["official"] += float(r.get("official_amount") or 0)
    return agg


def _load_font(size):
    from PIL import ImageFont
    for name in ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf",
                 "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _draw_donut(data, title, path, unit="", value_fmt="%.2f", total_label="Total"):
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return False
    W, H = 680, 400
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_title, f_text, f_center = _load_font(20), _load_font(14), _load_font(13)
    d.text((24, 16), title, fill=(33, 37, 41), font=f_title)
    data = [(n, v) for n, v in data if v and v > 0]
    total = sum(v for _, v in data)
    cx, cy, r = 170, 225, 135
    inner = r * 0.62
    if not data or total <= 0:
        d.text((cx - 24, cy), "No data", fill=(120, 120, 120), font=f_text)
        img.save(path)
        return True
    start = -90.0
    for i, (n, v) in enumerate(data):
        ang = v / total * 360.0
        d.pieslice([cx - r, cy - r, cx + r, cy + r], start=start, end=start + ang,
                   fill=PIE_PALETTE[i % len(PIE_PALETTE)], outline="white", width=2)
        start += ang
    d.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], fill="white")
    d.text((cx - 26, cy - 14), total_label, fill=(90, 90, 90), font=f_center)
    d.text((cx - 46, cy + 4), (value_fmt % total) + unit, fill=(33, 37, 41), font=f_center)
    y = 60
    for i, (n, v) in enumerate(data):
        d.rectangle([365, y + 2, 383, y + 18], fill=PIE_PALETTE[i % len(PIE_PALETTE)])
        d.text((390, y), "%s  %.1f%%" % (str(n)[:20], v / total * 100), fill=(33, 37, 41), font=f_text)
        d.text((575, y), value_fmt % v, fill=(90, 90, 90), font=f_text)
        y += 22
    img.save(path)
    return True


def _render_two_pies(items, cost_map):
    """Two donut charts: token total share and cost share. Returns list of file paths."""
    tok = [(it.get("service_name", ""), float(it.get("total_token") or 0) / 1000.0) for it in items]
    cost = []
    for it in items:
        nm = (it.get("service_name") or "").strip().lower()
        c = (cost_map or {}).get(nm, {}).get("amount", 0.0)
        if c and c > 0:
            cost.append((it.get("service_name", ""), float(c)))
    out_dir = os.path.join(os.getcwd(), "maas_charts")
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    p1 = os.path.join(out_dir, "token_donut_%s.png" % ts)
    p2 = os.path.join(out_dir, "cost_donut_%s.png" % ts)
    ok1 = _draw_donut(tok, "Token Total Share", p1, unit=" M tokens", total_label="Total")
    ok2 = _draw_donut(cost, "Cost Share (USD)", p2, unit=" USD", total_label="Total")
    return [p for p, ok in ((p1, ok1), (p2, ok2)) if ok]


def _enrich_max(cfg, items, start, end, tzname, infer_type):
    """Per-service show-detail-chart: max of each bucket (max_latency/max_ttft/max_tpot/max_*_token)."""
    if not items:
        return
    gran = 2 if (end - start) / 86400000.0 <= 7 else 3
    todo = [it for it in items if it.get("service_id")]
    if len(todo) > 1:
        print("(max/detail metrics require show-detail-chart per service, rate-limited to 1 req/20s; "
              "%d services, ~%d s)" % (len(todo), (len(todo) - 1) * 21), file=sys.stderr)
    first = True
    for it in todo:
        if not first:
            time.sleep(21)
        first = False
        body = {"service_type": it.get("_service_type", 2), "start_time": start, "end_time": end,
                "time_granularity": gran, "timezone": tzname, "infer_type": infer_type}
        try:
            data = call_api(cfg, "/v1/%s/maas/monitoring/%s/show-detail-chart"
                            % (cfg.project_id, it["service_id"]), body)
        except Exception as e:  # noqa
            it["_max_err"] = str(e)
            continue
        buckets = data.get("items") or []

        def mx(k):
            vals = [b.get(k) for b in buckets if b.get(k) is not None]
            return max(vals) if vals else None

        for key in ("max_latency", "max_ttft", "max_tpot", "max_prompt_token", "max_completion_token"):
            it[key] = mx(key)


def _print_services_table(items, token_size=False, cost_map=None, show_latency=False):
    def cache(x):
        r = x.get("cache_hit_ratio")
        if r is None:
            return "-"
        try:
            return "%.2f%%" % float(r)
        except (TypeError, ValueError):
            return "-"

    def per_req(tot_k, req):
        if not req:
            return "-"
        try:
            return "%.0f" % (float(tot_k) * 1000.0 / req)
        except (TypeError, ValueError):
            return "-"

    def max_tok(k):
        if k is None:
            return "-"
        try:
            return "%.0f" % (float(k) * 1000.0)
        except (TypeError, ValueError):
            return "-"

    def cost(x):
        c = (cost_map or {}).get((x.get("service_name") or "").strip().lower())
        return "%.2f" % c.get("amount", 0.0) if c else "-"

    cols = [
        ("Model", 26, lambda x: str(x.get("service_name", ""))),
        ("Requests", 10, lambda x: _num(x.get("request_count"))),
        ("Error %", 9, lambda x: _pct(x)),
        ("Input(M)", 11, lambda x: _mtok(x.get("prompt_token"))),
        ("Output(M)", 11, lambda x: _mtok(x.get("completion_token"))),
        ("Total(M)", 11, lambda x: _mtok(x.get("total_token"))),
        ("Cache Hit", 10, cache),
        ("Cost(USD)", 10, cost),
    ]
    if show_latency:
        cols += [
            ("Avg E2E(ms)", 12, lambda x: _num(x.get("avg_latency"))),
            ("Max E2E(ms)", 12, lambda x: _num(x.get("max_latency"))),
            ("Avg TTFT(ms)", 13, lambda x: _num(x.get("avg_ttft"))),
            ("Max TTFT(ms)", 13, lambda x: _num(x.get("max_ttft"))),
            ("Avg TPOT(ms)", 13, lambda x: _num(x.get("avg_tpot"))),
            ("Max TPOT(ms)", 13, lambda x: _num(x.get("max_tpot"))),
        ]
    if token_size:
        cols += [
            ("Avg In Tok", 11, lambda x: per_req(x.get("prompt_token"), x.get("request_count"))),
            ("Max In Tok", 11, lambda x: max_tok(x.get("max_prompt_token"))),
            ("Avg Out Tok", 12, lambda x: per_req(x.get("completion_token"), x.get("request_count"))),
            ("Max Out Tok", 12, lambda x: max_tok(x.get("max_completion_token"))),
        ]
    header = "  ".join(_pad(name, w) for name, w, _ in cols)
    print(header)
    print("-" * len(header))
    for it in items:
        print("  ".join(_pad(fn(it), w) for _, w, fn in cols))


def cmd_ips(cfg, args):
    start = parse_time_ms(args.start, False, cfg.timezone) if args.start else parse_time_ms(args.last, False, cfg.timezone)
    end = parse_time_ms(args.end, True, cfg.timezone) if args.end else _now_ms()
    _validate_range(start, end)
    results = []
    for st in _service_type_list(args.service_type):
        offset = args.offset or 0
        page_limit = args.limit if args.limit is not None else 100
        page = 0
        while True:
            body = {"service_type": st, "start_time": start, "end_time": end,
                    "timezone": cfg.timezone, "limit": page_limit, "offset": offset}
            if args.ip_search:
                body["ip_search"] = args.ip_search
            if args.service_id:
                body["service_id"] = args.service_id
            if args.api_keys:
                body["api_keys"] = args.api_keys
            data = call_api(cfg, "/v1/%s/maas/monitoring/source-ips" % cfg.project_id, body)
            if cfg.dry_run:
                return 0
            items = data.get("items") or []
            results.append({"service_type": st, "total": data.get("total"), "items": items})
            fetched = offset + len(items)
            need_more = args.all and items and fetched < (data.get("total") or 0)
            page += 1
            if need_more and page < 100:
                offset = fetched
                if page_limit == 0:
                    break
                continue
            break
    if args.json:
        print(json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False, indent=2))
        return 0
    print("=" * 60)
    print("Huawei Cloud MaaS caller source IPs")
    print("Time range: %s ~ %s (%s)" % (_fmt_ms(start, cfg.timezone), _fmt_ms(end, cfg.timezone), cfg.timezone))
    _tznote = _local_tz_note(args)
    if _tznote:
        print(_tznote)
    print("=" * 60)
    for r in results:
        print("[%s] total %s IPs:" % (_st_label(r["service_type"]), r.get("total")))
        if not r["items"]:
            print("  (none)")
        for ip in r["items"]:
            print("  - %s" % ip)
        print("")
    return 0


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------
def _validate_range(start, end):
    if end < start:
        raise SystemExit("End time cannot be earlier than start time.")
    if end - start > 30 * 24 * 3600 * 1000:
        raise SystemExit("Start and end must be within 30 days.")


def _num(v):
    if v is None:
        return "-"
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else ("%g" % f)
    except (TypeError, ValueError):
        return str(v)


def _mtok(k):
    """thousand tokens -> million tokens string."""
    if k is None:
        return "-"
    try:
        return "%.3f" % (float(k) / 1000.0)
    except (TypeError, ValueError):
        return "-"


def _pct(x):
    if x.get("error_rate") is not None:
        try:
            return "%.2f%%" % (float(x["error_rate"]) * 100)
        except (TypeError, ValueError):
            pass
    req, err = x.get("request_count") or 0, x.get("error_count") or 0
    return "%.2f%%" % ((err / req * 100) if req else 0.0)


def _pad(s, width):
    s = str(s)
    disp = sum(2 if ord(c) > 127 else 1 for c in s)
    if disp > width:
        out, w = "", 0
        for c in s:
            cw = 2 if ord(c) > 127 else 1
            if w + cw > width:
                break
            out += c
            w += cw
        return out + " " * max(0, width - w)
    return s + " " * (width - disp)


# ---------------------------------------------------------------------------
# Billing (OCE res-fee-records)
# ---------------------------------------------------------------------------
def default_bss_endpoint():
    return os.environ.get("MAAS_BSS_ENDPOINT") or "bss-intl.myhuaweicloud.com"


def _billing_get(cfg, url):
    if cfg.token:
        headers = {"Host": urllib.parse.urlsplit(url).netloc, "X-Auth-Token": cfg.token}
    else:
        headers, _ = sign_request("GET", url, b"", cfg.ak, cfg.sk,
                                  region=cfg.region, service="bss", auth_style=cfg.auth_style)
    if cfg.dry_run:
        print("[dry-run] GET %s" % url)
        for k in ("Host", "X-Auth-Token", "X-Sdk-Date", "Authorization"):
            if k in headers:
                v = headers[k]
                if k in ("X-Auth-Token", "Authorization") and len(v) > 20:
                    v = v[:20] + "..."
                print("  %s: %s" % (k, v))
        return {"_dry_run": True}
    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        code = msg = None
        try:
            o = json.loads(raw)
            code, msg = o.get("error_code"), o.get("error_msg")
        except Exception:
            msg = raw
        hint = (" (auth failed: check AK/SK; intl uses bss-intl.myhuaweicloud.com, "
                "China uses bss.myhuaweicloud.com)") if e.code in (401, 403) else ""
        raise ApiError(e.code, code, "%s%s" % (msg, hint), raw)
    except urllib.error.URLError as e:
        raise ApiError(-1, "NetworkError",
                       "Cannot reach %s: %s" % (urllib.parse.urlsplit(url).netloc, e.reason))


def _extract_model_name(rec):
    s = rec.get("product_spec_desc") or rec.get("product_name") or ""
    # model name is the ASCII prefix; drop any non-ASCII suffix (e.g. localized spec text)
    s = re.sub(r"[^\x20-\x7e].*$", "", s).strip()
    return s or "(unknown model)"


def _is_token_record(rec):
    if rec.get("cloud_service_type") != "hws.service.type.modelarts":
        return False
    if "token" in str(rec.get("unit", "")).lower():
        return True
    return rec.get("usage_type") in ("input", "output", "cached_input_tokens")


def _resolve_tz(name):
    if name:
        if ZoneInfo is None:
            raise SystemExit("zoneinfo/tzdata unavailable; use a fixed offset or install tzdata.")
        return ZoneInfo(name)
    return datetime.now().astimezone().tzinfo


def _parse_local_dt(s, tzinfo):
    s = (s or "").strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=tzinfo)
    except ValueError:
        pass
    d = datetime.fromisoformat(s)
    return d.replace(tzinfo=tzinfo) if d.tzinfo is None else d


def _fmt_tz(tzinfo):
    try:
        off = tzinfo.utcoffset(datetime.now())
    except Exception:
        off = None
    if off is None:
        return str(tzinfo)
    total = int(off.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return "UTC%s%02d:%02d" % (sign, total // 3600, (total % 3600) // 60)


def _local_tz_note(args):
    """Return a notice when no timezone was specified (so the local timezone is used)."""
    if (getattr(args, "timezone", None)
            or os.environ.get("HWCLOUD_TIMEZONE")
            or os.environ.get("TZ")):
        return None
    return "Note: no timezone specified; using detected user timezone %s (%s)." % (
        _local_tz_name(), _fmt_tz(_user_tzinfo(_local_tz_name())))


def _fetch_fee_records(cfg, bss, base_params):
    records, offset, obj = [], 0, {}
    while True:
        params = dict(base_params)
        params["limit"], params["offset"] = 200, offset
        url = "https://%s/v2/bills/customer-bills/res-fee-records?%s" % (
            bss, urllib.parse.urlencode(params))
        obj = _billing_get(cfg, url)
        if cfg.dry_run:
            return None, None
        recs = obj.get("fee_records") or []
        records.extend(recs)
        total = obj.get("total_count", 0)
        offset += len(recs)
        if offset >= total or not recs:
            break
    return records, (obj.get("currency") or "USD")


def _hour_start(rec):
    ct = rec.get("consume_time") or rec.get("effective_time") or ""
    s = (ct.split("Z-")[0] + "Z") if "Z-" in ct else ct
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def cmd_billing(cfg, args):
    bss = args.bss_endpoint or default_bss_endpoint()
    window_mode = bool(args.date or args.start or args.end)
    if window_mode:
        tzinfo = _resolve_tz(args.timezone or _local_tz_name())
        if args.date:
            begin = _parse_local_dt(args.date, tzinfo)
            end = begin + timedelta(days=1)
        elif args.start:
            begin = _parse_local_dt(args.start, tzinfo)
            if args.end:
                end = _parse_local_dt(args.end, tzinfo)
                if end <= begin:
                    end += timedelta(days=1)
            else:
                end = begin + timedelta(days=1)
        else:
            end = _parse_local_dt(args.end, tzinfo)
            begin = end.replace(hour=0, minute=0, second=0, microsecond=0)
            end = begin + timedelta(days=1)
        begin_utc, end_utc = begin.astimezone(timezone.utc), end.astimezone(timezone.utc)
        bj = timezone(timedelta(hours=8))
        bstart, bend = begin_utc.astimezone(bj), end_utc.astimezone(bj)
        cycle = bstart.strftime("%Y-%m")
        if bend.strftime("%Y-%m") != cycle:
            print("Billing is queried per calendar month (Beijing time); window must stay within one month.",
                  file=sys.stderr)
            return 2
        base = {"cycle": cycle, "statistic_type": 3, "cloud_service_type": "hws.service.type.modelarts",
                "bill_date_begin": bstart.strftime("%Y-%m-%d"), "bill_date_end": bend.strftime("%Y-%m-%d")}
        if args.region:
            base["region"] = args.region
        records, currency = _fetch_fee_records(cfg, bss, base)
        if cfg.dry_run:
            return 0
        token_recs = [r for r in records if _is_token_record(r)
                      and _hour_start(r) is not None and begin_utc <= _hour_start(r) < end_utc]
    else:
        cycle = args.cycle or datetime.now().strftime("%Y-%m")
        base = {"cycle": cycle, "statistic_type": 2, "cloud_service_type": "hws.service.type.modelarts"}
        if args.region:
            base["region"] = args.region
        records, currency = _fetch_fee_records(cfg, bss, base)
        if cfg.dry_run:
            return 0
        token_recs = [r for r in records if _is_token_record(r)]

    agg = {}
    for r in token_recs:
        name = _extract_model_name(r)
        a = agg.setdefault(name, {"input": 0.0, "output": 0.0, "cached": 0.0,
                                  "official": 0.0, "amount": 0.0})
        ut, u = r.get("usage_type"), float(r.get("usage") or 0)
        if ut in ("input", "output", "cached_input_tokens"):
            a[{"input": "input", "output": "output", "cached_input_tokens": "cached"}[ut]] += u
        a["official"] += float(r.get("official_amount") or 0)
        a["amount"] += float(r.get("amount") or 0)

    if args.json:
        meta = {"cycle": cycle, "currency": currency, "models": agg}
        if window_mode:
            meta.update({"grain": "hour", "timezone": _fmt_tz(tzinfo),
                         "local_window_begin": begin.isoformat(), "local_window_end": end.isoformat(),
                         "utc_window_begin": begin_utc.isoformat(), "utc_window_end": end_utc.isoformat()})
        else:
            meta.update({"grain": "day", "time_basis": "Asia/Shanghai"})
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0

    print("=" * 66)
    print("Huawei Cloud MaaS model cost (official resource consumption records)")
    if window_mode:
        print("Local window: %s ~ %s (%s)" % (
            begin.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"), _fmt_tz(tzinfo)))
        print("As UTC: %s ~ %s (hourly detail)" % (
            begin_utc.strftime("%Y-%m-%d %H:%M"), end_utc.strftime("%Y-%m-%d %H:%M")))
        _tznote = _local_tz_note(args)
        if _tznote:
            print(_tznote)
    else:
        print("Cycle: %s (whole month, daily by Beijing time)" % cycle)
    print("Region: %s  Currency: %s  Detail records %d, model-token records in window %d"
          % (args.region or "all", currency, len(records), len(token_recs)))
    print("=" * 66)
    if not agg:
        print("(No MaaS model token billing records in window. Possible: no token billing, "
              "billing latency, or wrong region/cycle.)")
        return 0
    rows = sorted(agg.items(), key=lambda kv: kv[1]["amount"], reverse=True)
    cols = [
        ("Model", 28, lambda n, v: n),
        ("Input(M)", 11, lambda n, v: _mtok(v["input"])),
        ("Output(M)", 11, lambda n, v: _mtok(v["output"])),
        ("Cached(M)", 11, lambda n, v: _mtok(v["cached"])),
        ("Official(USD)", 13, lambda n, v: "%.2f" % v["official"]),
    ]
    header = "  ".join(_pad(c[0], c[1]) for c in cols)
    print(header)
    print("-" * len(header))
    ti = to = tc = toff = 0.0
    for n, v in rows:
        print("  ".join(_pad(c[2](n, v), c[1]) for c in cols))
        ti += v["input"]; to += v["output"]; tc += v["cached"]; toff += v["official"]
    print("-" * len(header))
    print(_pad("Total", 28) + "  " + _pad(_mtok(ti), 11) + "  " + _pad(_mtok(to), 11) + "  "
          + _pad(_mtok(tc), 11) + "  " + _pad("%.2f" % toff, 13))
    print("")
    print("Note: official price = before discount (official_amount), unit %s; input excludes cached; "
          "tokens in millions (M)." % currency)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--region", help="Region (default ap-southeast-1)")
    common.add_argument("--project-id", help="Project ID (or HWCLOUD_PROJECT_ID)")
    common.add_argument("--endpoint", help="Override MaaS endpoint host")
    common.add_argument("--timezone", help="Timezone (default: your local timezone)")
    common.add_argument("--dry-run", action="store_true", help="Print the signed request only, no network")

    p = argparse.ArgumentParser(prog="maas_statistics.py",
                                description="Huawei Cloud MaaS (Model as a Service) invocation statistics",
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def add_time(sp):
        sp.add_argument("--start", help="Start time (epoch ms / ISO8601 / today / yesterday)")
        sp.add_argument("--end", help="End time (default now)")
        sp.add_argument("--last", default="24h", help="Relative window like 24h/7d/30d (default 24h)")

    def add_common(sp):
        sp.add_argument("--service-type", default="2", help="2 preset / 4 custom / all (default 2)")
        sp.add_argument("--infer-type", default="real_time", choices=["real_time", "batch"],
                        help="Inference type (default real_time)")
        sp.add_argument("--model-type", choices=MODEL_TYPES, help="Model type")
        sp.add_argument("--json", action="store_true", help="Print raw JSON")

    sp_s = sub.add_parser("summary", help="Aggregate statistics", parents=[common])
    add_time(sp_s); add_common(sp_s)
    sp_s.add_argument("--api-keys", nargs="*", help="Filter by API Key label")
    sp_s.add_argument("--ips", nargs="*", help="Filter by client source IP")
    sp_s.set_defaults(func=cmd_summary)

    sp_v = sub.add_parser("services", help="Per-model statistics", parents=[common])
    add_time(sp_v); add_common(sp_v)
    sp_v.add_argument("--service-names", nargs="*", help="Filter by service name (fuzzy)")
    sp_v.add_argument("--api-keys", nargs="*", help="Filter by API Key label")
    sp_v.add_argument("--ips", nargs="*", help="Filter by client source IP")
    sp_v.add_argument("--limit", type=int, default=100, help="Page size (0 = all, default 100)")
    sp_v.add_argument("--offset", type=int, default=0, help="Pagination offset (default 0)")
    sp_v.add_argument("--all", action="store_true", help="Auto-paginate all data")
    sp_v.add_argument("--no-max", action="store_true", help="Skip show-detail-chart max metrics")
    sp_v.add_argument("--token-size", action="store_true", help="Also show avg/max input/output tokens per request")
    sp_v.add_argument("--latency", action="store_true",
                      help="Show avg/max end-to-end latency, avg/max TTFT, avg/max TPOT (default hidden)")
    sp_v.add_argument("--no-cost", action="store_true", help="Skip the cost (USD) column")
    sp_v.add_argument("--no-chart", action="store_true", help="Do not generate the two donut charts")
    sp_v.add_argument("--days", type=float, default=None, help="Last N days (alternative to --start)")
    sp_v.add_argument("--models", nargs="*", default=None, help="Filter by model name(s), fuzzy")
    sp_v.set_defaults(func=cmd_services)

    sp_i = sub.add_parser("ips", help="Caller source IP list", parents=[common])
    add_time(sp_i); add_common(sp_i)
    sp_i.add_argument("--ip-search", help="IP prefix search like 192.168")
    sp_i.add_argument("--service-id", help="Filter by service ID")
    sp_i.add_argument("--api-keys", nargs="*", help="Filter by API Key label")
    sp_i.add_argument("--limit", type=int, default=100, help="Page size (default 100)")
    sp_i.add_argument("--offset", type=int, default=0, help="Pagination offset (default 0)")
    sp_i.add_argument("--all", action="store_true", help="Auto-paginate all data")
    sp_i.set_defaults(func=cmd_ips)

    sp_b = sub.add_parser("billing", help="Per-model real cost (official bill)", parents=[common])
    sp_b.add_argument("--cycle", help="Billing cycle YYYY-MM (whole month)")
    sp_b.add_argument("--date", help="Single local day YYYY-MM-DD")
    sp_b.add_argument("--start", help="Start date YYYY-MM-DD")
    sp_b.add_argument("--end", help="End date YYYY-MM-DD")
    sp_b.add_argument("--bss-endpoint", help="Billing endpoint (intl bss-intl.myhuaweicloud.com)")
    sp_b.add_argument("--json", action="store_true", help="Print JSON")
    sp_b.set_defaults(func=cmd_billing)

    sub.add_parser("selftest", help="Verify signing (official example)").set_defaults(
        func=lambda c, a: _selftest())
    return p


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args()
    if args.command == "selftest":
        sys.exit(_selftest())
    try:
        cfg = Config(args)
        if not args.dry_run:
            cfg.require(need_project=(args.command != "billing"))
        else:
            if not cfg.project_id:
                cfg.project_id = "<PROJECT_ID>"
            if not cfg.token and not (cfg.ak and cfg.sk):
                cfg.ak, cfg.sk = "<AK>", "<SK>"
        return args.func(cfg, args)
    except ApiError as e:
        print("Request failed: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main() or 0)
