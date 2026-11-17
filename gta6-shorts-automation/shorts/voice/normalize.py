"""Turn display text into words a TTS engine reads correctly.

Captions keep the original tokens ("$79.99", "PS5"); the voice gets
"seventy-nine ninety-nine", "P S five". Normalisation is done per token so
each caption word knows exactly what is spoken for it (used for timing).
"""
from __future__ import annotations

import re

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ORD_IRREGULAR = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
                  "nine": "ninth", "twelve": "twelfth"}
MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
          "nov", "dec"}

SPECIAL = {
    "GTA": "G T A", "PS5": "P S five", "PS4": "P S four", "PC": "P C", "X|S": "X and S", "&": "and",
    "vs": "versus", "vs.": "versus", "AI": "A I", "DLC": "D L C", "NPC": "N P C", "NPCs": "N P Cs",
    "TV": "T V", "4K": "four K", "FPS": "F P S", "RPG": "R P G", "US": "U S", "UK": "U K", "EU": "E U",
    "T-MINUS": "T minus", "Xbox": "Xbox",
}
ROMAN_AFTER = {"GTA": {"VI": "six", "V": "five", "IV": "four", "III": "three"},
               "Auto": {"VI": "six", "V": "five", "IV": "four", "III": "three"}}

_PUNCT_LEAD = re.compile(r"^([\"'“‘(\[]*)(.*?)([\"'”’)\].,!?;:…]*)$", re.S)


def int_to_words(n: int) -> str:
    if n < 0:
        return "minus " + int_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else "-" + _ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + " hundred" + ("" if rest == 0 else " " + int_to_words(rest))
    for div, word in ((10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        if n >= div:
            rest = n % div
            return int_to_words(n // div) + f" {word}" + ("" if rest == 0 else " " + int_to_words(rest))
    return str(n)


def ordinal_words(n: int) -> str:
    words = int_to_words(n)
    head, sep, last = words.rpartition("-") if "-" in words.split()[-1] else words.rpartition(" ")
    if last in _ORD_IRREGULAR:
        last = _ORD_IRREGULAR[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return f"{head}{sep}{last}" if head else last


def year_words(n: int) -> str:
    if 2000 <= n <= 2009:
        return "two thousand" + ("" if n == 2000 else " " + _ONES[n - 2000])
    hi, lo = divmod(n, 100)
    if lo == 0:
        return int_to_words(hi) + " hundred"
    return int_to_words(hi) + " " + (("oh " + _ONES[lo]) if lo < 10 else int_to_words(lo))


def _number(core: str) -> str:
    digits = core.replace(",", "")
    if "." in digits:
        whole, frac = digits.split(".", 1)
        return int_to_words(int(whole or 0)) + " point " + " ".join(_ONES[int(d)] for d in frac)
    return int_to_words(int(digits))


def speak_core(core: str, prev: str = "") -> str:
    """Spoken form of one token without surrounding punctuation."""
    if not core:
        return core
    if len(core) > 2 and core[-2:] in ("'s", "’s") and any(ch.isdigit() or ch.isupper() for ch in core[:-2]):
        return speak_core(core[:-2], prev) + "'s"          # "6's" -> "six's", "GTA's" -> "G T A's"
    prev_clean = re.sub(r"[^\w|]", "", prev)
    if prev_clean in ROMAN_AFTER and core in ROMAN_AFTER[prev_clean]:
        return ROMAN_AFTER[prev_clean][core]
    if core in SPECIAL:
        return SPECIAL[core]
    m = re.fullmatch(r"([$€£])(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{2}))?", core)
    if m:
        cur, whole, cents = m.groups()
        unit = {"$": "dollars", "€": "euros", "£": "pounds"}[cur]
        whole_w = int_to_words(int(whole.replace(",", "")))
        if cents and cents != "00":
            spoken = f"{whole_w} {int_to_words(int(cents))}"
            return spoken if cur == "$" else f"{spoken} {unit}"
        return f"{whole_w} {unit}"
    m = re.fullmatch(r"(\d+)([MKB])", core)
    if m:
        return int_to_words(int(m.group(1))) + {"M": " million", "K": " thousand", "B": " billion"}[m.group(2)]
    m = re.fullmatch(r"#(\d+)", core)
    if m:
        return "number " + int_to_words(int(m.group(1)))
    m = re.fullmatch(r"(\d+)(st|nd|rd|th)", core, re.I)
    if m:
        return ordinal_words(int(m.group(1)))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)%", core)
    if m:
        return _number(m.group(1)) + " percent"
    if re.fullmatch(r"(19|20)\d{2}", core):
        return year_words(int(core))
    if re.fullmatch(r"\d{1,2}", core) and prev_clean.lower() in MONTHS:
        return ordinal_words(int(core))
    if re.fullmatch(r"\d{1,3}(,\d{3})+|\d+(\.\d+)?", core):
        return _number(core)
    if re.search(r"\d", core) and "-" in core:  # 24-hour, 20-minute
        return "-".join(speak_core(part) for part in core.split("-"))
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", core)  # e.g. PS5-like codes not in SPECIAL
    if m and m.group(1).isupper():
        return " ".join(m.group(1)) + " " + int_to_words(int(m.group(2)))
    return core.replace("|", " ")


def split_punct(token: str) -> tuple[str, str, str]:
    m = _PUNCT_LEAD.match(token)
    if not m:
        return "", token, ""
    lead, core, trail = m.groups()
    # Keep a decimal/currency core intact: "$79.99." -> core "$79.99", trail "."
    return lead, core, trail


def speak_tokens(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for i, tok in enumerate(tokens):
        lead, core, trail = split_punct(tok)
        prev = split_punct(tokens[i - 1])[1] if i else ""
        out.append(f"{speak_core(core, prev)}{trail}")
    return out


def speakable(text: str) -> str:
    """Whole-string normalisation (used for the TTS input)."""
    return " ".join(speak_tokens(text.split()))
