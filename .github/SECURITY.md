# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.7.x (latest) | yes |
| 1.6.x | security fixes only |
| < 1.6 | no |

We recommend always running the latest release. Use `nostos update --check` to see if you are behind.

## Reporting a vulnerability

Please report security issues **privately** by opening a [GitHub Security Advisory](https://github.com/prodrom3/nostos/security/advisories/new). Do not file a public issue for vulnerabilities that have not yet been disclosed.

Public issues are acceptable for:
- Already-disclosed CVEs (e.g. git version warnings).
- Clearly non-sensitive hardening suggestions (e.g. adding a new PRAGMA, tightening a permission check).

We aim to acknowledge reports within 48 hours and provide a fix or mitigation plan within 7 days. Critical issues (RCE, credential leak, index corruption) are treated as P0.

## Threat model

nostos is a local-first tool designed for operators who maintain a large fleet of cloned git repositories. The primary threats it defends against:

| Threat | Mitigation |
| --- | --- |
| Malicious hooks in cloned repos (CVE-2024-32002/32004/32465) | Clone paths (`nostos add <url>`, and clone-on-import in `nostos import`) clone with `--no-checkout` and disable hooks via `GIT_CONFIG_*` environment variables. Checkout happens in a second step with the same protections. |
| Argument / transport injection via a hostile clone URL | Clone URLs are validated against the remote-URL allowlist, git is invoked with a `--` separator so a URL beginning with `-` cannot be parsed as an option, and `protocol.ext.allow=never` is pinned in the clone environment. This blocks a git option (`--upload-pack=...`, `-c ...`) or dangerous transport (`ext::sh -c ...`, `file://`) smuggled in through an untrusted import bundle's `remote_url`. |
| Credential leakage in logs or output | HTTPS credentials are stripped from `remote_url` before writing to logs, the SQLite index, the vault, and any exported bundle. Probe requests are https-only, and the `Authorization` / `Cookie` headers are dropped on any HTTP redirect that changes host, so a token cannot be forwarded to an unintended host. |
| Index as an intelligence artifact | The SQLite file at `$XDG_DATA_HOME/nostos/index.db` reveals the operator's full toolchain. The database file is created `0600` before SQLite opens it, its `-wal` / `-shm` sidecars are held at `0600`, and the parent dir is `0700`. PRAGMAs: `journal_mode=WAL`, `secure_delete=ON` (deleted rows overwritten on disk), `foreign_keys=ON`. No built-in encryption; at-rest confidentiality should be handled at the disk layer (LUKS / FileVault / BitLocker). |
| Upstream probe leaking the tool inventory | Probes only contact hosts explicitly listed in `~/.config/nostos/auth.toml` (`0600`, ownership-checked). Unknown hosts are silently skipped (fail-closed). Per-repo `quiet=1` flag suppresses all probing and info-level logging for that repo. `--offline` hard-disables the network layer. |
| auth.toml token exposure | Tokens are sourced from environment variables by default (`token_env`). Inline tokens are supported but discouraged. Tokens are sent only as `Authorization: Bearer` headers and are excluded from every log path and every error message (verified by test). The auth file is rejected if its permissions are not `0600` or if it is not owned by the invoking user on Unix. |
| Vault as an intelligence artifact | Vault files carry the same sensitivity as the index. Written `0600`, repos subdirectory `0700`. Credentials defensively redacted at render time. |
| Export bundle leaking sensitive context | `nostos export --redact` strips notes, source, and remote_url. The `redacted: true` envelope flag lets downstream consumers verify. Non-redacted bundles are written `0600`. |
| Self-update supply chain | `nostos update` issues a single HTTPS GET to api.github.com. The `--verify` flag runs `git verify-tag` on the release tag for source-clone installs; if the signature does not verify, the upgrade is refused (fail-closed, and `--yes` does not override it). `--verify` is only meaningful once the maintainer signs release tags (`git tag -s`; see the release checklist in [MAINTAINERS.md](../MAINTAINERS.md)) and you trust their public key - against an unsigned tag it fails closed by design. `--offline` disables the network call entirely. pip installs are never upgraded automatically. |
| Shell injection | Every subprocess call uses list arguments. `shell=True` is never used anywhere in the codebase. |
| Config/watchlist tampering | `~/.nostosrc` and the legacy `~/.nostos_repos` are rejected if not owned by the invoking user or if group- or world-writable (Unix). |
| CI / release supply chain | Third-party GitHub Actions are pinned to full commit SHAs (kept current by Dependabot). PyPI releases are built and published via OIDC trusted publishing with PEP 740 provenance attestations - no long-lived tokens. CI runs `bandit` and `pip-audit` on every change. |

## Hardening recommendations

1. **Encrypt at rest.** Place `$XDG_DATA_HOME/nostos/` and the Obsidian vault directory on an encrypted volume.
2. **Use `token_env`, not inline tokens.** Rotate tokens via your secrets manager; nostos reads them from the environment at runtime.
3. **Mark sensitive repos `quiet`.** `nostos add --quiet-upstream <path>` prevents any network call about that repo, forever, until you explicitly clear the flag.
4. **Run `nostos digest` weekly.** The "archived upstream" section is your supply-chain early-warning system.
5. **Keep git up to date.** nostos warns at startup if git < 2.45.1, but only the operator can actually upgrade it.

## Scope

nostos is a CLI tool, not a service. There is no daemon, no listening socket, no web UI, no telemetry, no analytics. The only network traffic leaves the machine in two cases:
- `nostos refresh` (upstream probes, opsec-gated, opt-in per host).
- `nostos update` (release check against api.github.com, operator-invoked).

Both are disabled by `--offline`.
