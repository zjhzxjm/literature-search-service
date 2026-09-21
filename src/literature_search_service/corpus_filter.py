"""Create deterministic ColBERT build inputs from a keyword-filtered corpus.

The source collection is streamed and never modified. Output local PIDs are
renumbered from zero while preserving the source PMID mapping.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
from typing import Iterable


def _validate_expected(expected: dict) -> None:
    records = expected.get("records")
    if type(records) is not int or records <= 0:
        raise ValueError("records must be a positive integer")
    for key in ("collection_sha256", "mapping_sha256"):
        digest = expected.get(key)
        if not isinstance(digest, str) or len(digest) != 64 or any(
            c not in "0123456789abcdef" for c in digest
        ):
            raise ValueError(f"Invalid {key}")


def _load_keywords(values: Iterable[str], keyword_file: Path | None) -> tuple[str, ...]:
    raw = list(values)
    if keyword_file is not None:
        raw.extend(keyword_file.read_text(encoding="utf-8").splitlines())
    cleaned = []
    seen = set()
    for value in raw:
        keyword = value.strip()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        cleaned.append(keyword)
    if not cleaned:
        raise ValueError("At least one non-empty keyword is required")
    return tuple(cleaned)


def _matches(text: str, keywords: tuple[str, ...], mode: str, case_sensitive: bool) -> bool:
    haystack = text if case_sensitive else text.casefold()
    needles = keywords if case_sensitive else tuple(keyword.casefold() for keyword in keywords)
    tests = (needle in haystack for needle in needles)
    return all(tests) if mode == "all" else any(tests)


def filter_inputs(
    collection: Path,
    mapping: Path,
    expected: dict,
    output: Path,
    *,
    keywords: tuple[str, ...],
    mode: str = "any",
    case_sensitive: bool = False,
) -> dict:
    """Filter build inputs in one streaming pass and atomically publish outputs."""
    _validate_expected(expected)
    if mode not in {"any", "all"}:
        raise ValueError("mode must be 'any' or 'all'")
    if not keywords or any(not isinstance(k, str) or not k.strip() for k in keywords):
        raise ValueError("keywords must contain non-empty strings")
    if output.exists():
        raise FileExistsError(output)

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    source_text_hash = hashlib.sha256()
    source_map_hash = hashlib.sha256()
    filtered_text_hash = hashlib.sha256()
    filtered_map_hash = hashlib.sha256()
    source_count = 0
    matched_count = 0

    try:
        out_collection = temp / "collection.tsv"
        out_mapping = temp / "id-pmid.u64"
        with collection.open("rb") as texts, mapping.open("rb") as ids, \
                out_collection.open("wb") as filtered_texts, out_mapping.open("wb") as filtered_ids:
            for source_pid, line in enumerate(texts):
                source_text_hash.update(line)
                pid, separator, content = line.partition(b"\t")
                if pid != str(source_pid).encode() or not separator or not content.strip():
                    raise ValueError(f"Invalid collection row {source_pid}")
                if b"\t" in content or b"\r" in content:
                    raise ValueError(f"Non-normalized collection row {source_pid}")
                text = content.rstrip(b"\n").decode("utf-8", errors="strict")

                pair = ids.read(16)
                if len(pair) != 16:
                    raise ValueError(f"Missing mapping row {source_pid}")
                source_map_hash.update(pair)
                mapped_pid, pmid = struct.unpack("<QQ", pair)
                if mapped_pid != source_pid or pmid == 0:
                    raise ValueError(f"Invalid mapping row {source_pid}")

                if _matches(text, keywords, mode, case_sensitive):
                    new_line = f"{matched_count}\t{text}\n".encode("utf-8")
                    new_pair = struct.pack("<QQ", matched_count, pmid)
                    filtered_texts.write(new_line)
                    filtered_ids.write(new_pair)
                    filtered_text_hash.update(new_line)
                    filtered_map_hash.update(new_pair)
                    matched_count += 1
                source_count += 1

            if ids.read(1):
                raise ValueError("Extra mapping bytes")

        source_actual = {
            "records": source_count,
            "collection_sha256": source_text_hash.hexdigest(),
            "mapping_sha256": source_map_hash.hexdigest(),
        }
        if any(source_actual[key] != expected[key] for key in source_actual):
            raise ValueError("Source input hash mismatch")
        if matched_count == 0:
            raise ValueError("Keyword filter matched zero records")

        filtered_expected = {
            "records": matched_count,
            "collection_sha256": filtered_text_hash.hexdigest(),
            "mapping_sha256": filtered_map_hash.hexdigest(),
        }
        (temp / "expected.json").write_text(
            json.dumps(filtered_expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        receipt = {
            "schema_version": 1,
            "source": source_actual,
            "filter": {
                "kind": "literal_substring",
                "keywords": list(keywords),
                "mode": mode,
                "case_sensitive": case_sensitive,
                "text_field": "normalized_title_abstract",
            },
            "result": filtered_expected,
        }
        (temp / "filter.json").write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, output)
        return receipt
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--keyword-file", type=Path)
    parser.add_argument("--mode", choices=("any", "all"), default="any")
    parser.add_argument("--case-sensitive", action="store_true")
    args = parser.parse_args(argv)

    keywords = _load_keywords(args.keyword, args.keyword_file)
    receipt = filter_inputs(
        args.collection.resolve(),
        args.mapping.resolve(),
        json.loads(args.expected.read_text(encoding="utf-8")),
        args.output,
        keywords=keywords,
        mode=args.mode,
        case_sensitive=args.case_sensitive,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
