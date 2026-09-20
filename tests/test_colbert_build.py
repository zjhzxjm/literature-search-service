import hashlib
import json
from pathlib import Path
import struct

import pytest

from literature_search_service import colbert_build as build


def inputs(tmp_path, text=b"0\tFirst title.\n1\tSecond abstract.\n", pairs=None):
    collection, mapping = tmp_path / "collection.tsv", tmp_path / "id-pmid.u64"
    collection.write_bytes(text)
    mapping.write_bytes(pairs if pairs is not None else struct.pack("<QQQQ", 0, 42, 1, 99))
    expected = dict(records=2, collection_sha256=hashlib.sha256(text).hexdigest(),
                    mapping_sha256=hashlib.sha256(mapping.read_bytes()).hexdigest())
    manifest = tmp_path / "expected.json"
    manifest.write_text(json.dumps(expected))
    return collection, mapping, expected, manifest


def test_verify_valid_inputs(tmp_path):
    collection, mapping, expected, _ = inputs(tmp_path)
    assert build.verify_inputs(collection, mapping, expected) == expected


@pytest.mark.parametrize("text,pairs", [
    (b"0\tFirst\n2\tSecond\n", None),
    (b"0\tFirst\n1\t \n", None),
    (b"0\tFirst\n1\tSecond\textra\n", None),
    (b"0\tFirst\n1\tSecond\n", struct.pack("<QQQQ", 0, 42, 2, 99)),
    (b"0\tFirst\n1\tSecond\n", struct.pack("<QQ", 0, 42)),
    (b"0\tFirst\n1\tSecond\n", struct.pack("<QQQQ", 0, 42, 1, 0)),
    (b"0\tFirst\n1\tSecond\n", struct.pack("<QQQQ", 0, 42, 1, 99) + b"x"),
])
def test_reject_bad_structure_even_with_matching_hashes(tmp_path, text, pairs):
    collection, mapping, expected, _ = inputs(tmp_path, text, pairs)
    with pytest.raises(ValueError):
        build.verify_inputs(collection, mapping, expected)


@pytest.mark.parametrize("field,value", [("records", 3), ("records", True),
                                          ("collection_sha256", "0" * 64),
                                          ("mapping_sha256", "invalid")])
def test_reject_identity_mismatch(tmp_path, field, value):
    collection, mapping, expected, _ = inputs(tmp_path)
    expected[field] = value
    with pytest.raises(ValueError):
        build.verify_inputs(collection, mapping, expected)


def test_build_uses_returned_path_and_does_not_reuse_output(tmp_path, monkeypatch):
    collection, mapping, _, manifest = inputs(tmp_path)
    checkpoint = tmp_path / "model"
    checkpoint.mkdir()
    output = tmp_path / "build"
    actual_index = tmp_path / "different-layout/index"
    monkeypatch.setattr(build, "build_index", lambda *a: str(actual_index))
    commands = []
    monkeypatch.setattr(build.subprocess, "run", lambda cmd, **kw: commands.append(cmd))
    args = ["build", "--collection", str(collection), "--mapping", str(mapping),
            "--expected", str(manifest), "--checkpoint", str(checkpoint), "--output", str(output)]
    assert build.main(args) == 0
    assert commands[0][commands[0].index("--input") + 1] == str(actual_index)
    receipt = json.loads((output / "build.json").read_text())
    assert receipt["status"] == "coalesced_not_query_validated"
    assert receipt["query_validated"] is False
    with pytest.raises(FileExistsError):
        build.main(args)


def test_build_failure_is_recorded(tmp_path, monkeypatch):
    collection, mapping, _, manifest = inputs(tmp_path)
    checkpoint = tmp_path / "model"
    checkpoint.mkdir()
    def fail(*args):
        raise RuntimeError("simulated index failure")
    monkeypatch.setattr(build, "build_index", fail)
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="simulated"):
        build.main(["build", "--collection", str(collection), "--mapping", str(mapping),
                    "--expected", str(manifest), "--checkpoint", str(checkpoint),
                    "--output", str(output)])
    assert json.loads((output / "build.json").read_text())["status"] == "failed"
