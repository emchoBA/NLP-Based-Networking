import spacy
from spacy.matcher import Matcher

# ── Load spaCy’s pipeline ─────────────────────────────────────────
nlp = spacy.load("en_core_web_sm")

# ── Matcher for IPv4 addresses ────────────────────────────────────
matcher = Matcher(nlp.vocab)
matcher.add(
    "IP_ADDRESS",
    [[{"TEXT": {"REGEX": r"^(?:\d{1,3}\.){3}\d{1,3}$"}}]]
)

# ── What verbs count as actions ────────────────────────────────────
ACTION_VERBS = {
    "block", "deny", "drop", "reject",
    "allow", "permit", "accept"
}

# ── Prepositions that precede the IP clause ───────────────────────
_IP_PREPS = {"from", "to"}

def preprocess(text: str) -> str:
    """
    1) Trim whitespace
    2) Lowercase everything
    3) Collapse multiple spaces
    """
    text = text.strip().lower()
    return " ".join(text.split())

def parse_single(cmd: str) -> dict:
    """
    Parse one clause like "drop facebook from 1.2.3.4".
    Returns {'action': verb, 'service': noun, 'ip': address}.
    """
    clean = preprocess(cmd)
    doc   = nlp(clean)

    result = {"action": None, "service": None, "ip": None}

    # 1) ACTION: first token whose lemma is in ACTION_VERBS
    action_idx = None
    for i, tok in enumerate(doc):
        lem = tok.lemma_.lower()
        if lem in ACTION_VERBS:
            result["action"] = lem
            action_idx = i
            break

    # 2) SERVICE: first *non‐stop, non‐prep, alpha* token after the action
    if action_idx is not None:
        for tok in doc[action_idx+1 :]:
            if tok.is_stop or tok.is_punct:
                continue
            tl = tok.lemma_.lower()  # using lemma normalizes plurals, etc.
            if tl in _IP_PREPS:
                break
            if tok.is_alpha:
                result["service"] = tl
                break

    # 3) IP: first regex match via Matcher
    for match_id, start, end in matcher(doc):
        result["ip"] = doc[start:end].text
        break

    return result

def parse_commands(text: str) -> list:
    """
    Splits input into sentences, parses each one,
    and returns a list of {action, service, ip} dicts
    (only if both action & ip were found).
    """
    clean = preprocess(text)
    doc   = nlp(clean)
    out   = []
    for sent in doc.sents:
        cmd = parse_single(sent.text)
        if cmd["action"] and cmd["ip"]:
            out.append(cmd)
    return out

# ── Example usage ─────────────────────────────────────────────────
if __name__ == "__main__":
    test = (
        "Deny all Internet from 192.168.1.2.  "
        "Also drop Facebook to 10.0.0.5.  "
        "Finally allow SSH access to 192.168.1.100"
    )
    for parsed in parse_commands(test):
        print(parsed)
