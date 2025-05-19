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


# In nlp.py, replace your ENTIRE existing parse_single function with this:

def parse_single(cmd: str) -> dict:
    """
    Parse one clause AFTER aliases have been resolved.
    Attempts to handle action verbs appearing late in the sentence and
    improves service identification around common words.
    """
    doc = nlp(cmd)
    log.debug(f"[NLP parse_single] Input: '{cmd}'")

    result = {
        "action": None, "service": None,
        "source_ip": None, "destination_ip": None,
        "target_device_ip": None,
    }

    # --- Pass 1: Identify all potential action verbs and their positions ---
    potential_actions = []
    for i, token in enumerate(doc):
        if token.lemma_.lower() in ACTION_VERBS:
            potential_actions.append({"token": token, "index": i, "lemma": token.lemma_.lower()})

    if not potential_actions:
        log.warning(f"[NLP parse_single] No action verb found in '{cmd}'.")
        return {}

    # --- Heuristic: Choose the LAST action verb found as the primary action ---
    chosen_action_info = potential_actions[-1]
    result["action"] = chosen_action_info["lemma"]
    action_idx = chosen_action_info["index"]
    log.debug(
        f"[NLP parse_single] Chosen action: '{result['action']}' (original text: '{chosen_action_info['token'].text}') at index {action_idx}")

    # --- Service Identification (Revised Again) ---
    service_found_flag = False
    result["service"] = None  # Explicitly reset before search

    # Attempt 1: Look for service AFTER the chosen action
    if action_idx + 1 < len(doc):
        log.debug(
            f"[NLP parse_single] Attempt 1: Searching service AFTER action '{result['action']}' in: '{doc[action_idx + 1:].text}'")
        # List of common non-service words that might appear before the actual service name
        skippable_service_prefix_words = {"all", "any", "incoming", "outgoing", "traffic", "access", "queries"}

        temp_service_candidate_after = None
        for i, tok in enumerate(doc[action_idx + 1:]):
            actual_token_index_in_doc = action_idx + 1 + i
            if actual_token_index_in_doc >= len(doc): break

            log.debug(f"[NLP parse_single] Service check (after action): token='{tok.text}', lemma='{tok.lemma_}'...")
            if tok.is_stop or tok.is_punct:
                log.debug(f"[NLP parse_single] Skipping token '{tok.text}' (stop/punct).")
                continue

            tl = tok.lemma_.lower()
            # Check for IP or boundary preposition to stop search
            if ip_matcher(doc[actual_token_index_in_doc: actual_token_index_in_doc + 1]):
                log.debug(f"[NLP parse_single] Token '{tok.text}' is an IP. Stopping service search (after action).")
                break
            if tl in BOUNDARY_PREPS:
                log.debug(
                    f"[NLP parse_single] Token '{tok.text}' is a boundary preposition. Stopping service search (after action).")
                break

            if tok.is_alpha:  # Using is_alpha as per your base for service candidate
                if tl in skippable_service_prefix_words and temp_service_candidate_after is None:
                    # It's a skippable word, and we haven't found a better candidate yet from this direction.
                    # We note it but continue, hoping a more specific service follows.
                    log.debug(f"[NLP parse_single] Token '{tok.text}' is a skippable prefix. Continuing search...")
                    # We could store this as a very weak candidate if nothing better is found
                    # temp_service_candidate_after = tl # Option: store it weakly
                    continue
                else:
                    # This is either a non-skippable alpha word, or a skippable one appearing after another candidate
                    # (which shouldn't happen with current logic if we break on first non-skippable).
                    # We take this as the service.
                    temp_service_candidate_after = tl
                    log.debug(
                        f"[NLP parse_single] Strong service candidate (after action): '{temp_service_candidate_after}' from token '{tok.text}'")
                    break  # Found a strong potential service (or a non-skippable word)
            else:
                log.debug(
                    f"[NLP parse_single] Token '{tok.text}' is not alpha. Stopping service search (after action).")
                break

        if temp_service_candidate_after:
            result["service"] = temp_service_candidate_after
            service_found_flag = True
            log.debug(f"[NLP parse_single] Final service from Attempt 1 (after action): '{result['service']}'")

    # Attempt 2: If no specific service found AFTER action, look BEFORE the chosen action
    if not service_found_flag and action_idx > 0:
        log.debug(
            f"[NLP parse_single] Attempt 2: No specific service after action. Searching service BEFORE action '{result['action']}' in: '{doc[:action_idx].text}'")

        # Heuristic: iterate backwards, take first non-skippable alpha token.
        # Skippable words should ideally be known general terms or configurable.
        skippable_service_general_words = {"all", "any", "incoming", "outgoing", "traffic", "access", "queries",
                                           "ensure", "please"}  # Add more as needed

        temp_service_candidate_before = None
        for i in range(action_idx - 1, -1, -1):
            tok = doc[i]
            log.debug(f"[NLP parse_single] Service check (before action): token='{tok.text}', lemma='{tok.lemma_}'...")
            if tok.is_stop or tok.is_punct: continue

            tl = tok.lemma_.lower()
            # Don't pick up parts of "on DeviceX" or other prepositions as service
            if ip_matcher(doc[i:i + 1]): continue
            if tl in BOUNDARY_PREPS: continue
            if tl in TARGET_DEVICE_PREPS: continue  # Also skip "on", "at" themselves

            if tok.is_alpha:
                # If it's not a generally skippable word, consider it strong.
                if tl not in skippable_service_general_words:
                    temp_service_candidate_before = tl
                    log.debug(
                        f"[NLP parse_single] Strong service candidate (before action): '{temp_service_candidate_before}' from token '{tok.text}'")
                    break  # Found strong candidate
                elif temp_service_candidate_before is None:  # First skippable word encountered
                    temp_service_candidate_before = tl  # Weak candidate

        if temp_service_candidate_before:
            result["service"] = temp_service_candidate_before
            service_found_flag = True
            log.debug(f"[NLP parse_single] Final service from Attempt 2 (before action): '{result['service']}'")

    if not service_found_flag:
        log.debug(f"[NLP parse_single] No specific service identified by either attempt.")

    # --- IP Identification and Role Assignment (from your working version) ---
    ip_matches_found = []
    for match_id, start, end in ip_matcher(doc):
        ip_text = doc[start:end].text
        preceding_token_lemma = doc[start - 1].lemma_.lower() if start > 0 else None
        ip_matches_found.append({"ip": ip_text, "prep": preceding_token_lemma, "start_index": start})
    log.debug(f"[NLP parse_single] IP matches in '{doc.text}': {ip_matches_found}")

    target_assigned_explicitly = False;
    source_assigned = False;
    destination_assigned = False
    remaining_matches = list(ip_matches_found)

    temp_remaining_target = []
    for match in remaining_matches:
        if match["prep"] in TARGET_DEVICE_PREPS:
            if not result["target_device_ip"]:
                result["target_device_ip"] = match["ip"];
                target_assigned_explicitly = True
                log.debug(f"[NLP parse_single] Explicit Target IP: {match['ip']}")
            else:
                log.warning(f"[NLP parse_single] Multiple 'on/at' IPs. Using first: {result['target_device_ip']}.")
                temp_remaining_target.append(match)
        else:
            temp_remaining_target.append(match)
    remaining_matches = temp_remaining_target

    temp_remaining_source = []
    for match in remaining_matches:
        if match["prep"] in SOURCE_IP_PREPS:
            if not result["source_ip"]:
                result["source_ip"] = match["ip"];
                source_assigned = True
                log.debug(f"[NLP parse_single] Source IP: {match['ip']}")
            else:
                log.warning(f"[NLP parse_single] Multiple 'from' IPs. Using first.")
        else:
            temp_remaining_source.append(match)
    remaining_matches = temp_remaining_source

    temp_remaining_dest = []
    for match in remaining_matches:
        if match["prep"] in DESTINATION_IP_PREPS:
            if not result["destination_ip"]:
                result["destination_ip"] = match["ip"];
                destination_assigned = True
                log.debug(f"[NLP parse_single] Destination IP: {match['ip']}")
            else:
                log.warning(f"[NLP parse_single] Multiple 'to' IPs. Using first.")
        else:
            temp_remaining_dest.append(match)
    remaining_matches = temp_remaining_dest

    if len(remaining_matches) == 1 and not source_assigned and not destination_assigned:
        # Check if this IP was already used as an explicit target
        # This check is important if the explicit target itself didn't have a prep like "on" before it
        # which is less likely with current IP/Alias resolution but good for robustness.
        match_ip = remaining_matches[0]["ip"]
        if not (target_assigned_explicitly and result["target_device_ip"] == match_ip):
            result["source_ip"] = match_ip;
            source_assigned = True
            log.debug(f"[NLP parse_single] Defaulted remaining IP as Source: {match_ip}")
            remaining_matches.pop(0)  # Consume it

    if remaining_matches:
        # Filter out IPs already assigned to ensure warning is for truly unassigned ones
        unassigned_ips_final = []
        assigned_ips = {result["target_device_ip"], result["source_ip"], result["destination_ip"]}
        for m in remaining_matches:
            if m["ip"] not in assigned_ips:
                unassigned_ips_final.append(m["ip"])
        if unassigned_ips_final:
            log.warning(f"[NLP parse_single] Unassigned IPs at end: {unassigned_ips_final}")

    if not target_assigned_explicitly:
        if destination_assigned and result["destination_ip"]:
            result["target_device_ip"] = result["destination_ip"]
        elif source_assigned and result["source_ip"]:
            result["target_device_ip"] = result["source_ip"]

    # --- Final Validation & Defaulting Service ---
    if not result["action"] or not result["target_device_ip"] or not (result["source_ip"] or result["destination_ip"]):
        log.warning(
            f"[NLP parse_single] Validation failed for '{doc.text}'. Missing core component(s). Result: {result}")
        return {}  # Return empty if core components are missing

    if not result["service"]:  # If still no service after both attempts
        result["service"] = "any"
        log.debug(f"[NLP parse_single] Service defaulted to 'any' for action '{result['action']}' at the end")

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