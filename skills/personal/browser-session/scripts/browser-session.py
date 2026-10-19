#!/usr/bin/env python3
"""Manage dedicated macOS Chrome profiles and explicit agent-browser connections."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')


def resolve(value, base):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def settings(args):
    project = Path(args.project).expanduser().resolve()
    config_path = project / '.browser-session.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    if not isinstance(config, dict) or set(config) - {'profile', 'download_dir'}:
        raise ValueError('Project config accepts only profile and download_dir')
    for value in config.values():
        if not isinstance(value, str) or not value:
            raise ValueError('Config values must be nonempty paths')
    profile = resolve(args.profile or config.get('profile', '~/.agent-browser/profiles/shared'), project)
    daily = Path('~/Library/Application Support/Google/Chrome').expanduser().resolve()
    if profile == daily or daily in profile.parents:
        raise ValueError('Use a dedicated user-data directory outside everyday Chrome')
    if args.action in {'run', 'release'} and not args.session:
        raise ValueError('--session is required for run/release; use a unique name per chat')
    session = args.session or 'project-' + hashlib.sha256(str(project).encode()).hexdigest()[:12]
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', session):
        raise ValueError('Session must be 1-80 letters, digits, underscores or hyphens')
    key = hashlib.sha256(str(profile).encode()).hexdigest()[:16]
    runtime = Path('/tmp') / f'kb-{os.getuid()}' / key
    return project, profile, session, runtime, config


def chrome_process(profile):
    result = subprocess.run(['ps', '-axo', 'pid=,args='], capture_output=True, text=True, check=True)
    marker = f'--user-data-dir={profile}'
    for line in result.stdout.splitlines():
        if str(CHROME) in line and marker in line:
            tail = line.split(marker, 1)[1]
            if not tail or tail[0].isspace():
                return int(line.strip().split(None, 1)[0])
    return None



def endpoint(profile):
    pid = chrome_process(profile)
    if not pid:
        return None
    try:
        lines = (profile / 'DevToolsActivePort').read_text().splitlines()
        port = int(lines[0])
        if not 1 <= port <= 65535 or not lines[1].startswith('/devtools/browser/'):
            return None
        listener = subprocess.run(['/usr/sbin/lsof', '-nP', '-a', '-p', str(pid),
                                   f'-iTCP:{port}', '-sTCP:LISTEN'],
                                  capture_output=True, text=True, timeout=3)
        if listener.returncode != 0 or not listener.stdout.strip():
            return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/json/version', timeout=1) as response:
            info = json.load(response)
        ws = info.get('webSocketDebuggerUrl', '')
        if ws != f'ws://127.0.0.1:{port}{lines[1]}' and ws != f'ws://localhost:{port}{lines[1]}':
            return None
        if not info.get('Browser', '').startswith('Chrome/'):
            return None
        return f'http://127.0.0.1:{port}'
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def ensure(profile, runtime):
    if not CHROME.is_file():
        raise ValueError(f'Ordinary Chrome not found: {CHROME}')
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (runtime / 'launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        active = endpoint(profile)
        if active:
            return active
        if chrome_process(profile):
            raise ValueError('Profile is running but CDP is unavailable; do not launch another instance')
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (profile / 'SingletonLock').is_symlink() or (profile / 'SingletonLock').exists():
            raise ValueError('Profile is locked; inspect its owner before restarting (locks are never removed)')
        with (runtime / 'chrome.log').open('ab') as log:
            subprocess.Popen([str(CHROME), f'--user-data-dir={profile}',
                              '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
                              '--no-first-run', '--no-default-browser-check', 'about:blank'],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            active = endpoint(profile)
            if active:
                return active
            time.sleep(0.2)
        raise ValueError(f'Chrome did not expose CDP within 20s; inspect {runtime / "chrome.log"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default=os.getcwd())
    parser.add_argument('--profile')
    parser.add_argument('--session')
    parser.add_argument('action', choices=['plan', 'ensure', 'run', 'release'])
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    project, profile, session, runtime, config = settings(args)
    if args.action == 'plan':
        print(json.dumps({'project': str(project), 'profile': str(profile), 'session': session,
                          'chrome': str(CHROME), 'runtime': str(runtime),
                          'download_dir': str(resolve(config['download_dir'], project)) if 'download_dir' in config else None}, indent=2))
        return 0
    command = args.command
    if command[:1] == ['--']:
        command = command[1:]
    if args.action == 'run':
        if not command or command[0].startswith('-'):
            raise ValueError('run requires a browser command after --')
        if command[0] in {'close', 'connect', 'install', 'upgrade', 'batch', 'session', 'chat', 'mcp'}:
            raise ValueError('Lifecycle/global commands are not supported through run; use release for disconnect')
        forbidden = {'--cdp', '--auto-connect', '--session', '--profile', '--config', '--namespace', '--provider', '-p', '--executable-path', '--no-pin-tab', '--pin-tab', '--args', '--extension'}
        if any(part.split('=')[0] in forbidden for part in command):
            raise ValueError('Do not override wrapper connection/session options')
    if args.action == 'release':
        if not runtime.exists():
            return 0
        active = None  # Never start or attach a browser just to release a session.
        command = ['close']
    else:
        active = ensure(profile, runtime)
    if args.action == 'ensure':
        print(json.dumps({'profile': str(profile), 'endpoint': active}))
        return 0
    binary = shutil.which('agent-browser')
    if not binary:
        raise ValueError('agent-browser is not installed')
    empty_config = runtime / 'agent-browser.json'
    empty_config.write_text('{}\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith('AGENT_BROWSER_')}
    env['AGENT_BROWSER_SOCKET_DIR'] = str(runtime)
    env['AGENT_BROWSER_NAMESPACE'] = 'p-' + runtime.name[:8]
    agent_session = session[:12] + '-' + hashlib.sha256(session.encode()).hexdigest()[:12]
    options = [binary, '--config', str(empty_config), '--session', agent_session]
    if active:
        options += ['--cdp', active, '--pin-tab', '--content-boundaries']
        if 'download_dir' in config:
            download = resolve(config['download_dir'], project)
            download.mkdir(parents=True, exist_ok=True)
            options += ['--download-path', str(download)]
    return subprocess.run(options + command, env=env, cwd=project).returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f'browser-session: {error}', file=sys.stderr)
        sys.exit(1)
