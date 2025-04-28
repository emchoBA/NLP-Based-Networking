import spacy
from spacy.matcher import Matcher

# Load spaCy's pipeline
nlp = spacy.load("en_core_web_sm")

# Matcher for IPv4 addresses
matcher = Matcher(nlp.vocab)
matcher.add(
    "IP_ADDRESS",
    [[{"TEXT": {"REGEX": r"^(?:\d{1,3}\.){3}\d{1,3}$"}}]]
)

# What verbs count as actions
ACTION_VERBS = {
    "block", "deny", "drop", "reject",
    "allow", "permit", "accept"
}

# Prepositions identifying the *target device* (where the rule applies)
TARGET_DEVICE_PREPS = {"on", "at"}
# Prepositions identifying the *subject IP* (used in the rule condition)
SUBJECT_IP_PREPS = {"from", "to"}

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
    Parse one clause like "block ssh from 1.2.3.4" or "on 10.0.0.1 deny traffic from 1.2.3.4".
    Returns a dict containing:
    {'action': str|None, 'service': str|None,
     'subject_ip': str|None, 'subject_ip_direction': str|None,
     'target_device_ip': str|None}
    """
    clean = preprocess(cmd)
    doc   = nlp(clean)

    result = {
        "action": None,
        "service": None,
        "subject_ip": None,
        "subject_ip_direction": None,
        "target_device_ip": None,
    }

    # 1) ACTION: Find the first action verb
    action_idx = -1 # Use -1 to indicate not found yet
    for i, tok in enumerate(doc):
        lem = tok.lemma_.lower()
        if lem in ACTION_VERBS:
            result["action"] = lem
            action_idx = i
            break

    # 2) SERVICE: Find the first relevant noun after the action (if action exists)
    if action_idx != -1:
        # Define boundary prepositions that usually end the service description
        boundary_preps = TARGET_DEVICE_PREPS.union(SUBJECT_IP_PREPS)
        for tok in doc[action_idx + 1:]:
            if tok.is_stop or tok.is_punct:
                continue
            tl = tok.lemma_.lower()
            # Stop if we hit a preposition indicating an IP role or target device
            if tl in boundary_preps:
                break
            if tok.is_alpha:
                result["service"] = tl
                break # Found the service

    # 3) IPs: Find all IP addresses and try to determine their role based on preceding prepositions.
    ip_matches = []
    for match_id, start, end in matcher(doc):
        ip_text = doc[start:end].text
        preceding_token_lemma = None
        if start > 0:
            preceding_token_lemma = doc[start - 1].lemma_.lower()
        ip_matches.append({
            "ip": ip_text,
            "prep": preceding_token_lemma,
            "start_index": start
        })

    # Try to assign roles: Target Device has priority if specified
    assigned_target = False
    assigned_subject = False

    # Prioritize finding the target device IP ("on"/"at")
    temp_matches = list(ip_matches) # Work on a copy
    for i, match in enumerate(temp_matches):
        if match["prep"] in TARGET_DEVICE_PREPS:
            result["target_device_ip"] = match["ip"]
            print(f"[NLP DEBUG] Found Target Device IP: {match['ip']} (preceded by '{match['prep']}')")
            ip_matches.pop(i) # Remove from original list so it's not reused
            assigned_target = True
            break # Assume only one target device specifier per command

    # Then, try to find the subject IP ("from"/"to") among remaining matches
    temp_matches = list(ip_matches) # Refresh copy
    for i, match in enumerate(temp_matches):
         if match["prep"] in SUBJECT_IP_PREPS:
             result["subject_ip"] = match["ip"]
             result["subject_ip_direction"] = match["prep"]
             print(f"[NLP DEBUG] Found Subject IP: {match['ip']} (preceded by '{match['prep']}')")
             ip_matches.pop(i) # Remove from original list
             assigned_subject = True
             break # Assume only one subject IP specifier per command

    # If subject IP wasn't found via "from/to", but there's exactly one *remaining* IP,
    # assume it's the subject IP (but direction will be None).
    if not assigned_subject and len(ip_matches) == 1:
        match = ip_matches[0]
        result["subject_ip"] = match["ip"]
        result["subject_ip_direction"] = None # Direction is unknown
        print(f"[NLP DEBUG] Found Subject IP: {match['ip']} (no clear 'from/to' preposition)")
        assigned_subject = True


    # If no target device was explicitly specified ("on"/"at"),
    # but we *did* find a subject IP, assume the rule applies *on* the subject IP's device.
    if not assigned_target and assigned_subject:
        result["target_device_ip"] = result["subject_ip"]
        print(f"[NLP DEBUG] No Target Device specified, defaulting to Subject IP: {result['target_device_ip']}")


    # Final check: ensure essential parts were found
    if not result["action"]:
        print("[NLP WARN] No action verb found.")
        return {} # Return empty if no action
    if not result["subject_ip"]:
         print("[NLP WARN] No subject IP found or assigned.")
         return {} # Return empty if no subject IP

    # Target device IP MUST be set by now (either explicitly or via fallback)
    if not result["target_device_ip"]:
        print("[NLP ERROR] Logic error: Target device IP not set.")
        return {}


    print(f"[NLP PARSED] {result}")
    return result


def parse_commands(text: str) -> list:
    """
    Splits input into sentences, parses each one using parse_single,
    and returns a list of valid dictionaries (must have action & subject_ip).
    """
    clean = preprocess(text)
    doc   = nlp(clean)
    out   = []
    print(f"\n[NLP] Parsing text: '{clean}'")
    for i, sent in enumerate(doc.sents):
        print(f"[NLP] Processing sentence {i+1}: '{sent.text}'")
        cmd_dict = parse_single(sent.text)
        # Check if the dict is non-empty (meaning basic requirements were met)
        if cmd_dict:
            out.append(cmd_dict)
        else:
            print(f"[NLP] Sentence {i+1} did not yield a valid command structure.")
    print(f"[NLP] Finished parsing. Found {len(out)} command(s).")
    return out

# Example usage
if __name__ == "__main__":
    tests = [
        "Deny all Internet from 192.168.1.2.", # Single IP
        "On 10.0.0.1 block Facebook to 10.0.0.5.", # Two IPs, target specified
        "Allow SSH to 192.168.1.100.", # Single IP
        "At 192.168.1.254 reject traffic from 192.168.5.5.", # Two IPs, target specified
        "permit icmp 1.1.1.1", # Single IP, no direction
        "on router drop 8.8.8.8", # Invalid IP as target (for now), no subject IP prep
        "Accept connection from 1.2.3.4 on device 5.6.7.8", # Cannot parse 'device' name
        "at 10.10.10.1 permit from 10.10.10.200", # Two IPs, service missing but ok
        "block 1.1.1.1" # Single IP, no direction
    ]
    all_results = []
    for test in tests:
        print(f"\n--- Testing: '{test}' ---")
        parsed = parse_commands(test)
        all_results.extend(parsed)
        print("--- End Test ---")

    print("\n=== Final Parsed Results ===")
    for i, res in enumerate(all_results):
        print(f"{i+1}: {res}")
    print("============================")