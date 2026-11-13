"""
Per-module metrics catalog: a `metrics.yaml` next to a module's code that describes each
column once (label, description, format, range, colour scale), so tables, General Statistics
and plots read the same definition instead of repeating header dicts.

File shape:

    <table>:
      <column>:
        label: Concordance
        description: Fraction of markers that agree
        fmt: pct2
        range: [0, 100]
        scale: RdYlGn
        general_stats: true
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Literal, Optional, Tuple, Union

import yaml
from pydantic import BaseModel, ConfigDict, RootModel, field_validator

FORMAT_CODE_RE = re.compile(r"^(num|pct|mult)([0-4])$")
FORMAT_CODE_SUFFIX = {"num": "", "pct": "%", "mult": "x"}


def parse_format_code(fmt: str) -> Tuple[int, str]:
    """Return (decimals, suffix) for a format code such as `pct2` or `num0`."""
    match = FORMAT_CODE_RE.match(fmt)
    if not match:
        raise ValueError(f'"{fmt}" is not a format code (expected num0-4, pct0-4 or mult0-4)')
    kind, decimals = match.groups()
    return int(decimals), FORMAT_CODE_SUFFIX[kind]


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    description: Optional[str] = None
    fmt: Optional[str] = None
    range: Optional[Tuple[float, float]] = None
    scale: Optional[Union[str, Literal[False]]] = None
    hidden: bool = False
    general_stats: bool = False

    @field_validator("fmt")
    @classmethod
    def _check_fmt(cls, fmt: Optional[str]) -> Optional[str]:
        if fmt is not None:
            parse_format_code(fmt)
        return fmt


class MetricsCatalog(RootModel[Dict[str, Dict[str, Metric]]]):
    """Metrics keyed by table name, then column name."""


@lru_cache(maxsize=None)
def load(path: Path) -> MetricsCatalog:
    with path.open() as fh:
        data = yaml.safe_load(fh)
    try:
        return MetricsCatalog.model_validate(data)
    except ValueError as e:
        raise ValueError(f"Invalid metrics catalog {path}:\n{e}") from e
