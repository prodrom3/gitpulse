# Architecture

How nostos is organized internally: module layout, dependency graph, and the two most important end-to-end flows.

## Module layout

```
nostos.py                   # thin entrypoint -> core.cli.run
core/
├── cli.py                   # argparse subparsers, legacy flag shim, default-verb injection
├── paths.py                 # XDG-compliant paths ($XDG_CONFIG_HOME / $XDG_DATA_HOME)
├── index.py                 # SQLite metadata index: schema, migrations, CRUD, PRAGMAs
├── config.py                # ~/.nostosrc loader + safety checks
├── discovery.py             # depth-limited directory walk, exclude globs, ownership check
├── logging_config.py        # logs/ setup, rotation, symlink protection
├── models.py                # RepoResult, RepoStatus dataclasses
├── output.py                # human + JSON summaries, ANSI colour handling
├── updater.py               # per-repo pull / fetch, git version guard, SSH multiplexing
├── updater_self.py          # self-update via GitHub releases API
├── watchlist.py             # hardened clone (used by `add`) + legacy watchlist readers
├── portable.py              # export / import bundle (schema v1 + v2)
├── upstream.py              # GitHub / GitLab / Gitea upstream probes
├── auth.py                  # per-host auth token loader for upstream probes
├── vault.py                 # Obsidian vault bridge
├── dashboard.py             # static HTML fleet dashboard
├── digest.py                # weekly changeset report
├── doctor.py                # integrity / health checks
├── taxonomy.py              # MITRE ATT&CK lookup table
└── commands/
    ├── pull.py              # verb: pull (default)
    ├── add.py               # verb: add
    ├── list_cmd.py          # verb: list
    ├── show.py              # verb: show
    ├── tag.py               # verb: tag
    ├── note.py              # verb: note
    ├── triage.py            # verb: triage
    ├── rm.py                # verb: rm
    ├── refresh.py           # verb: refresh (upstream probes)
    ├── digest.py            # verb: digest
    ├── dashboard.py         # verb: dashboard
    ├── vault.py             # verb: vault
    ├── export_cmd.py        # verb: export
    ├── import_cmd.py        # verb: import
    ├── update.py            # verb: update (self-update)
    ├── doctor.py            # verb: doctor
    ├── attack.py            # verb: attack
    ├── completion.py        # verb: completion
    └── _common.py           # shared helpers (error reporter, watchlist migration)
```

## Module dependencies

```mermaid
flowchart LR
    entry[nostos.py<br/>entrypoint]
    cli[core.cli<br/>subparsers + shim]
    paths[core.paths<br/>XDG]
    idx[core.index<br/>SQLite]
    cmds[core.commands.*<br/>one module per verb]
    config[core.config]
    logcfg[core.logging_config]
    discovery[core.discovery]
    updater[core.updater]
    watchlist[core.watchlist<br/>safe-clone]
    output[core.output]
    models[core.models]
    portable[core.portable]
    upstream[core.upstream]

    entry --> cli --> cmds
    cmds --> idx
    cmds --> config
    cmds --> logcfg
    cmds --> discovery
    cmds --> updater
    cmds --> watchlist
    cmds --> output
    cmds --> portable
    cmds --> upstream
    idx --> paths
    updater --> models
    output --> models
    portable --> idx
    portable -. clones via .-> watchlist
    watchlist -. invokes hardened clone for `add` .-> updater
```

## Run flow: `nostos pull`

```mermaid
flowchart TD
    start([nostos invoked]) --> rewrite[Rewrite legacy flags<br/>inject default verb]
    rewrite --> disp[Dispatch to<br/>core.commands.pull.run]
    disp --> mig[First-run watchlist<br/>migration into index]
    mig --> rc[Load ~/.nostosrc]
    rc --> src{Source of repos}
    src -->|--from-index| idx[Read metadata index]
    src -->|directory| scan[Walk directory tree]
    src -->|both| idx
    src -->|both| scan
    idx --> dedup[Deduplicate]
    scan --> dedup
    dedup --> pool[ThreadPoolExecutor<br/>N workers]
    pool --> state[Per-repo: check state<br/>detached / dirty / no upstream?]
    state -->|not pullable| skip[Skip with reason]
    state -->|pullable| fetch[git fetch]
    fetch --> mode{fetch-only?}
    mode -->|yes| report[Record behind count]
    mode -->|no| pull[git pull / --rebase]
    skip --> collect[Collect result]
    report --> collect
    pull --> collect
    collect --> register[Auto-register in index<br/>+ update last_touched_at]
    register --> summary[Print summary<br/>human or JSON]
    summary --> done([Exit 0 / 1])
```

## Intake flow: `nostos add` -> `triage`

```mermaid
flowchart LR
    url[URL or path<br/>from intel feed]
    add[nostos add<br/>hardened clone]
    index[(metadata index)]
    triage[nostos triage<br/>interactive loop]
    list[nostos list<br/>filters]
    show[nostos show<br/>per-repo view]

    url --> add
    add -->|status=new| index
    index --> triage
    triage -->|status=in-use / flagged / dropped<br/>tags + notes| index
    index --> list
    index --> show
```

## Import flow: `nostos import` with clone-on-import

```mermaid
flowchart TD
    bundle([bundle.json]) --> validate[Validate schema<br/>accept v1 or v2]
    validate --> plan[plan_import:<br/>resolve each entry]
    plan --> resolve{Per-entry resolution}
    resolve -->|path match post-remap| reg[Register]
    resolve -->|path_relative_to_home match| reg
    resolve -->|--no-clone| reg2[Register metadata-only]
    resolve -->|has remote_url| clone[Clone to clone-dir<br/>via hardened routine]
    resolve -->|nothing matches| skip[Skip with hint]
    clone --> reg3[Register at clone path]
    reg --> stats[Accumulate stats]
    reg2 --> stats
    reg3 --> stats
    skip --> stats
    stats --> summary[Print summary<br/>human or JSON]
```

## Key design constraints

- **No telemetry, no background network.** Network calls happen only when the operator invokes a verb that needs them (`refresh`, `update --check`, clone-on-import, `add` with a URL).
- **Local-first state.** Config, index, logs, and vault all live under the operator's home / XDG dirs. The bundle format is the only sanctioned transport between machines.
- **Thread-safe SQLite.** The index uses WAL mode and a short busy_timeout so the pull command's worker pool can update `last_touched_at` concurrently.
- **Graceful shutdown.** SIGINT flips a `threading.Event`; in-flight workers finish their current repo and nothing new starts.
