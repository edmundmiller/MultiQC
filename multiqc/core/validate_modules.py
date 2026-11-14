"""
`multiqc validate`: check that a module's metrics.yaml agrees with what the module parses from
its test data, and report each problem with a file and line an author or agent can act on.

Checks, per module:
- metrics.yaml matches the catalog schema (known keys, valid format codes, required labels)
- every search pattern of the module matches at least one test-data file
- the module finds samples in its test data and runs without error
- every column of a table the module displays through the catalog is one the module parses
- every parsed column of such a module has a metrics.yaml entry (warning)
- every table in metrics.yaml is used by the module (warning)
"""

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

import click
import yaml
from pydantic import ValidationError

from multiqc import config, report
from multiqc.base_module import ModuleNoSamplesFound
from multiqc.core import metrics_catalog

SEARCH_PATTERNS_PATH = config.MODULE_DIR / "search_patterns.yaml"


@dataclass
class Finding:
    level: Literal["error", "warning"]
    location: str
    message: str


def validate_module(module_id: str, data_dir: Path) -> List[Finding]:
    """Validate one module against the test data in `data_dir/modules/<module_id>`."""
    module_cls = config.avail_modules[module_id].load()
    path = metrics_catalog.path_for(module_cls)
    lines = _key_lines(path)

    def at(*keys: str) -> str:
        """`path:line` of the deepest key in metrics.yaml that exists."""
        for depth in range(len(keys), 0, -1):
            if keys[:depth] in lines:
                return f"{_display(path)}:{lines[keys[:depth]]}"
        return _display(path)

    try:
        catalog = metrics_catalog.MetricsCatalog.model_validate(yaml.safe_load(path.read_text()))
    except ValidationError as e:
        return [Finding("error", at(*map(str, err["loc"])), err["msg"]) for err in e.errors()]

    mod_dir = data_dir / "modules" / module_id
    if not mod_dir.is_dir():
        return [Finding("error", module_id, f"no test data at {mod_dir}")]

    config.reset()
    report.reset()
    config.quiet = True
    config.preserve_module_raw_data = True
    metrics_catalog.tables_used.clear()
    report.analysis_files = [str(mod_dir)]
    report.search_files([module_id])

    findings: List[Finding] = []
    sp_lines = _key_lines(SEARCH_PATTERNS_PATH)
    for sp_key in config.sp:
        if sp_key.split("/", 1)[0] == module_id and not report.files.get(sp_key):
            findings.append(
                Finding(
                    "error",
                    f"{_display(SEARCH_PATTERNS_PATH)}:{sp_lines.get((sp_key,), 0)}",
                    f'search pattern "{sp_key}" matched no files in {mod_dir}',
                )
            )

    try:
        instance = module_cls()
    except ModuleNoSamplesFound:
        return findings + [Finding("error", module_id, f"found no samples in {mod_dir}")]
    except Exception as e:
        return findings + [Finding("error", module_id, f"failed on {mod_dir}: {type(e).__name__}: {e}")]

    produced: Set[str] = set()
    for module in instance if isinstance(instance, list) else [instance]:
        for dataset in (module.saved_raw_data or {}).values():
            for row in dataset.values() if isinstance(dataset, dict) else []:
                if isinstance(row, dict):
                    produced.update(str(k) for k in row)

    used = {table for p, table, _ in metrics_catalog.tables_used if p == path}
    # Only tables shown through metric_headers() are tables of parsed columns; a table used
    # only for a plot axis (metric_pconfig) can describe a derived value.
    shown_as_columns = {table for p, table, use in metrics_catalog.tables_used if p == path and use == "columns"}
    for table, columns in catalog.root.items():
        if table not in used:
            findings.append(Finding("warning", at(table), f'table "{table}" is not used by the module'))
        if table not in shown_as_columns:
            continue
        for column in columns:
            if column not in produced:
                findings.append(
                    Finding(
                        "error",
                        at(table, column),
                        f'column "{column}" is not parsed from the test data '
                        f"(parsed: {', '.join(sorted(produced)) or 'nothing'})",
                    )
                )

    if shown_as_columns:
        described = {column for columns in catalog.root.values() for column in columns}
        for column in sorted(produced - described):
            findings.append(
                Finding(
                    "warning",
                    _display(path),
                    f'parsed column "{column}" has no metrics.yaml entry (add it, or mark it hidden)',
                )
            )

    return findings


def modules_with_catalog() -> List[str]:
    """IDs of the installed modules that ship a metrics.yaml."""
    found = []
    for module_id, entry_point in config.avail_modules.items():
        if module_id == "custom_content":
            continue
        if metrics_catalog.path_for(entry_point.load()).exists():
            found.append(module_id)
    return found


def _key_lines(path: Path) -> Dict[Tuple[str, ...], int]:
    """1-based line number of every mapping key in a YAML file, keyed by its key path."""
    lines: Dict[Tuple[str, ...], int] = {}

    def walk(node: Any, prefix: Tuple[str, ...]) -> None:
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                key = prefix + (str(key_node.value),)
                lines[key] = key_node.start_mark.line + 1
                walk(value_node, key)

    walk(yaml.compose(path.read_text()), ())
    return lines


def _display(path: Path) -> str:
    try:
        return os.path.relpath(path)
    except ValueError:  # different drive on Windows
        return str(path)


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("modules", nargs=-1)
@click.option(
    "--test-data",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Test data directory containing modules/<module_id>/. Default: $MULTIQC_TEST_DATA_DIR/data.",
)
@click.option("--json", "as_json", is_flag=True, help="Print findings as JSON.")
def validate_cli(modules: Tuple[str, ...], test_data: Optional[Path], as_json: bool):
    """
    Check each module's metrics.yaml against what the module parses from its test data.
    Without MODULES, checks every module that has a metrics.yaml.
    """
    from multiqc.utils import testing

    data_dir = test_data or testing.data_dir()
    module_ids = list(modules) or modules_with_catalog()
    unknown = [m for m in module_ids if m not in config.avail_modules]
    if unknown:
        raise click.BadParameter(f"unknown module(s): {', '.join(unknown)}", param_hint="MODULES")

    findings = {module_id: validate_module(module_id, data_dir) for module_id in module_ids}
    errors = sum(f.level == "error" for fs in findings.values() for f in fs)
    warnings = sum(f.level == "warning" for fs in findings.values() for f in fs)

    if as_json:
        out = {
            "modules": {m: [asdict(f) for f in fs] for m, fs in findings.items()},
            "errors": errors,
            "warnings": warnings,
        }
        click.echo(json.dumps(out, indent=2))
    else:
        for fs in findings.values():
            for f in fs:
                click.echo(f"{f.location}: {f.level}: {f.message}")
        click.echo(f"{errors} errors, {warnings} warnings in {len(findings)} modules")

    sys.exit(1 if errors else 0)
