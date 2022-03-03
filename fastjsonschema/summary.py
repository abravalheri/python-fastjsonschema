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
                f"non-predefined acceptable {self._jargon('property names')}"
            ),
            "patternProperties": f"{self._jargon('properties')} named via pattern",
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
        self, schema: Union[dict, list], prefix: str = "", *, _path: List[str] = []
    ) -> str:
        if isinstance(schema, list):
            return self._handle_list(schema, prefix, _path)

        filtered = self._filter_unecessary(schema)
        simple = self._handle_simple_dict(filtered, _path)
        if simple:
            return f"{prefix}{simple}"

        child_prefix = self._child_prefix(prefix, "  ")
        item_prefix = self._child_prefix(prefix, "- ")
        indent = len(prefix) * " "
        with io.StringIO() as buffer:
            for i, (key, value) in enumerate(filtered.items()):
                child_path = [*_path, key]
                buffer.write(f"{prefix if i == 0 else indent}{self._label(child_path)}:")
                # ^  just the first item should receive the complete prefix
                if isinstance(value, dict):
                    filtered = self._filter_unecessary(value)
                    simple = self._handle_simple_dict(filtered, child_path)
                    buffer.write(
                        f" {simple}"
                        if simple
                        else f"\n{self(value, child_prefix, _path=child_path)}"
                    )
                elif isinstance(value, list):
                    children = self._handle_list(value, item_prefix, child_path)
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

    def _handle_simple_dict(self, value: dict, path: List[str]) -> Optional[str]:
        inline = any(p in value for p in self._guess_inline_defs)
        simple = not any(isinstance(v, (list, dict)) for v in value.values())
        if inline or simple:
            return f"{{{', '.join(self._inline_attrs(value, path))}}}\n"
        return None

    def _handle_list(
        self, schemas: list, prefix: str = "", path: List[str] = []
    ) -> str:
        repr_ = repr(schemas)
        if all(not isinstance(e, (dict, list)) for e in schemas) and len(repr_) < 60:
            return f"{repr_}\n"

        item_prefix = self._child_prefix(prefix, "- ")
        return "".join(
            self(v, item_prefix, _path=[*path, f"[{i}]"]) for i, v in enumerate(schemas)
        )

    def _is_property(self, path: List[str]):
        """Check if the given path can correspond to an arbitrarily named property"""
        if not path:
            return False

        counter = 0
        for key in path[-2::-1]:
            if key not in {"properties", "patternProperties"}:
                break
            counter += 1

        # If the counter if even, the path correspond to a JSON Schema keyword
        # otherwise it can be any arbitrary string naming a property
        return counter % 2 == 1

    def _label(self, path: List[str]) -> str:
        *parents, key = path
        if not self._is_property(path):
            norm_key = separate_terms(key)
            return self._terms.get(key) or " ".join(self._jargon(k) for k in norm_key)

        if parents[-1] == "patternProperties":
            return f"(regex {key!r})"
        return repr(key)  # property name

    def _value(self, value: Any, path: List[str]) -> str:
        if not self._is_property(path) and path[-1] == "type":
            return self._jargon(value)
        return repr(value)

    def _inline_attrs(self, schema: dict, path: List[str]) -> str:
        for key, value in schema.items():
            child_path = [*path, key]
            yield f"{self._label(child_path)}: {self._value(value, child_path)}"

    def _child_prefix(self, parent_prefix: str, child_prefix: str) -> str:
        return len(parent_prefix) * " " + child_prefix


def separate_terms(word: str) -> Iterator[str]:
    """
    >>> separate_terms("FooBar-foo")
    "foo bar foo"
    """
    return (w.lower() for w in _CAMEL_CASE_SPLITTER.split(word) if w)
