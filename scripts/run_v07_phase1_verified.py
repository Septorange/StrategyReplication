#!/usr/bin/env python3
"""Capture frozen-tree hashes before/after a fresh Phase 1 rebuild."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def tree_hash(root: Path) -> dict:
    files = []
    for base in ("src", "scripts", "config", "data/raw", "data/processed"):
        directory = root / base
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.name == ".DS_Store":
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size, "sha256": digest})
    tree = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"root": str(root), "tree_sha256": tree, "file_count": len(files), "files": files}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v6-root", default="/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现6")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--end", default="2026-09-24")
    args = parser.parse_args()
    root = Path(args.v6_root).resolve()
    output = Path(args.output_root).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"output root must be fresh: {output}")
    before = tree_hash(root)
    command = [sys.executable, str(Path(__file__).with_name("rebuild_v07_phase1.py")), "--v6-root", str(root), "--output-root", str(output), "--end", args.end]
    run = subprocess.run(command, check=False, text=True)
    if run.returncode:
        raise SystemExit(run.returncode)
    after = tree_hash(root)
    reports = Path(__file__).resolve().parents[1] / "reports"
    (reports / "V0.7_FROZEN_HASHES_BEFORE.json").write_text(json.dumps({"scope": "src,scripts,config,data/raw,data/processed", **before}, ensure_ascii=False, indent=2) + "\n")
    (reports / "V0.7_FROZEN_HASHES_AFTER.json").write_text(json.dumps({"scope": "src,scripts,config,data/raw,data/processed", **after, "unchanged": before["tree_sha256"] == after["tree_sha256"]}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "PASS" if before["tree_sha256"] == after["tree_sha256"] else "BLOCKED", "before_tree_sha256": before["tree_sha256"], "after_tree_sha256": after["tree_sha256"], "file_count": before["file_count"]}))
    return 0 if before["tree_sha256"] == after["tree_sha256"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
