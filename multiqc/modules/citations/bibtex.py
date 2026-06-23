"""Parse BibTeX (.bib) citations into the shared Citation model.

BibTeX is an optional alternative input to CSL-JSON. A small reader handles the
entry shape that pipelines emit (one `@type{key, field = {value}, ...}` block
per tool). It is not a general-purpose BibTeX parser: it does not resolve
`@string` macros or string concatenation, and skips `@comment`/`@preamble`/
`@string` blocks. Keeping it self-contained means the citations module adds no
dependency; tools that only have a DOI can reach the canonical CSL-JSON format
via DOI content negotiation instead.

BibTeX has no standard field for the tool name or the runtime version, so:

- tool name comes from a `tool` field if present, else the entry citation key;
- runtime version comes from a non-standard `version` field if present.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from .citation import Authors, Citation, clean_doi

log = logging.getLogger(__name__)

_AND_SPLIT = re.compile(r"\s+and\s+", flags=re.IGNORECASE)
_ENTRY_START = re.compile(r"@(\w+)\s*\{")

# BibTeX constructs that define macros or metadata rather than a citation entry.
_NON_ENTRY_TYPES = {"comment", "preamble", "string"}


def _read_balanced(text: str, open_idx: int) -> Tuple[str, int]:
    """`text[open_idx]` is `{`; return (inner text, index past the matching `}`)."""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : i], i + 1
    raise ValueError("unbalanced braces")


def _split_top_level_commas(text: str) -> List[str]:
    """Split on commas that sit outside any `{...}` group or `"..."` string."""
    parts: List[str] = []
    depth = 0
    in_quote = False
    start = 0
    for i, c in enumerate(text):
        if c == '"' and depth == 0:
            in_quote = not in_quote
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "," and depth == 0 and not in_quote:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def _strip_value_delimiters(raw: str) -> str:
    """Drop the outer `{...}` or `"..."` around a field value, if present."""
    if len(raw) >= 2 and raw[0] == "{" and raw[-1] == "}":
        return raw[1:-1]
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1]
    return raw


def _parse_entry(entrytype: str, body: str) -> Dict[str, str]:
    """Turn an entry body (`key, name = value, ...`) into a field dict.

    Field names are lowercased; `ENTRYTYPE` and `ID` mirror the keys the rest of
    the module expects.
    """
    chunks = _split_top_level_commas(body)
    entry: Dict[str, str] = {"ENTRYTYPE": entrytype, "ID": chunks[0].strip()}
    for chunk in chunks[1:]:
        name, sep, raw = chunk.partition("=")
        if not sep:
            continue
        entry[name.strip().lower()] = _strip_value_delimiters(raw.strip())
    return entry


def _tokenize(content: str) -> List[Dict[str, str]]:
    """Read BibTeX content into a list of entry field dicts."""
    entries: List[Dict[str, str]] = []
    pos = 0
    for m in _ENTRY_START.finditer(content):
        if m.start() < pos:
            continue  # this `@...{` sits inside a value we already consumed
        entrytype = m.group(1).lower()
        body, pos = _read_balanced(content, m.end() - 1)
        if entrytype in _NON_ENTRY_TYPES:
            continue
        entries.append(_parse_entry(entrytype, body))
    return entries


def _debrace(value: Optional[str]) -> Optional[str]:
    """Strip BibTeX grouping braces and collapse whitespace."""
    if value is None:
        return None
    return re.sub(r"\s+", " ", value.replace("{", "").replace("}", "")).strip() or None


def _split_bibtex_name(name: str) -> Tuple[str, str]:
    """Split a single BibTeX name into (surname, given), per BibTeX semantics.

    "Andrews, S" -> ("Andrews", "S"); "Heng Li" -> ("Li", "Heng").
    """
    if "," in name:
        last, _, given = name.partition(",")
        return last.strip(), given.strip()
    parts = name.split()
    if len(parts) <= 1:
        return name.strip(), ""
    return parts[-1], " ".join(parts[:-1])


def _normalize_bibtex_authors(field: Optional[str]) -> Authors:
    """Normalise a BibTeX `author` value to an `Authors`."""
    field = _debrace(field)
    if not field:
        return Authors.from_names([], False)

    raw_names = [n.strip() for n in _AND_SPLIT.split(field) if n.strip()]
    has_etal = any(n.lower() == "others" for n in raw_names)  # BibTeX "and others"
    raw_names = [n for n in raw_names if n.lower() != "others"]

    names: List[Tuple[str, str]] = []
    for name in raw_names:
        last, given = _split_bibtex_name(name)
        names.append((last, f"{last} {given}".strip() if given else last))

    return Authors.from_names(names, has_etal)


def _entry_to_citation(entry: Dict[str, str]) -> Citation:
    tool = _debrace(entry.get("tool")) or entry.get("ID")
    if not tool:
        raise ValueError(f"BibTeX entry is missing both a `tool` field and a citation key: {entry!r}")

    year: Optional[int] = None
    raw_year = _debrace(entry.get("year"))
    if raw_year:
        match = re.search(r"\d{4}", raw_year)
        if match:
            year = int(match.group())

    return Citation(
        tool=str(tool),
        version=_debrace(entry.get("version")),
        title=_debrace(entry.get("title")),
        authors=_normalize_bibtex_authors(entry.get("author")),
        year=year,
        container_title=_debrace(entry.get("journal")) or _debrace(entry.get("booktitle")),
        doi=clean_doi(_debrace(entry.get("doi"))),
        url=_debrace(entry.get("url")) or _debrace(entry.get("howpublished")),
        csl_type=entry.get("ENTRYTYPE"),
    )


def parse_bibtex(content: str, fn: str = "<citations>") -> List[Citation]:
    """Parse BibTeX file content into Citations.

    Raises ValueError with the file path on a parse failure.
    """
    try:
        entries = _tokenize(content)
    except ValueError as exc:
        raise ValueError(f"Could not parse BibTeX citations file '{fn}': {exc}") from exc

    return [_entry_to_citation(entry) for entry in entries]
