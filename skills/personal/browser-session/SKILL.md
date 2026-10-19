---
name: browser-session
description: Manage persistent ordinary Google Chrome profiles for agent-browser tasks. Use when a browser task needs a project-specific or shared login, a verified CDP connection, or a named browser session.
---

# Browser Session

Use the shared wrapper to start or reuse ordinary Google Chrome with a deliberate persistent profile, then give `agent-browser` the exact verified CDP endpoint. The wrapper owns browser lifecycle; the agent-browser skill owns page interaction.

## Before opening a page

Read the project's `.browser-session.json` when it exists. Resolve the profile in this order:

1. A profile passed with `--profile` for this invocation.
2. The project's `profile` setting.
3. The shared default, `~/.agent-browser/profiles/shared`.

Use a project-specific profile when the task needs a particular account, durable login state, account switching, or sensitive site settings. Use the shared profile for ordinary browsing where sharing cookies and site state is acceptable. A named session separates tab ownership; it does not isolate cookies or accounts.

The project's login, download, security, and human-in-the-loop constraints take precedence. The agent may navigate to a login or 2FA page, but a human completes credentials, approval prompts, and other required verification.

## Lifecycle

Resolve `scripts/browser-session.py` relative to this skill directory, not the project directory. In the examples below, replace that path with its absolute path and set `--project` to the project that owns the task:

```bash
python3 scripts/browser-session.py --project PATH [--profile PATH] [--session NAME] plan
python3 scripts/browser-session.py --project PATH [--profile PATH] [--session NAME] ensure
python3 scripts/browser-session.py --project PATH --session NAME run -- snapshot -i
python3 scripts/browser-session.py --project PATH --session NAME release
```

`plan` is read-only and shows the resolved project, profile, download directory, and session. `ensure` starts or reuses the selected browser. `plan` and `ensure` may derive a stable default session from the project; `run` and `release` require an explicit session so each chat has an unambiguous tab claim.

The wrapper launches the installed ordinary Google Chrome with a dynamic remote-debugging port. It must reuse the selected profile's `DevToolsActivePort` only after checking that the port belongs to the live Chrome process and that the endpoint responds. Never assume port `9222`, scan for an arbitrary CDP endpoint, or attach to the user's everyday Chrome. Never use `--auto-connect` as a substitute for the verified endpoint.

`run` passes the command after `--` to `agent-browser` with the verified `--cdp` endpoint, the requested `--session`, and `--pin-tab`. Use the current chat ID (with a project prefix) as the session name, or generate a UUID once and retain it throughout the task. Never use a fixed project-wide name for concurrent chats; the wrapper does not enforce chat ownership for identical session names. Use the version-matched agent-browser core skill for snapshots, navigation, forms, downloads, and other page actions.

`release` disconnects this task's agent-browser session only. It does not terminate Chrome, remove the profile, clear cookies, or discard the login state. Do not kill a shared browser to clean up a session.

## Profile and concurrency rules

- A profile is owned by one Chrome instance at a time. Reuse that instance or choose another profile; do not start a second Chrome against the same data directory.
- Treat the shared profile as a shared account and browser state. If one task must switch accounts or alter account-wide settings, give it a project-specific profile.
- Keep profile data outside repositories and do not commit it. Keep downloads in the project's configured `download_dir`.
- Do not promise cookie isolation from `--session` or `--pin-tab`; use a separate profile when isolation matters.
- Do not silently migrate existing exporters or browser workflows. Adopt this wrapper when a project is changed or a new browser workflow is added, preserving the project's existing constraints.

For the supported project configuration and examples, read `references/configuration.md`.
