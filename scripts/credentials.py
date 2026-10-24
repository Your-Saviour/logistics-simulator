#!/usr/bin/env python3
"""Explicit local credential display; never run in CI logs."""
import json
from pathlib import Path
import sys

app=sys.argv[1]
if app not in ('manufacturing','storage','logistics','shipping','twin'):
    raise SystemExit('Choose a single application')
path=Path(__file__).resolve().parents[1]/'deploy'/'generated'/(app+'.secrets.json')
print('Username:', app+'-operator')
print('Password:',json.loads(path.read_text())['application'])
