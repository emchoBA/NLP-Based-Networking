#!/usr/bin/env python3
"""
policy_engine.py

Uses enhanced NLP (source_ip, destination_ip), service_mapper,
builds potentially complex iptables command(s), and prepares them for dispatch.
"""

import logging
import service_mapper # Assuming service_mapper.py is available
from nlp import parse_commands # Assuming nlp.py is available
import admin_connect # Assuming admin_connect.py is available

# --- Get Logger ---
log = logging.getLogger(__name__)
if not log.hasHandlers():
     # Basic config if run standalone
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(name)s] %(levelname)s - %(message)s')

# Services that don't use port/protocol specifics
SERVICES_TO_IGNORE = {"any", "all", "traffic", None}

# Map action verbs to iptables targets
ACTION_TO_IPTABLES_TARGET = {
    "block": "DROP", "deny": "DROP", "drop": "DROP", "reject": "DROP",
    "allow": "ACCEPT", "permit": "ACCEPT", "accept": "ACCEPT",
}

def parse_and_generate_commands(nl_text: str) -> list[tuple[str, str | None, str | None, list[str]]]:
    """
    Parses NL text, generates commands using source/destination IPs,
    and returns them for preview/dispatch.

    Args:
        nl_text: The natural language policy string.

    Returns:
        A list of tuples. Each tuple contains:
        (target_device_ip, source_ip, destination_ip, list_of_commands)
        Returns an empty list if no valid rules/commands are generated.
    """
    log.debug(f"[ENGINE] Parsing and generating commands for: '{nl_text}'")
    rules = parse_commands(nl_text) # Uses enhanced nlp.py

    if not rules:
        log.warning("[ENGINE] No valid rules derived from text.")
        return []

    all_generated_commands = []

    for i, rule in enumerate(rules):
        log.debug(f"[ENGINE] Processing Rule {i+1}: {rule}")

        # --- Use new keys from NLP result ---
        action_verb      = rule.get('action')
        service_name     = rule.get('service')
        source_ip        = rule.get('source_ip')
        destination_ip   = rule.get('destination_ip')
        target_device_ip = rule.get('target_device_ip') # WHERE the rule applies

        # Basic validation (already done partly in NLP, but good to double check)
        if not all([action_verb, target_device_ip]) or not (source_ip or destination_ip):
            log.warning(f"[ENGINE] Rule {i+1} is incomplete or lacks IP context ({rule}). Skipping generation.")
            continue

        iptables_target = ACTION_TO_IPTABLES_TARGET.get(action_verb)
        if not iptables_target:
            log.warning(f"[ENGINE] Unknown action verb '{action_verb}' in rule {i+1}. Skipping generation.")
            continue

        # --- Determine Chain (Simplified Logic) ---
        # This logic determines the chain ON the target_device_ip
        chain = "INPUT" # Default
        if target_device_ip == source_ip and destination_ip:
             # Rule applied ON source, affecting traffic going TO destination -> OUTPUT
             chain = "OUTPUT"
             log.debug(f"[ENGINE] Chain set to OUTPUT (Target '{target_device_ip}' == Source '{source_ip}')")
        elif target_device_ip == destination_ip and source_ip:
             # Rule applied ON destination, affecting traffic coming FROM source -> INPUT
             chain = "INPUT"
             log.debug(f"[ENGINE] Chain set to INPUT (Target '{target_device_ip}' == Destination '{destination_ip}')")
        elif source_ip and destination_ip:
             # Rule applied on a third device (e.g., gateway) -> FORWARD (Ideal but complex)
             # Defaulting to INPUT, assuming target filters INCOMING traffic that matches src/dest
             chain = "INPUT" # Or FORWARD
             log.debug(f"[ENGINE] Chain set to INPUT (Target '{target_device_ip}' != Source/Dest - assuming INPUT filter)")
        elif source_ip: # Only source specified
             # Applied on source device (target==source): Block outgoing FROM source? -> Not logical usually.
             # Applied on other device: Block incoming from source? -> INPUT
             chain = "INPUT"
             log.debug(f"[ENGINE] Chain set to INPUT (Source IP '{source_ip}' only specified)")
        elif destination_ip: # Only destination specified
             # Applied on dest device (target==dest): Block outgoing TO dest? -> OUTPUT
             # Applied on other device: Block incoming destined for dest? -> INPUT
             # Defaulting to OUTPUT (block own traffic going TO destination)
             chain = "OUTPUT"
             log.debug(f"[ENGINE] Chain set to OUTPUT (Destination IP '{destination_ip}' only specified)")
        else:
             # Should not happen due to validation, but fallback
             log.warning(f"[ENGINE] Could not determine chain reliably for rule {rule}. Defaulting to INPUT.")
             chain = "INPUT"

        # --- Build base command parts ---
        base_cmd_parts = ["iptables", "-A", chain]
        if source_ip:
            base_cmd_parts.extend(["-s", source_ip])
        if destination_ip:
            base_cmd_parts.extend(["-d", destination_ip])

        # --- Generate specific command(s) based on service ---
        commands_for_this_rule = []

        if service_name in SERVICES_TO_IGNORE:
            # Generate single command without service specifics
            cmd_parts = base_cmd_parts + ["-j", iptables_target]
            commands_for_this_rule.append(" ".join(cmd_parts))
            log.debug(f"[ENGINE] Generated IP-only command for service '{service_name}'")
        else:
            param_list = service_mapper.get_service_params(service_name)
            if param_list:
                log.debug(f"[ENGINE] Generating {len(param_list)} specific command(s) for service '{service_name}'")
                for param_dict in param_list:
                    cmd_parts = list(base_cmd_parts) # Start with base parts
                    proto = param_dict.get("proto")
                    dport = param_dict.get("dport")
                    # Add protocol if specified
                    if proto:
                        cmd_parts.extend(["-p", proto])
                        # Add dport only if relevant proto and dport exists
                        if proto in ["tcp", "udp"] and dport is not None:
                            cmd_parts.extend(["--dport", str(dport)])
                        elif dport is not None:
                            log.warning(f"[ENGINE] Dport ({dport}) specified for non-TCP/UDP proto '{proto}' in service '{service_name}'. Ignoring dport.")
                    # Final target action
                    cmd_parts.extend(["-j", iptables_target])
                    commands_for_this_rule.append(" ".join(cmd_parts))
            else:
                 # Service not found/defined, generate IP-only rule
                 log.warning(f"[ENGINE] Service '{service_name}' not found/defined. Generating IP-only command.")
                 cmd_parts = base_cmd_parts + ["-j", iptables_target]
                 commands_for_this_rule.append(" ".join(cmd_parts))

        # --- Store the result for this rule ---
        if commands_for_this_rule:
            log.debug(f"[ENGINE] For Rule {i+1}, generated {len(commands_for_this_rule)} command(s) targeting device {target_device_ip}.")
            # Add tuple: (target_device, source, destination, command_list)
            all_generated_commands.append(
                (target_device_ip, source_ip, destination_ip, commands_for_this_rule)
            )
        else:
             log.warning(f"[ENGINE] No commands were generated for rule {i+1}.")

    return all_generated_commands


def process_and_dispatch(nl_text: str):
    """
    Parses, generates, and immediately dispatches commands.
    NOTE: Uses the new parse_and_generate_commands structure.
    """
    log.info(f"[ENGINE] Processing and dispatching: '{nl_text}'")
    generated_tuples = parse_and_generate_commands(nl_text)

    if not generated_tuples:
        log.warning("[ENGINE] No commands generated, nothing to dispatch.")
        return

    total_sent = 0
    for target_ip, src_ip, dest_ip, cmd_list in generated_tuples:
        log.info(f"[DISPATCH] Sending {len(cmd_list)} command(s) to target {target_ip} (Rule context: src={src_ip}, dest={dest_ip})")
        for cmd in cmd_list:
            try:
                admin_connect.send_command(target_ip, cmd)
                total_sent += 1
            except ConnectionError as e:
                log.error(f"[DISPATCH] Failed to send command to {target_ip}: {e}")
                # Stop sending remaining commands for this target if one fails?
                break
            except Exception as e:
                 log.error(f"[DISPATCH] Unexpected error sending command to {target_ip}: {e}")
                 break # Stop on unexpected errors too
    log.info(f"[DISPATCH] Finished. Total commands sent: {total_sent}")


# Example usage
if __name__ == "__main__":
    # Set logging level for testing
    logging.getLogger('policy_engine').setLevel(logging.DEBUG)
    logging.getLogger('nlp').setLevel(logging.DEBUG)
    logging.getLogger('service_mapper').setLevel(logging.INFO) # Keep mapper info level

    test_nl = "deny ssh from 192.168.1.12 to 192.168.1.11. allow http from 10.0.0.5 to 192.168.1.11. on 10.0.0.1 block dns from 10.0.0.50."

    print("\n--- Testing parse_and_generate_commands ---")
    commands = parse_and_generate_commands(test_nl)
    print("\n--- Generated Command Tuples ---")
    if commands:
        for t in commands:
            print(f"  Target: {t[0]}, Source: {t[1]}, Dest: {t[2]}")
            for cmd in t[3]:
                print(f"    - {cmd}")
    else:
        print("  No commands generated.")
    print("-" * 30)

    # Simulate connected clients if needed for process_and_dispatch test
    # print("\n--- Testing process_and_dispatch ---")
    # if not admin_connect.clients:
    #     print("[ENGINE TEST SETUP] Simulating connected clients for dispatch test.")
    #     admin_connect.clients = {ip: object() for ip in ['192.168.1.11', '10.0.0.1', '10.0.0.50']}
    # process_and_dispatch(test_nl)
    # print("-" * 30)