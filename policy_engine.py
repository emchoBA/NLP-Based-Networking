# policy_engine.py

#!/usr/bin/env python3
"""
policy_engine.py

Takes a natural-language policy string, parses it via spaCy,
and pushes commands to the correct Pi over TCP (via admin_connect).
"""

from nlp import parse_commands     # your existing NLP parser
import admin_connect

def process_and_dispatch(nl_text: str):
    """
    1) Parse the user’s input into [{'action','service','ip'}, ...]
    2) For each dict, build a command string and send it.
    """
    rules = parse_commands(nl_text)
    if not rules:
        print("[ENGINE] No valid commands found.")
        return

    for rule in rules:
        action  = rule['action']
        service = rule['service'] or 'all'
        ipaddr  = rule['ip']
        # stub iptables syntax—to be refined later
        cmd = f"iptables -A INPUT -s {ipaddr} -j {action.upper()}"
        # send to the device
        admin_connect.send_command(ipaddr, cmd)

if __name__ == "__main__":
    # quick manual test
    example = "deny internet from 192.168.1.2. drop facebook to 10.0.0.5"
    process_and_dispatch(example)
