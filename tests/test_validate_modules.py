import shutil

import pytest

from multiqc import config
from multiqc.core import metrics_catalog
from multiqc.core.validate_modules import modules_with_catalog, validate_module


def _quoted_names(findings):
    return {f.message.split('"')[1] for f in findings}


def test_catalog_modules_pass(data_dir):
    module_ids = modules_with_catalog()
    assert {"conpair", "kat", "leehom", "percolator"} <= set(module_ids)

    for module_id in module_ids:
        findings = validate_module(module_id, data_dir)
        assert [f for f in findings if f.level == "error"] == [], module_id

    # Conpair parses marker counts and thresholds that its metrics.yaml does not describe
    assert _quoted_names(validate_module("conpair", data_dir)) == {
        "concordance_marker_threshold",
        "concordance_min_base_quality",
        "concordance_min_mapping_quality",
        "concordance_total_markers",
        "concordance_used_markers",
    }


@pytest.mark.parametrize(
    "old, new, line, message",
    [
        ("contamination_tumor:", "contamination_tumour:", 15, '"contamination_tumour" is not parsed'),
        ("fmt: pct2", "fmt: pct22", 4, '"pct22" is not a format code'),
    ],
)
def test_catalog_problems_point_at_the_line(tmp_path, monkeypatch, data_dir, old, new, line, message):
    original = metrics_catalog.path_for(config.avail_modules["conpair"].load())
    broken = tmp_path / "metrics.yaml"
    broken.write_text(original.read_text().replace(old, new))
    monkeypatch.setattr(metrics_catalog, "path_for", lambda _: broken)

    errors = [f for f in validate_module("conpair", data_dir) if f.level == "error"]

    assert len(errors) == 1
    assert errors[0].location.endswith(f"metrics.yaml:{line}")
    assert message in errors[0].message


def test_search_pattern_without_test_files(tmp_path, data_dir):
    shutil.copytree(data_dir / "modules" / "conpair" / "concordance", tmp_path / "modules" / "conpair" / "concordance")

    errors = [f for f in validate_module("conpair", tmp_path) if f.level == "error"]

    assert "search_patterns.yaml:" in errors[0].location
    assert 'search pattern "conpair/contamination" matched no files' in errors[0].message
    # Without contamination logs, the contamination columns are not parsed either
    assert _quoted_names(errors[1:]) == {"contamination_normal", "contamination_tumor"}
