import logging
# Assuming service_mapper.py is in the same 'backend' package or accessible
from .. import service_mapper  # Relative import for sibling module in package

log = logging.getLogger(__name__)

# Services that don't use port/protocol specifics
SERVICES_TO_IGNORE = {"any", "all", "traffic", None}

# Map action verbs to iptables targets
ACTION_TO_IPTABLES_TARGET = {
    "block": "DROP", "deny": "DROP", "drop": "DROP", "reject": "DROP",  # Could use REJECT for reject
    "allow": "ACCEPT", "permit": "ACCEPT", "accept": "ACCEPT",
}


class IPTablesCommandBuilder:
    def __init__(self):
        pass  # No specific state needed for now

    def build_commands(self, interpreted_rule: dict) -> list[str]:
        """
        Builds iptables command strings from an interpreted rule.

        Args:
            interpreted_rule: A dictionary from RuleInterpreter, containing
                              'final_target_ip', 'chain', 'action', 'service',
                              'source_ip', 'destination_ip'.

        Returns:
            A list of iptables command strings.
        """
        chain = interpreted_rule.get('chain')
        action_verb = interpreted_rule.get('action')
        service_name = interpreted_rule.get('service')
        source_ip = interpreted_rule.get('source_ip')
        destination_ip = interpreted_rule.get('destination_ip')
        # final_target_ip is for dispatch, not part of the iptables command itself.

        if not action_verb or not chain:
            log.warning(f"[CmdBuilder] Missing action or chain in rule: {interpreted_rule}. Cannot build commands.")
            return []

        # At least one of source_ip or destination_ip should typically be present for meaningful rules,
        # unless it's a very generic rule like "block all on eth0" (which this engine doesn't fully support yet).
        # For now, we rely on NLP to provide some IP context.
        if not source_ip and not destination_ip and service_name in SERVICES_TO_IGNORE:
            # This implies a very broad rule like "block all" or "allow all" on a chain.
            # Be cautious with such rules. For now, we'll proceed if an action and chain are present.
            log.debug(f"[CmdBuilder] Building a broad rule for chain {chain} with action {action_verb}")

        iptables_target_action = ACTION_TO_IPTABLES_TARGET.get(action_verb.lower())
        if not iptables_target_action:
            log.warning(f"[CmdBuilder] Unknown action verb '{action_verb}'. Cannot map to iptables target.")
            return []

        base_cmd_parts = ["iptables", "-A", chain]
        if source_ip:
            base_cmd_parts.extend(["-s", source_ip])
        if destination_ip:
            base_cmd_parts.extend(["-d", destination_ip])

        commands_for_this_rule = []

        if service_name and service_name.lower() in SERVICES_TO_IGNORE:
            cmd_parts = base_cmd_parts + ["-j", iptables_target_action]
            commands_for_this_rule.append(" ".join(cmd_parts))
        else:
            # Use the imported service_mapper
            param_list = service_mapper.get_service_params(service_name)
            if param_list:
                for param_dict in param_list:
                    cmd_parts_for_service = list(base_cmd_parts)  # Start fresh for each proto/port combo
                    proto = param_dict.get("proto")
                    dport = param_dict.get("dport")

                    if proto:
                        cmd_parts_for_service.extend(["-p", proto])
                        if proto.lower() in ["tcp", "udp"] and dport is not None:
                            cmd_parts_for_service.extend(["--dport", str(dport)])
                        elif dport is not None:  # dport specified but proto not tcp/udp
                            log.warning(
                                f"[CmdBuilder] Dport '{dport}' specified for non-TCP/UDP proto '{proto}' "
                                f"in service '{service_name}'. Dport will be ignored for this part of the rule."
                            )
                    cmd_parts_for_service.extend(["-j", iptables_target_action])
                    commands_for_this_rule.append(" ".join(cmd_parts_for_service))
            else:
                log.warning(f"[CmdBuilder] Service '{service_name}' not found or undefined in service_mapper. "
                            f"Generating IP-only rule if possible, or rule may be ineffective.")
                # If service is unknown, generate a rule without -p or --dport if IPs are present.
                # If no IPs, this might be an invalid/too broad rule.
                if source_ip or destination_ip:  # Only add IP-only rule if there's some specificity
                    cmd_parts = base_cmd_parts + ["-j", iptables_target_action]
                    commands_for_this_rule.append(" ".join(cmd_parts))
                else:
                    log.warning(
                        f"[CmdBuilder] Cannot generate meaningful IP-only rule for unknown service '{service_name}' without source/destination IPs.")

        if not commands_for_this_rule and (source_ip or destination_ip):
            # Fallback if service was specified but yielded no specific commands (e.g. bad service name)
            # but we still have IP information.
            log.debug(
                f"[CmdBuilder] No service-specific commands for '{service_name}', but IPs exist. Generating generic IP rule.")
            cmd_parts = base_cmd_parts + ["-j", iptables_target_action]
            commands_for_this_rule.append(" ".join(cmd_parts))

        log.debug(f"[CmdBuilder] Generated {len(commands_for_this_rule)} commands for rule: {interpreted_rule}")
        return commands_for_this_rule