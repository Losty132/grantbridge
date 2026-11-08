"""Text utilities: HTML cleanup, safe display, sentence splitting, tokenizing, TF-IDF, quote checks."""
import html
import math
import re
from collections import Counter

STOPWORDS = set("""
a an and are as at be been being but by can could did do does for from had has have he her his how i if in into is it its
may more most must no not of on or our out over shall she should so such than that the their them then there these they this
those through to under up upon us was we were what when where which while who whom will with within without would you your
also any all each other both only own same very about above after again against before below between during further once
here just now off too via per new including include includes based well across among
""".split())
GRANT_STOPWORDS = set("""
grant grants program programs project projects funding fund funds funded award awards awarded applicant applicants
application applications apply eligible eligibility opportunity opportunities federal state states support supports
activities activity provide provides provided purpose purposes year years fiscal fy notice nofo agency agencies office
department national services service organizations organization entity entities cooperative agreement agreements
information please contact see section requirements required total approximately estimated number available
""".split())
_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]+")


def strip_html(text) -> str:
    if not text:
        return ""
    t = re.sub(r"<(br|p|li|div|tr)[^>]*>", " ", str(text), flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-!|>~<$])")


def md_safe(text, limit: int | None = None) -> str:
    """Escape API/user text before showing it with st.markdown so it can't inject links, images or HTML."""
    t = strip_html(text)
    if limit and len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + " …"
    return _MD_SPECIAL.sub(r"\\\1", t)


_ABBREV = re.compile(r"\b(U\.S|U\.S\.C|No|Nos|Sec|Secs|Dr|Mr|Ms|Mrs|St|e\.g|i\.e|etc|Inc|Pub|L|vs|approx|Jan|Feb|Mar|Apr|"
                     r"Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|[A-Z])\.$")


def sentences(text: str) -> list[str]:
    """Split into sentences without breaking on abbreviations like 'U.S.' or 'Sec.'."""
    raw = re.split(r"(?<=[.!?;])\s+(?=[A-Z0-9\"“(\[])", strip_html(text))
    out, buf = [], ""
    for part in raw:
        buf = f"{buf} {part}".strip() if buf else part
        if _ABBREV.search(buf.split(" ")[-1] if " " in buf else buf):
            continue
        out.append(buf)
        buf = ""
    if buf:
        out.append(buf)
    return [p.strip() for p in out if len(p.strip()) > 20]


def norm_for_match(text: str) -> str:
    t = strip_html(text).lower()
    t = t.replace("“", '"').replace("”", '"').replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9$%]+", " ", t).strip()


def quote_in_source(quote: str, source: str) -> bool:
    """True if the quote appears in the source text (ignoring case, punctuation and spacing)."""
    q = norm_for_match(quote)
    return bool(q) and len(q) >= 12 and q in norm_for_match(source)


def tokenize(text: str) -> list[str]:
    toks = _TOKEN.findall((text or "").lower())
    return [t for t in toks if t not in STOPWORDS and t not in GRANT_STOPWORDS and len(t) > 2 and not t.isdigit()]


class TfIdf:
    def __init__(self, documents: list[str]):
        self.n = max(1, len(documents))
        df = Counter()
        for d in documents:
            df.update(set(tokenize(d)))
        self.idf = {t: math.log((1 + self.n) / (1 + c)) + 1.0 for t, c in df.items()}
        self.default_idf = math.log(1 + self.n) + 1.0

    def vector(self, text: str) -> dict:
        tf = Counter(tokenize(text))
        if not tf:
            return {}
        v = {t: (1 + math.log(c)) * self.idf.get(t, self.default_idf) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}


def sparse_cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def keyword_hits(keywords: list[str], text: str) -> list[str]:
    found = []
    for kw in keywords:
        k = kw.strip()
        if not k:
            continue
        if len(k) <= 4 and k.isupper():
            pat = re.compile(r"\b" + re.escape(k) + r"\b")
            if pat.search(text or ""):
                found.append(kw)
        elif re.search(r"\b" + re.escape(k.lower()) + r"s?\b", (text or "").lower()):
            found.append(kw)
        elif " " not in k and len(k) >= 6:
            # light stemming for single words: 'digitize' finds 'digitization', 'recycling' finds 'recycle'
            stem = re.sub(r"(ing|ed|es|e|s)$", "", k.lower())
            if len(stem) >= 5 and re.search(r"\b" + re.escape(stem) + r"\w{0,6}\b", (text or "").lower()):
                found.append(kw)
    return found


def safe_keyword(q: str) -> str:
    """Validate a search keyword before sending it to an external API."""
    q = re.sub(r"[^A-Za-z0-9 \-&/']", " ", q or "")
    return re.sub(r"\s+", " ", q).strip()[:100]
