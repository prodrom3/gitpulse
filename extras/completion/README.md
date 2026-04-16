# Shell completions for gitpulse

Static completion files for bash, zsh, and fish. No runtime dependency required.

## Bash

```bash
source /path/to/gitpulse/extras/completion/gitpulse.bash

# Or install system-wide:
sudo cp extras/completion/gitpulse.bash /etc/bash_completion.d/gitpulse
```

## Zsh

```zsh
# Add to fpath before compinit in your .zshrc:
fpath=(/path/to/gitpulse/extras/completion $fpath)
autoload -Uz compinit && compinit

# Or copy the file to an existing fpath directory:
cp extras/completion/gitpulse.zsh /usr/local/share/zsh/site-functions/_gitpulse
```

The file is named `gitpulse.zsh` and uses `#compdef gitpulse` so zsh will pick it up when the directory is in `$fpath`.

## Fish

```fish
cp extras/completion/gitpulse.fish ~/.config/fish/completions/gitpulse.fish
```

Fish auto-loads completions from `~/.config/fish/completions/`.
