# Bash completion for nostos
# Source this file or copy to /etc/bash_completion.d/nostos
#
#   source extras/completion/nostos.bash

_nostos() {
    local cur prev words cword
    _init_completion || return

    local verbs="pull add list show tag note triage rm refresh digest vault export import update"
    local vault_subs="export sync"
    local statuses="new reviewed in-use dropped flagged"

    # Complete verb at position 1
    if [[ $cword -eq 1 ]]; then
        COMPREPLY=($(compgen -W "$verbs -v --version -h --help" -- "$cur"))
        return
    fi

    local verb="${words[1]}"

    # vault sub-verbs
    if [[ "$verb" == "vault" && $cword -eq 2 ]]; then
        COMPREPLY=($(compgen -W "$vault_subs" -- "$cur"))
        return
    fi

    # Per-verb flag completion
    case "$verb" in
        pull)
            COMPREPLY=($(compgen -W "--dry-run --fetch-only --rebase --depth --workers --timeout --exclude --from-index --watchlist --json -q --quiet -h --help" -- "$cur"))
            ;;
        add)
            COMPREPLY=($(compgen -W "--tag --source --note --status --quiet-upstream --auto-tags --clone-dir -h --help" -- "$cur"))
            ;;
        list)
            COMPREPLY=($(compgen -W "--tag --status --untouched-over --upstream-archived --upstream-dormant --upstream-stale --json -h --help" -- "$cur"))
            ;;
        show)
            COMPREPLY=($(compgen -W "--json -h --help" -- "$cur"))
            ;;
        tag)
            COMPREPLY=($(compgen -W "-h --help" -- "$cur"))
            ;;
        note)
            COMPREPLY=($(compgen -W "-h --help" -- "$cur"))
            ;;
        triage)
            COMPREPLY=($(compgen -W "--status -h --help" -- "$cur"))
            ;;
        rm)
            COMPREPLY=($(compgen -W "--purge --cleanup-vault --yes -h --help" -- "$cur"))
            ;;
        refresh)
            COMPREPLY=($(compgen -W "--repo --since --all --force --offline --auto-tags --json -h --help" -- "$cur"))
            ;;
        digest)
            COMPREPLY=($(compgen -W "--since --stale --dormant --json -h --help" -- "$cur"))
            ;;
        vault)
            local vault_sub="${words[2]}"
            case "$vault_sub" in
                export)
                    COMPREPLY=($(compgen -W "--path --subdir --quiet -h --help" -- "$cur"))
                    ;;
                sync)
                    COMPREPLY=($(compgen -W "--path --subdir --json -h --help" -- "$cur"))
                    ;;
            esac
            ;;
        export)
            COMPREPLY=($(compgen -W "--out --redact --pretty -h --help" -- "$cur"))
            ;;
        import)
            COMPREPLY=($(compgen -W "--merge --replace --remap --dry-run --yes --json -h --help" -- "$cur"))
            ;;
        update)
            COMPREPLY=($(compgen -W "--check --offline --yes -h --help" -- "$cur"))
            ;;
    esac

    # Complete --status values
    if [[ "$prev" == "--status" ]]; then
        COMPREPLY=($(compgen -W "$statuses" -- "$cur"))
        return
    fi
}

complete -F _nostos -o default nostos
complete -F _nostos -o default nostos.py
