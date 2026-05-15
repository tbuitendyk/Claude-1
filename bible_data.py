"""Bible data loader and fuzzy verse search — supports multiple translations."""

import json
import re
import unicodedata
from pathlib import Path

try:
    from rapidfuzz import fuzz, process as rfprocess
    _USE_RAPIDFUZZ = True
except ImportError:
    from difflib import SequenceMatcher
    _USE_RAPIDFUZZ = False

DATA_FILE = Path(__file__).parent / "kjv.json"
VP_FILE   = Path(__file__).parent / "vp.json"

_cache: dict = {}  # {str(path): [verses]}

# ---------------------------------------------------------------------------
# Book name alias tables — maps lowercase/abbreviated names to the canonical
# form stored in each translation's JSON file.
# ---------------------------------------------------------------------------

_KJV_BOOKS: dict[str, str] = {
    # Old Testament
    "genesis": "Genesis", "gen": "Genesis", "gn": "Genesis",
    "exodus": "Exodus", "ex": "Exodus", "exo": "Exodus", "exod": "Exodus",
    "leviticus": "Leviticus", "lev": "Leviticus", "lv": "Leviticus",
    "numbers": "Numbers", "num": "Numbers", "nm": "Numbers",
    "deuteronomy": "Deuteronomy", "deut": "Deuteronomy", "deu": "Deuteronomy", "dt": "Deuteronomy",
    "joshua": "Joshua", "josh": "Joshua", "jos": "Joshua",
    "judges": "Judges", "judg": "Judges", "jdg": "Judges",
    "ruth": "Ruth", "ru": "Ruth",
    "1 samuel": "1 Samuel", "1sam": "1 Samuel", "1sa": "1 Samuel", "i samuel": "1 Samuel",
    "2 samuel": "2 Samuel", "2sam": "2 Samuel", "2sa": "2 Samuel", "ii samuel": "2 Samuel",
    "1 kings": "1 Kings", "1kgs": "1 Kings", "1ki": "1 Kings", "i kings": "1 Kings",
    "2 kings": "2 Kings", "2kgs": "2 Kings", "2ki": "2 Kings", "ii kings": "2 Kings",
    "1 chronicles": "1 Chronicles", "1chr": "1 Chronicles", "1ch": "1 Chronicles",
    "2 chronicles": "2 Chronicles", "2chr": "2 Chronicles", "2ch": "2 Chronicles",
    "ezra": "Ezra", "ezr": "Ezra",
    "nehemiah": "Nehemiah", "neh": "Nehemiah",
    "esther": "Esther", "est": "Esther", "esth": "Esther",
    "job": "Job",
    "psalms": "Psalms", "psalm": "Psalms", "ps": "Psalms", "psa": "Psalms",
    "proverbs": "Proverbs", "prov": "Proverbs", "pro": "Proverbs", "pr": "Proverbs",
    "ecclesiastes": "Ecclesiastes", "eccl": "Ecclesiastes", "ecc": "Ecclesiastes",
    "song of solomon": "Song of Solomon", "song": "Song of Solomon",
    "song of songs": "Song of Solomon", "sos": "Song of Solomon", "canticles": "Song of Solomon",
    "isaiah": "Isaiah", "isa": "Isaiah",
    "jeremiah": "Jeremiah", "jer": "Jeremiah",
    "lamentations": "Lamentations", "lam": "Lamentations",
    "ezekiel": "Ezekiel", "ezek": "Ezekiel", "eze": "Ezekiel",
    "daniel": "Daniel", "dan": "Daniel",
    "hosea": "Hosea", "hos": "Hosea",
    "joel": "Joel",
    "amos": "Amos",
    "obadiah": "Obadiah", "oba": "Obadiah", "ob": "Obadiah",
    "jonah": "Jonah", "jon": "Jonah",
    "micah": "Micah", "mic": "Micah",
    "nahum": "Nahum", "nah": "Nahum",
    "habakkuk": "Habakkuk", "hab": "Habakkuk",
    "zephaniah": "Zephaniah", "zeph": "Zephaniah", "zep": "Zephaniah",
    "haggai": "Haggai", "hag": "Haggai",
    "zechariah": "Zechariah", "zech": "Zechariah", "zec": "Zechariah",
    "malachi": "Malachi", "mal": "Malachi",
    # New Testament
    "matthew": "Matthew", "matt": "Matthew", "mt": "Matthew",
    "mark": "Mark", "mk": "Mark",
    "luke": "Luke", "lk": "Luke",
    "john": "John", "jn": "John", "joh": "John",
    "acts": "Acts", "ac": "Acts",
    "romans": "Romans", "rom": "Romans",
    "1 corinthians": "1 Corinthians", "1cor": "1 Corinthians", "1co": "1 Corinthians",
    "2 corinthians": "2 Corinthians", "2cor": "2 Corinthians", "2co": "2 Corinthians",
    "galatians": "Galatians", "gal": "Galatians",
    "ephesians": "Ephesians", "eph": "Ephesians",
    "philippians": "Philippians", "phil": "Philippians", "php": "Philippians",
    "colossians": "Colossians", "col": "Colossians",
    "1 thessalonians": "1 Thessalonians", "1thess": "1 Thessalonians", "1th": "1 Thessalonians",
    "2 thessalonians": "2 Thessalonians", "2thess": "2 Thessalonians", "2th": "2 Thessalonians",
    "1 timothy": "1 Timothy", "1tim": "1 Timothy", "1ti": "1 Timothy",
    "2 timothy": "2 Timothy", "2tim": "2 Timothy", "2ti": "2 Timothy",
    "titus": "Titus", "tit": "Titus",
    "philemon": "Philemon", "phlm": "Philemon", "phm": "Philemon",
    "hebrews": "Hebrews", "heb": "Hebrews",
    "james": "James", "jas": "James",
    "1 peter": "1 Peter", "1pet": "1 Peter", "1pe": "1 Peter",
    "2 peter": "2 Peter", "2pet": "2 Peter", "2pe": "2 Peter",
    "1 john": "1 John", "1jn": "1 John",
    "2 john": "2 John", "2jn": "2 John",
    "3 john": "3 John", "3jn": "3 John",
    "jude": "Jude",
    "revelation": "Revelation", "rev": "Revelation", "apoc": "Revelation",
}

_VP_BOOKS: dict[str, str] = {
    # Old Testament (Spanish)
    "genesis": "Génesis", "gen": "Génesis", "gn": "Génesis", "génesis": "Génesis",
    "exodo": "Éxodo", "ex": "Éxodo", "éxodo": "Éxodo", "exodus": "Éxodo",
    "levitico": "Levítico", "lev": "Levítico", "levítico": "Levítico",
    "numeros": "Números", "num": "Números", "números": "Números",
    "deuteronomio": "Deuteronomio", "deut": "Deuteronomio", "dt": "Deuteronomio",
    "josue": "Josué", "jos": "Josué", "josué": "Josué",
    "jueces": "Jueces", "jue": "Jueces",
    "rut": "Rut", "ru": "Rut",
    "1 samuel": "1 Samuel", "1sam": "1 Samuel", "1sa": "1 Samuel",
    "2 samuel": "2 Samuel", "2sam": "2 Samuel", "2sa": "2 Samuel",
    "1 reyes": "1 Reyes", "1re": "1 Reyes", "1r": "1 Reyes",
    "2 reyes": "2 Reyes", "2re": "2 Reyes", "2r": "2 Reyes",
    "1 cronicas": "1 Crónicas", "1cr": "1 Crónicas", "1 crónicas": "1 Crónicas",
    "2 cronicas": "2 Crónicas", "2cr": "2 Crónicas",
    "esdras": "Esdras", "esd": "Esdras",
    "nehemias": "Nehemías", "neh": "Nehemías", "nehemías": "Nehemías",
    "ester": "Ester", "est": "Ester",
    "job": "Job",
    "salmos": "Salmos", "sal": "Salmos", "ps": "Salmos", "sl": "Salmos",
    "proverbios": "Proverbios", "prov": "Proverbios", "pr": "Proverbios",
    "eclesiastes": "Eclesiastés", "ecl": "Eclesiastés", "eclesiastés": "Eclesiastés",
    "ecclesiastes": "Eclesiastés",
    "cantares": "Cantares", "cnt": "Cantares", "ct": "Cantares",
    "isaias": "Isaías", "isa": "Isaías", "is": "Isaías", "isaías": "Isaías",
    "jeremias": "Jeremías", "jer": "Jeremías", "jeremías": "Jeremías",
    "lamentaciones": "Lamentaciones", "lam": "Lamentaciones",
    "ezequiel": "Ezequiel", "eze": "Ezequiel", "ez": "Ezequiel",
    "daniel": "Daniel", "dan": "Daniel",
    "oseas": "Oseas", "os": "Oseas",
    "joel": "Joel",
    "amos": "Amós", "amós": "Amós",
    "abdias": "Abdías", "abd": "Abdías", "abdías": "Abdías",
    "jonas": "Jonás", "jon": "Jonás", "jonás": "Jonás",
    "miqueas": "Miqueas", "miq": "Miqueas",
    "nahum": "Nahúm", "nah": "Nahúm", "nahúm": "Nahúm",
    "habacuc": "Habacuc", "hab": "Habacuc",
    "sofonias": "Sofonías", "sof": "Sofonías", "sofonías": "Sofonías",
    "hageo": "Hageo", "hag": "Hageo",
    "zacarias": "Zacarías", "zac": "Zacarías", "zacarías": "Zacarías",
    "malaquias": "Malaquías", "mal": "Malaquías", "malaquías": "Malaquías",
    # New Testament (Spanish)
    "mateo": "Mateo", "mt": "Mateo",
    "marcos": "Marcos", "mr": "Marcos", "mc": "Marcos",
    "lucas": "Lucas", "lc": "Lucas",
    "juan": "Juan", "jn": "Juan",
    "hechos": "Hechos", "hch": "Hechos",
    "romanos": "Romanos", "rom": "Romanos",
    "1 corintios": "1 Corintios", "1cor": "1 Corintios", "1co": "1 Corintios",
    "2 corintios": "2 Corintios", "2cor": "2 Corintios", "2co": "2 Corintios",
    "galatas": "Gálatas", "gal": "Gálatas", "gálatas": "Gálatas",
    "efesios": "Efesios", "ef": "Efesios",
    "filipenses": "Filipenses", "fil": "Filipenses",
    "colosenses": "Colosenses", "col": "Colosenses",
    "1 tesalonicenses": "1 Tesalonicenses", "1ts": "1 Tesalonicenses",
    "2 tesalonicenses": "2 Tesalonicenses", "2ts": "2 Tesalonicenses",
    "1 timoteo": "1 Timoteo", "1tim": "1 Timoteo",
    "2 timoteo": "2 Timoteo", "2tim": "2 Timoteo",
    "tito": "Tito", "tit": "Tito",
    "filemon": "Filemón", "flm": "Filemón", "filemón": "Filemón",
    "hebreos": "Hebreos", "heb": "Hebreos",
    "santiago": "Santiago", "stg": "Santiago",
    "1 pedro": "1 Pedro", "1pe": "1 Pedro",
    "2 pedro": "2 Pedro", "2pe": "2 Pedro",
    "1 juan": "1 Juan", "1jn": "1 Juan",
    "2 juan": "2 Juan", "2jn": "2 Juan",
    "3 juan": "3 Juan", "3jn": "3 Juan",
    "judas": "Judas", "jud": "Judas",
    "apocalipsis": "Apocalipsis", "ap": "Apocalipsis",
}


def _normalize(text: str) -> str:
    # Decompose accented chars (é→e+´) then drop the accent marks, then lowercase and strip punctuation
    nfd = unicodedata.normalize("NFD", text.lower())
    no_accents = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s]", "", no_accents)


def _load(data_file: Path = None) -> list:
    data_file = data_file or DATA_FILE
    key = str(data_file)
    if key in _cache:
        return _cache[key]

    if not data_file.exists():
        raise FileNotFoundError(f"Bible data not found: {data_file}")

    with open(data_file, encoding="utf-8") as f:
        raw = json.load(f)

    verses = []
    if isinstance(raw, list) and raw and "chapters" in raw[0]:
        for book_data in raw:
            book_name = book_data.get("name") or book_data.get("book", "Unknown")
            for chap_idx, chapter in enumerate(book_data["chapters"]):
                for verse_idx, text in enumerate(chapter):
                    verses.append({
                        "book": book_name,
                        "chapter": chap_idx + 1,
                        "verse": verse_idx + 1,
                        "text": text.strip(),
                    })
    elif isinstance(raw, list) and raw and ("t" in raw[0] or "text" in raw[0]):
        for entry in raw:
            verses.append({
                "book": entry.get("book", str(entry.get("b", ""))),
                "chapter": int(entry.get("c", entry.get("chapter", 0))),
                "verse": int(entry.get("v", entry.get("verse", 0))),
                "text": entry.get("t", entry.get("text", "")).strip(),
            })
    else:
        raise ValueError(f"Unrecognised Bible JSON format in {data_file}")

    _cache[key] = verses
    return verses


def _match_word(qw: str, verse_words: set) -> float:
    """Score how well a query word matches any word in a verse (0.0–1.0).

    Returns 1.0 for an exact match. For words of 4+ characters, scans verse
    words for the longest common leading-character run and scores it as
    common_len / len(qw). Short words (< 4 chars) require an exact match.
    A score of 0.70 or above is treated as a successful match.
    """
    if qw in verse_words:
        return 1.0
    if len(qw) < 4:
        return 0.0
    best = 0.0
    for vw in verse_words:
        n = 0
        for a, b in zip(qw, vw):
            if a == b:
                n += 1
            else:
                break
        if n >= 4:
            best = max(best, n / len(qw))
    return best


_MATCH_THRESHOLD = 0.70  # minimum per-word score to count as a match


def find_verse_by_all_words(snippet: str, data_file: Path = None) -> int:
    """Return the index of the best-scoring verse where every query word
    meets _MATCH_THRESHOLD, or -1 if none qualifies.

    Scoring is proportional to how much of each query word is matched, so
    longer shared prefixes rank higher — e.g. 'libras' scores 5/6 = 0.83
    against 'libranos' but only 4/6 = 0.67 against 'libro', correctly
    preferring Matthew 6:13 over Deuteronomy 29:21.
    """
    verses = _load(data_file)
    words = _normalize(snippet).split()
    if not words:
        return -1
    best_idx, best_total = -1, -1.0
    for i, v in enumerate(verses):
        vwords = set(_normalize(v["text"]).split())
        total = 0.0
        ok = True
        for qw in words:
            s = _match_word(qw, vwords)
            if s < _MATCH_THRESHOLD:
                ok = False
                break
            total += s
        if ok and total > best_total:
            best_total = total
            best_idx = i
    return best_idx


def find_verse_by_reference(book: str, chapter: int, verse: int,
                             data_file: Path = None) -> int:
    """Return index of verse matching book/chapter/verse, or -1."""
    verses = _load(data_file)
    aliases = _VP_BOOKS if (data_file is not None and data_file == VP_FILE) else _KJV_BOOKS
    key = re.sub(r"\s+", " ", book.lower().strip())
    canonical = aliases.get(key, book).lower()
    for i, v in enumerate(verses):
        if (v["book"].lower() == canonical
                and v["chapter"] == chapter
                and v["verse"] == verse):
            return i
    return -1


def find_verse_index(snippet: str, data_file: Path = None) -> int:
    verses = _load(data_file)
    norm_snippet = _normalize(snippet)

    if _USE_RAPIDFUZZ:
        norm_texts = [_normalize(v["text"]) for v in verses]
        result = rfprocess.extractOne(
            norm_snippet, norm_texts, scorer=fuzz.token_set_ratio,
        )
        return result[2]
    else:
        best_idx, best_score = 0, 0.0
        for i, v in enumerate(verses):
            score = SequenceMatcher(None, norm_snippet, _normalize(v["text"])).ratio()
            if score > best_score:
                best_score = score
                best_idx = i
        return best_idx


def get_passage(center_idx: int, n: int, data_file: Path = None) -> list:
    verses = _load(data_file)
    start = max(0, center_idx - n)
    end = min(len(verses) - 1, center_idx + n)
    return verses[start : end + 1]


def _make_reference(first: dict, last: dict) -> str:
    if first["book"] == last["book"]:
        if first["chapter"] == last["chapter"]:
            if first["verse"] == last["verse"]:
                return f"{first['book']} {first['chapter']}:{first['verse']}"
            return f"{first['book']} {first['chapter']}:{first['verse']}-{last['verse']}"
        return f"{first['book']} {first['chapter']}:{first['verse']} - {last['chapter']}:{last['verse']}"
    return f"{first['book']} {first['chapter']}:{first['verse']} - {last['book']} {last['chapter']}:{last['verse']}"


def format_passage(verses_slice: list) -> str:
    paragraphs = [v["text"] for v in verses_slice]
    reference = _make_reference(verses_slice[0], verses_slice[-1])
    return "\n\n".join(paragraphs) + "\n\n" + reference
