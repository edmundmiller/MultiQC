import importlib.util
import sys

import pytest

from multiqc import config

METRICS_YAML = """
tbl:
  pct_dup:
    label: Duplicates
    description: Fraction of duplicate reads
    fmt: pct1
    range: [0, 100]
    scale: OrRd
    general_stats: true
  coverage:
    label: Coverage
    fmt: mult2
    hidden: true
"""


def _module_with_catalog(tmp_path, metrics_yaml):
    """A module class whose source file sits next to the given metrics.yaml."""
    (tmp_path / "metrics.yaml").write_text(metrics_yaml)
    (tmp_path / "mod.py").write_text(
        "from multiqc.base_module import BaseMultiqcModule\nclass MultiqcModule(BaseMultiqcModule):\n    pass\n"
    )
    name = f"mod_{tmp_path.name}"
    spec = importlib.util.spec_from_file_location(name, tmp_path / "mod.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod.MultiqcModule.__new__(mod.MultiqcModule)  # helpers need no parsing state


def test_metric_headers(tmp_path):
    module = _module_with_catalog(tmp_path, METRICS_YAML)

    assert module.metric_headers("tbl") == {
        "pct_dup": {
            "title": "Duplicates",
            "description": "Fraction of duplicate reads",
            "hidden": False,
            "format": "{:,.1f}",
            "suffix": "%",
            "min": 0,
            "max": 100,
            "scale": "OrRd",
        },
        "coverage": {"title": "Coverage", "hidden": True, "format": "{:,.2f}", "suffix": "x"},
    }
    assert list(module.metric_headers("tbl", general_stats=True)) == ["pct_dup"]
    assert module.metric_pconfig("tbl", "pct_dup") == {
        "ylab": "Duplicates",
        "tt_decimals": 1,
        "ysuffix": "%",
        "ymin": 0,
        "ymax": 100,
    }


COUNTS_YAML = """
tbl:
  total:
    label: Reads
    description: Total reads
    fmt: reads
  kept:
    label: Bases kept
    fmt: bases
"""


def test_count_codes_follow_user_config(tmp_path):
    config.read_count_prefix, config.read_count_desc = "K", "thousands"
    config.base_count_prefix, config.base_count_desc = "Gb", "billions"
    module = _module_with_catalog(tmp_path, COUNTS_YAML)

    assert module.metric_headers("tbl") == {
        "total": {
            "title": "K Reads",
            "description": "Total reads (thousands)",
            "hidden": False,
            "shared_key": "read_count",
        },
        "kept": {
            "title": "Gb Bases kept",
            "description": "Bases kept (billions)",
            "hidden": False,
            "shared_key": "base_count",
        },
    }
    assert module.metric_pconfig("tbl", "total") == {"ylab": "Reads", "tt_decimals": 0}


def test_count_codes_without_prefix_keep_label(tmp_path):
    config.read_count_prefix = ""
    module = _module_with_catalog(tmp_path, COUNTS_YAML)

    assert module.metric_headers("tbl")["total"] == {
        "title": "Reads",
        "description": "Total reads",
        "hidden": False,
        "shared_key": "read_count",
    }


@pytest.mark.parametrize(
    "metrics_yaml, error",
    [
        ("tbl:\n  a:\n    label: A\n    fmt: pct9\n", "is not a format code"),
        ("tbl:\n  a:\n    label: A\n    fmt: read\n", "is not a format code"),
        ("tbl:\n  a:\n    label: A\n    colour: red\n", "colour"),
        ("tbl:\n  a:\n    fmt: num0\n", "label"),
    ],
)
def test_invalid_catalog_fails_loudly(tmp_path, metrics_yaml, error):
    module = _module_with_catalog(tmp_path, metrics_yaml)
    with pytest.raises(ValueError, match=error):
        module.metric_headers("tbl")


def test_unknown_table(tmp_path):
    module = _module_with_catalog(tmp_path, METRICS_YAML)
    with pytest.raises(KeyError, match='"other" is not defined'):
        module.metric_headers("other")
