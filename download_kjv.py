#!/usr/bin/env python3
"""
One-time setup: download the public-domain KJV Bible JSON and save as kjv.json.

Sources tried in order:
  1. farskipper/kjv — pure KJV 1769, single file, reference-keyed JSON
  2. aruljohn/Bible-kjv — 66 book files, hierarchical structure
  3. scrollmapper/bible_databases — flat b/c/v/t format (last resort)

Run once before starting the MCP server:
    python download_kjv.py
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "kjv.json"

BOOK_NAMES = [
    "Genesis","Exodus","Leviticus","Numbers","Deuteronomy","Joshua","Judges",
    "Ruth","1 Samuel","2 Samuel","1 Kings","2 Kings","1 Chronicles",
    "2 Chronicles","Ezra","Nehemiah","Esther","Job","Psalms","Proverbs",
    "Ecclesiastes","Song of Solomon","Isaiah","Jeremiah","Lamentations",
    "Ezekiel","Daniel","Hosea","Joel","Amos","Obadiah","Jonah","Micah",
    "Nahum","Habakkuk","Zephaniah","Haggai","Zechariah","Malachi",
    "Matthew","Mark","Luke","John","Acts","Romans","1 Corinthians",
    "2 Corinthians","Galatians","Ephesians","Philippians","Colossians",
    "1 Thessalonians","2 Thessalonians","1 Timothy","2 Timothy","Titus",
    "Philemon","Hebrews","James","1 Peter","2 Peter","1 John","2 John",
    "3 John","Jude","Revelation",
]


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "kjv-mcp-setup/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _clean_text(text: str) -> str:
    """Strip farskipper formatting markers from verse text.

    # marks a paragraph break within a verse — remove it.
    [word] marks italicised supplied words — keep the word, drop the brackets.
    """
    text = text.replace("#", "")
    text = re.sub(r"\[([^\]]*)\]", r"\1", text)
    return text.strip()


def _try_farskipper() -> list | None:
    """Primary source: farskipper/kjv — pure KJV 1769 text.

    Format: {"Genesis 1:1": "verse text", ...}
    Returns flat list of {book, chapter, verse, text} dicts, or None on failure.
    """
    url = "https://raw.githubusercontent.com/farskipper/kjv/master/json/verses-1769.json"
    print(f"Trying farskipper/kjv: {url}")
    try:
        raw = json.loads(_fetch(url).decode("utf-8"))
    except Exception as exc:
        print(f"  Failed: {exc}")
        return None

    if not isinstance(raw, dict):
        print("  Unexpected format (expected dict).")
        return None

    verses = []
    for ref, text in raw.items():
        m = re.match(r"^(.+?)\s+(\d+):(\d+)$", ref)
        if not m:
            continue
        verses.append({
            "book": m.group(1),
            "chapter": int(m.group(2)),
            "verse": int(m.group(3)),
            "text": _clean_text(str(text)),
        })

    if not verses:
        print("  No verses parsed.")
        return None

    print(f"  Parsed {len(verses):,} verses.")
    return verses


def _try_aruljohn() -> list | None:
    """Fallback: aruljohn/Bible-kjv — 66 book files.

    Format per file: {"book": "Genesis", "chapters":
        [{"chapter":"1", "verses":[{"verse":"1","text":"..."},...]},...]}
    """
    books_url = "https://raw.githubusercontent.com/aruljohn/Bible-kjv/master/Books.json"
    print(f"Trying aruljohn/Bible-kjv: {books_url}")
    try:
        book_list = json.loads(_fetch(books_url).decode("utf-8"))
    except Exception as exc:
        print(f"  Failed to fetch book list: {exc}")
        return None

    verses = []
    for book_name in book_list:
        file_name = book_name.replace(" ", "") + ".json"
        url = f"https://raw.githubusercontent.com/aruljohn/Bible-kjv/master/{file_name}"
        try:
            book_data = json.loads(_fetch(url).decode("utf-8"))
        except Exception as exc:
            print(f"  Failed to fetch {file_name}: {exc}")
            return None

        for chap in book_data.get("chapters", []):
            c = int(chap["chapter"])
            for v_entry in chap.get("verses", []):
                verses.append({
                    "book": book_name,
                    "chapter": c,
                    "verse": int(v_entry["verse"]),
                    "text": v_entry["text"].strip(),
                })

    if not verses:
        print("  No verses parsed.")
        return None

    print(f"  Parsed {len(verses):,} verses.")
    return verses


def _try_scrollmapper() -> list | None:
    """Last resort: scrollmapper flat b/c/v/t format."""
    url = "https://raw.githubusercontent.com/scrollmapper/bible_databases/master/json/t_kjv.json"
    print(f"Trying scrollmapper: {url}")
    try:
        raw = json.loads(_fetch(url).decode("utf-8"))
    except Exception as exc:
        print(f"  Failed: {exc}")
        return None

    if not (isinstance(raw, list) and raw and "t" in raw[0]):
        print("  Unexpected format.")
        return None

    verses = []
    for entry in raw:
        b = int(entry["b"]) - 1
        verses.append({
            "book": BOOK_NAMES[b] if b < len(BOOK_NAMES) else f"Book {b+1}",
            "chapter": int(entry["c"]),
            "verse": int(entry["v"]),
            "text": entry["t"].strip(),
        })

    print(f"  Parsed {len(verses):,} verses.")
    return verses


def download() -> None:
    if OUT.exists():
        print(f"kjv.json already exists at {OUT} — delete it to re-download.")
        return

    verses = (
        _try_farskipper()
        or _try_aruljohn()
        or _try_scrollmapper()
    )

    if not verses:
        print(
            "\nAll sources failed. Please download a KJV JSON manually and save it\n"
            f"as: {OUT}\n\n"
            'Expected format: [{"book":"Genesis","chapter":1,"verse":1,"text":"..."},...]\n'
        )
        sys.exit(1)

    # Sanity check — Genesis 1:1 should contain "beginning"
    first = next((v for v in verses if v["chapter"] == 1 and v["verse"] == 1
                  and v["book"] == "Genesis"), None)
    if not first or "beginning" not in first["text"].lower():
        print(f"  Sanity check failed on Genesis 1:1: {first}")
        sys.exit(1)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(verses, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Saved {len(verses):,} verses to {OUT}")


if __name__ == "__main__":
    download()
