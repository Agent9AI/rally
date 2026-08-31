# Local Rally runner

The Cloudflare Worker holds commissions durably while the Mac is asleep. The
LaunchAgent in this directory starts the authenticated local runner after login
and restarts it only when it exits with an error.

Install for the current user:

```bash
mkdir -p .runtime "$HOME/Library/LaunchAgents"
cp ops/dev.agent9.rally.runner.plist "$HOME/Library/LaunchAgents/"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/dev.agent9.rally.runner.plist"
```

Inspect without exposing credentials:

```bash
launchctl print "gui/$(id -u)/dev.agent9.rally.runner"
tail -f .runtime/runner.log .runtime/runner.error.log
```

Stop and remove it:

```bash
launchctl bootout "gui/$(id -u)/dev.agent9.rally.runner"
rm "$HOME/Library/LaunchAgents/dev.agent9.rally.runner.plist"
```

The plist contains no secrets. The runner reads existing credentials from the
macOS Keychain and leaves mail in D1 when a required credential is unavailable.
