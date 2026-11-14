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

import inspect
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Set, Tuple, Union

import yaml
from pydantic import BaseModel, ConfigDict, RootModel, field_validator

FORMAT_CODE_RE = re.compile(r"^(num|pct|mult)([0-4])$")
FORMAT_CODE_SUFFIX = {"num": "", "pct": "%", "mult": "x"}

# Count codes map to the table's existing `shared_key` presets, which scale values by the
# user's `*_count_multiplier` and add `*_count_prefix` as the suffix.
COUNT_SHARED_KEYS = {"reads": "read_count", "long_reads": "long_read_count", "bases": "base_count"}


def parse_format_code(fmt: str) -> Tuple[int, str]:
    """Return (decimals, suffix) for a numeric format code such as `pct2` or `num0`."""
    match = FORMAT_CODE_RE.match(fmt)
    if not match:
        raise ValueError(
            f'"{fmt}" is not a format code (expected num0-4, pct0-4, mult0-4, {", ".join(COUNT_SHARED_KEYS)})'
        )
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
        if fmt is not None and fmt not in COUNT_SHARED_KEYS:
            parse_format_code(fmt)
        return fmt


class MetricsCatalog(RootModel[Dict[str, Dict[str, Metric]]]):
    """Metrics keyed by table name, then column name."""


# (catalog path, table, use) for every table a module has looked up, where use is "columns"
# (metric_headers) or "axis" (metric_pconfig). Read by `multiqc validate`.
tables_used: Set[Tuple[Path, str, Literal["columns", "axis"]]] = set()


def path_for(module_obj: Any) -> Path:
    """The metrics.yaml next to the source file of a module class or entry point function."""
    return Path(inspect.getfile(module_obj)).with_name("metrics.yaml")


@lru_cache(maxsize=None)
def load(path: Path) -> MetricsCatalog:
    with path.open() as fh:
        data = yaml.safe_load(fh)
    try:
        return MetricsCatalog.model_validate(data)
    except ValueError as e:
        raise ValueError(f"Invalid metrics catalog {path}:\n{e}") from e
