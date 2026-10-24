#!/usr/bin/env python3
"""Check published schemas match runtime models, then validate real fixtures."""
import argparse
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from simulator.contracts import Envelope
from simulator.providers import SeededInput

ROOT=Path(__file__).resolve().parents[1]
MODELS={'sample.completed':Envelope,'seeded-input':SeededInput}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--write',action='store_true');args=parser.parse_args()
    for name,model in MODELS.items():
        path=ROOT/'contracts/v1'/(name+'.schema.json')
        expected=model.model_json_schema()
        if args.write:
            path.write_text(json.dumps(expected,indent=2)+'\n')
        published=json.loads(path.read_text())
        assert published==expected, f'{name}: published schema drifted from its runtime model'
        Draft202012Validator.check_schema(published)
        validator=Draft202012Validator(published,format_checker=FormatChecker())
        valid=json.loads((ROOT/'contracts/v1/fixtures'/(name+'.json')).read_text())
        validator.validate(valid)
        model.model_validate(valid)
        invalid={**valid,'quantity':-1} if name=='seeded-input' else {**valid,'type':'analytics.sample.v1'}
        try:
            validator.validate(invalid)
        except ValidationError:
            pass
        else:
            raise AssertionError(name+': accepted an invalid/analytics fixture')
        print(name+': schema, runtime parity, valid and rejected fixtures passed')


if __name__=='__main__':
    main()
