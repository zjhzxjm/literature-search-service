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


def checkpoint(tmp_path, *, context=None, tokenizer_limit=None):
    path = tmp_path / "model"
    path.mkdir()
    if context is not None:
        (path / "config.json").write_text(json.dumps({"max_position_embeddings": context}))
    if tokenizer_limit is not None:
        (path / "tokenizer_config.json").write_text(json.dumps({"model_max_length": tokenizer_limit}))
    return path


def mapping_args(collection, mapping, manifest):
    return ["--collection", str(collection), "--mapping", str(mapping), "--expected", str(manifest)]


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


def test_checkpoint_context_limit_and_jina_8k(tmp_path):
    model = checkpoint(tmp_path, context=8194, tokenizer_limit=8194)
    config = dict(dim=128, nbits=2, doc_maxlen=8192, query_maxlen=32,
                  index_bsize=8, kmeans_niters=4)
    assert build.validate_build_options(model, config) == 8194
    identity = build.checkpoint_identity(model)
    assert identity["model_id"] == build.DEFAULT_MODEL_ID
    assert identity["revision"] == build.DEFAULT_MODEL_REVISION
    assert identity["config.json_sha256"] == hashlib.sha256(
        (model / "config.json").read_bytes()
    ).hexdigest()


def test_checkpoint_limit_rejects_too_long_and_unknown_long_context(tmp_path):
    bert = checkpoint(tmp_path, context=512, tokenizer_limit=512)
    config = dict(dim=128, nbits=2, doc_maxlen=513, query_maxlen=32,
                  index_bsize=64, kmeans_niters=4)
    with pytest.raises(ValueError, match="exceeds checkpoint context limit 512"):
        build.validate_build_options(bert, config)

    unknown = tmp_path / "unknown"
    unknown.mkdir()
    config["doc_maxlen"] = 8192
    with pytest.raises(ValueError, match="requires local checkpoint context metadata"):
        build.validate_build_options(unknown, config)


def test_build_records_explicit_config_and_returned_path(tmp_path, monkeypatch):
    collection, mapping, _, manifest = inputs(tmp_path)
    model = checkpoint(tmp_path, context=8194, tokenizer_limit=8194)
    output = tmp_path / "build"
    actual_index = tmp_path / "different-layout/index"
    captured = {}

    def fake_build(collection_arg, checkpoint_arg, output_arg, gpus_arg, config_arg):
        captured.update(config_arg)
        return str(actual_index)

    monkeypatch.setattr(build, "build_index", fake_build)
    commands = []
    monkeypatch.setattr(build.subprocess, "run", lambda cmd, **kw: commands.append(cmd))
    args = ["build", *mapping_args(collection, mapping, manifest),
            "--checkpoint", str(model), "--checkpoint-revision", "rev123",
            "--model-id", "jinaai/jina-colbert-v2",
            "--output", str(output), "--gpus", "0", "--doc-maxlen", "8192",
            "--index-bsize", "8"]
    assert build.main(args) == 0
    assert captured["doc_maxlen"] == 8192
    assert captured["index_bsize"] == 8
    assert commands[0][commands[0].index("--input") + 1] == str(actual_index)
    receipt = json.loads((output / "build.json").read_text())
    assert receipt["status"] == "coalesced_not_query_validated"
    assert receipt["query_validated"] is False
    assert receipt["checkpoint_context_limit"] == 8194
    assert receipt["checkpoint"]["model_id"] == "jinaai/jina-colbert-v2"
    assert receipt["checkpoint"]["revision"] == "rev123"
    assert receipt["build_config"]["doc_maxlen"] == 8192
    with pytest.raises(FileExistsError):
        build.main(args)


def test_build_failure_is_recorded(tmp_path, monkeypatch):
    collection, mapping, _, manifest = inputs(tmp_path)
    model = checkpoint(tmp_path, context=512, tokenizer_limit=512)

    def fail(*args):
        raise RuntimeError("simulated index failure")

    monkeypatch.setattr(build, "build_index", fail)
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="simulated"):
        build.main(["build", *mapping_args(collection, mapping, manifest),
                    "--checkpoint", str(model), "--output", str(output),
                    "--doc-maxlen", "256"])
    assert json.loads((output / "build.json").read_text())["status"] == "failed"


def test_jina_is_the_default_build_profile(tmp_path, monkeypatch):
    collection, mapping, _, manifest = inputs(tmp_path)
    model = checkpoint(tmp_path, context=8194, tokenizer_limit=8194)
    output = tmp_path / "jina-default"
    captured = {}

    def fake_build(collection_arg, checkpoint_arg, output_arg, gpus_arg, config_arg):
        captured.update(config_arg)
        return str(tmp_path / "index")

    monkeypatch.setattr(build, "build_index", fake_build)
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **kw: None)
    build.main([
        "build", *mapping_args(collection, mapping, manifest),
        "--checkpoint", str(model), "--output", str(output),
    ])
    receipt = json.loads((output / "build.json").read_text())
    assert captured["doc_maxlen"] == 8192
    assert captured["index_bsize"] == 8
    assert receipt["checkpoint"]["model_id"] == build.DEFAULT_MODEL_ID
    assert receipt["checkpoint"]["revision"] == build.DEFAULT_MODEL_REVISION
