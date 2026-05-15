#!/usr/bin/env python3
"""
Download the Valera Purificada 1602 (VP) Bible text and save as vp.json.

Source: llromerorr/TextosBiblicos on GitHub
Format: plain-text .txt files, one per book
  #title Génesis
  1:1 EN el principio creó Dios el cielo y la tierra.
  1:2 ...
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "vp.json"
API_URL = "https://api.github.com/repos/llromerorr/TextosBiblicos/contents/V1602P"

# Correct known misspellings in the source #title lines
_BOOK_NAME_FIX = {
    "Ecclesiastés": "Eclesiastés",
}


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "kjv-mcp-setup/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _fix_ecclesiastes(book_verses: list) -> list:
    """
    The source file 21_Ec.txt has two structural bugs:
      1. Chapters are labeled starting at 3 instead of 1.
      2. Chapters 5-8 are scrambled — the file order is 1,2,3,4,5,7,6,8,9-12
         but chapters 5,6,7,8 all carry duplicate labels (7 or 8).

    Strategy: split the verse list into 12 blocks by detecting verse-number
    resets (each block starts at verse 1), then map block index → real chapter.

    Verified block-to-real-chapter mapping (identified from verse 1 content):
      block 0 (labeled 3, "PALABRAS del Predicador")          → ch 1
      block 1 (labeled 4, "DIJE yo en mi corazón")            → ch 2
      block 2 (labeled 5, "PARA todas las cosas hay sazón")   → ch 3
      block 3 (labeled 6, "Y TORNÉME yo, y ví")               → ch 4
      block 4 (labeled 7, "CUANDO fueres a la casa de Dios")  → ch 5
      block 5 (labeled 7, "MEJOR es un buen nombre")          → ch 7  ← out of order in file
      block 6 (labeled 8, "HAY un mal que he visto")          → ch 6  ← out of order in file
      block 7 (labeled 8, "¿QUIÉN como el sabio?")            → ch 8
      block 8 (labeled 9)                                     → ch 9
      block 9 (labeled 10)                                    → ch 10
      block 10 (labeled 11)                                   → ch 11
      block 11 (labeled 12)                                   → ch 12
    """
    BLOCK_TO_REAL_CH = [1, 2, 3, 4, 5, 7, 6, 8, 9, 10, 11, 12]

    blocks: list[list] = []
    cur: list = []
    for v in book_verses:
        if v["verse"] == 1 and cur:
            blocks.append(cur)
            cur = [v]
        else:
            cur.append(v)
    if cur:
        blocks.append(cur)

    if len(blocks) != 12:
        # Source structure changed — skip correction rather than corrupt data
        print(f"  WARNING: Ecclesiastes fix expected 12 blocks, found {len(blocks)} — skipping correction")
        return book_verses

    fixed = []
    for block_idx, block in enumerate(blocks):
        real_ch = BLOCK_TO_REAL_CH[block_idx]
        for v in block:
            v2 = dict(v)
            v2["chapter"] = real_ch
            fixed.append(v2)

    # Re-sort into canonical chapter order (file has chs 5-8 scrambled)
    fixed.sort(key=lambda v: (v["chapter"], v["verse"]))
    return fixed


def download() -> None:
    if OUT.exists():
        print(f"vp.json already exists at {OUT} — delete it to re-download.")
        return

    print("Fetching file list from GitHub...")
    try:
        listing = json.loads(_fetch(API_URL))
    except Exception as exc:
        print(f"Failed to fetch file list: {exc}")
        sys.exit(1)

    txt_files = sorted(
        [f for f in listing if f["name"].endswith(".txt")],
        key=lambda f: int(f["name"].split("_")[0]),
    )
    print(f"Found {len(txt_files)} book files.")

    verses = []
    for file_info in txt_files:
        filename = file_info["name"]
        url = file_info["download_url"]  # use the exact URL GitHub provides
        try:
            content = _fetch(url).decode("utf-8")
        except Exception as exc:
            print(f"  Failed to fetch {filename}: {exc}")
            sys.exit(1)

        book_name = None
        book_verses: list = []
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#title "):
                raw = line[7:].strip()
                book_name = _BOOK_NAME_FIX.get(raw, raw)
            elif line.startswith("#") or not line:
                continue
            else:
                m = re.match(r"^(\d+):(\d+)\s+(.+)$", line)
                if m and book_name:
                    book_verses.append({
                        "book": book_name,
                        "chapter": int(m.group(1)),
                        "verse": int(m.group(2)),
                        "text": m.group(3).strip(),
                    })

        # Fix structural bugs in the Ecclesiastes source file
        if book_name == "Eclesiastés":
            book_verses = _fix_ecclesiastes(book_verses)

        verses.extend(book_verses)
        print(f"  {filename}: {book_name} ({len(book_verses)} verses)")

    if not verses:
        print("No verses parsed — aborting.")
        sys.exit(1)

    # Sanity check — Génesis 1:1 should contain "principio"
    gen_1_1 = next((v for v in verses if v["chapter"] == 1 and v["verse"] == 1), None)
    if not gen_1_1 or "principio" not in gen_1_1["text"].lower():
        print(f"Sanity check failed on Genesis 1:1: {gen_1_1}")
        sys.exit(1)

    # Sanity check — Eclesiastés 4:8 should contain "trabajo" (not riches/plata)
    ec_4_8 = next(
        (v for v in verses if v["book"] == "Eclesiastés" and v["chapter"] == 4 and v["verse"] == 8),
        None,
    )
    if not ec_4_8 or "trabajo" not in ec_4_8["text"].lower():
        print(f"Ecclesiastes sanity check failed at 4:8: {ec_4_8}")
        sys.exit(1)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(verses, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nSaved {len(verses):,} verses to {OUT}")


if __name__ == "__main__":
    download()
