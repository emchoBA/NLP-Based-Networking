# !/usr/bin/env python3
"""
policy_engine.py

Uses enhanced NLP (source_ip, destination_ip), service_mapper,
builds potentially complex iptables command(s), and prepares them for dispatch.
Optionally uses a preferred_target_ip from GUI if rule isn't explicit.
"""

import logging
import service_mapper  # Assuming service_mapper.py is available
from nlp import parse_commands  # Assuming nlp.py is available
import admin_connect  # Assuming admin_connect.py is available

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


def parse_and_generate_commands(nl_text: str, preferred_target_ip: str | None = None) -> list[
    tuple[str, str | None, str | None, list[str]]]:
    """
    Parses NL text, generates commands using source/destination IPs,
    and returns them for preview/dispatch.
    Optionally uses a preferred_target_ip from GUI if rule has no explicit target.

    Args:
        nl_text: The natural language policy string.
        preferred_target_ip: Optional IP from GUI selection to use if rule has no explicit target.

    Returns:
        A list of tuples. Each tuple contains:
        (final_target_device_ip, source_ip, destination_ip, list_of_commands)
        Returns an empty list if no valid rules/commands are generated.
    """
    log.debug(f"[ENGINE] Parsing for: '{nl_text}', Preferred Target from GUI: {preferred_target_ip}")
    rules = parse_commands(nl_text)  # From nlp.py

    if not rules:
        log.warning("[ENGINE] No valid rules derived from text by NLP.")
        return []

    all_generated_commands = []

    for i, rule in enumerate(rules):
        log.debug(f"[ENGINE] Processing Parsed Rule {i + 1} from NLP: {rule}")

        action_verb = rule.get('action')
        service_name = rule.get('service')
        source_ip = rule.get('source_ip')
        destination_ip = rule.get('destination_ip')

        nlp_target_device_ip = rule.get('target_device_ip')
        # This is the key field that might be overridden by GUI selection
        final_target_device_ip = nlp_target_device_ip

        # Logic to determine if NLP's target was explicit or implicit
        # An NLP target is considered "explicit" if it was set by "on X" or "at X"
        # and is NOT the same as the source_ip or destination_ip (unless that was the explicit target).
        # This is a heuristic. A more robust NLP would pass an 'explicit_target_found' flag.
        nlp_target_was_explicit = False
        if nlp_target_device_ip:
            # If nlp_target is different from both source and dest (and they exist), it was likely "on X"
            if source_ip and destination_ip and \
                    nlp_target_device_ip != source_ip and nlp_target_device_ip != destination_ip:
                nlp_target_was_explicit = True
            # If only source, and nlp_target is not source, it was "on X"
            elif source_ip and not destination_ip and nlp_target_device_ip != source_ip:
                nlp_target_was_explicit = True
            # If only dest, and nlp_target is not dest, it was "on X"
            elif destination_ip and not source_ip and nlp_target_device_ip != destination_ip:
                nlp_target_was_explicit = True
            # If NLP target is same as source/dest, it's only explicit if "on source_ip" was used.
            # This requires checking the original command string, which is complex here.
            # For now, we simplify: if preferred_target_ip is provided, and NLP's target *could* have been a default,
            # we might override. If NLP's target is clearly different, we assume it was explicit.

        if preferred_target_ip:
            if not nlp_target_device_ip:  # NLP found no target at all
                log.info(f"[ENGINE] NLP found no target device. Using GUI preferred '{preferred_target_ip}'.")
                final_target_device_ip = preferred_target_ip
            elif not nlp_target_was_explicit:
                # If NLP's target seems like it was a default (e.g., same as source or dest)
                # and not from an explicit "on/at" phrase that points elsewhere.
                # (This condition can be tricky to get perfect without more info from NLP)
                # A simpler override: If preferred_target is set, and NLP target is implicit.
                is_nlp_target_implicit_default = False
                if nlp_target_device_ip == source_ip and (not destination_ip or destination_ip == source_ip):
                    is_nlp_target_implicit_default = True
                elif nlp_target_device_ip == destination_ip:
                    is_nlp_target_implicit_default = True

                if is_nlp_target_implicit_default:
                    log.info(
                        f"[ENGINE] NLP target '{nlp_target_device_ip}' was implicit. Overriding with GUI preferred '{preferred_target_ip}'.")
                    final_target_device_ip = preferred_target_ip
                else:  # NLP target was different from src/dest, assume it was explicit "on X"
                    log.debug(
                        f"[ENGINE] NLP target '{nlp_target_device_ip}' appears explicit or preferred not applicable. Keeping NLP target.")
            else:  # NLP target was explicit
                log.debug(
                    f"[ENGINE] NLP target '{nlp_target_device_ip}' was explicit. GUI preferred target '{preferred_target_ip}' ignored for this rule.")

        # Final check for a target
        if not final_target_device_ip:
            log.warning(
                f"[ENGINE] Rule {i + 1} has no resolvable target device after considering preferred. Parsed: {rule}. Skipping.")
            continue

        log.debug(f"[ENGINE] Final Target Device for rule {i + 1}: {final_target_device_ip}")

        # Validate other essential parts
        if not action_verb or not (source_ip or destination_ip):
            log.warning(
                f"[ENGINE] Rule {i + 1} incomplete. Action: {action_verb}, Src: {source_ip}, Dest: {destination_ip}. Skipping.")
            continue

        iptables_target = ACTION_TO_IPTABLES_TARGET.get(action_verb)
        if not iptables_target:
            log.warning(f"[ENGINE] Unknown action verb '{action_verb}' in rule {i + 1}. Skipping generation.")
            continue

        # --- Determine Chain based on final_target_device_ip ---
        chain = "INPUT"  # Default
        if final_target_device_ip == source_ip and destination_ip:
            chain = "OUTPUT"
        elif final_target_device_ip == destination_ip and source_ip:
            chain = "INPUT"
        elif source_ip and destination_ip:  # Target is a third party (gateway)
            chain = "FORWARD"  # If target is not src or dest, assume FORWARD
        elif source_ip:  # Only source specified
            if final_target_device_ip == source_ip:
                chain = "OUTPUT"  # Rule on source, about its own outgoing traffic
            else:
                chain = "INPUT"  # Rule on other device, about incoming from source
        elif destination_ip:  # Only destination specified
            if final_target_device_ip == destination_ip:
                chain = "OUTPUT"  # Rule on dest, about its own outgoing
            else:
                chain = "INPUT"  # Rule on other device, about incoming for dest
        log.debug(f"[ENGINE] Chain determined as: {chain} for target {final_target_device_ip}")

        base_cmd_parts = ["iptables", "-A", chain]
        if source_ip: base_cmd_parts.extend(["-s", source_ip])
        if destination_ip: base_cmd_parts.extend(["-d", destination_ip])

        commands_for_this_rule = []
        if service_name in SERVICES_TO_IGNORE:
            cmd_parts = base_cmd_parts + ["-j", iptables_target]
            commands_for_this_rule.append(" ".join(cmd_parts))
        else:
            param_list = service_mapper.get_service_params(service_name)
            if param_list:
                for param_dict in param_list:
                    cmd_parts = list(base_cmd_parts)
                    proto = param_dict.get("proto")
                    dport = param_dict.get("dport")
                    if proto:
                        cmd_parts.extend(["-p", proto])
                        if proto in ["tcp", "udp"] and dport is not None:
                            cmd_parts.extend(["--dport", str(dport)])
                        elif dport is not None:
                            log.warning(
                                f"[ENGINE] Dport for non-TCP/UDP proto '{proto}' in '{service_name}'. Ignoring dport.")
                    cmd_parts.extend(["-j", iptables_target])
                    commands_for_this_rule.append(" ".join(cmd_parts))
            else:
                log.warning(f"[ENGINE] Service '{service_name}' not found/defined. IP-only command.")
                cmd_parts = base_cmd_parts + ["-j", iptables_target]
                commands_for_this_rule.append(" ".join(cmd_parts))

        if commands_for_this_rule:
            log.debug(
                f"[ENGINE] For Rule {i + 1}, generated {len(commands_for_this_rule)} cmd(s) target: {final_target_device_ip}, src: {source_ip}, dest: {destination_ip}")
            all_generated_commands.append(
                (final_target_device_ip, source_ip, destination_ip, commands_for_this_rule)
            )
        else:
            log.warning(f"[ENGINE] No commands were generated for rule {i + 1}.")
    return all_generated_commands


def process_and_dispatch(nl_text: str, preferred_target_ip: str | None = None):  # Add arg
    log.info(f"[ENGINE] Processing and dispatching: '{nl_text}', Preferred Target: {preferred_target_ip}")
    generated_tuples = parse_and_generate_commands(nl_text, preferred_target_ip)  # Pass arg
    if not generated_tuples:
        log.warning("[ENGINE] No commands generated, nothing to dispatch.")
        return

    total_sent = 0
    for target_ip, src_ip, dest_ip, cmd_list in generated_tuples:
        log.info(
            f"[DISPATCH] Sending {len(cmd_list)} cmd(s) to target {target_ip} (Rule: src={src_ip}, dest={dest_ip})")
        for cmd in cmd_list:
            try:
                if admin_connect and hasattr(admin_connect, 'send_command'):
                    admin_connect.send_command(target_ip, cmd)
                    total_sent += 1
                else:
                    log.error("[DISPATCH] admin_connect unavailable.")
                    break
            except ConnectionError as e:
                log.error(f"[DISPATCH] Failed to send to {target_ip}: {e}")
                break
            except Exception as e:
                log.error(f"[DISPATCH] Unexpected error sending to {target_ip}: {e}")
                break
    log.info(f"[DISPATCH] Finished. Total commands sent: {total_sent}")


if __name__ == "__main__":
    logging.getLogger('policy_engine').setLevel(logging.DEBUG)
    logging.getLogger('nlp').setLevel(logging.DEBUG)  # Keep NLP debug for now
    logging.getLogger('service_mapper').setLevel(logging.INFO)

    # Test case 1: NLP defaults target, GUI overrides
    test_nl1 = "deny 192.168.1.12"  # NLP target will be 1.12
    preferred1 = "192.168.1.11"  # GUI selected this
    print(f"\n--- Test 1: '{test_nl1}' with Preferred Target '{preferred1}' ---")
    commands1 = parse_and_generate_commands(test_nl1, preferred_target_ip=preferred1)
    for t_ip, s_ip, d_ip, c_list in commands1: print(f"  Target: {t_ip}, Src: {s_ip}, Dest: {d_ip}, Cmds: {c_list}")

    # Test case 2: NLP is explicit, GUI selection ignored
    test_nl2 = "on 192.168.1.50 allow ssh from 192.168.1.60"  # NLP target is 1.50
    preferred2 = "192.168.1.11"  # GUI selected this
    print(
        f"\n--- Test 2: '{test_nl2}' with Preferred Target '{preferred2}' (should be ignored by engine if NLP explicit) ---")
    commands2 = parse_and_generate_commands(test_nl2, preferred_target_ip=preferred2)
    for t_ip, s_ip, d_ip, c_list in commands2: print(f"  Target: {t_ip}, Src: {s_ip}, Dest: {d_ip}, Cmds: {c_list}")

    # Test case 3: NLP defaults target (dest), GUI overrides
    test_nl3 = "allow http to 192.168.1.70"  # NLP target will be 1.70
    preferred3 = "192.168.1.11"
    print(f"\n--- Test 3: '{test_nl3}' with Preferred Target '{preferred3}' ---")
    commands3 = parse_and_generate_commands(test_nl3, preferred_target_ip=preferred3)
    for t_ip, s_ip, d_ip, c_list in commands3: print(f"  Target: {t_ip}, Src: {s_ip}, Dest: {d_ip}, Cmds: {c_list}")

    # Test case 4: Two IPs, NLP defaults target (dest), GUI overrides
    test_nl4 = "block dns from 192.168.1.80 to 192.168.1.90"  # NLP target will be 1.90
    preferred4 = "192.168.1.11"
    print(f"\n--- Test 4: '{test_nl4}' with Preferred Target '{preferred4}' ---")
    commands4 = parse_and_generate_commands(test_nl4, preferred_target_ip=preferred4)
    for t_ip, s_ip, d_ip, c_list in commands4: print(f"  Target: {t_ip}, Src: {s_ip}, Dest: {d_ip}, Cmds: {c_list}")

    # Test Case 5: Multi-sentence, one with implicit target, one explicit
    test_nl5 = "deny 192.168.1.20. on 192.168.1.21 allow 192.168.1.22"
    preferred5 = "192.168.1.100"
    print(f"\n--- Test 5: '{test_nl5}' with Preferred Target '{preferred5}' ---")
    commands5 = parse_and_generate_commands(test_nl5, preferred_target_ip=preferred5)
    print("Expected: Rule 1 Target=100 (override), Rule 2 Target=21 (explicit)")
    for t_ip, s_ip, d_ip, c_list in commands5: print(f"  Target: {t_ip}, Src: {s_ip}, Dest: {d_ip}, Cmds: {c_list}")