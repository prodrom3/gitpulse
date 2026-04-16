# Obsidian vault bridge

`nostos vault export` writes one markdown file per repo into an Obsidian vault, with YAML frontmatter that Obsidian renders as native Properties (tags become clickable, upstream fields become dataview-queryable). This turns your fleet into a browsable, searchable knowledge base without running a separate database.

## Configure the vault path

Add the vault to `~/.nostosrc`:

```ini
[vault]
path   = /home/user/obsidian/red-team
subdir = repos
```

Or override per-run: `nostos vault export --path ~/obsidian/red-team --subdir tools`.

## What gets written

Each repo produces `<vault>/<subdir>/<slug>.md` where `slug` is `<owner>-<name>` from the upstream metadata (or the repo path's basename when there is no upstream record). The frontmatter is valid YAML:

```yaml
---
nostos_id: 42
path: "/home/user/tools/recon-kit"
remote_url: "git@github.com:org/recon-kit.git"
source: "blog:orange.tw, 2026-04-12"
status: "in-use"
quiet: false
added: "2026-04-12T10:00:00+00:00"
last_touched: "2026-04-15T14:00:00+00:00"
tags: ["recon", "passive"]
upstream:
  provider: "github"
  host: "github.com"
  owner: "org"
  name: "recon-kit"
  stars: 1243
  archived: false
  default_branch: "main"
  last_push: "2026-04-11T00:00:00Z"
  latest_release: "v2.3.1"
  license: "MIT"
  fetched_at: "2026-04-15T13:00:00+00:00"
---
```

The body below the frontmatter is rendered Markdown:

```markdown
# org/recon-kit

*Exported by nostos on 2026-04-15T14:10:00+00:00*

## Description

(upstream description here)

## Notes

- **2026-04-12T10:05:00+00:00** - "mentioned for OOB DNS recon"
- **2026-04-14T09:30:00+00:00** - "used in demo"
```

## Narrow two-way sync

The vault is reconciliable with the DB, but **on a deliberately narrow surface**. `nostos vault sync` reads operator edits to `status` and `tags` out of each file's frontmatter, applies them to the DB, and then regenerates every `.md` from the reconciled state.

| Field | Writer | Sync behaviour |
| --- | --- | --- |
| `status` | operator (Obsidian Properties) | vault wins, DB is updated on next `vault sync` |
| `tags` | operator (Obsidian Properties) | vault wins, DB tag set is replaced to match |
| `upstream.*` | `nostos refresh` | DB wins, vault values are regenerated on sync |
| `last_touched`, `remote_url`, `path`, `added`, `nostos_id` | nostos | DB wins, regenerated on sync |
| Note body (Markdown) | nostos (via `nostos note`) | DB wins, body is regenerated on sync; vault edits to the Notes section are ignored |

The two sides never write to the same field, so there is no merge-conflict surface and no precedence timestamp needed. Orphan vault files (whose `nostos_id` no longer matches a repo in the DB) are reported, not deleted; the operator decides.

```bash
# Edit tags / status in Obsidian, then pull them into the DB
nostos vault sync

# JSON summary for scripting / cron
nostos vault sync --json

# Override the vault path per invocation
nostos vault sync --path ~/other-vault
```

`nostos vault export` is still supported and useful as a one-shot "rebuild from DB" operation (for example right after a large `nostos refresh`); `vault sync` is the right daily verb because it also catches any tag / status curation you did in Obsidian.

## Security posture

The vault contains the same sensitive operator context as the index (tags, sources, notes, upstream metadata). Treat the vault directory with the same opsec posture as `$XDG_DATA_HOME/nostos/`:

- Files are written `0600`.
- The `repos` subdirectory is created `0700` on Unix.
- Keep the vault on an encrypted volume at rest.

## Dataview queries

Once repos are exported you can query across your fleet from inside Obsidian with the Dataview plugin:

```
TABLE status, upstream.stars, upstream.archived, upstream.last_push
FROM "repos"
WHERE contains(tags, "c2") AND !upstream.archived
SORT upstream.stars DESC
```

```
TABLE status, upstream.last_push
FROM "repos"
WHERE upstream.archived = true
```
