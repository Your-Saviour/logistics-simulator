"""Published adapter JSON Schema must reject the same invalid commands as runtime."""
import copy
import json
from pathlib import Path
from uuid import uuid4
import jsonschema
import pytest
from pydantic import ValidationError
from simulator.adapter_protocol import Command,PAYLOADS


def validate_runtime(raw):
    command=Command.model_validate(raw)
    PAYLOADS[command.operation].model_validate(command.payload)


def test_published_adapter_schema_rejects_wrong_version_units_epoch_and_unknown_fields():
    schema=json.loads(Path('contracts/adapter/v1/command.schema.json').read_text())
    validator=jsonschema.Draft202012Validator(schema,format_checker=jsonschema.FormatChecker())
    good={'version':'1.0','request_id':str(uuid4()),'run_id':str(uuid4()),'epoch':str(uuid4()),'session_id':str(uuid4()),
          'operation':'publish_value','payload':{'value':2,'unit':'item'}}
    validate_runtime(good);validator.validate(good)
    invalid=[]
    for changes in ({'version':'2.0'},{'epoch':'not-a-uuid'},{'unexpected':True},{'operation':'secret-operation'},
                    {'payload':{'value':2,'unit':'kg'}},{'payload':{'value':2,'unit':'item','secret':True}}):
        invalid.append({**copy.deepcopy(good),**changes})
    for command in invalid:
        with pytest.raises(ValidationError): validate_runtime(command)
        assert list(validator.iter_errors(command))
