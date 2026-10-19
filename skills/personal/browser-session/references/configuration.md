# Browser session configuration

Each project may place a `.browser-session.json` at its root. Keep the file limited to the two project-level settings understood by the wrapper:

```json
{
  "profile": "~/.beancount-acquire-chrome",
  "download_dir": "files-to-import"
}
```

`profile` selects the persistent Chrome user-data directory. Prefer an explicit path under `~` or an absolute path. The wrapper's fallback is `~/.agent-browser/profiles/shared`, a dedicated profile separate from the user's everyday Chrome profile. A project may omit `profile` when that shared identity is appropriate.

`download_dir` names the project's download destination. Use the project's existing convention; a relative path is relative to the project root. Do not put downloaded statements or receipts in the browser profile.

The command-line `--profile` option overrides the project setting for one invocation. If neither is supplied, use the shared default. Keep account-specific profiles stable so their logged-in state survives later runs. Profile directories contain credentials and cookies; never check them into source control or print their contents.

## Choosing a profile

Use a project-specific profile for a bank, payroll account, store account, or any workflow where account identity must persist. For example:

```json
{
  "profile": "~/.beancount-acquire-chrome",
  "download_dir": "files-to-import"
}
```

Use the shared profile for public pages or tasks that intentionally share one browser identity:

```json
{
  "profile": "~/.agent-browser/profiles/shared",
  "download_dir": "downloads"
}
```

The profile is the isolation boundary. Agent-browser sessions and pinned tabs identify task ownership within that browser, but they do not create separate cookies, accounts, permissions, or site settings. Do not use the shared profile for concurrent account switching.

## Typical commands

Inspect resolution without starting Chrome:

```bash
python3 scripts/browser-session.py --project . plan
```

Start or reuse Chrome, then run one agent-browser command in a named session:

```bash
python3 scripts/browser-session.py --project . --session beancount-CHAT_UUID run -- snapshot -i
```

When the task ends, release only its session:

```bash
python3 scripts/browser-session.py --project . --session beancount-CHAT_UUID release
```

The wrapper may be used with another project profile for a one-off task:

```bash
python3 scripts/browser-session.py --project . --profile ~/.another-project-chrome --session one-off run -- get url
```

The Chrome process remains available after `release`; this is intentional so another task can reuse the same persistent profile. A human must handle initial login, 2FA, or an approval prompt when the site requires it.
