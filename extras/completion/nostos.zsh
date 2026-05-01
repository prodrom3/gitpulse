#compdef nostos nostos.py
# Zsh completion for nostos
# Add this directory to fpath or copy to a directory in $fpath:
#
#   fpath=(/path/to/nostos/extras/completion $fpath)
#   autoload -Uz compinit && compinit

local -a verbs
verbs=(
    'pull:Batch-update discovered repositories'
    'add:Register a repository in the metadata index'
    'list:List repositories in the metadata index'
    'show:Show full metadata for a single repository'
    'tag:Add or remove tags on a repository'
    'tags:List every tag in the index with attachment counts'
    'note:Append a note to a repository'
    'triage:Walk newly-added repositories and classify them'
    'rm:Remove a repository from the metadata index'
    'refresh:Fetch upstream metadata for registered repositories'
    'topics:Manage topic curation rules (deny / alias)'
    'digest:Print a weekly changeset report'
    'vault:Bridge the metadata index with an Obsidian vault'
    'export:Write a portable JSON bundle of the metadata index'
    'import:Load a portable JSON bundle into the metadata index'
    'update:Check for or apply a nostos self-update'
)

local -a statuses
statuses=(new reviewed in-use dropped flagged)

_nostos() {
    local curcontext="$curcontext" state line

    _arguments -C \
        '-v[Show version]' \
        '--version[Show version]' \
        '-h[Show help]' \
        '--help[Show help]' \
        '1:verb:->verb' \
        '*::arg:->args'

    case $state in
        verb)
            _describe 'command' verbs
            ;;
        args)
            case ${line[1]} in
                pull)
                    _arguments \
                        '--dry-run[List repos without pulling]' \
                        '--fetch-only[Fetch only, do not merge]' \
                        '--rebase[Use --rebase when pulling]' \
                        '--depth[Max scan depth]:depth:' \
                        '--workers[Concurrent workers]:n:' \
                        '--timeout[Timeout per operation]:seconds:' \
                        '--exclude[Glob patterns to skip]:pattern:' \
                        '--from-index[Pull every repo in the index]' \
                        '--json[JSON output]' \
                        '-q[Quiet mode]' \
                        '--quiet[Quiet mode]' \
                        '1:path:_directories'
                    ;;
                add)
                    _arguments \
                        '--tag[Attach tag]:tag:' \
                        '--source[Provenance text]:source:' \
                        '--note[Initial note]:note:' \
                        '--status[Initial status]:status:($statuses)' \
                        '--quiet-upstream[Opsec: never probe upstream]' \
                        '--auto-tags[Fetch repo topics from upstream as tags]' \
                        '--clone-dir[Clone directory]:dir:_directories' \
                        '1:target:_files'
                    ;;
                list)
                    _arguments \
                        '--tag[Filter by tag]:tag:' \
                        '--status[Filter by status]:status:($statuses)' \
                        '--untouched-over[Untouched threshold]:days:' \
                        '--upstream-archived[Only archived upstream]' \
                        '--upstream-dormant[Dormant threshold]:days:' \
                        '--upstream-stale[Stale cache threshold]:days:' \
                        '--json[JSON output]'
                    ;;
                show)
                    _arguments '--json[JSON output]' '1:target:'
                    ;;
                tag)
                    _arguments '1:target:' '*:tags:'
                    ;;
                tags)
                    _arguments \
                        '--include-orphans[Also list tags with zero attached repos]' \
                        '--prune-orphans[Delete orphan tag rows]' \
                        '--json[JSON output]'
                    ;;
                note)
                    _arguments '1:target:' '2:body:'
                    ;;
                triage)
                    _arguments '--status[Queue status]:status:($statuses)'
                    ;;
                rm)
                    _arguments \
                        '--purge[Delete clone and vault file]' \
                        '--cleanup-vault[Delete vault .md file]' \
                        '--yes[Skip confirmation]' \
                        '1:target:'
                    ;;
                refresh)
                    _arguments \
                        '--repo[Refresh single repo]:target:' \
                        '--since[TTL window]:days:' \
                        '--all[Refresh everything]' \
                        '--force[Same as --all]' \
                        '--offline[No network]' \
                        '--auto-tags[Merge upstream topics into tag list]' \
                        '--json[JSON output]'
                    ;;
                topics)
                    local -a topics_subs
                    topics_subs=(
                        'list:Show current rules'
                        'deny:Add topics to the deny list'
                        'allow:Remove topics from the deny list'
                        'alias:Rewrite SRC to DST during topic import'
                        'unalias:Remove alias entries by source name'
                        'export:Write rules as TOML to PATH or stdout'
                        'import:Load a rules TOML; merge or replace'
                        'apply:Retroactively curate existing repo tags'
                    )
                    _arguments '1:subcommand:->topics_sub' '*::topics_arg:->topics_args'
                    case $state in
                        topics_sub)
                            _describe 'topics subcommand' topics_subs
                            ;;
                        topics_args)
                            _arguments \
                                '--json[JSON output]' \
                                '--merge[Union deny lists, overlay alias maps]' \
                                '--replace[Replace the local rules]' \
                                '--repo[Apply to a single repo]:target:' \
                                '--dry-run[Print what would change without writing]' \
                                '*:file:_files'
                            ;;
                    esac
                    ;;
                digest)
                    _arguments \
                        '--since[Window]:days:' \
                        '--stale[Stale threshold]:days:' \
                        '--dormant[Dormant threshold]:days:' \
                        '--json[JSON output]'
                    ;;
                vault)
                    local -a vault_subs
                    vault_subs=(
                        'export:Write markdown files to the vault'
                        'sync:Reconcile vault edits back into the DB'
                    )
                    _arguments '1:subcommand:->vault_sub' '*::vault_arg:->vault_args'
                    case $state in
                        vault_sub)
                            _describe 'vault subcommand' vault_subs
                            ;;
                        vault_args)
                            _arguments \
                                '--path[Vault path]:dir:_directories' \
                                '--subdir[Subdirectory name]:name:' \
                                '--quiet[Suppress progress]' \
                                '--json[JSON output]'
                            ;;
                    esac
                    ;;
                export)
                    _arguments \
                        '--out[Output file]:file:_files' \
                        '--redact[Strip sensitive fields]' \
                        '--pretty[Pretty-print JSON]'
                    ;;
                import)
                    _arguments \
                        '--merge[Additive import (default)]' \
                        '--replace[Wipe and replace]' \
                        '--remap[Path rewrite]:src\:dst:' \
                        '--dry-run[Preview only]' \
                        '--yes[Skip confirmation]' \
                        '--json[JSON summary]' \
                        '1:bundle:_files'
                    ;;
                update)
                    _arguments \
                        '--check[Report only]' \
                        '--offline[No network]' \
                        '--yes[Skip confirmation]'
                    ;;
            esac
            ;;
    esac
}

_nostos "$@"
