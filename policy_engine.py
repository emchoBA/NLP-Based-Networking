#!/usr/bin/env python3
"""
policy_engine.py

Takes a natural-language policy string, parses it via enhanced NLP,
uses service_mapper to get port/protocol specifics, builds command(s),
and pushes them to the correct TARGET Pi over TCP (via admin_connect).
"""

from nlp import parse_commands
import admin_connect, service_mapper

# --- START CHANGE 1: Define services to ignore port/proto specifics ---
# Keep this here as it dictates policy engine behavior
SERVICES_TO_IGNORE = {"any", "all", "traffic", None}
# --- END CHANGE 1 ---

# Map the parsed action verbs (lemmas) to actual iptables targets
ACTION_TO_IPTABLES_TARGET = {
    "block": "DROP", "deny": "DROP", "drop": "DROP", "reject": "DROP",
    "allow": "ACCEPT", "permit": "ACCEPT", "accept": "ACCEPT",
}

def process_and_dispatch(nl_text: str):
    """
    Processes natural language, generates potentially multiple iptables
    commands based on service mappings obtained from service_mapper,
    and dispatches them.
    """
    print(f"\n[ENGINE] Received text for processing: '{nl_text}'")
    rules = parse_commands(nl_text)

    if not rules:
        print("[ENGINE] No valid commands derived from text.")
        return

    print(f"[ENGINE] Parsed {len(rules)} rule(s). Now generating commands...")

    total_commands_sent = 0
    for i, rule in enumerate(rules):
        print(f"\n[ENGINE] Processing Rule {i+1}: {rule}")

        action_verb          = rule.get('action')
        service_name         = rule.get('service') # Get the service name
        subject_ip           = rule.get('subject_ip')
        subject_ip_direction = rule.get('subject_ip_direction')
        target_device_ip     = rule.get('target_device_ip')

        # Validate essential components
        if not all([action_verb, subject_ip, target_device_ip]):
            print(f"[ENGINE WARN] Rule {i+1} is incomplete ({rule}). Skipping.")
            continue

        iptables_target = ACTION_TO_IPTABLES_TARGET.get(action_verb)
        if not iptables_target:
            print(f"[ENGINE WARN] Unknown action verb '{action_verb}' in rule {i+1}. Skipping.")
            continue

        # Determine base chain/flag (same logic as before)
        chain = "INPUT"; ip_flag = "-s" # Defaults
        if subject_ip_direction == "from":
            chain = "INPUT"; ip_flag = "-s"
        elif subject_ip_direction == "to":
            if target_device_ip == subject_ip:
                 chain = "OUTPUT"; ip_flag = "-d"
            else:
                 chain = "INPUT"; ip_flag = "-d"
        elif subject_ip_direction is None:
             print(f"[ENGINE WARN] No clear direction ('from'/'to') for Subject IP {subject_ip}. Defaulting to INPUT -s.")
             chain = "INPUT"; ip_flag = "-s"

        # --- START CHANGE 2: Generate command(s) using service_mapper ---
        commands_to_send = []
        base_cmd_parts = ["iptables", "-A", chain, ip_flag, subject_ip]

        # Check if the service should bypass specific mapping lookup
        if service_name in SERVICES_TO_IGNORE:
            print(f"[ENGINE] Service '{service_name}' ignores specifics. Applying rule to IP only.")
            cmd_parts = base_cmd_parts + ["-j", iptables_target]
            commands_to_send.append(" ".join(cmd_parts))
        else:
            # Get parameters from the dedicated mapper module
            param_list = service_mapper.get_service_params(service_name)

            if param_list: # Mapper returned a list of definitions
                print(f"[ENGINE] Applying specific rules for service '{service_name}' using {len(param_list)} definition(s).")
                # Generate a command for each definition in the list
                for param_dict in param_list:
                    cmd_parts = list(base_cmd_parts) # Start with a copy
                    proto = param_dict.get("proto")
                    dport = param_dict.get("dport")

                    if proto:
                        cmd_parts.extend(["-p", proto])
                        # Only add dport if proto is TCP/UDP and dport is present
                        if proto in ["tcp", "udp"] and dport is not None:
                             cmd_parts.extend(["--dport", str(dport)])
                        elif dport is not None:
                             print(f"[ENGINE WARN] Dport ({dport}) specified for non-TCP/UDP proto '{proto}' in service '{service_name}'. Ignoring dport.")

                    cmd_parts.extend(["-j", iptables_target])
                    commands_to_send.append(" ".join(cmd_parts))

            else: # Service not found in map, or map unavailable/empty definition
                 print(f"[ENGINE WARN] Service '{service_name}' not found/defined in mappings or map unavailable. Applying rule to IP only.")
                 cmd_parts = base_cmd_parts + ["-j", iptables_target]
                 commands_to_send.append(" ".join(cmd_parts))
        # --- END CHANGE 2 ---

        # Dispatch the generated commands (same logic as before)
        if not commands_to_send:
             print(f"[ENGINE WARN] No commands were generated for rule {i+1}. Check logic.")
             continue

        print(f"[ENGINE] For Rule {i+1}, generated {len(commands_to_send)} command(s):")
        for cmd_index, cmd in enumerate(commands_to_send):
             print(f"  {cmd_index+1}: {cmd}")
             print(f"[ENGINE] Sending command {cmd_index+1} to TARGET device: {target_device_ip}")
             admin_connect.send_command(target_device_ip, cmd)
             total_commands_sent += 1

    print(f"\n[ENGINE] Finished processing. Total commands sent: {total_commands_sent}")


if __name__ == "__main__":
    # Simulate connected clients if needed
    if not admin_connect.clients:
         print("\n[ENGINE TEST SETUP] Simulating connected clients for testing.")
         # Use a comprehensive list covering potential targets from tests
         admin_connect.clients = {ip: object() for ip in [
             '192.168.1.2', '192.168.1.100', '10.0.0.1', '192.168.1.254',
             '192.168.1.1', '1.1.1.1', '10.0.0.2', '10.0.0.5', '10.0.0.30',
             '192.168.5.5', '8.8.8.8'
         ]}

    # Test cases (same as before)
    test_commands = [
        "deny ssh from 192.168.1.2",
        "allow dns to 8.8.8.8",
        "on 10.0.0.1 block http from 10.0.0.5",
        "permit ping from 192.168.1.100",
        "block traffic from 1.1.1.1",
        "reject telnet to 192.168.1.1 on 192.168.1.254",
        "allow web from 10.0.0.30",
        "deny ftp traffic from 10.0.0.2",
        "block unknownservice from 10.0.0.5",
    ]

    for cmd_text in test_commands:
        process_and_dispatch(cmd_text)
        print("-" * 20)