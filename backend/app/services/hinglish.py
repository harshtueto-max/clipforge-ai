"""Hindi (Devanagari) and Hinglish (Romanized Hindi + English) text processing utilities.

100% local, deterministic, zero external dependencies:
- Detects Devanagari script (`\u0900`–`\u097F`).
- Converts Devanagari words into natural creator-style Roman Hinglish using a curated high-frequency lexicon
  plus a phonetic Devanagari transliterator with Hindi schwa-deletion rules, while leaving English words untouched.
- Supplies Hinglish stopwords and rhetorical cue patterns so clip discovery scores Hindi/Hinglish speech accurately.
"""
from __future__ import annotations

import re

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_DEV_TOKEN_RE = re.compile(r"[\u0900-\u097F]+")

# High-frequency Hindi words mapped to standard Indian short-form creator Hinglish spellings
LEXICON: dict[str, str] = {
    "है": "hai", "हैं": "hain", "हूँ": "hoon", "हूं": "hoon", "हो": "ho", "था": "tha", "थी": "thi", "थे": "the",
    "थीं": "thin", "गया": "gaya", "गई": "gayi", "गयी": "gayi", "गए": "gaye", "गये": "gaye",
    "मैं": "main", "में": "mein", "मेरा": "mera", "मेरी": "meri", "मेरे": "mere", "मुझे": "mujhe", "मुझको": "mujhko",
    "हम": "hum", "हमारा": "hamara", "हमारी": "hamari", "हमारे": "hamare", "हमें": "humein",
    "आप": "aap", "आपका": "aapka", "आपकी": "aapki", "आपके": "aapke", "आपको": "aapko",
    "तुम": "tum", "तुम्हारा": "tumhara", "तुम्हारी": "tumhari", "तुम्हें": "tumhein", "तू": "tu", "तेरा": "tera", "तेरी": "teri", "तेरे": "tere", "तुझे": "tujhe",
    "यह": "yeh", "ये": "ye", "वह": "woh", "वो": "wo", "इस": "is", "उस": "us", "इन": "in", "उन": "un", "यहाँ": "yahan", "यहा": "yaha", "वहाँ": "wahan", "वहा": "waha",
    "का": "ka", "की": "ki", "के": "ke", "को": "ko", "से": "se", "पर": "par", "पे": "pe", "तक": "tak", "लिए": "liye", "लिये": "liye", "साथ": "saath", "बिना": "bina",
    "और": "aur", "या": "ya", "तो": "toh", "भी": "bhi", "ही": "hi", "ना": "na", "नहीं": "nahi", "नही": "nahi", "मत": "mat",
    "हाँ": "haan", "हां": "haan", "जी": "ji", "अच्छा": "achha", "अच्छी": "achhi", "अच्छे": "achhe", "ठीक": "theek", "सही": "sahi", "गलत": "galat", "ग़लत": "galat",
    "क्या": "kya", "क्यों": "kyun", "क्यूँ": "kyun", "क्योंकि": "kyunki", "कैसे": "kaise", "कैसा": "kaisa", "कैसी": "kaisi", "कब": "kab", "कहाँ": "kahan", "कौन": "kaun", "कितना": "kitna", "कितने": "kitne", "कितनी": "kitni",
    "अगर": "agar", "मगर": "magar", "लेकिन": "lekin", "परन्तु": "parantu", "फिर": "phir", "सिर्फ": "sirf", "सिर्फ़": "sirf", "बस": "bas", "शायद": "shayad", "बिल्कुल": "bilkul", "बिलकुल": "bilkul",
    "बहुत": "bahut", "बड़ा": "bada", "बड़ी": "badi", "बड़े": "bade", "छोटा": "chhota", "छोटी": "chhoti", "ज़्यादा": "zyada", "ज्यादा": "zyada", "कम": "kam", "पूरा": "poora", "पूरी": "poori", "पूरे": "poore",
    "सब": "sab", "सभी": "sabhi", "सबसे": "sabse", "कुछ": "kuch", "कोई": "koi", "हर": "har", "एक": "ek", "दो": "do", "तीन": "teen", "चार": "chaar", "पाँच": "paanch", "पांच": "paanch", "दस": "das", "सौ": "sau", "हज़ार": "hazaar", "लाख": "lakh", "करोड़": "crore",
    "भाई": "bhai", "यार": "yaar", "दोस्त": "dost", "दोस्तों": "dosto", "लोग": "log", "लोगों": "logo", "बच्चा": "bachcha", "बच्चे": "bachche", "बच्चों": "bachcho", "माँ": "maa", "पापा": "papa", "घर": "ghar",
    "बात": "baat", "बातें": "baatein", "काम": "kaam", "नाम": "naam", "आज": "aaj", "कल": "kal", "अभी": "abhi", "अब": "ab", "जब": "jab", "तब": "tab", "पहले": "pehle", "बाद": "baad", "हमेशा": "hamesha", "कभी": "kabhi",
    "ज़िंदगी": "zindagi", "जिंदगी": "zindagi", "ज़िन्दगी": "zindagi", "दुनिया": "duniya", "दिल": "dil", "प्यार": "pyaar", "पैसा": "paisa", "पैसे": "paise", "वक़्त": "waqt", "वक्त": "waqt", "समय": "samay", "सपना": "sapna", "सपने": "sapne", "कहानी": "kahani", "सच": "sach", "झूठ": "jhooth", "मज़ा": "maza", "मजा": "maza", "मज़ाक": "mazaak", "मजाक": "mazaak",
    "मतलब": "matlab", "समझ": "samajh", "लगता": "lagta", "लगती": "lagti", "लगते": "lagte", "पता": "pata", "चाहिए": "chahiye", "चाहता": "chahta", "चाहती": "chahti",
    "करना": "karna", "करते": "karte", "करता": "karta", "करती": "karti", "किया": "kiya", "किए": "kiye", "करो": "karo", "करिए": "kariye", "रहा": "raha", "रही": "rahi", "रहे": "rahe",
    "आता": "aata", "आती": "aati", "आते": "aate", "आया": "aaya", "आयी": "aayi", "जाता": "jaata", "जाती": "jaati", "जाना": "jaana", "चलो": "chalo", "देखा": "dekha", "देखो": "dekho", "देखिए": "dekhiye",
    "बोलो": "bolo", "बोला": "bola", "कहा": "kaha", "सुनो": "suno", "सुना": "suna", "मिला": "mila", "मिली": "mili", "दिया": "diya", "लिया": "liya", "हुआ": "hua", "हुई": "hui", "हुए": "hue",
    "वाला": "wala", "वाली": "wali", "वाले": "wale", "नमस्ते": "namaste", "स्वागत": "swagat", "धन्यवाद": "dhanyawad", "शुक्रिया": "shukriya", "माफ़": "maaf", "माफ": "maaf", "अरे": "arey", "वाह": "waah", "ओह": "oh",
}

_INDEP_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e",
}

_MATRAS = {
    "ा": "a", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
}

_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "ळ": "l",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
}

_NUKTA_CONSONANTS = {
    "क़": "q", "ख़": "kh", "ग़": "gh", "ज़": "z", "ड़": "d", "ढ़": "rh", "फ़": "f", "य़": "y",
}

_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_HALANT = "्"
_NUKTA = "़"


def has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI_RE.search(text or ""))


def _transliterate_word(word: str) -> str:
    if word in LEXICON:
        return LEXICON[word]
    w = word.translate(_DIGITS)
    if w in LEXICON:
        return LEXICON[w]
    n = len(w)
    out: list[str] = []
    i = 0
    while i < n:
        ch = w[i]
        # Consonant (+ optional nukta)
        if ch in _CONSONANTS or (i + 1 < n and w[i: i + 2] in _NUKTA_CONSONANTS):
            if i + 1 < n and w[i: i + 2] in _NUKTA_CONSONANTS:
                base = _NUKTA_CONSONANTS[w[i: i + 2]]
                i += 2
            else:
                base = _CONSONANTS[ch]
                i += 1
                if i < n and w[i] == _NUKTA:
                    i += 1
            if i < n and w[i] == _HALANT:
                out.append(base)
                i += 1
            elif i < n and w[i] in _MATRAS:
                matra = _MATRAS[w[i]]
                # Word-initial or short 'aa' looks natural as 'aa' when stressed, 'a' at word end
                if w[i] == "ा" and i + 1 < n:
                    matra = "aa"
                out.append(base + matra)
                i += 1
            else:
                # Inherent schwa ('a'): delete at word end (Hindi schwa deletion), keep elsewhere
                at_end = (i == n) or (i == n - 1 and w[i] in ("ं", "ँ"))
                # Single-consonant word keeps 'a' (e.g. न -> na)
                if not at_end or len(out) == 0:
                    out.append(base + "a")
                else:
                    out.append(base)
        elif ch in _INDEP_VOWELS:
            out.append(_INDEP_VOWELS[ch])
            i += 1
        elif ch in _MATRAS:
            out.append(_MATRAS[ch])
            i += 1
        elif ch in ("ं", "ँ"):
            # Anusvara / chandrabindu: 'm' before labials (p/b/m), 'n' elsewhere
            nxt = w[i + 1] if i + 1 < n else ""
            out.append("m" if nxt in ("प", "फ", "ब", "भ", "म") else "n")
            i += 1
        elif ch == "ः":
            out.append("h")
            i += 1
        elif ch in (_HALANT, _NUKTA, "ऽ"):
            i += 1
        else:
            out.append(ch)
            i += 1
    res = "".join(out)
    # Clean common double-a endings like 'aaha' -> 'aah'
    res = re.sub(r"aa$", "a", res) if len(res) > 4 else res
    return res


def to_hinglish(text: str) -> str:
    """Convert any Devanagari spans in `text` to natural Roman Hinglish while keeping English words untouched."""
    if not text:
        return text
    t = text.replace("।", ".").replace("॥", ".").translate(_DIGITS)
    if not has_devanagari(t):
        return t
    out = _DEV_TOKEN_RE.sub(lambda m: _transliterate_word(m.group(0)), t)
    # Capitalize sentence openings cleanly
    out = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), out)
    return out


HINGLISH_STOPWORDS = {
    "hai", "hain", "hoon", "ho", "tha", "thi", "the", "main", "mein", "hum", "aap", "tum", "tu",
    "ye", "yeh", "wo", "woh", "ka", "ki", "ke", "ko", "se", "par", "pe", "bhi", "toh", "aur", "ya",
    "ek", "kya", "nahi", "na", "haan", "ji", "acha", "achha", "bhai", "yaar", "kuch", "sab", "koi",
    "kar", "kiya", "raha", "rahi", "rahe", "wala", "wali", "wale", "ab", "jab", "tab",
}

HINGLISH_PATTERNS: dict[str, list[tuple[str, float]]] = {
    "hook": [
        (r"\b(sach batau|dekho bhai|sabse (bada|badi|important)|ek baat (batau|samjho)|kya aapko pata|galatfehmi)\b", 1.0),
        (r"\b(koi nahi batata|log सोचते|log sochte|kasam se|shocking|bawaal)\b", 0.9),
    ],
    "conclusion": [
        (r"\b(isliye|toh baat yeh hai|bas yahi|samajh gaye|khatam baat|asli baat)\b", 0.9),
    ],
    "story": [
        (r"\b(ek baar|jab main|mujhe yaad hai|kahani|tab hua yeh|bachpan mein)\b", 0.8),
    ],
    "advice": [
        (r"\b(aapko chahiye|hamesha yaad rakho|meri mano|ek tip|mat karo|zaroor karo)\b", 0.8),
    ],
    "humor": [
        (r"\b(mazaak|mazak|hasi|pagal|bakwaas|bhai sahab|arey yaar|khatarnaak)\b", 0.7),
    ],
    "emotion": [
        (r"\b(dil|pyaar|rona|ro diya|dard|zindagi|maa|sapna|mehnat|garv|khushi)\b", 0.8),
    ],
}
