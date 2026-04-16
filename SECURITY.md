# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 2.5.x (latest) | yes |
| 2.4.x | security fixes only |
| < 2.4 | no |

We recommend always running the latest release. Use `gitpulse update --check` to see if you are behind.

## Reporting a vulnerability

Please report security issues **privately** by opening a [GitHub Security Advisory](https://github.com/prodrom3/gitpulse/security/advisories/new). Do not file a public issue for vulnerabilities that have not yet been disclosed.

Public issues are acceptable for:
- Already-disclosed CVEs (e.g. git version warnings).
- Clearly non-sensitive hardening suggestions (e.g. adding a new PRAGMA, tightening a permission check).

We aim to acknowledge reports within 48 hours and provide a fix or mitigation plan within 7 days. Critical issues (RCE, credential leak, index corruption) are treated as P0.

## Threat model

gitpulse is a local-first tool designed for operators who maintain a large fleet of cloned git repositories. The primary threats it defends against:

| Threat | Mitigation |
| --- | --- |
| Malicious hooks in cloned repos (CVE-2024-32002/32004/32465) | `gitpulse add <url>` clones with `--no-checkout` and disables hooks via `GIT_CONFIG_*` environment variables. Checkout happens in a second step with the same protections. |
| Credential leakage in logs or output | HTTPS credentials are stripped from `remote_url` before writing to logs, the SQLite index, the vault, and any exported bundle. |
| Index as an intelligence artifact | The SQLite file at `$XDG_DATA_HOME/gitpulse/index.db` reveals the operator's full toolchain. Created `0600`, parent dir `0700`. PRAGMAs: `journal_mode=WAL`, `secure_delete=ON` (deleted rows overwritten on disk), `foreign_keys=ON`. No built-in encryption; at-rest confidentiality should be handled at the disk layer (LUKS / FileVault / BitLocker). |
| Upstream probe leaking the tool inventory | Probes only contact hosts explicitly listed in `~/.config/gitpulse/auth.toml` (`0600`, ownership-checked). Unknown hosts are silently skipped (fail-closed). Per-repo `quiet=1` flag suppresses all probing and info-level logging for that repo. `--offline` hard-disables the network layer. |
| auth.toml token exposure | Tokens are sourced from environment variables by default (`token_env`). Inline tokens are supported but discouraged. Tokens are sent only as `Authorization: Bearer` headers and are excluded from every log path and every error message (verified by test). The auth file is rejected if its permissions are not `0600` or if it is not owned by the invoking user on Unix. |
| Vault as an intelligence artifact | Vault files carry the same sensitivity as the index. Written `0600`, repos subdirectory `0700`. Credentials defensively redacted at render time. |
| Export bundle leaking sensitive context | `gitpulse export --redact` strips notes, source, and remote_url. The `redacted: true` envelope flag lets downstream consumers verify. Non-redacted bundles are written `0600`. |
| Self-update supply chain | `gitpulse update` issues a single HTTPS GET to api.github.com. The `--verify` flag runs `git verify-tag` on the release tag if the local install is a source clone with GPG or SSH signing configured. `--offline` disables the network call entirely. pip installs are never upgraded automatically. |
| Shell injection | Every subprocess call uses list arguments. `shell=True` is never used anywhere in the codebase. |
| Config/watchlist tampering | `~/.gitpulserc` and the legacy `~/.gitpulse_repos` are rejected if not owned by the invoking user or if world-writable (Unix). |

## Hardening recommendations

1. **Encrypt at rest.** Place `$XDG_DATA_HOME/gitpulse/` and the Obsidian vault directory on an encrypted volume.
2. **Use `token_env`, not inline tokens.** Rotate tokens via your secrets manager; gitpulse reads them from the environment at runtime.
3. **Mark sensitive repos `quiet`.** `gitpulse add --quiet-upstream <path>` prevents any network call about that repo, forever, until you explicitly clear the flag.
4. **Run `gitpulse digest` weekly.** The "archived upstream" section is your supply-chain early-warning system.
5. **Keep git up to date.** gitpulse warns at startup if git < 2.45.1, but only the operator can actually upgrade it.

## Scope

gitpulse is a CLI tool, not a service. There is no daemon, no listening socket, no web UI, no telemetry, no analytics. The only network traffic leaves the machine in two cases:
- `gitpulse refresh` (upstream probes, opsec-gated, opt-in per host).
- `gitpulse update` (release check against api.github.com, operator-invoked).

Both are disabled by `--offline`.
