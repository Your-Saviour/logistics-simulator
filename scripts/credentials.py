#!/usr/bin/env python3
"""Explicit local credential display; never run in CI logs."""
import json
from pathlib import Path
import sys

app=sys.argv[1]
if app not in ('manufacturing','storage','logistics','shipping','twin'):
    raise SystemExit('Choose a single application')
path=Path(__file__).resolve().parents[1]/'deploy'/'generated'/(app+'.secrets.json')
role=sys.argv[2] if len(sys.argv)>2 else 'operator'
keys={'operator':'application','employee':'employee','observer':'observer'}
if role not in keys: raise SystemExit('Choose operator, employee or observer')
print('Username:',app+'-'+role)
print('Password:',json.loads(path.read_text())[keys[role]])
