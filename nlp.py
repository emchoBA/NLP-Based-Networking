import spacy
from spacy.matcher import Matcher
import logging # Use logging
import re # Import regular expressions
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
    2. Iteratively find and replace known aliases with their IP addresses using regex.
    """
    # Initial cleanup: lowercase, strip whitespace, normalize multiple spaces
    processed_text = text.strip().lower()
    processed_text = processed_text.replace(',', ' ') # Replace commas with spaces
    processed_text = " ".join(processed_text.split()) # Normalize spaces

    if not alias_manager:
        log.warning("[NLP Preprocess] alias_manager not available. Skipping alias resolution.")
        return processed_text

    all_aliases = alias_manager.get_all_aliases() # Returns {alias_lower: ip}
    if not all_aliases:
        log.debug("[NLP Preprocess] No aliases defined in alias_manager.")
        return processed_text

    # Sort by length of alias descending to handle overlapping aliases correctly
    # (e.g., "web server" before "server")
    sorted_alias_keys = sorted(all_aliases.keys(), key=len, reverse=True)

    original_text_for_logging = processed_text
    for alias_key in sorted_alias_keys:
        ip_address = all_aliases[alias_key]
        # Use regex for whole word replacement (case-insensitive due to prior lowercasing of text)
        # re.escape is important if aliases can contain special regex characters
        pattern = r'\b' + re.escape(alias_key) + r'\b'
        # Count occurrences for logging, then replace
        # num_occurrences = len(re.findall(pattern, processed_text))
        # if num_occurrences > 0:
        processed_text_before_replace = processed_text
        processed_text = re.sub(pattern, ip_address, processed_text)
        # if processed_text != processed_text_before_replace:
        #      log.debug(f"[NLP Preprocess] Replaced '{alias_key}' with '{ip_address}' ({num_occurrences} times)")


    if original_text_for_logging != processed_text:
        log.info(f"[NLP Preprocess] Resolved aliases: '{original_text_for_logging}' -> '{processed_text}'")
    else:
        log.debug(f"[NLP Preprocess] No aliases resolved in: '{original_text_for_logging}'")

    return " ".join(processed_text.split()) # Final space normalization


def parse_single(cmd: str) -> dict:
    """
    Parse one clause AFTER aliases have been resolved in the input string.
    """
    # 'cmd' here is assumed to be a single sentence string, already preprocessed
    # and with aliases resolved to IPs by the calling function (parse_commands).
    doc = nlp(cmd)

    log.debug(
        f"[NLP parse_single] Input to parse_single (after alias resolution and sentence split): '{cmd}'")  # Log input

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

    # 2) SERVICE: Find the first relevant noun after the action (if action exists)
    if action_idx != -1:
        log.debug(
            f"[NLP parse_single] Searching for service after action '{result['action']}' in: '{doc[action_idx + 1:].text}'")
        service_found_flag = False  # Flag to see if we ever assign it
        for i, tok in enumerate(doc[action_idx + 1:]):
            actual_token_index_in_doc = action_idx + 1 + i  # Index in the full 'doc'

            # Ensure we don't go out of bounds if action_idx was the last token (unlikely but safe)
            if actual_token_index_in_doc >= len(doc):
                break

            log.debug(
                f"[NLP parse_single] Service check: token='{tok.text}', lemma='{tok.lemma_}', is_alpha={tok.is_alpha}, is_stop={tok.is_stop}, is_punct={tok.is_punct}")

            if tok.is_stop or tok.is_punct:
                log.debug(f"[NLP parse_single] Skipping token '{tok.text}' (stop/punct).")
                continue

            tl = tok.lemma_.lower()

            # Check if the current token starts an IP address (more robust boundary)
            # This means if we see "allow 192.168.1.10 ..." it won't mistake 192 for service
            is_ip_check_span = doc[actual_token_index_in_doc: actual_token_index_in_doc + 1]
            if ip_matcher(is_ip_check_span):  # Check if the token itself is an IP
                log.debug(f"[NLP parse_single] Token '{tok.text}' is an IP. Stopping service search.")
                break

            if tl in BOUNDARY_PREPS:  # Stop if we hit any IP-related preposition
                log.debug(
                    f"[NLP parse_single] Token '{tok.text}' (lemma '{tl}') is a boundary preposition. Stopping service search.")
                break

            if tok.is_alpha:  # Must be alphabetic
                result["service"] = tl
                service_found_flag = True  # Mark service as found
                log.debug(f"[NLP parse_single] Service FOUND: '{result['service']}' from token '{tok.text}'")
                break  # Found the service
            else:
                # If it's not alpha, not stop/punct, not an IP, and not a boundary, stop.
                # This could be a number or other symbol that shouldn't be a service.
                log.debug(
                    f"[NLP parse_single] Token '{tok.text}' is not alpha (and not other known category). Stopping service search here.")
                break

        if not service_found_flag:
            log.debug(
                f"[NLP parse_single] No specific service found after action. Defaulting to 'any' if needed later.")
            # Defaulting to 'any' now happens at the end of parse_single if service is still None

    # 3) IPs: Find all IP addresses and try to determine their roles
    ip_matches_found = []
    for match_id, start, end in ip_matcher(doc):  # Use ip_matcher here
        ip_text = doc[start:end].text
        preceding_token_lemma = doc[start - 1].lemma_.lower() if start > 0 else None
        ip_matches_found.append({
            "ip": ip_text,
            "prep": preceding_token_lemma,
            "start_index": start
        })

    log.debug(f"[NLP parse_single] IP matches in '{doc.text}': {ip_matches_found}")

    target_assigned_explicitly = False
    source_assigned = False
    destination_assigned = False
    remaining_matches = list(ip_matches_found)

    # Priority 1: Explicit Target Device ("on"/"at")
    temp_remaining_target = []
    for match in remaining_matches:
        if match["prep"] in TARGET_DEVICE_PREPS:
            if not result["target_device_ip"]:
                result["target_device_ip"] = match["ip"]
                target_assigned_explicitly = True
                log.debug(f"[NLP parse_single] Explicit Target IP: {match['ip']} (from '{match['prep']}')")
            else:
                log.warning(
                    f"[NLP parse_single] Multiple 'on/at' IPs. Using first: {result['target_device_ip']}. Ignoring: {match['ip']}")
                temp_remaining_target.append(match)
        else:
            temp_remaining_target.append(match)
    remaining_matches = temp_remaining_target

    # Priority 2: Source IP ("from")
    temp_remaining_source = []
    for match in remaining_matches:
        if match["prep"] in SOURCE_IP_PREPS:
            if not result["source_ip"]:
                result["source_ip"] = match["ip"]
                source_assigned = True
                log.debug(f"[NLP parse_single] Source IP: {match['ip']} (from '{match['prep']}')")
            else:
                log.warning(
                    f"[NLP parse_single] Multiple 'from' IPs. Using first: {result['source_ip']}. Ignoring: {match['ip']}")
        else:
            temp_remaining_source.append(match)
    remaining_matches = temp_remaining_source

    # Priority 3: Destination IP ("to")
    temp_remaining_dest = []
    for match in remaining_matches:
        if match["prep"] in DESTINATION_IP_PREPS:
            if not result["destination_ip"]:
                result["destination_ip"] = match["ip"]
                destination_assigned = True
                log.debug(f"[NLP parse_single] Destination IP: {match['ip']} (from '{match['prep']}')")
            else:
                log.warning(
                    f"[NLP parse_single] Multiple 'to' IPs. Using first: {result['destination_ip']}. Ignoring: {match['ip']}")
        else:
            temp_remaining_dest.append(match)
    remaining_matches = temp_remaining_dest

    # Priority 4: Unassigned IP (Default single remaining IP to Source)
    if len(remaining_matches) == 1 and not source_assigned and not destination_assigned:
        match = remaining_matches[0]
        result["source_ip"] = match["ip"]
        source_assigned = True  # Mark as assigned
        log.debug(f"[NLP parse_single] Defaulted remaining IP as Source IP: {match['ip']}")
        remaining_matches.pop(0)

    if remaining_matches:
        log.warning(
            f"[NLP parse_single] Unassigned IPs after all assignments in '{doc.text}': {[m['ip'] for m in remaining_matches]}")

    # --- Determine Final Target Device IP ---
    if not target_assigned_explicitly:
        if destination_assigned:
            result["target_device_ip"] = result["destination_ip"]
            log.debug(f"[NLP parse_single] Implicit Target IP set to Destination IP: {result['target_device_ip']}")
        elif source_assigned:
            result["target_device_ip"] = result["source_ip"]
            log.debug(f"[NLP parse_single] Implicit Target IP set to Source IP: {result['target_device_ip']}")

    # --- Final Validation ---
    if not result["action"]:
        log.warning(f"[NLP parse_single] Validation failed for '{doc.text}': No action. Result: {result}")
        return {}
    if not result["target_device_ip"]:
        log.warning(f"[NLP parse_single] Validation failed for '{doc.text}': No target device. Result: {result}")
        return {}
    if not result["source_ip"] and not result["destination_ip"]:
        log.warning(f"[NLP parse_single] Validation failed for '{doc.text}': No source or dest IP. Result: {result}")
        return {}

    # If service wasn't found, default it
    if result["action"] and not result["service"]:
        result["service"] = "any"
        log.debug(f"[NLP parse_single] Service defaulted to 'any' for action '{result['action']}'")

    log.info(f"[NLP parse_single] Final Parsed Result for '{doc.text}': {result}")
    return result

def parse_commands(text: str) -> list:
    """
    1. Preprocesses text and resolves aliases.
    2. Splits input into sentences.
    3. Parses each sentence using parse_single.
    4. Returns a list of valid dictionaries.
    """
    resolved_text = preprocess_and_resolve_aliases(text)
    doc = nlp(resolved_text)
    out = []
    log.debug(f"\n[NLP] Parsing (alias-resolved) text: '{resolved_text}'")

    for i, sent in enumerate(doc.sents):
        log.debug(f"[NLP] Processing sentence {i+1}: '{sent.text}'")
        # Pass the sentence string (which already has IPs from resolved_text)
        cmd_dict = parse_single(sent.text)
        if cmd_dict:
            out.append(cmd_dict)
        else:
            log.warning(f"[NLP] Sentence {i+1} ('{sent.text}') did not yield a valid command structure.")

    log.debug(f"[NLP] Finished parsing. Found {len(out)} command(s) total.")
    return out

# Example usage
if __name__ == "__main__":
    logging.getLogger("nlp").setLevel(logging.DEBUG)
    if alias_manager: # Ensure alias_manager is available for testing
        logging.getLogger("alias_manager").setLevel(logging.DEBUG)
        alias_manager.add_alias("192.168.1.11", "DeviceA")
        alias_manager.add_alias("192.168.1.12", "DeviceB")
        alias_manager.add_alias("10.0.0.1", "Gateway")
        alias_manager.add_alias("10.0.0.2", "WebServer")
        alias_manager.add_alias("company server one", "10.0.0.3") # Multi-word alias
    else:
        print("WARNING: alias_manager not imported, alias tests will not work as expected.")


    tests = [
        # --- Alias Tests ---
        "on DeviceA deny ssh from 192.168.1.12",
        "allow http from DeviceB to Gateway",
        "block WebServer", # Should resolve WebServer to IP
        "at Gateway reject 192.168.1.11",
        "permit traffic from company server one to DeviceA", # Test multi-word
        # --- Original Tests ---
        "deny ssh from 192.168.1.12 to 192.168.1.11",
        "allow http from 10.0.0.5 to 192.168.1.11",
        "on 192.168.1.1 permit tcp from 192.168.1.12 to 192.168.1.11",
        "Deny all Internet from 192.168.1.2.",
        "block 1.1.1.1",
        # --- Multi-sentence test with aliases ---
        "on DeviceA deny DeviceB. allow ssh to Gateway.",
        # --- Test cases that were failing before ---
        "allow pop3 from DeviceB",
        "reject telnet to DeviceA",
        "on DeviceA deny rdp from DeviceB",
        "on DeviceA allow ssh from DeviceB. at DeviceB deny all traffic from DeviceA."
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