import io
import re
from functools import partial
from collections.abc import Mapping
from itertools import chain
from textwrap import indent
from typing import Callable, List, Optional, Union, Any, Iterator

_CAMEL_CASE_SPLITTER = re.compile(r"\W+|([A-Z][^A-Z\W]*)")
_IDENTIFIER = re.compile(r"^[\w_]+$", re.I)

TOML_JARGON = {
    "object": "table",
    "property": "key",
    "properties": "keys",
    "property names": "keys",
}


class SummaryWriter:
    # """
    # >>> writer = SummaryWriter()
    # >>> writer({"enum": ["A", "B", "C"]})
    # "one of ['A', 'B', 'C']"
    # >>> writer({"const": 42})
    # 'specifically 42'
    # >>> writer({"not": {"type": "number"})
    # 'NOT ("negative" match):\n- a number'
    # >>> writer({"type": "number", "minimum": 3, "maximum": 4})
    # 'a number (minimum: 3, maximum: 4)'
    # >>> writer({"type": "string", "pattern": ".*"})
    # "a string (pattern: '.*')"
    # """

    _IGNORE = {"description", "default", "title", "examples"}

    def __init__(self, jargon: Optional[dict] = None):
        self.jargon = jargon or {}
        # Clarify confusing terms
        self._terms = {
            "anyOf": "at least one of the following",
            "oneOf": "exactly one of the following",
            "allOf": "all of the following",
            "not": "(*NOT* the following)",
            "prefixItems": f"{self._jargon('items')} (in order)",
            "items": "items",
            "contains": "contains at least one of",
            "propertyNames": (
                "non-predefined acceptable "
                f"{self._jargon('property names')}"
            ),
            "patternProperties": (
                f"{self._jargon('properties')} named via pattern"
            ),
            "const": "predefined value",
        }
        # Attributes that indicate that the definition is easy and can be done
        # inline (e.g. string and number)
        self._guess_inline_defs = [
            "enum",
            "const",
            "maxLength",
            "minLength",
            "pattern",
            "format",
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "exclusiveMaximum",
            "multipleOf",
        ]

    def _jargon(self, term: str) -> str:
        return self.jargon.get(term, term)

    def __call__(
        self, schema: Union[dict, list], prefix: str = "", *, _parent: str = ""
    ) -> str:
        if isinstance(schema, list):
            return self._handle_list(schema, prefix, _parent)

        filtered = self._filter_unecessary(schema)
        simple = self._handle_simple_dict(filtered, _parent)
        if simple:
            return f"{prefix}{simple}"

        child_prefix = self._child_prefix(prefix, "  ")
        item_prefix = self._child_prefix(prefix, "- ")
        with io.StringIO() as buffer:
            for key, value in filtered.items():
                buffer.write(f"{prefix}{self._label(key, _parent)}:")
                if isinstance(value, dict):
                    filtered = self._filter_unecessary(value)
                    simple = self._handle_simple_dict(filtered, key)
                    buffer.write(
                        f" {simple}"
                        if simple
                        else f"\n{self(value, child_prefix, _parent=key)}"
                    )
                elif isinstance(value, list):
                    children = self._handle_list(value, item_prefix, key)
                    sep = " " if children.startswith("[") else "\n"
                    buffer.write(f"{sep}{children}")
                else:
                    buffer.write(f" {value!r}\n")
            return buffer.getvalue()

    def _filter_unecessary(self, schema: dict):
        return {
            key: value
            for key, value in schema.items()
            if not (any(key.startswith(k) for k in "$_") or key in self._IGNORE)
        }

    def _handle_simple_dict(self, value: dict, parent: str) -> Optional[str]:
        inline = any(p in value for p in self._guess_inline_defs)
        simple = not any(isinstance(v, (list, dict)) for v in value.values())
        if inline or simple:
            return f"{{{', '.join(self._inline_attrs(value, parent))}}}\n"
        return None

    def _handle_list(self, schemas: list, prefix: str = "", parent: str = "") -> str:
        repr_ = repr(schemas)
        if all(not isinstance(e, (dict, list)) for e in schemas) and len(repr_) < 60:
            return f"{repr_}\n"

        item_prefix = self._child_prefix(prefix, "- ")
        return "".join(self(v, item_prefix, _parent=parent) for v in schemas)

    def _label(self, key: str, parent: str) -> str:
        if parent == "patternProperties":
            return f"(regex {key!r})"
        if parent == "properties":
            return key
        norm_key = separate_terms(key)
        return self._terms.get(key) or " ".join(self._jargon(k) for k in norm_key)

    def _value(self, value: Any, key: str) -> str:
        return self._jargon(value) if key == "type" else repr(value)

    def _inline_attrs(self, schema: dict, parent: str) -> str:
        for key, value in schema.items():
            yield f"{self._label(key, parent)}: {self._value(value, key)}"

    def _child_prefix(self, parent_prefix: str, child_prefix: str) -> str:
        return len(parent_prefix) * " " + child_prefix


def separate_terms(word: str) -> Iterator[str]:
    """
    >>> separate_terms("FooBar-foo")
    "foo bar foo"
    """
    return (w.lower() for w in _CAMEL_CASE_SPLITTER.split(word) if w)
