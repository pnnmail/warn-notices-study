"""Name normalisation and parsing of employer name variants."""
import re

# service words are stripped only from the end of the name ("Bank of America, N.A." -> "bank of america")
TAIL = {"incorporated", "inc", "llc", "l l c", "corporation", "corp", "company", "co", "lp", "l p", "llp", "ltd",
        "limited", "plc", "pllc", "na", "n a", "national association", "holdings", "holding", "group", "usa", "us",
        "u s", "the", "and", "of", "pc", "p c", "sa", "s a", "nv", "bv", "ag", "gmbh", "lllp", "pa", "ulc", "pty",
        "pte", "sas", "s a s", "srl", "s r l", "sarl", "bv", "b v", "n v", "kg", "ab", "oy", "spa", "s p a", "lp"}


US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware", "florida",
    "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska",
    "nevada", "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", "texas",
    "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
    "puerto rico", "canada", "mexico", "united kingdom", "england", "germany", "france", "china", "japan",
    "india", "netherlands", "ireland", "luxembourg", "singapore", "australia", "brazil", "cayman islands",
    "bermuda", "switzerland", "spain", "italy", "hong kong", "korea", "israel", "belgium", "sweden"}
JUNK = {"name", "subsidiaries", "subsidiary", "jurisdiction", "state", "country", "organization",
        "incorporation", "place of incorporation", "jurisdiction of incorporation", "exhibit", "list of subsidiaries",
        "subsidiaries of registrant", "doing business as", "ownership", "percent", "domestic", "foreign",
        "international", "services", "holding", "management", "properties", "capital", "financial", "global"}

# Franchise brands: the employer under them is almost always a local franchisee, not the public company
FRANCHISE_BRANDS = {
    "mcdonald s", "mcdonalds", "burger king", "wendy s", "wendys", "taco bell", "kfc", "pizza hut", "subway",
    "dunkin", "dunkin donuts", "popeyes", "domino s", "dominos", "applebee s", "applebees", "ihop", "denny s",
    "dennys", "jack in box", "sonic", "arby s", "arbys", "dairy queen", "chick fil", "papa john s", "little caesars",
    "panera", "tim hortons", "7 eleven", "planet fitness", "h r block", "re max", "remax", "marriott", "hilton",
    "hyatt", "holiday inn", "hampton inn", "courtyard", "sheraton", "westin", "doubletree", "embassy suites",
    "best western", "radisson", "wyndham", "ramada", "choice hotels", "la quinta", "red robin", "buffalo wild wings",
    "chili s", "olive garden", "outback", "jersey mike s", "firehouse subs", "jimmy john s", "carl s jr", "hardee s",
    "anytime fitness", "orangetheory", "massage envy", "great clips", "supercuts", "midas", "jiffy lube", "meineke",
    "servpro", "goodyear", "ace hardware", "circle k", "shell", "chevron", "exxon", "bp", "sunoco", "speedway"}


# for subsidiaries: strip only legal forms, keep "group/holdings/management"
TAIL_LIGHT = {"incorporated", "inc", "llc", "l l c", "corporation", "corp", "company", "co", "lp", "l p", "llp",
              "ltd", "limited", "plc", "pllc", "na", "n a", "pc", "p c", "sa", "s a", "nv", "n v", "bv", "b v", "ag",
              "gmbh", "lllp", "pa", "ulc", "pty", "pte", "sas", "s a s", "srl", "s r l", "sarl", "kg", "ab", "oy",
              "spa", "s p a", "the"}


def norm_light(s):
    return norm(s, tail=TAIL_LIGHT)


def norm(s, tail=None):
    tail = TAIL if tail is None else tail
    s = str(s or "").lower()
    s = s.replace("&amp;", "&")
    for _ in range(2):  # SEC suffixes: "QUALCOMM INC/DE", "NORTHROP GRUMMAN CORP /DE/", "XYZ CORP /NEW/"
        s = re.sub(r"\s*/[a-z]{2,4}/?\s*$", "", s.strip())
    s = re.sub(r"['’`]", "", s)               # «Kohl's» = «KOHLS», «McDonald's» = «mcdonalds»
    s = re.sub(r"#\s*\d+", " ", s)            # «Walmart #1258»
    s = re.sub(r"\(.*?\)", " ", s)          # «(San Antonio)», «(BMS)»
    s = re.sub(r"\(.*$", " ", s)             # an unclosed parenthesis
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\b(dba|d b a|fka|f k a|aka|a k a)\b.*$", " ", s)  # tails after d/b/a — as a separate variant
    # ", a Delaware limited liability company" and the like
    s = re.sub(r"\s(a|an) (?:[a-z]+ ){1,3}(limited liability company|limited partnership|corporation|company)\b.*$", " ", s)
    w = s.split()
    while w:
        for k in (3, 2, 1):  # «l l c», «s a s», «n a», «inc»
            if len(w) >= k and " ".join(w[-k:]) in tail:
                w = w[:-k]
                break
        else:
            break
    if w and w[0] == "the":
        w = w[1:]
    return " ".join(w)


HEADER = re.compile(r"\b(subsidiar|exhibit|name of|entity|jurisdiction|incorporat|organized|as of|december|"
                    r"state or|percent|ownership|registrant|legal name|company name)")


def is_junk_name(n):
    return (not n or len(n) < 3 or n in US_STATES or n in JUNK or re.fullmatch(r"[\d\s]+", n) is not None
            or HEADER.search(n) is not None)


DBA = r"\b(?:d\s*/\s*b\s*/\s*a|d\.b\.a\.?|dba|doing business as)\b\.?"
FKA = r"\b(?:f\s*/\s*k\s*/\s*a|f\.k\.a\.?|fka|formerly known as|formerly)\b\.?"
PARENT = (r"\b(?:a |an )?(?:wholly[- ]owned |indirect |direct )*(?:subsidiary|affiliate|division|unit|"
          r"business unit|company) of\b")


def variants(raw):
    """Name variants: legal (legal entity), dba (trade name), fka (former), parent (mentioned parent),
    part (parts of a list "A; B and C, LLC"). Returns [(kind, raw text, normalised)]."""
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    out = []
    m = re.search(PARENT, s, re.I)
    if m:
        out.append(("parent", s[m.end():]))
        s = s[:m.start()].rstrip(" ,;-")
    m = re.search(FKA, s, re.I)
    if m:
        out.append(("fka", s[m.end():]))
        s = s[:m.start()].rstrip(" ,;-")
    m = re.search(DBA, s, re.I)
    if m:
        out.append(("dba", s[m.end():]))
        s = s[:m.start()].rstrip(" ,;-")
    out.insert(0, ("legal", s))
    if ";" in s or " / " in s:  # «StratFS, LLC; Strategic Consulting, LLC», WA: «Maverick Washington LLC / Chips Casino»
        for part in re.split(r";| / ", s):
            out.append(("part", part))
    res, seen = [], set()
    for kind, text in out:
        text = text.strip(" ,;-.")
        n = norm(text)
        if n and not is_junk_name(n) and (kind, n) not in seen:
            seen.add((kind, n))
            res.append((kind, text, n))
    return res


def is_franchise(n):
    return any(n == b or n.startswith(b + " ") for b in FRANCHISE_BRANDS)
