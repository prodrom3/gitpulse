"""MITRE ATT&CK technique taxonomy for structured tagging.

Provides a lookup table of technique IDs to human-readable names so
operators can tag repos with `attack:T1059` and get meaningful output
in list / show / digest / vault without memorising the matrix.

Usage convention
- Tags prefixed with `attack:` are treated as ATT&CK technique IDs.
- The prefix is case-insensitive on input; stored lowercase.
- `gitpulse tag <repo> +attack:T1059` adds the tag `attack:t1059`.
- `gitpulse list --attack T1059` filters by it.
- `gitpulse attack list` prints the built-in lookup table.

The table is intentionally a curated subset of the most common
offensive-tool-relevant techniques, not the full 700+ matrix. Pull
requests to expand it are welcome.
"""

from __future__ import annotations

# Subset of MITRE ATT&CK Enterprise techniques most relevant to
# red-team tool classification. Source: attack.mitre.org
# Format: {technique_id_lower: (technique_id_display, name, tactic)}
TECHNIQUES: dict[str, tuple[str, str, str]] = {
    # Reconnaissance
    "t1595": ("T1595", "Active Scanning", "Reconnaissance"),
    "t1592": ("T1592", "Gather Victim Host Information", "Reconnaissance"),
    "t1589": ("T1589", "Gather Victim Identity Information", "Reconnaissance"),
    "t1590": ("T1590", "Gather Victim Network Information", "Reconnaissance"),
    "t1593": ("T1593", "Search Open Websites/Domains", "Reconnaissance"),
    "t1594": ("T1594", "Search Victim-Owned Websites", "Reconnaissance"),
    "t1591": ("T1591", "Gather Victim Org Information", "Reconnaissance"),
    # Resource Development
    "t1583": ("T1583", "Acquire Infrastructure", "Resource Development"),
    "t1586": ("T1586", "Compromise Accounts", "Resource Development"),
    "t1584": ("T1584", "Compromise Infrastructure", "Resource Development"),
    "t1587": ("T1587", "Develop Capabilities", "Resource Development"),
    "t1588": ("T1588", "Obtain Capabilities", "Resource Development"),
    "t1585": ("T1585", "Establish Accounts", "Resource Development"),
    # Initial Access
    "t1190": ("T1190", "Exploit Public-Facing Application", "Initial Access"),
    "t1133": ("T1133", "External Remote Services", "Initial Access"),
    "t1566": ("T1566", "Phishing", "Initial Access"),
    "t1078": ("T1078", "Valid Accounts", "Initial Access"),
    "t1189": ("T1189", "Drive-by Compromise", "Initial Access"),
    "t1199": ("T1199", "Trusted Relationship", "Initial Access"),
    # Execution
    "t1059": ("T1059", "Command and Scripting Interpreter", "Execution"),
    "t1203": ("T1203", "Exploitation for Client Execution", "Execution"),
    "t1047": ("T1047", "Windows Management Instrumentation", "Execution"),
    "t1053": ("T1053", "Scheduled Task/Job", "Execution"),
    "t1129": ("T1129", "Shared Modules", "Execution"),
    # Persistence
    "t1098": ("T1098", "Account Manipulation", "Persistence"),
    "t1547": ("T1547", "Boot or Logon Autostart Execution", "Persistence"),
    "t1136": ("T1136", "Create Account", "Persistence"),
    "t1543": ("T1543", "Create or Modify System Process", "Persistence"),
    "t1546": ("T1546", "Event Triggered Execution", "Persistence"),
    "t1505": ("T1505", "Server Software Component", "Persistence"),
    # Privilege Escalation
    "t1548": ("T1548", "Abuse Elevation Control Mechanism", "Privilege Escalation"),
    "t1068": ("T1068", "Exploitation for Privilege Escalation", "Privilege Escalation"),
    # Defense Evasion
    "t1140": ("T1140", "Deobfuscate/Decode Files or Information", "Defense Evasion"),
    "t1070": ("T1070", "Indicator Removal", "Defense Evasion"),
    "t1036": ("T1036", "Masquerading", "Defense Evasion"),
    "t1027": ("T1027", "Obfuscated Files or Information", "Defense Evasion"),
    "t1055": ("T1055", "Process Injection", "Defense Evasion"),
    # Credential Access
    "t1110": ("T1110", "Brute Force", "Credential Access"),
    "t1003": ("T1003", "OS Credential Dumping", "Credential Access"),
    "t1558": ("T1558", "Steal or Forge Kerberos Tickets", "Credential Access"),
    "t1552": ("T1552", "Unsecured Credentials", "Credential Access"),
    # Discovery
    "t1087": ("T1087", "Account Discovery", "Discovery"),
    "t1046": ("T1046", "Network Service Discovery", "Discovery"),
    "t1135": ("T1135", "Network Share Discovery", "Discovery"),
    "t1018": ("T1018", "Remote System Discovery", "Discovery"),
    "t1082": ("T1082", "System Information Discovery", "Discovery"),
    # Lateral Movement
    "t1021": ("T1021", "Remote Services", "Lateral Movement"),
    "t1080": ("T1080", "Taint Shared Content", "Lateral Movement"),
    "t1210": ("T1210", "Exploitation of Remote Services", "Lateral Movement"),
    # Collection
    "t1560": ("T1560", "Archive Collected Data", "Collection"),
    "t1005": ("T1005", "Data from Local System", "Collection"),
    "t1039": ("T1039", "Data from Network Shared Drive", "Collection"),
    "t1113": ("T1113", "Screen Capture", "Collection"),
    # Command and Control
    "t1071": ("T1071", "Application Layer Protocol", "Command and Control"),
    "t1132": ("T1132", "Data Encoding", "Command and Control"),
    "t1573": ("T1573", "Encrypted Channel", "Command and Control"),
    "t1105": ("T1105", "Ingress Tool Transfer", "Command and Control"),
    "t1090": ("T1090", "Proxy", "Command and Control"),
    "t1572": ("T1572", "Protocol Tunneling", "Command and Control"),
    # Exfiltration
    "t1041": ("T1041", "Exfiltration Over C2 Channel", "Exfiltration"),
    "t1048": ("T1048", "Exfiltration Over Alternative Protocol", "Exfiltration"),
    "t1567": ("T1567", "Exfiltration Over Web Service", "Exfiltration"),
    # Impact
    "t1485": ("T1485", "Data Destruction", "Impact"),
    "t1486": ("T1486", "Data Encrypted for Impact", "Impact"),
    "t1489": ("T1489", "Service Stop", "Impact"),
    "t1529": ("T1529", "System Shutdown/Reboot", "Impact"),
}


def lookup(technique_id: str) -> tuple[str, str, str] | None:
    """Resolve a technique ID to (display_id, name, tactic) or None."""
    key = technique_id.lower().removeprefix("attack:")
    return TECHNIQUES.get(key)


def normalize_attack_tag(raw: str) -> str:
    """Normalise an attack tag to the canonical form: attack:tNNNN."""
    cleaned = raw.lower().strip()
    if cleaned.startswith("attack:"):
        return cleaned
    if cleaned.startswith("t") and cleaned[1:].isdigit():
        return f"attack:{cleaned}"
    return cleaned


def render_table() -> str:
    """Render the full taxonomy as a human-readable table."""
    lines: list[str] = []
    current_tactic = ""
    for key in sorted(TECHNIQUES, key=lambda k: (TECHNIQUES[k][2], k)):
        display_id, name, tactic = TECHNIQUES[key]
        if tactic != current_tactic:
            if current_tactic:
                lines.append("")
            lines.append(f"  {tactic}")
            lines.append(f"  {'=' * len(tactic)}")
            current_tactic = tactic
        lines.append(f"    {display_id:<8} {name}")
    return "\n".join(lines) + "\n"
