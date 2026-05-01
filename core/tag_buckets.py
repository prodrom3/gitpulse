"""Tag bucket categorization for `nostos tags --grouped`.

Maps each tag name to one of a small set of human-readable buckets
(`discipline`, `attack-class`, `recon-technique`, `tool-kind`,
`secret-leaks`, `project-name`, `language`, `os`, `tech`, `other`)
purely for grouped CLI output.

This is a *display-only* concern: it does not affect tag storage,
querying, or the topic_rules curation layer. Tags not in any bucket
fall through to `other`.

Adding new tags
- Edit the BUCKETS table below; first match wins, so order entries
  by specificity (most specific bucket first when a tag could fit
  multiple).
- A tag does not need to be added here for `nostos list --tag X`
  or `nostos tag <repo> +X` to work - the bucket map only affects
  the `--grouped` view of `nostos tags`.
"""

from __future__ import annotations

# Order matters: first match wins. When a tag could fit multiple
# buckets (e.g. `fuzzing` is both a recon-technique and a tool-kind
# concept), we put it in the more specific / higher-signal bucket.
BUCKETS: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "discipline",
        frozenset({
            "recon", "pentest", "websec", "redteam", "bugbounty",
            "hacking", "hacks", "infosec", "cybersecurity",
            "offsec", "offensive-security", "security-tools",
            "security-research", "security-testing", "security-audit",
            "application-security", "appsec", "ethical-hacking",
            "penetration-test", "pentester", "pentesting-guides",
            "methodology", "hackthebox", "oscp", "oscp-tools", "osep",
            "ctf", "ctf-tools", "red-team-manual",
            "adversary-emulation", "owasp", "linux-pentesting",
            "netsec", "web-hacking", "ethical-hacking-tools",
        }),
    ),
    (
        "attack-class",
        frozenset({
            "vulnerability", "vulnerabilities", "security-vulnerability",
            "xss", "dom-xss", "csrf", "xsrf", "ssrf",
            "server-side-request-forgery", "cors", "command-injection",
            "open-redirect", "open-redirections",
            "subdomain-takeover", "subdomain-takeovers", "takeover",
            "takeover-subdomain", "hostile",
            "hostile-subdomain-takeover", "exploitation", "exploit",
            "crlf-injection", "vulnerable-libraries", "attack-surface",
            "hash-cracking", "bruteforce", "bruteforce-wordlist",
            "brute-force-attacks", "brute-force",
            "privilege-escalation", "bypass", "obfuscation",
            "reverse-shell", "insecure-libraries",
        }),
    ),
    (
        "recon-technique",
        frozenset({
            "subdomain", "subdomains", "subdomain-bruteforcing",
            "dns", "dns-bruteforcer", "dns-resolution", "dns-resolver",
            "github-recon", "visual-recon",
            "js-enumeration", "port-scan", "port-scanner",
            "portscanner", "port-enumeration", "scan-ports",
            "fuzzing", "wayback", "dorking", "dork", "dorks",
            "google-dorks", "enumeration", "content-discovery",
            "reconnaissance", "network-discovery", "service-discovery",
            "service-enumeration", "discovery-service",
            "cdn-exclusion", "reverse-lookups", "fingerprint",
            "virtual-host", "virtual-hosts", "vhost", "vhosts",
            "domains", "endpoints", "subdomain-finder",
            "massdns", "information-gathering", "osint",
        }),
    ),
    (
        "tool-kind",
        frozenset({
            "scanner", "scanning", "fuzzer", "wordlist", "wordlists",
            "payload", "payloads", "payload-generator", "parameter",
            "parameter-finder", "urls-parameters", "c2",
            "c2-framework", "security-scanner", "cve-scanner",
            "security-automation", "automated", "csrf-scanner",
            "cors-scanner", "cors-misconfiguration-scanner",
            "xss-scanner", "waf-detection", "waffit", "waf",
            "web-application-firewall", "sbom", "sbom-generator",
            "sbom-tool", "software-composition-analysis", "monitor",
            "realtime", "filtering", "honeypot", "password-generator",
            "verification", "dast", "static-analysis",
            "dynamic-analysis", "precommit",
            "secret-management", "secrets-management",
        }),
    ),
    (
        "secret-leaks",
        frozenset({
            "secret", "secrets", "credentials", "leaks", "breach",
            "breach-checker", "data-breach", "email-security",
            "privacy",
        }),
    ),
    (
        "project-name",
        frozenset({
            "nuclei", "nuclei-engine", "commix", "ssrfmap", "xsstrike",
            "trufflehog", "mythic", "caldera", "metasploit",
            "metasploit-payloads", "openvas", "openvas-scanner",
            "greenbone", "gvm", "mitre", "mitre-attack",
            "mitre-corporation", "pegasus", "nso", "paybag",
            "lazyscript", "xposedornot", "customtkinter", "exiftool",
            "exif", "radar",
        }),
    ),
    (
        "language",
        frozenset({
            "python", "python3", "py", "py3", "go", "golang",
            "javascript", "ruby", "lua", "c", "c-plus-plus", "cpp",
            "powershell", "shell-script", "shell",
        }),
    ),
    (
        "os",
        frozenset({
            "linux", "kali", "kali-linux", "parrot-os", "ubuntu",
            "osx", "windows", "termux", "termux-hacking",
            "termux-tool", "termux-tools",
        }),
    ),
    (
        "tech",
        frozenset({
            "ssl", "ssl-certificate", "http", "pcre", "libpcap",
            "socket", "multithreading", "asynchronous", "thread",
            "pipeline", "machine-learning", "ai", "agentic-ai", "gui",
            "chrome-extension", "firefox-extension", "chrome-headless",
            "chromium", "grunt-plugins", "build-tool", "tool", "list",
            "lib", "files", "extract", "urls", "parser", "cli",
            "git", "github", "github-api", "cyint", "goquery",
            "open-source", "ping", "netcat", "cidr-notation", "service-discovery",
            "discovery-service", "secret-rotation", "ssh",
            "devsecops", "dev-tools", "automation", "fingerprint",
            "ruby",
        }),
    ),
)

_TAG_TO_BUCKET: dict[str, str] = {}
for _bucket_name, _tags in BUCKETS:
    for _tag in _tags:
        # First-match-wins: don't overwrite if already mapped from
        # a higher-priority bucket.
        _TAG_TO_BUCKET.setdefault(_tag, _bucket_name)


def bucket_for(tag: str) -> str:
    """Return the bucket name for a tag, or 'other' if unmatched."""
    return _TAG_TO_BUCKET.get(tag.strip().lower(), "other")


# Display order for `nostos tags --grouped`. Higher-signal buckets
# first; `other` always last.
DISPLAY_ORDER: tuple[str, ...] = (
    "discipline",
    "attack-class",
    "recon-technique",
    "tool-kind",
    "secret-leaks",
    "project-name",
    "language",
    "os",
    "tech",
    "other",
)


__all__ = ["BUCKETS", "bucket_for", "DISPLAY_ORDER"]
