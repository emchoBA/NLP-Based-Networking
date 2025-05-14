import spacy
from spacy.matcher import Matcher
import logging # Use logging
import alias_manager # Import the alias manager

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
    raise SystemExit("Spacy model not found.")


# Matcher for IPv4 addresses
ip_matcher = Matcher(nlp.vocab) # Renamed to avoid conflict
ip_matcher.add(
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


def preprocess_and_resolve_aliases(text: str) -> str:
    """
    1. Basic preprocessing (lowercase, strip, reduce spaces).
    2. Iteratively find and replace known aliases with their IP addresses.
       This is a simpler string-replacement approach before full spaCy parsing.
    """
    processed_text = text.strip().lower()
    # Replace commas early, they can interfere with alias multi-word matching
    processed_text = processed_text.replace(',', ' ')
    processed_text = " ".join(processed_text.split()) # Normalize spaces

    if not alias_manager: # Should not happen if imported correctly
        log.warning("[NLP Preprocess] alias_manager not available. Skipping alias resolution.")
        return processed_text

    # Iterate to replace aliases. This might need to be more sophisticated
    # if aliases can contain other aliases, but for simple cases this works.
    # We get all aliases and sort them by length (longest first) to avoid
    # shorter aliases (e.g., "server") matching parts of longer ones ("web server").
    all_aliases = alias_manager.get_all_aliases() # Returns {alias_lower: ip}
    # Sort by length of alias descending
    sorted_alias_keys = sorted(all_aliases.keys(), key=len, reverse=True)

    original_text_for_logging = processed_text
    for alias_key in sorted_alias_keys:
        ip_address = all_aliases[alias_key]
        # Replace whole word alias only to avoid partial matches within words
        # Using f" {alias_key} " ensures spaces, also check start/end of string
        # This is still a bit crude for multi-word aliases if they aren't space-separated from prepositions.
        # A regex replacement might be better: r'\b' + re.escape(alias_key) + r'\b'
        # For now, let's try direct replacement and see.
        if f" {alias_key} " in f" {processed_text} ": # Check with surrounding spaces
            processed_text = processed_text.replace(f" {alias_key} ", f" {ip_address} ")
        elif processed_text.startswith(f"{alias_key} "):
            processed_text = processed_text.replace(f"{alias_key} ", f"{ip_address} ", 1)
        elif processed_text.endswith(f" {alias_key}"):
            processed_text = processed_text.replace(f" {alias_key}", f" {ip_address}")
        elif processed_text == alias_key: # Alias is the whole string
            processed_text = ip_address

    if original_text_for_logging != processed_text:
        log.info(f"[NLP Preprocess] Resolved aliases: '{original_text_for_logging}' -> '{processed_text}'")
    else:
        log.debug(f"[NLP Preprocess] No aliases resolved in: '{original_text_for_logging}'")

    return " ".join(processed_text.split()) # Final space normalization

def parse_single(cmd: str) -> dict:
    """
    Parse one clause AFTER aliases have been resolved in the input string.
    (Based on your provided working version)
    """
    # Alias resolution now happens in preprocess_and_resolve_aliases,
    # called by parse_commands before this. So 'cmd' here should have IPs.
    doc = nlp(cmd) # cmd is already preprocessed and aliases resolved

    result = {
        "action": None, "service": None,
        "source_ip": None, "destination_ip": None,
        "target_device_ip": None,
    }
    action_idx = -1
    for i, tok in enumerate(doc):
        lem = tok.lemma_.lower()
        if lem in ACTION_VERBS:
            result["action"] = lem
            action_idx = i
            break

    if action_idx != -1:
        for tok in doc[action_idx + 1:]:
            if tok.is_stop or tok.is_punct: continue
            tl = tok.lemma_.lower()
            if tl in BOUNDARY_PREPS: break
            if tok.is_alpha:
                result["service"] = tl
                break

    # Use ip_matcher (renamed from global 'matcher' to avoid confusion if any)
    ip_matches_found = []
    for match_id, start, end in ip_matcher(doc): # Use ip_matcher here
        ip_text = doc[start:end].text
        preceding_token_lemma = doc[start - 1].lemma_.lower() if start > 0 else None
        ip_matches_found.append({
            "ip": ip_text,
            "prep": preceding_token_lemma,
            "start_index": start # For debugging or more complex logic later
        })

    log.debug(f"[NLP] Found IP matches in (alias-resolved) clause '{doc.text}': {ip_matches_found}")

    target_assigned_explicitly = False
    source_assigned = False
    destination_assigned = False
    remaining_matches = list(ip_matches_found)

    temp_remaining = []
    for match in remaining_matches:
        if match["prep"] in TARGET_DEVICE_PREPS:
            if not result["target_device_ip"]:
                result["target_device_ip"] = match["ip"]
                target_assigned_explicitly = True
                log.debug(f"[NLP] Assigned Explicit Target IP: {match['ip']} (from '{match['prep']}')")
            else:
                 log.warning(f"[NLP] Multiple 'on/at' IPs. Using first: {result['target_device_ip']}. Ignoring: {match['ip']}")
                 temp_remaining.append(match)
        else:
            temp_remaining.append(match)
    remaining_matches = temp_remaining

    temp_remaining = []
    for match in remaining_matches:
        if match["prep"] in SOURCE_IP_PREPS:
            if not result["source_ip"]:
                result["source_ip"] = match["ip"]
                source_assigned = True
                log.debug(f"[NLP] Assigned Source IP: {match['ip']} (from '{match['prep']}')")
            else:
                log.warning(f"[NLP] Multiple 'from' IPs. Using first: {result['source_ip']}. Ignoring: {match['ip']}")
        else:
            temp_remaining.append(match)
    remaining_matches = temp_remaining

    temp_remaining = []
    for match in remaining_matches:
        if match["prep"] in DESTINATION_IP_PREPS:
            if not result["destination_ip"]:
                result["destination_ip"] = match["ip"]
                destination_assigned = True
                log.debug(f"[NLP] Assigned Destination IP: {match['ip']} (from '{match['prep']}')")
            else:
                log.warning(f"[NLP] Multiple 'to' IPs. Using first: {result['destination_ip']}. Ignoring: {match['ip']}")
        else:
            temp_remaining.append(match)
    remaining_matches = temp_remaining

    if len(remaining_matches) == 1 and not source_assigned and not destination_assigned:
        match = remaining_matches[0]
        result["source_ip"] = match["ip"]
        source_assigned = True
        log.debug(f"[NLP] Assigned remaining IP as Source IP (default): {match['ip']}")
        remaining_matches.pop(0)

    if remaining_matches:
         log.warning(f"[NLP] Unassigned IP addresses remaining after parsing: {[m['ip'] for m in remaining_matches]}")

    if not target_assigned_explicitly:
        if destination_assigned:
            result["target_device_ip"] = result["destination_ip"]
        elif source_assigned:
            result["target_device_ip"] = result["source_ip"]

    if not result["action"] or not result["target_device_ip"] or not (result["source_ip"] or result["destination_ip"]):
        log.warning(f"[NLP] Validation failed for '{doc.text}'. Result: {result}")
        return {}

    if result["action"] and not result["service"]: result["service"] = "any"
    log.info(f"[NLP] Parsed Result from '{doc.text}': {result}")
    return result

def parse_commands(text: str) -> list:
    """
    1. Preprocesses text and resolves aliases.
    2. Splits input into sentences.
    3. Parses each sentence using parse_single.
    4. Returns a list of valid dictionaries.
    """
    # Preprocess and resolve aliases ONCE for the entire input string
    resolved_text = preprocess_and_resolve_aliases(text)
    doc = nlp(resolved_text) # spaCy processes the alias-resolved text
    out = []
    log.debug(f"\n[NLP] Parsing (alias-resolved) text: '{resolved_text}'")

    for i, sent in enumerate(doc.sents):
        log.debug(f"[NLP] Processing sentence {i+1}: '{sent.text}'")
        # parse_single now gets a sentence string that already has IPs, not aliases
        cmd_dict = parse_single(sent.text)
        if cmd_dict:
            out.append(cmd_dict)
        else:
            log.warning(f"[NLP] Sentence {i+1} ('{sent.text}') did not yield a valid command structure.")

    log.debug(f"[NLP] Finished parsing. Found {len(out)} command(s) total.")
    return out


# Example usage
if __name__ == "__main__":
    logging.getLogger("nlp").setLevel(logging.DEBUG) # Show debug for this module
    logging.getLogger("alias_manager").setLevel(logging.DEBUG) # And for alias manager

    # Setup some aliases for testing
    if alias_manager:
        alias_manager.add_alias("192.168.1.11", "DeviceA")
        alias_manager.add_alias("192.168.1.12", "DeviceB")
        alias_manager.add_alias("10.0.0.1", "Gateway")
        alias_manager.add_alias("10.0.0.2", "WebServer")
        alias_manager.add_alias("company server", "10.0.0.3") # Multi-word alias

    tests = [
        # --- Alias Tests ---
        "on DeviceA deny ssh from 192.168.1.12",
        "allow http from DeviceB to Gateway",
        "block WebServer",
        "at Gateway reject 192.168.1.11",
        "permit traffic from Company Server to DeviceA",
        # --- Original Tests (should still work) ---
        "deny ssh from 192.168.1.12 to 192.168.1.11",
        "allow http from 10.0.0.5 to 192.168.1.11",
        "on 192.168.1.1 permit tcp from 192.168.1.12 to 192.168.1.11",
        "Deny all Internet from 192.168.1.2.",
        "block 1.1.1.1",
        # --- Multi-sentence test with aliases ---
        "on DeviceA deny DeviceB. allow ssh to Gateway.",
    ]
    all_results = []
    for test_cmd in tests:
        print(f"\n--- Testing NLP with: '{test_cmd}' ---")
        parsed_rules = parse_commands(test_cmd)
        all_results.extend(parsed_rules)
        print("--- NLP Test End ---")

    print("\n=== Final Parsed NLP Results ===")
    if all_results:
        for i, res_dict in enumerate(all_results):
            print(f"{i+1}: {res_dict}")
    else:
        print("  No rules generated.")
    print("============================")