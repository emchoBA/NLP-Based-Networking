#!/usr/bin/env python3
"""
policy_engine.py

Takes a natural-language policy string, parses it via enhanced NLP
(handling 1 or 2 IPs to determine subject and target device),
maps verbs to correct iptables targets (ACCEPT/DROP),
determines direction (INPUT/OUTPUT, -s/-d) based on subject IP's context,
and pushes commands to the correct TARGET Pi over TCP (via admin_connect).
"""

from nlp import parse_commands
import admin_connect

# Map the parsed action verbs (lemmas) to actual iptables targets
ACTION_TO_IPTABLES_TARGET = {
    "block": "DROP", "deny": "DROP", "drop": "DROP", "reject": "DROP",
    "allow": "ACCEPT", "permit": "ACCEPT", "accept": "ACCEPT",
}

def process_and_dispatch(nl_text: str):
    """
    1) Parse the user’s input using enhanced NLP into potentially complex rules.
       Rule dict contains: {'action', 'service', 'subject_ip', 'subject_ip_direction', 'target_device_ip'}
    2) For each rule:
       a) Validate necessary components are present.
       b) Map action verb to iptables target (DROP/ACCEPT).
       c) Determine iptables chain (INPUT/OUTPUT) and IP flag (-s/-d) based on subject_ip_direction.
       d) Build the command string using subject_ip.
       e) Send the command to the target_device_ip.
    """
    print(f"\n[ENGINE] Received text for processing: '{nl_text}'")
    rules = parse_commands(nl_text) # Use the enhanced parser

    if not rules:
        print("[ENGINE] No valid commands derived from text.")
        return

    print(f"[ENGINE] Parsed {len(rules)} rule(s). Now dispatching...")

    for i, rule in enumerate(rules):
        print(f"\n[ENGINE] Processing Rule {i+1}: {rule}")

        action_verb          = rule.get('action')
        service              = rule.get('service', 'any') # Default service if not parsed
        subject_ip           = rule.get('subject_ip')
        subject_ip_direction = rule.get('subject_ip_direction')
        target_device_ip     = rule.get('target_device_ip')

        if not all([action_verb, subject_ip, target_device_ip]):
            print(f"[ENGINE WARN] Rule {i+1} is incomplete ({rule}). Skipping.")
            continue

        iptables_target = ACTION_TO_IPTABLES_TARGET.get(action_verb)
        if not iptables_target:
            print(f"[ENGINE WARN] Unknown action verb '{action_verb}' in rule {i+1}. Skipping.")
            continue

        chain = "INPUT"  # Default chain
        ip_flag = "-s"   # Default flag

        if subject_ip_direction == "from":
            chain = "INPUT"
            ip_flag = "-s"
            # print(f"[ENGINE] Rule applies to traffic FROM {subject_ip}")
        elif subject_ip_direction == "to":
            # If rule is "block traffic TO subject_ip", and applied on target_device_ip,
            # it likely means blocking traffic *destined for* subject_ip arriving *at* target_device_ip.
            # This implies INPUT chain with destination IP on the target device.
            # Or, if target_device_ip *is* subject_ip, it means blocking its own OUTPUT.
            # Let's refine this:
            if target_device_ip == subject_ip:
                 # Rule applied ON the subject device, concerning traffic TO it? -> OUTPUT
                 chain = "OUTPUT"
                 ip_flag = "-d"
                 print(f"[ENGINE] Interpreting 'to {subject_ip}' on device {target_device_ip} as OUTPUT rule.")
            else:
                 # Rule applied on a DIFFERENT device, concerning traffic TO subject_ip? -> FORWARD or INPUT?
                 # Let's stick to INPUT -d for now, assuming target is filtering incoming traffic destined elsewhere. Simpler start.
                 # A more robust system would need FORWARD chain logic.
                 chain = "INPUT" # Or FORWARD?
                 ip_flag = "-d" # Traffic destined for subject_ip
                 print(f"[ENGINE] Interpreting 'to {subject_ip}' on device {target_device_ip} as INPUT -d rule.")

        elif subject_ip_direction is None:
            # No "from" or "to" found for the subject IP. Defaulting to INPUT -s.
             print(f"[ENGINE WARN] No clear direction ('from'/'to') found for Subject IP {subject_ip}. Defaulting to INPUT chain, source IP (-s).")
             chain = "INPUT"
             ip_flag = "-s"

        # (Service mapping still deferred)
        # Example: iptables -A INPUT -s 192.168.1.2 -j DROP
        # Example: iptables -A OUTPUT -d 10.0.0.5 -j DROP (if target==subject and direction=="to")
        cmd = f"iptables -A {chain} {ip_flag} {subject_ip} -j {iptables_target}"

        print(f"[ENGINE] Preparing command '{cmd}'")
        print(f"[ENGINE] Sending command to TARGET device: {target_device_ip}")
        admin_connect.send_command(target_device_ip, cmd)

if __name__ == "__main__":
    # Test cases incorporating single and double IP patterns
    test_commands = [
        "deny internet from 192.168.1.2", # -> Send INPUT -s 192.168.1.2 DROP to 192.168.1.2
        "allow ssh to 192.168.1.100",    # -> Send OUTPUT -d 192.168.1.100 ACCEPT to 192.168.1.100
        "on 10.0.0.1 block traffic from 10.0.0.5", # -> Send INPUT -s 10.0.0.5 DROP to 10.0.0.1
        "at 192.168.1.254 reject telnet from 192.168.5.5", # -> Send INPUT -s 192.168.5.5 DROP to 192.168.1.254
        "permit ping to 8.8.8.8 on gateway", # Needs 'gateway' mapped to IP
        "on 192.168.1.1 allow from 192.168.1.50", # -> Send INPUT -s 192.168.1.50 ACCEPT to 192.168.1.1
        "block 1.1.1.1",                  # -> Send INPUT -s 1.1.1.1 DROP to 1.1.1.1 (default direction)
        "on 10.0.0.2 permit 10.0.0.30"     # -> Send INPUT -s 10.0.0.30 ACCEPT to 10.0.0.2 (default direction for subject)
    ]

    for cmd_text in test_commands:
        # Simulate getting connected clients for testing purposes if admin_connect isn't running
        # In a real run, admin_connect manages the clients dictionary
        if not admin_connect.clients:
             print("[ENGINE TEST SETUP] Simulating connected clients for testing.")
             admin_connect.clients = {
                 '192.168.1.2': object(), '192.168.1.100': object(),
                 '10.0.0.1': object(), '192.168.1.254': object(),
                 '192.168.1.1': object(), '1.1.1.1': object(),
                 '10.0.0.2': object(), '10.0.0.5': object(), '192.168.5.5': object(),
                 '10.0.0.30': object()
             } # Replace object() with mock sockets if needed for send tests

        process_and_dispatch(cmd_text)
        print("-" * 20)