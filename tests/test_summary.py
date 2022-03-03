"""Test summary generation from schema examples"""
import json
from pathlib import Path

import pytest

from fastjsonschema.summary import SummaryWriter

HERE = Path(__file__).parent
EXAMPLES = (HERE / "summary").glob("*")


def load_example(file):
    text = file.read_text(encoding="utf-8")
    schema, _, summary = text.partition("# - # - # - #\n")

    return json.loads(schema), summary


@pytest.mark.parametrize("example", EXAMPLES)
def test_summary_generation(example):
    schema, expected = load_example(example)
    summarize = SummaryWriter()
    summary = summarize(schema)
    assert summary == expected
