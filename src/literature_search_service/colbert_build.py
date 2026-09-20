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


def build_index(collection: Path, checkpoint: Path, output: Path, gpus: list[int],
                doc_maxlen: int) -> str:
    """Caller verifies immutable inputs first. Return the authoritative index path."""
    from colbert import Indexer
    from colbert.infra import ColBERTConfig, Run, RunConfig

    with Run().context(RunConfig(nranks=len(gpus), gpus=gpus,
                                root=str(output / "runs"), experiment="build")):
        config = ColBERTConfig(dim=128, nbits=2, doc_maxlen=doc_maxlen,
                               query_maxlen=32, index_bsize=64, kmeans_niters=4)
        indexer = Indexer(checkpoint=str(checkpoint), config=config)
        return str(indexer.index(name="index", collection=str(collection), overwrite=False))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["verify", "build"])
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--gpus", type=int, nargs="+", default=[0])
    parser.add_argument("--doc-maxlen", type=int, default=256)
    args = parser.parse_args(argv)
    if not 4 <= args.doc_maxlen <= 512:
        parser.error("doc-maxlen must be between 4 and 512")
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
    output = args.output.resolve()
    # Never reuse a directory containing partial or successful index artifacts.
    output.mkdir(parents=True, exist_ok=False)
    receipt = dict(status="building", inputs=actual, collection=str(collection),
                   mapping=str(mapping), checkpoint=str(args.checkpoint.resolve()),
                   gpus=args.gpus, doc_maxlen=args.doc_maxlen,
                   runtime_python=sys.version, query_validated=False)
    try:
        (output / "build.json").write_text(json.dumps(receipt, indent=2))
        index_path = build_index(collection, args.checkpoint.resolve(), output,
                                 args.gpus, args.doc_maxlen)
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
