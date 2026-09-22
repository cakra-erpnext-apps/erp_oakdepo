#!/usr/bin/env python3
import json
import subprocess
import sys

with open('/tmp/apps.json') as f:
    apps = json.load(f)

for app in apps:
    name = app['name']
    url = app['url']
    branch = app['branch']
    commit = app.get('commit')
    print('=' * 80, flush=True)
    print(f'Installing app source: {name}', flush=True)
    print(f'URL    : {url}', flush=True)
    print(f'Branch : {branch}', flush=True)
    if commit:
        print(f'Commit : {commit}', flush=True)
    print('=' * 80, flush=True)
    try:
        subprocess.check_call([
            'bench',
            'get-app',
            '--skip-assets',
            '--branch',
            branch,
            url,
        ])
        if commit:
            subprocess.check_call(['git', '-C', f'apps/{name}', 'checkout', commit])
    except subprocess.CalledProcessError as e:
        print('=' * 80, flush=True)
        print(f'FAILED installing app: {name}', flush=True)
        print(f'URL       : {url}', flush=True)
        print(f'Branch    : {branch}', flush=True)
        if commit:
            print(f'Commit    : {commit}', flush=True)
        print(f'Exit code : {e.returncode}', flush=True)
        print('=' * 80, flush=True)
        sys.exit(e.returncode)
