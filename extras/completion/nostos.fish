# Fish completion for nostos
# Copy to ~/.config/fish/completions/nostos.fish
#   cp extras/completion/nostos.fish ~/.config/fish/completions/

set -l verbs pull add list show tag note triage rm refresh digest vault export import update
set -l statuses new reviewed in-use dropped flagged

# Disable file completions by default; re-enable per-verb where needed
complete -c nostos -f

# Top-level verbs
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a pull    -d "Batch-update discovered repositories"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a add     -d "Register a repository in the index"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a list    -d "List repositories in the index"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a show    -d "Show full metadata for one repo"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a tag     -d "Add or remove tags"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a note    -d "Append a note"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a triage  -d "Walk newly-added repos"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a rm      -d "Remove from the index"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a refresh -d "Fetch upstream metadata"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a digest  -d "Weekly changeset report"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a vault   -d "Obsidian vault bridge"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a export  -d "Write a portable JSON bundle"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a import  -d "Load a JSON bundle"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -a update  -d "Self-update"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -s v -l version -d "Show version"
complete -c nostos -n "not __fish_seen_subcommand_from $verbs" -s h -l help    -d "Show help"

# pull
complete -c nostos -n "__fish_seen_subcommand_from pull" -l dry-run     -d "List repos without pulling"
complete -c nostos -n "__fish_seen_subcommand_from pull" -l fetch-only  -d "Fetch only"
complete -c nostos -n "__fish_seen_subcommand_from pull" -l rebase      -d "Use --rebase"
complete -c nostos -n "__fish_seen_subcommand_from pull" -l depth       -d "Max scan depth" -r
complete -c nostos -n "__fish_seen_subcommand_from pull" -l workers     -d "Worker threads" -r
complete -c nostos -n "__fish_seen_subcommand_from pull" -l timeout     -d "Timeout (seconds)" -r
complete -c nostos -n "__fish_seen_subcommand_from pull" -l exclude     -d "Exclude patterns" -r
complete -c nostos -n "__fish_seen_subcommand_from pull" -l from-index  -d "Pull every indexed repo"
complete -c nostos -n "__fish_seen_subcommand_from pull" -l json        -d "JSON output"
complete -c nostos -n "__fish_seen_subcommand_from pull" -s q -l quiet  -d "Quiet mode"

# add
complete -c nostos -n "__fish_seen_subcommand_from add" -l tag            -d "Attach tag" -r
complete -c nostos -n "__fish_seen_subcommand_from add" -l source         -d "Provenance" -r
complete -c nostos -n "__fish_seen_subcommand_from add" -l note           -d "Initial note" -r
complete -c nostos -n "__fish_seen_subcommand_from add" -l status         -d "Initial status" -ra "$statuses"
complete -c nostos -n "__fish_seen_subcommand_from add" -l quiet-upstream -d "Opsec: never probe"
complete -c nostos -n "__fish_seen_subcommand_from add" -l clone-dir      -d "Clone directory" -ra "(__fish_complete_directories)"

# list
complete -c nostos -n "__fish_seen_subcommand_from list" -l tag               -d "Filter by tag" -r
complete -c nostos -n "__fish_seen_subcommand_from list" -l status            -d "Filter by status" -ra "$statuses"
complete -c nostos -n "__fish_seen_subcommand_from list" -l untouched-over    -d "Untouched threshold (days)" -r
complete -c nostos -n "__fish_seen_subcommand_from list" -l upstream-archived -d "Only archived upstream"
complete -c nostos -n "__fish_seen_subcommand_from list" -l upstream-dormant  -d "Dormant threshold (days)" -r
complete -c nostos -n "__fish_seen_subcommand_from list" -l upstream-stale    -d "Stale cache threshold (days)" -r
complete -c nostos -n "__fish_seen_subcommand_from list" -l json              -d "JSON output"

# show
complete -c nostos -n "__fish_seen_subcommand_from show" -l json -d "JSON output"

# triage
complete -c nostos -n "__fish_seen_subcommand_from triage" -l status -d "Queue status" -ra "$statuses"

# rm
complete -c nostos -n "__fish_seen_subcommand_from rm" -l purge         -d "Delete clone and vault file"
complete -c nostos -n "__fish_seen_subcommand_from rm" -l cleanup-vault -d "Delete vault .md file"
complete -c nostos -n "__fish_seen_subcommand_from rm" -l yes           -d "Skip confirmation"

# refresh
complete -c nostos -n "__fish_seen_subcommand_from refresh" -l repo    -d "Single repo" -r
complete -c nostos -n "__fish_seen_subcommand_from refresh" -l since   -d "TTL window (days)" -r
complete -c nostos -n "__fish_seen_subcommand_from refresh" -l all     -d "Refresh everything"
complete -c nostos -n "__fish_seen_subcommand_from refresh" -l force   -d "Same as --all"
complete -c nostos -n "__fish_seen_subcommand_from refresh" -l offline -d "No network"
complete -c nostos -n "__fish_seen_subcommand_from refresh" -l json    -d "JSON output"

# digest
complete -c nostos -n "__fish_seen_subcommand_from digest" -l since   -d "Window (days)" -r
complete -c nostos -n "__fish_seen_subcommand_from digest" -l stale   -d "Stale threshold (days)" -r
complete -c nostos -n "__fish_seen_subcommand_from digest" -l dormant -d "Dormant threshold (days)" -r
complete -c nostos -n "__fish_seen_subcommand_from digest" -l json    -d "JSON output"

# vault (sub-verbs)
complete -c nostos -n "__fish_seen_subcommand_from vault; and not __fish_seen_subcommand_from export sync" -a export -d "Write markdown files"
complete -c nostos -n "__fish_seen_subcommand_from vault; and not __fish_seen_subcommand_from export sync" -a sync   -d "Reconcile vault edits"
complete -c nostos -n "__fish_seen_subcommand_from vault; and __fish_seen_subcommand_from export sync" -l path   -d "Vault path" -ra "(__fish_complete_directories)"
complete -c nostos -n "__fish_seen_subcommand_from vault; and __fish_seen_subcommand_from export sync" -l subdir -d "Subdirectory" -r
complete -c nostos -n "__fish_seen_subcommand_from vault; and __fish_seen_subcommand_from export" -l quiet -d "Suppress progress"
complete -c nostos -n "__fish_seen_subcommand_from vault; and __fish_seen_subcommand_from sync"   -l json  -d "JSON output"

# export
complete -c nostos -n "__fish_seen_subcommand_from export; and not __fish_seen_subcommand_from vault" -l out    -d "Output file" -rF
complete -c nostos -n "__fish_seen_subcommand_from export; and not __fish_seen_subcommand_from vault" -l redact -d "Strip sensitive fields"
complete -c nostos -n "__fish_seen_subcommand_from export; and not __fish_seen_subcommand_from vault" -l pretty -d "Pretty-print JSON"

# import
complete -c nostos -n "__fish_seen_subcommand_from import" -l merge   -d "Additive import"
complete -c nostos -n "__fish_seen_subcommand_from import" -l replace -d "Wipe and replace"
complete -c nostos -n "__fish_seen_subcommand_from import" -l remap   -d "Path rewrite (src:dst)" -r
complete -c nostos -n "__fish_seen_subcommand_from import" -l dry-run -d "Preview only"
complete -c nostos -n "__fish_seen_subcommand_from import" -l yes     -d "Skip confirmation"
complete -c nostos -n "__fish_seen_subcommand_from import" -l json    -d "JSON summary"

# update
complete -c nostos -n "__fish_seen_subcommand_from update" -l check   -d "Report only"
complete -c nostos -n "__fish_seen_subcommand_from update" -l offline -d "No network"
complete -c nostos -n "__fish_seen_subcommand_from update" -l yes     -d "Skip confirmation"
