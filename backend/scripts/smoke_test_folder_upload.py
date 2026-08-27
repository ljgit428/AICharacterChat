# -*- coding: utf-8 -*-
"""Smoke test: folder-group upload + paginated read against a running dev server.

Uses real files from the folder in SMOKE_TEST_SRC (defaults to the author's
local dataset) to exercise the same code path as the browser folder upload
(multipart + relative_paths JSON).
"""
import io
import json
import os
import random
import string
import sys

import requests

BASE = "http://127.0.0.1:8000/api"
SRC = os.environ.get("SMOKE_TEST_SRC", r"F:\git\BA_Script_CN_Extract\result\圣亚剧情")


def pick_files():
    """Pick a representative subset across the whole hierarchy."""
    picks = []
    for root, _dirs, files in os.walk(SRC):
        rel_root = os.path.relpath(root, SRC)
        txts = sorted(f for f in files if f.endswith(".txt"))
        # take up to 2 files per leaf dir
        for name in txts[:2]:
            picks.append(os.path.normpath(os.path.join(rel_root, name)))
    return picks


def main():
    suffix = "".join(random.choice(string.ascii_lowercase) for _ in range(6))
    s = requests.Session()

    char_resp = s.post(
        f"{BASE}/characters/",
        json={
            "name": f"圣亚冒烟测试-{suffix}",
            "description": "folder upload smoke test",
            "scenario": "",
            "example_dialogue": "",
        },
    )
    print("create character:", char_resp.status_code)
    assert char_resp.status_code in (200, 201), char_resp.text[:300]
    char_id = char_resp.json()["id"]

    try:
        rel_paths = pick_files()
        print(f"uploading {len(rel_paths)} files with hierarchy...")
        files = []
        for rel in rel_paths:
            full = os.path.join(SRC, rel)
            with open(full, "rb") as fh:
                files.append(
                    ("files", (rel.replace("\\", "/"), fh.read(), "text/plain"))
                )
        payload = [("relative_paths", json.dumps([p.replace("\\", "/") for p in rel_paths]))]

        up = s.post(f"{BASE}/characters/{char_id}/knowledge_assets/", files=files, data=payload)
        print("upload:", up.status_code)
        assert up.status_code == 201, up.text[:500]
        assets = up.json()["assets"]
        assert len(assets) == len(rel_paths), f"expected {len(rel_paths)} assets"

        nested = [a["file_name"] for a in assets]
        sample = [
            "Momotalk/基础圣亚/圣亚_Momotalk_1.txt",
            "Scenario/主线_伊甸园条约/31010.txt",
            "羁绊剧情/泳装圣亚/",
            "整理说明.txt",
        ]
        for probe in sample:
            hit = any(probe in n for n in nested)
            print(f"  asset contains '{probe}': {hit}")
            assert hit, f"missing {probe} in {nested[:5]}..."

        lst = s.get(f"{BASE}/characters/{char_id}/knowledge_assets/")
        print("list knowledge_assets:", lst.status_code, "count =", len(lst.json()["assets"]))
        assert lst.status_code == 200

        tree = s.get(f"{BASE}/characters/{char_id}/soul_files/?recursive=true&max_entries=200")
        print("soul_files recursive:", tree.status_code)
        entries = tree.json()
        paths = {e["path"] for e in entries["entries"]}
        expected_dirs = {
            "raw/character_setup/uploads/Momotalk",
            "raw/character_setup/uploads/Momotalk/基础圣亚",
            "raw/character_setup/uploads/Scenario/主线_伊甸园条约",
            "raw/character_setup/uploads/羁绊剧情/泳装圣亚",
        }
        for d in sorted(expected_dirs):
            print(f"  tree has dir '{d}':", d in paths)
            assert d in paths, f"dir missing: {d}"
        print("  truncated flag:", entries.get("truncated"))

        # non-recursive listing of uploads root (what SoulPanel lazy-loads)
        lvl = s.get(
            f"{BASE}/characters/{char_id}/soul_files/",
            params={"path_prefix": "raw/character_setup/uploads"},
        )
        lvl_entries = lvl.json()["entries"]
        names = [(e["path"], e["entry_type"], e.get("child_count")) for e in lvl_entries]
        print("uploads root listing:", lvl.status_code)
        for row in names:
            print("   ", row)

        # offset pagination on the longest uploaded file
        long_rel = max(
            rel_paths,
            key=lambda p: os.path.getsize(os.path.join(SRC, p)),
        ).replace("\\", "/")
        vpath = f"raw/character_setup/uploads/{long_rel}"
        first = s.get(
            f"{BASE}/characters/{char_id}/soul_file/",
            params={"path": vpath, "max_chars": 600},
        ).json()
        print(
            "page1:",
            {k: first[k] for k in ("offset", "next_offset", "total_chars", "has_more")},
            "len(content) =", len(first["content"]),
        )
        acc = first["content"]
        guard = 0
        while first["has_more"] and guard < 50:
            first = s.get(
                f"{BASE}/characters/{char_id}/soul_file/",
                params={
                    "path": vpath,
                    "max_chars": 600,
                    "offset": first["next_offset"],
                },
            ).json()
            acc += first["content"]
            guard += 1
        # newline='' keeps \r\n so we compare against what the server stores;
        # the extractor strips trailing newline(s) from stored text.
        src_text = open(os.path.join(SRC, long_rel), encoding="utf-8", newline="").read()
        ok = acc == src_text or acc == src_text.rstrip("\r\n")
        print(f"paginated read rounds={guard + 1} assembled={len(acc)} source={len(src_text)} equal={ok}")
        assert ok, "assembled content differs from source file"
        assert guard + 1 >= 2, "expected multiple pages for this file"

        # mismatched relative_paths must 400
        one = s.post(
            f"{BASE}/characters/{char_id}/knowledge_assets/",
            files=[("files", ("x.txt", b"x", "text/plain"))],
            data={"relative_paths": json.dumps(["a.txt", "b.txt"])},
        )
        print("mismatch relative_paths -> ", one.status_code)
        assert one.status_code == 400

        # delete one asset then confirm gone from listing
        victim = next(a for a in assets if a["file_name"] == "整理说明.txt")
        dele = s.delete(f"{BASE}/characters/{char_id}/knowledge_assets/{victim['id']}/")
        print("delete asset:", dele.status_code)
        assert dele.status_code in (200, 204)
        after = s.get(f"{BASE}/characters/{char_id}/knowledge_assets/").json()["assets"]
        assert all(a["id"] != victim["id"] for a in after)

        print("\nALL SMOKE CHECKS PASSED")
    finally:
        del_resp = s.delete(f"{BASE}/characters/{char_id}/")
        print("cleanup character:", del_resp.status_code)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
