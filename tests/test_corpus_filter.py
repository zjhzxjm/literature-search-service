import hashlib
import json
from pathlib import Path
import struct

import pytest

from literature_search_service import corpus_filter


def source_inputs(tmp_path: Path):
    text = (
        "0\tAlpha cancer study. Biomarker response.\n"
        "1\tbeta diabetes cohort. Insulin response.\n"
        "2\tALPHA metabolism. Diabetes and cancer overlap.\n"
    ).encode()
    mapping_bytes = struct.pack("<QQQQQQ", 0, 101, 1, 202, 2, 303)
    collection = tmp_path / "collection.tsv"
    mapping = tmp_path / "id-pmid.u64"
    expected_path = tmp_path / "expected.json"
    collection.write_bytes(text)
    mapping.write_bytes(mapping_bytes)
    expected = {
        "records": 3,
        "collection_sha256": hashlib.sha256(text).hexdigest(),
        "mapping_sha256": hashlib.sha256(mapping_bytes).hexdigest(),
    }
    expected_path.write_text(json.dumps(expected))
    return collection, mapping, expected, expected_path


def mapping_rows(path: Path):
    data = path.read_bytes()
    return [struct.unpack("<QQ", data[i:i + 16]) for i in range(0, len(data), 16)]


def test_any_casefold_filter_renumbers_and_preserves_pmids(tmp_path):
    collection, mapping, expected, _ = source_inputs(tmp_path)
    output = tmp_path / "filtered"
    receipt = corpus_filter.filter_inputs(
        collection, mapping, expected, output, keywords=("alpha",), mode="any"
    )
    assert output.joinpath("collection.tsv").read_text() == (
        "0\tAlpha cancer study. Biomarker response.\n"
        "1\tALPHA metabolism. Diabetes and cancer overlap.\n"
    )
    assert mapping_rows(output / "id-pmid.u64") == [(0, 101), (1, 303)]
    assert receipt["result"]["records"] == 2
    assert json.loads((output / "filter.json").read_text())["filter"]["keywords"] == ["alpha"]


def test_all_and_case_sensitive_semantics(tmp_path):
    collection, mapping, expected, _ = source_inputs(tmp_path)
    output = tmp_path / "all"
    corpus_filter.filter_inputs(
        collection, mapping, expected, output, keywords=("diabetes", "cancer"), mode="all"
    )
    assert mapping_rows(output / "id-pmid.u64") == [(0, 303)]

    with pytest.raises(ValueError, match="zero records"):
        corpus_filter.filter_inputs(
            collection, mapping, expected, tmp_path / "case",
            keywords=("alpha",), case_sensitive=True,
        )
    assert not (tmp_path / "case").exists()


def test_keyword_file_combines_and_deduplicates(tmp_path):
    collection, mapping, expected, expected_path = source_inputs(tmp_path)
    keyword_file = tmp_path / "keywords.txt"
    keyword_file.write_text(" cancer \n\nalpha\ncancer\n")
    output = tmp_path / "cli"
    assert corpus_filter.main([
        "--collection", str(collection), "--mapping", str(mapping),
        "--expected", str(expected_path), "--output", str(output),
        "--keyword", "alpha", "--keyword-file", str(keyword_file),
        "--mode", "all",
    ]) == 0
    metadata = json.loads((output / "filter.json").read_text())
    assert metadata["filter"]["keywords"] == ["alpha", "cancer"]
    assert metadata["result"]["records"] == 2


def test_source_identity_failure_leaves_no_output(tmp_path):
    collection, mapping, expected, _ = source_inputs(tmp_path)
    expected = dict(expected)
    expected["collection_sha256"] = "0" * 64
    output = tmp_path / "bad"
    with pytest.raises(ValueError, match="Source input hash mismatch"):
        corpus_filter.filter_inputs(collection, mapping, expected, output, keywords=("alpha",))
    assert not output.exists()


def test_bad_mapping_and_existing_output_fail_closed(tmp_path):
    collection, mapping, expected, _ = source_inputs(tmp_path)
    bad_mapping = tmp_path / "bad-mapping.u64"
    bad_mapping.write_bytes(struct.pack("<QQQQQQ", 0, 101, 9, 202, 2, 303))
    bad_expected = dict(expected)
    bad_expected["mapping_sha256"] = hashlib.sha256(bad_mapping.read_bytes()).hexdigest()
    output = tmp_path / "badmap"
    with pytest.raises(ValueError, match="Invalid mapping row 1"):
        corpus_filter.filter_inputs(collection, bad_mapping, bad_expected, output, keywords=("alpha",))
    assert not output.exists()

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        corpus_filter.filter_inputs(collection, mapping, expected, existing, keywords=("alpha",))


def test_keywords_must_be_nonempty(tmp_path):
    collection, mapping, expected, _ = source_inputs(tmp_path)
    with pytest.raises(ValueError, match="non-empty"):
        corpus_filter.filter_inputs(collection, mapping, expected, tmp_path / "empty", keywords=())
