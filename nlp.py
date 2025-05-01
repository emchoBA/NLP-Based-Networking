# --- START OF FILE nlp.py ---

import spacy
from spacy.matcher import Matcher
import logging # Use logging

# --- Get Logger specific to this module ---
log = logging.getLogger(__name__)
if not log.hasHandlers():
     # Basic config if run standalone (won't interfere with GUI handler)
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(name)s] %(levelname)s - %(message)s')

# Load spaCy's pipeline
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    log.error("Spacy model 'en_core_web_sm' not found. Please run: python -m spacy download en_core_web_sm")
    # Handle the error appropriately, maybe raise or exit
    raise SystemExit("Spacy model not found.")


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

# --- Define preposition roles ---
TARGET_DEVICE_PREPS = {"on", "at"}
SOURCE_IP_PREPS = {"from"}
DESTINATION_IP_PREPS = {"to"}
# Combine for boundary checking during service parsing
BOUNDARY_PREPS = TARGET_DEVICE_PREPS.union(SOURCE_IP_PREPS).union(DESTINATION_IP_PREPS)


def preprocess(text: str) -> str:
    """Standard preprocessing."""
    text = text.strip().lower()
    # Basic cleanup - might need refinement
    text = text.replace(',', ' ')
    return " ".join(text.split())

def parse_single(cmd: str) -> dict:
    """
    Parse one clause. Can handle:
    - action [service] from [IP]
    - action [service] to [IP]
    - action [service] from [IP1] to [IP2]
    - on [IP_Target] action [service] from [IP_Source]
    - on [IP_Target] action [service] to [IP_Dest]
    - on [IP_Target] action [service] from [IP_Source] to [IP_Dest]

    Returns a dict containing:
    {'action': str|None, 'service': str|None,
     'source_ip': str|None, 'destination_ip': str|None,
     'target_device_ip': str|None} # Target is WHERE the rule is applied
    Returns {} if essential parts are missing.
    """
    clean = preprocess(cmd) # Use basic preprocessing for single clause
    doc = nlp(clean)

    # --- Initialize result dictionary with new structure ---
    result = {
        "action": None, "service": None,
        "source_ip": None, "destination_ip": None,
        "target_device_ip": None,
    }

    # 1) ACTION: Find the first action verb
    action_idx = -1
    for i, tok in enumerate(doc):
        lem = tok.lemma_.lower()
        if lem in ACTION_VERBS:
            result["action"] = lem
            action_idx = i
            break

    # 2) SERVICE: Find the first relevant noun after the action (if action exists)
    if action_idx != -1:
        for tok in doc[action_idx + 1:]:
            if tok.is_stop or tok.is_punct:
                continue
            tl = tok.lemma_.lower()
            if tl in BOUNDARY_PREPS: # Stop if we hit any IP-related preposition
                break
            if tok.is_alpha:
                result["service"] = tl
                break # Found the service

    # 3) IPs: Find all IP addresses and try to determine their roles
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

    log.debug(f"[NLP] Found IP matches in clause '{doc.text}': {ip_matches}")

    # --- Assign IP Roles ---
    target_assigned_explicitly = False
    source_assigned = False
    destination_assigned = False
    remaining_matches = list(ip_matches) # Work on a copy

    # Priority 1: Explicit Target Device ("on"/"at")
    temp_remaining = []
    for match in remaining_matches:
        if match["prep"] in TARGET_DEVICE_PREPS:
            if not result["target_device_ip"]: # Assign only the first one found
                result["target_device_ip"] = match["ip"]
                target_assigned_explicitly = True
                log.debug(f"[NLP] Assigned Explicit Target IP: {match['ip']} (from '{match['prep']}')")
            else:
                 log.warning(f"[NLP] Multiple 'on/at' IPs found. Using first: {result['target_device_ip']}. Ignoring: {match['ip']}")
                 temp_remaining.append(match) # Keep it for potential source/dest roles if needed
        else:
            temp_remaining.append(match)
    remaining_matches = temp_remaining

    # Priority 2: Source IP ("from")
    temp_remaining = []
    for match in remaining_matches:
        if match["prep"] in SOURCE_IP_PREPS:
            if not result["source_ip"]: # Assign only first "from"
                result["source_ip"] = match["ip"]
                source_assigned = True
                log.debug(f"[NLP] Assigned Source IP: {match['ip']} (from '{match['prep']}')")
            else:
                log.warning(f"[NLP] Multiple 'from' IPs found. Using first: {result['source_ip']}. Ignoring: {match['ip']}")
                # Don't keep unmatched 'from' IPs usually
        else:
            temp_remaining.append(match)
    remaining_matches = temp_remaining

    # Priority 3: Destination IP ("to")
    temp_remaining = []
    for match in remaining_matches:
        if match["prep"] in DESTINATION_IP_PREPS:
            if not result["destination_ip"]: # Assign only first "to"
                result["destination_ip"] = match["ip"]
                destination_assigned = True
                log.debug(f"[NLP] Assigned Destination IP: {match['ip']} (from '{match['prep']}')")
            else:
                log.warning(f"[NLP] Multiple 'to' IPs found. Using first: {result['destination_ip']}. Ignoring: {match['ip']}")
                # Don't keep unmatched 'to' IPs usually
        else:
            temp_remaining.append(match)
    remaining_matches = temp_remaining

    # Priority 4: Unassigned IP (Default single remaining IP to Source)
    if len(remaining_matches) == 1 and not source_assigned and not destination_assigned:
        # If only one IP remains *after* checking for target/src/dest preps
        match = remaining_matches[0]
        result["source_ip"] = match["ip"]
        source_assigned = True
        log.debug(f"[NLP] Assigned remaining IP as Source IP (default): {match['ip']}")
        remaining_matches.pop(0)

    if remaining_matches:
         log.warning(f"[NLP] Unassigned IP addresses remaining after parsing: {[m['ip'] for m in remaining_matches]}")

    # --- Determine Final Target Device IP ---
    if not target_assigned_explicitly:
        # If target wasn't 'on X', default target to Destination, then Source
        if destination_assigned:
            result["target_device_ip"] = result["destination_ip"]
            log.debug(f"[NLP] Implicit Target IP set to Destination IP: {result['target_device_ip']}")
        elif source_assigned:
            # If no destination, default target to the source
            result["target_device_ip"] = result["source_ip"]
            log.debug(f"[NLP] Implicit Target IP set to Source IP: {result['target_device_ip']}")
        # Else: target_device_ip remains None if no IPs were found/assigned

    # --- Final Validation ---
    if not result["action"]:
        log.warning("[NLP] Parse failed: No action verb found.")
        return {}
    if not result["target_device_ip"]:
        # Can happen if only IPs without preps/actions are present
        log.warning("[NLP] Parse failed: Could not determine Target Device IP.")
        return {}
    if not result["source_ip"] and not result["destination_ip"]:
        # Need at least one IP for the rule itself
        log.warning("[NLP] Parse failed: No Source or Destination IP identified for the rule.")
        return {}

    # If service wasn't found, default it for clarity in output
    if result["action"] and not result["service"]:
        result["service"] = "any" # Default to 'any' if not specified

    log.info(f"[NLP] Parsed Result: {result}")
    return result


def parse_commands(text: str) -> list:
    """
    Splits input into sentences, parses each one using parse_single,
    and returns a list of valid dictionaries.
    """
    # Use basic preprocessing for the whole input text
    clean = preprocess(text)
    doc = nlp(clean)
    out = []
    log.debug(f"\n[NLP] Parsing text: '{clean}'")

    # --- Iterate through sentences ---
    for i, sent in enumerate(doc.sents):
        log.debug(f"[NLP] Processing sentence {i+1}: '{sent.text}'")
        # Parse each sentence independently
        cmd_dict = parse_single(sent.text)
        if cmd_dict: # Add if parse_single returned a valid dict
            out.append(cmd_dict)
        else:
            log.warning(f"[NLP] Sentence {i+1} did not yield a valid command structure.")
    # --- End iteration ---

    log.debug(f"[NLP] Finished parsing. Found {len(out)} command(s) total.")
    return out


# Example usage
if __name__ == "__main__":
    logging.getLogger(__name__).setLevel(logging.DEBUG) # Show debug for testing
    tests = [
        # --- Tests ---
        "deny ssh from 192.168.1.12 to 192.168.1.11",
        "allow http from 10.0.0.5 to 192.168.1.11",
        "block dns to 8.8.8.8 from 192.168.1.11",
        "on 192.168.1.1 permit tcp from 192.168.1.12 to 192.168.1.11",
        "at 192.168.1.254 reject from 10.1.1.1 to 10.2.2.2",
        "Deny all Internet from 192.168.1.2.",
        "Allow SSH to 192.168.1.100.",
        "At 192.168.1.254 reject traffic from 192.168.5.5.",
        "block 1.1.1.1",
        # --- Multi-sentence test ---
        "on 192.168.1.11 deny 192.168.1.12. allow 192.168.1.15 to 192.168.1.11",
    ]
    all_results = []
    for test in tests:
        print(f"\n--- Testing NLP: '{test}' ---")
        parsed = parse_commands(test)
        all_results.extend(parsed)
        print("--- NLP Test End ---")

    print("\n=== Final Parsed NLP Results ===")
    if all_results:
        for i, res in enumerate(all_results):
            print(f"{i+1}: {res}")
    else:
        print("  No rules generated.")
    print("============================")

# --- END OF FILE nlp.py ---