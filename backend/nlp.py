import spacy
from spacy.matcher import Matcher
import logging
import re
# Assuming alias_manager.py is in the same 'backend' package
from backend import alias_manager  # Relative import for sibling module in package

log = logging.getLogger(__name__)

# --- SpaCy Model and Matcher Setup ---
try:
    nlp_model = spacy.load("en_core_web_sm")
except OSError:
    log.error("Spacy model 'en_core_web_sm' not found. Please run: python -m spacy download en_core_web_sm")
    # In a real app, might raise a more specific error or have a fallback
    nlp_model = None  # Allow the program to continue but log errors when nlp_model is used
    # raise SystemExit("Spacy model not found, NLP functionality will be impaired.")

# Matcher for IPv4 addresses
ip_matcher = Matcher(nlp_model.vocab if nlp_model else spacy.blank("en").vocab)  # Handle nlp_model being None
if nlp_model:  # Only add pattern if model loaded
    ip_matcher.add(
        "IP_ADDRESS",
        [[{"TEXT": {"REGEX": r"^(?:\d{1,3}\.){3}\d{1,3}$"}}]]
    )
else:
    log.warning("NLP model not loaded. IP address matching will not function.")

# --- Constants ---
ACTION_VERBS = {
    "block", "deny", "drop", "reject",
    "allow", "permit", "accept"
}
TARGET_DEVICE_PREPS = {"on", "at"}
SOURCE_IP_PREPS = {"from"}
DESTINATION_IP_PREPS = {"to"}
BOUNDARY_PREPS = TARGET_DEVICE_PREPS.union(SOURCE_IP_PREPS).union(DESTINATION_IP_PREPS)


# --- Preprocessing ---
def _clean_raw_text(text: str) -> str:
    processed_text = text.strip().lower()
    processed_text = processed_text.replace(',', ' ')
    processed_text = " ".join(processed_text.split())  # Normalize spaces
    return processed_text


def _substitute_aliases_in_text(text: str, all_aliases_map: dict) -> str:
    processed_text = text
    # Sort by length of alias descending to handle overlapping aliases correctly
    sorted_alias_keys = sorted(all_aliases_map.keys(), key=len, reverse=True)

    for alias_key in sorted_alias_keys:
        ip_address = all_aliases_map[alias_key]
        pattern = r'\b' + re.escape(alias_key) + r'\b'
        processed_text = re.sub(pattern, ip_address, processed_text)
    return processed_text


def preprocess_and_resolve_aliases(text: str) -> str:
    """
    1. Basic preprocessing (lowercase, strip, reduce spaces).
    2. Iteratively find and replace known aliases with their IP addresses using regex.
    """
    cleaned_text = _clean_raw_text(text)

    if not alias_manager:
        log.warning("[NLP Preprocess] alias_manager not available. Skipping alias resolution.")
        return cleaned_text

    all_aliases = alias_manager.get_all_aliases()  # Returns {alias_lower: ip}
    if not all_aliases:
        log.debug("[NLP Preprocess] No aliases defined in alias_manager.")
        return cleaned_text

    text_with_aliases_resolved = _substitute_aliases_in_text(cleaned_text, all_aliases)

    if cleaned_text != text_with_aliases_resolved:
        log.info(f"[NLP Preprocess] Resolved aliases: '{cleaned_text}' -> '{text_with_aliases_resolved}'")
    else:
        log.debug(f"[NLP Preprocess] No aliases resolved in: '{cleaned_text}'")

    return " ".join(text_with_aliases_resolved.split())  # Final space normalization


# --- Internal Helper Functions for parse_single ---

def _find_primary_action(doc: spacy.tokens.Doc) -> tuple[str | None, int]:
    """Finds the primary action verb and its index."""
    potential_actions = []
    for i, token in enumerate(doc):
        if token.lemma_.lower() in ACTION_VERBS:
            potential_actions.append({"token": token, "index": i, "lemma": token.lemma_.lower()})

    if not potential_actions:
        return None, -1

    # Heuristic: Choose the LAST action verb found
    chosen_action_info = potential_actions[-1]
    log.debug(
        f"[NLP _find_primary_action] Chosen action: '{chosen_action_info['lemma']}' at index {chosen_action_info['index']}")
    return chosen_action_info['lemma'], chosen_action_info['index']


def _identify_service(doc: spacy.tokens.Doc, action_idx: int) -> str | None:
    """Identifies the service name based on tokens around the action verb."""
    service_name = None
    skippable_service_prefix_words = {"all", "any", "incoming", "outgoing", "traffic", "access", "queries"}
    skippable_service_general_words = skippable_service_prefix_words.union({"ensure", "please"})

    # Attempt 1: Look for service AFTER the chosen action
    if action_idx != -1 and action_idx + 1 < len(doc):
        log.debug(
            f"[NLP _identify_service] Attempt 1: Searching service AFTER action in: '{doc[action_idx + 1:].text}'")
        temp_service_candidate_after = None
        for i, tok in enumerate(doc[action_idx + 1:]):
            actual_token_index_in_doc = action_idx + 1 + i
            if ip_matcher(doc[actual_token_index_in_doc: actual_token_index_in_doc + 1]): break
            if tok.lemma_.lower() in BOUNDARY_PREPS: break
            if tok.is_stop or tok.is_punct: continue

            if tok.is_alpha:
                if tok.lemma_.lower() in skippable_service_prefix_words and temp_service_candidate_after is None:
                    continue
                else:
                    temp_service_candidate_after = tok.lemma_.lower()
                    break
            else:  # Non-alpha token, stop search
                break
        if temp_service_candidate_after:
            service_name = temp_service_candidate_after

    # Attempt 2: If no specific service found AFTER action, look BEFORE
    if not service_name and action_idx > 0:
        log.debug(f"[NLP _identify_service] Attempt 2: Searching service BEFORE action in: '{doc[:action_idx].text}'")
        temp_service_candidate_before = None
        for i in range(action_idx - 1, -1, -1):
            tok = doc[i]
            if ip_matcher(doc[i: i + 1]): continue
            if tok.lemma_.lower() in BOUNDARY_PREPS: continue
            if tok.is_stop or tok.is_punct: continue

            if tok.is_alpha:
                if tok.lemma_.lower() not in skippable_service_general_words:
                    temp_service_candidate_before = tok.lemma_.lower()
                    break
                elif temp_service_candidate_before is None:  # First skippable word (weak candidate)
                    temp_service_candidate_before = tok.lemma_.lower()
        if temp_service_candidate_before:
            service_name = temp_service_candidate_before

    log.debug(f"[NLP _identify_service] Identified service: '{service_name}'")
    return service_name


def _extract_ip_entities(doc: spacy.tokens.Doc) -> list[dict]:
    """Extracts IP addresses and their preceding prepositions."""
    ip_entities = []
    if not nlp_model:  # Guard against nlp_model not being loaded
        return ip_entities
    for _, start, end in ip_matcher(doc):
        ip_text = doc[start:end].text
        preceding_token_lemma = doc[start - 1].lemma_.lower() if start > 0 else None
        ip_entities.append({"ip": ip_text, "prep": preceding_token_lemma, "start_index": start})
    log.debug(f"[NLP _extract_ip_entities] Found IP entities: {ip_entities}")
    return ip_entities


def _assign_ip_roles(ip_entities: list[dict]) -> tuple[str | None, str | None, str | None, list[dict]]:
    """Assigns roles (source, destination, target) to extracted IP entities."""
    source_ip, destination_ip, target_device_ip = None, None, None
    remaining_ips = list(ip_entities)  # Work on a copy

    # Explicit Target IP (on/at)
    temp_remaining = []
    for entity in remaining_ips:
        if entity["prep"] in TARGET_DEVICE_PREPS:
            if not target_device_ip:
                target_device_ip = entity["ip"]
                log.debug(f"[NLP _assign_ip_roles] Explicit Target IP: {target_device_ip}")
            else:  # Already found an explicit target, keep this one for later
                log.warning(
                    f"[NLP _assign_ip_roles] Multiple 'on/at' IPs. Using first: {target_device_ip}. Keeping {entity['ip']} for now.")
                temp_remaining.append(entity)
        else:
            temp_remaining.append(entity)
    remaining_ips = temp_remaining

    # Source IP (from)
    temp_remaining = []
    for entity in remaining_ips:
        if entity["prep"] in SOURCE_IP_PREPS:
            if not source_ip:
                source_ip = entity["ip"]
                log.debug(f"[NLP _assign_ip_roles] Source IP: {source_ip}")
            else:
                log.warning(f"[NLP _assign_ip_roles] Multiple 'from' IPs. Using first: {source_ip}.")
        else:
            temp_remaining.append(entity)
    remaining_ips = temp_remaining

    # Destination IP (to)
    temp_remaining = []
    for entity in remaining_ips:
        if entity["prep"] in DESTINATION_IP_PREPS:
            if not destination_ip:
                destination_ip = entity["ip"]
                log.debug(f"[NLP _assign_ip_roles] Destination IP: {destination_ip}")
            else:
                log.warning(f"[NLP _assign_ip_roles] Multiple 'to' IPs. Using first: {destination_ip}.")
        else:
            temp_remaining.append(entity)
    remaining_ips = temp_remaining

    # Defaulting for remaining IPs
    # If one IP remains and it's not already the explicit target, and src/dest are not set, it's likely source.
    if len(remaining_ips) == 1 and not source_ip and not destination_ip:
        candidate_ip = remaining_ips[0]["ip"]
        if candidate_ip != target_device_ip:  # Avoid re-assigning explicit target as source
            source_ip = candidate_ip
            log.debug(f"[NLP _assign_ip_roles] Defaulted remaining IP as Source: {source_ip}")
            remaining_ips.pop(0)

    # Default target_device_ip if not explicitly set
    if not target_device_ip:
        if destination_ip:  # If there's a destination, the rule is likely *on* the destination
            target_device_ip = destination_ip
            log.debug(f"[NLP _assign_ip_roles] Defaulted Target IP to Destination IP: {target_device_ip}")
        elif source_ip:  # If only a source, the rule is likely *on* the source
            target_device_ip = source_ip
            log.debug(f"[NLP _assign_ip_roles] Defaulted Target IP to Source IP: {target_device_ip}")

    if remaining_ips:
        unassigned_ips_final = [m["ip"] for m in remaining_ips if
                                m["ip"] not in {target_device_ip, source_ip, destination_ip}]
        if unassigned_ips_final:
            log.warning(f"[NLP _assign_ip_roles] Unassigned IPs at end: {unassigned_ips_final}")

    return source_ip, destination_ip, target_device_ip, remaining_ips


# --- Main Parsing Functions ---

def parse_single(cmd_text: str) -> dict:
    """
    Parses a single, alias-resolved command string into a structured dictionary.
    """
    if not nlp_model:
        log.error(f"[NLP parse_single] SpaCy model not loaded. Cannot parse: '{cmd_text}'")
        return {}

    doc = nlp_model(cmd_text)
    log.debug(f"[NLP parse_single] Input: '{cmd_text}'")

    result = {
        "action": None, "service": None,
        "source_ip": None, "destination_ip": None,
        "target_device_ip": None,
    }

    # 1. Find Action
    action_verb, action_idx = _find_primary_action(doc)
    if not action_verb:
        log.warning(f"[NLP parse_single] No action verb found in '{cmd_text}'.")
        return {}
    result["action"] = action_verb

    # 2. Identify Service
    result["service"] = _identify_service(doc, action_idx)

    # 3. Extract IP Entities
    ip_entities_found = _extract_ip_entities(doc)

    # 4. Assign IP Roles
    source_ip, dest_ip, target_ip, _ = _assign_ip_roles(ip_entities_found)  # We don't use remaining_ips here
    result["source_ip"] = source_ip
    result["destination_ip"] = dest_ip
    result["target_device_ip"] = target_ip

    # 5. Final Validation & Defaulting Service
    # Core components: action and a target. Source or dest often needed for meaningful rules.
    if not result["action"] or not result["target_device_ip"]:
        log.warning(
            f"[NLP parse_single] Validation failed for '{doc.text}'. Missing action or target. Result: {result}")
        return {}

    # If target was defaulted to source or dest, but neither source nor dest was found,
    # then target_device_ip might still be None here. This indicates an issue.
    # Example: "block ssh" (no IPs, no "on DeviceX")
    if not result["target_device_ip"] and not (result["source_ip"] or result["destination_ip"]):
        log.warning(
            f"[NLP parse_single] No IPs found and no explicit target for '{doc.text}'. Cannot determine target. Rule: {result}")
        return {}

    if not result["service"]:  # If still no service after all attempts
        result["service"] = "any"  # Default to "any"
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
    if not nlp_model:
        log.error("[NLP parse_commands] SpaCy model not loaded. Cannot parse commands.")
        return []

    resolved_text = preprocess_and_resolve_aliases(text)
    doc = nlp_model(resolved_text)  # Process the whole resolved text once for sentence splitting
    parsed_rules = []
    log.debug(f"\n[NLP parse_commands] Parsing (alias-resolved) text: '{resolved_text}'")

    for i, sent in enumerate(doc.sents):
        log.debug(f"[NLP parse_commands] Processing sentence {i + 1}: '{sent.text}'")
        # Pass the sentence text string to parse_single, which will re-nlp it.
        # This is slightly inefficient (re-nlp-ing) but keeps parse_single self-contained.
        # Alternatively, pass the sent object (Span) and have parse_single work with it directly.
        # For now, keeping it simple.
        cmd_dict = parse_single(sent.text)
        if cmd_dict:  # Ensure cmd_dict is not empty
            parsed_rules.append(cmd_dict)
        else:
            log.warning(
                f"[NLP parse_commands] Sentence {i + 1} ('{sent.text}') did not yield a valid command structure.")

    log.info(f"[NLP parse_commands] Finished parsing. Found {len(parsed_rules)} command(s) total from input: '{text}'")
    return parsed_rules


# --- Example Usage (for standalone testing) ---
if __name__ == "__main__":
    # Ensure logger for this module is set to DEBUG for testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(name)s] %(levelname)s - %(message)s')
    log.setLevel(logging.DEBUG)  # Set this specific logger to DEBUG

    # For standalone testing, alias_manager needs to be importable.
    # If run as 'python -m backend.nlp', relative imports should work.
    # If run directly, sys.path might need adjustment if backend is not in it.
    if alias_manager:
        logging.getLogger("backend.alias_manager").setLevel(logging.DEBUG)  # Assuming it's now backend.alias_manager
        alias_manager.add_alias("192.168.1.11", "DeviceA")
        alias_manager.add_alias("192.168.1.12", "DeviceB")
        alias_manager.add_alias("10.0.0.1", "Gateway")
        alias_manager.add_alias("10.0.0.2", "WebServer")
        alias_manager.add_alias("company server one", "10.0.0.3")
    else:
        print("WARNING: alias_manager not available for standalone NLP test.")

    if not nlp_model:
        print("CRITICAL: SpaCy model not loaded. NLP tests cannot run effectively.")
    else:
        tests = [
            "on DeviceA deny ssh from 192.168.1.12",
            "allow http from DeviceB to Gateway",
            "block WebServer",
            "at Gateway reject 192.168.1.11",
            "permit traffic from company server one to DeviceA",
            "deny ssh from 192.168.1.12 to 192.168.1.11",
            "allow http from 10.0.0.5 to 192.168.1.11",
            "on 192.168.1.1 permit tcp from 192.168.1.12 to 192.168.1.11",
            "Deny all Internet from 192.168.1.2.",  # "Internet" will be a service
            "block 1.1.1.1",
            "on DeviceA deny DeviceB. allow ssh to Gateway.",
            "allow pop3 from DeviceB",
            "reject telnet to DeviceA",
            "on DeviceA deny rdp from DeviceB",
            "on DeviceA allow ssh from DeviceB. at DeviceB deny all traffic from DeviceA.",
            "block ftp",  # Test with no IPs, NLP should make target from context or fail gracefully
            "deny dns from any to Gateway"  # "any" as source
        ]
        all_results = []
        for test_cmd in tests:
            print(f"\n--- Testing NLP with: '{test_cmd}' ---")
            parsed_rules_list = parse_commands(test_cmd)  # parse_commands returns a list
            if parsed_rules_list:
                all_results.extend(parsed_rules_list)
            else:
                print(f"  No rules generated for: '{test_cmd}'")
            print("--- NLP Test End ---")

        print("\n=== Final Parsed NLP Results (from all tests) ===")
        if all_results:
            for i, res_dict in enumerate(all_results):
                print(f"{i + 1}: {res_dict}")
        else:
            print("  No rules generated overall.")
        print("============================")