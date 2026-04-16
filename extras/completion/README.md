# Shell completions for nostos

Static completion files for bash, zsh, and fish. No runtime dependency required.

## Bash

```bash
source /path/to/nostos/extras/completion/nostos.bash

# Or install system-wide:
sudo cp extras/completion/nostos.bash /etc/bash_completion.d/nostos
```

## Zsh

```zsh
# Add to fpath before compinit in your .zshrc:
fpath=(/path/to/nostos/extras/completion $fpath)
autoload -Uz compinit && compinit

# Or copy the file to an existing fpath directory:
cp extras/completion/nostos.zsh /usr/local/share/zsh/site-functions/_nostos
```

The file is named `nostos.zsh` and uses `#compdef nostos` so zsh will pick it up when the directory is in `$fpath`.

## Fish

```fish
cp extras/completion/nostos.fish ~/.config/fish/completions/nostos.fish
```

Fish auto-loads completions from `~/.config/fish/completions/`.
