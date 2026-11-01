# Security

This document describes the security model of **huaweicloud-maas-statistics** and how to deploy it safely.

## Security model (by design)

- **No third-party dependencies.** The CLI uses the Python 3 standard library only. There is no package supply chain to trust beyond the Python runtime.
- **AK/SK is used locally for signing only.** Requests are signed with `SDK-HMAC-SHA256`. The secret key never leaves the machine and is never placed in a request: the `Authorization` header contains only the access key ID and the computed signature.
- **HTTPS to Huawei Cloud endpoints only.** All network calls go to `https://*.myhuaweicloud.com` (ModelArts / IAM / `bss-intl` billing). There is no telemetry, no third-party endpoint, and no data exfiltration.
- **Read-only.** The tool only calls statistics and billing *query* APIs. It does not create, modify, or delete any cloud resource. Its only local outputs are PNG charts under `./maas_charts/`.
- **Secrets are not printed.** `--dry-run` shows the signed request with `Authorization` redacted as `***`; the secret key is never logged.

## Credential handling (important)

The secret key (SK) is a long-lived credential. How you store it dominates the real risk:

1. **Preferred: do not persist it.** Inject `HWCLOUD_AK` / `HWCLOUD_SK` from a secret manager (HashiCorp Vault, cloud KMS/Secrets Manager, CI secret store) or the OS environment at run time.
2. **Optional local file: `~/.config/huaweicloud-maas/credentials.json`.** If present, the CLI reads `{ak, sk, project_id, region}` from it. This file is **plaintext** and is protected only by filesystem permissions (`0600` on POSIX, an ACL restricted to the current user on Windows). Do **not** place it on shared machines, network drives, or cloud-sync folders. For stronger at-rest protection, wrap it with an OS keystore — **Windows DPAPI**, **macOS Keychain**, or **Linux Secret Service** — rather than a self-managed symmetric key (a key stored next to the ciphertext provides no real protection).
3. **Never** commit `credentials.json`, `.env`, or any key material to version control, and never paste an SK into chats, tickets, or logs.
4. **Rotate** the access key periodically and delete keys that are no longer used.

## Recommended IAM setup (least privilege)

Create a **dedicated IAM user used only for MaaS and bill queries** — do not use your primary account keys:

1. **Create a custom permission policy** — IAM → Permissions → Permission management → Create custom policy → JSON view. only billing queries need this policy:
   ```json
   {
       "Version": "1.1",
       "Statement": [
           { "Effect": "Allow", "Action": [ "bss:billDetail:view" ] }
       ]
   }
   ```
2. **Create a user group and attach the policy.**
3. **Create an IAM user in that group**, access type **Programmatic access only** (no console password), and generate its **access key (AK/SK)**.

## Data sensitivity

The tool can read **caller source IPs**, per-model token usage, and **billing cost**. Treat these as sensitive business data: restrict who holds the IAM user's credentials and where query output/charts are stored.

## Hardening checklist before distribution

- [ ] Ship the CLI with **AK/SK-only** code paths (no unused token/console-capture code).
- [ ] Distribute only over trusted channels; publish a checksum/hash and pin the version.
- [ ] Document that credentials must come from a secret manager or OS environment.
- [ ] If local storage is used, encrypt with an OS keystore (DPAPI / Keychain / Secret Service).
- [ ] Run in a trusted environment; be aware that a corporate MITM proxy or a compromised CA can intercept HTTPS traffic.

## Reporting a vulnerability

Please report suspected vulnerabilities privately to the maintainers rather than opening a public issue, and include reproduction steps and the affected version.
