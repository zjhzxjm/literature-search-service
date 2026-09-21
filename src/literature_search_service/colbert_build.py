"""Experimental single-shard tooling; no runtime installation or automatic resume.

Collection rows contain local PID, tab, full normalized title/abstract.
Mapping rows are little-endian uint64 pairs (local PID, PMID).
This checks internal consistency, not the corpus-wide identity of a shard.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys


def verify_inputs(collection: Path, mapping: Path, expected: dict) -> dict:
    """Stream both inputs together; reject changed bytes, IDs and empty text."""
    records = expected.get("records")
    if type(records) is not int or records <= 0:
        raise ValueError("records must be a positive integer")
    for key in ("collection_sha256", "mapping_sha256"):
        digest = expected.get(key)
        if not isinstance(digest, str) or len(digest) != 64 or any(
            c not in "0123456789abcdef" for c in digest
        ):
            raise ValueError(f"Invalid {key}")
    text_hash, map_hash = hashlib.sha256(), hashlib.sha256()
    count = 0
    with collection.open("rb") as texts, mapping.open("rb") as ids:
        for number, line in enumerate(texts):
            text_hash.update(line)
            pid, separator, content = line.partition(b"\t")
            if pid != str(number).encode() or not separator or not content.strip():
                raise ValueError(f"Invalid collection row {number}")
            if b"\t" in content or b"\r" in content:
                raise ValueError(f"Non-normalized collection row {number}")
            content.decode("utf-8", errors="strict")
            pair = ids.read(16)
            if len(pair) != 16:
                raise ValueError(f"Missing mapping row {number}")
            map_hash.update(pair)
            local_pid, pmid = struct.unpack("<QQ", pair)
            if local_pid != number or pmid == 0:
                raise ValueError(f"Invalid mapping row {number}")
            count += 1
        if ids.read(1):
            raise ValueError("Extra mapping bytes")
    if count != records:
        raise ValueError("Record count mismatch")
    actual = dict(records=count, collection_sha256=text_hash.hexdigest(),
                  mapping_sha256=map_hash.hexdigest())
    if any(actual[key] != expected[key] for key in actual):
        raise ValueError("Input hash mismatch")
    return actual


def _json_positive_int(path: Path, key: str) -> int | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8")).get(key)
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if type(value) is int and 0 < value <= 1_000_000:
        return value
    return None


def checkpoint_identity(checkpoint: Path, revision: str | None = None) -> dict:
    """Record local checkpoint config identity without loading or downloading a model."""
    result = {"path": str(checkpoint.resolve()), "revision": revision}
    for name in ("config.json", "tokenizer_config.json"):
        path = checkpoint / name
        result[f"{name}_sha256"] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    return result


def checkpoint_context_limit(checkpoint: Path) -> int | None:
    """Return a conservative local context limit when checkpoint metadata declares one."""
    limits = [
        _json_positive_int(checkpoint / "config.json", "max_position_embeddings"),
        _json_positive_int(checkpoint / "tokenizer_config.json", "model_max_length"),
    ]
    known = [value for value in limits if value is not None]
    return min(known) if known else None


def validate_build_options(checkpoint: Path, config: dict) -> int | None:
    """Fail before GPU work when numeric options or local context metadata are invalid."""
    for key in ("dim", "nbits", "doc_maxlen", "query_maxlen", "index_bsize", "kmeans_niters"):
        value = config.get(key)
        if type(value) is not int or value <= 0:
            raise ValueError(f"{key} must be a positive integer")
    limit = checkpoint_context_limit(checkpoint)
    if limit is not None and config["doc_maxlen"] > limit:
        raise ValueError(
            f"doc_maxlen {config['doc_maxlen']} exceeds checkpoint context limit {limit}"
        )
    if limit is None and config["doc_maxlen"] > 512:
        raise ValueError(
            "doc_maxlen above 512 requires local checkpoint context metadata"
        )
    return limit


def build_index(collection: Path, checkpoint: Path, output: Path, gpus: list[int],
                config_values: dict) -> str:
    """Caller verifies immutable inputs first. Return the authoritative index path."""
    from colbert import Indexer
    from colbert.infra import ColBERTConfig, Run, RunConfig

    with Run().context(RunConfig(nranks=len(gpus), gpus=gpus,
                                root=str(output / "runs"), experiment="build")):
        config = ColBERTConfig(**config_values)
        indexer = Indexer(checkpoint=str(checkpoint), config=config)
        return str(indexer.index(name="index", collection=str(collection), overwrite=False))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["verify", "build"])
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--checkpoint-revision")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--gpus", type=int, nargs="+", default=[0])
    parser.add_argument("--dim", type=int, default=128)
    parser.add_argument("--nbits", type=int, default=2)
    parser.add_argument("--doc-maxlen", type=int, default=256)
    parser.add_argument("--query-maxlen", type=int, default=32)
    parser.add_argument("--index-bsize", type=int, default=64)
    parser.add_argument("--kmeans-niters", type=int, default=4)
    args = parser.parse_args(argv)
    if len(set(args.gpus)) != len(args.gpus) or any(g < 0 for g in args.gpus):
        parser.error("gpus must be distinct non-negative visible device IDs")
    if args.mode == "build" and (
        args.output is None or args.checkpoint is None or not args.checkpoint.is_dir()
    ):
        parser.error("build requires --output and an existing local --checkpoint")
    collection, mapping = args.collection.resolve(), args.mapping.resolve()
    actual = verify_inputs(collection, mapping, json.loads(args.expected.read_text()))
    if args.mode == "verify":
        print(json.dumps(actual))
        return 0

    checkpoint = args.checkpoint.resolve()
    config_values = {
        "dim": args.dim,
        "nbits": args.nbits,
        "doc_maxlen": args.doc_maxlen,
        "query_maxlen": args.query_maxlen,
        "index_bsize": args.index_bsize,
        "kmeans_niters": args.kmeans_niters,
    }
    try:
        context_limit = validate_build_options(checkpoint, config_values)
    except ValueError as exc:
        parser.error(str(exc))

    output = args.output.resolve()
    # Never reuse a directory containing partial or successful index artifacts.
    output.mkdir(parents=True, exist_ok=False)
    receipt = dict(
        status="building",
        inputs=actual,
        collection=str(collection),
        mapping=str(mapping),
        checkpoint=checkpoint_identity(checkpoint, args.checkpoint_revision),
        checkpoint_context_limit=context_limit,
        gpus=args.gpus,
        build_config=config_values,
        runtime_python=sys.version,
        query_validated=False,
    )
    try:
        (output / "build.json").write_text(json.dumps(receipt, indent=2))
        index_path = build_index(collection, checkpoint, output, args.gpus, config_values)
        receipt["index_path"] = index_path
        mmap_path = output / "index-mmap"
        subprocess.run([sys.executable, "-m", "colbert.utils.coalesce", "--input",
                        index_path, "--output", str(mmap_path)], check=True)
        receipt.update(status="coalesced_not_query_validated", mmap_path=str(mmap_path))
    except Exception as exc:
        receipt.update(status="failed", error=str(exc))
        raise
    finally:
        (output / "build.json").write_text(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
