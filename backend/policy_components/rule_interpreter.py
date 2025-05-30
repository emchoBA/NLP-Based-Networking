import logging

log = logging.getLogger(__name__)


class RuleInterpreter:
    def __init__(self):
        pass  # No specific state needed for now

    def determine_final_target_and_chain(self, nlp_rule: dict, preferred_target_ip: str | None = None) -> dict | None:
        """
        Determines the final target IP and iptables chain for a given NLP rule.

        Args:
            nlp_rule: A dictionary from nlp.parse_commands.
                      Expected keys: 'action', 'service', 'source_ip',
                                     'destination_ip', 'target_device_ip'.
            preferred_target_ip: Optional IP from GUI selection.

        Returns:
            A dictionary with 'final_target_ip', 'chain', and other relevant
            details from nlp_rule if successful, otherwise None.
            Example: {'final_target_ip': '1.2.3.4', 'chain': 'INPUT',
                      'action': 'deny', 'service': 'ssh',
                      'source_ip': '5.6.7.8', 'destination_ip': None}
        """
        action_verb = nlp_rule.get('action')
        service_name = nlp_rule.get('service')
        source_ip = nlp_rule.get('source_ip')
        destination_ip = nlp_rule.get('destination_ip')
        nlp_target_device_ip = nlp_rule.get('target_device_ip')

        final_target_device_ip = nlp_target_device_ip

        # --- Logic to determine if NLP's target was explicit or implicit ---
        # This heuristic can be refined. A target is "explicit" if it was likely set by "on X"
        # and is distinct from source/destination (unless explicitly targeted).
        nlp_target_was_explicit = False
        if nlp_target_device_ip:
            is_different_from_source = source_ip and nlp_target_device_ip != source_ip
            is_different_from_dest = destination_ip and nlp_target_device_ip != destination_ip

            if (source_ip and destination_ip and is_different_from_source and is_different_from_dest) or \
                    (source_ip and not destination_ip and is_different_from_source) or \
                    (destination_ip and not source_ip and is_different_from_dest) or \
                    (not source_ip and not destination_ip):  # e.g. "on DeviceA block ssh"
                nlp_target_was_explicit = True

        if preferred_target_ip:
            if not nlp_target_device_ip:
                log.info(f"[Interpreter] NLP found no target. Using GUI preferred '{preferred_target_ip}'.")
                final_target_device_ip = preferred_target_ip
            elif not nlp_target_was_explicit:
                # If NLP's target seems like a default (e.g., same as source or dest)
                log.info(
                    f"[Interpreter] NLP target '{nlp_target_device_ip}' may be implicit. "
                    f"Overriding with GUI preferred '{preferred_target_ip}'."
                )
                final_target_device_ip = preferred_target_ip
            else:  # NLP target was explicit
                log.debug(
                    f"[Interpreter] NLP target '{nlp_target_device_ip}' was explicit. "
                    f"GUI preferred target '{preferred_target_ip}' ignored for this rule."
                )

        if not final_target_device_ip:
            log.warning(f"[Interpreter] No resolvable target device for rule: {nlp_rule}. Skipping.")
            return None

        # --- Determine Chain based on final_target_device_ip ---
        chain = "INPUT"  # Default
        if final_target_device_ip == source_ip and destination_ip:  # Rule on SRC about its OUT traffic to DEST
            chain = "OUTPUT"
        elif final_target_device_ip == destination_ip and source_ip:  # Rule on DEST about its IN traffic from SRC
            chain = "INPUT"
        elif source_ip and destination_ip:  # Target is a third party (gateway scenario)
            # If final_target_device_ip is NOT source_ip and NOT destination_ip
            if final_target_device_ip != source_ip and final_target_device_ip != destination_ip:
                chain = "FORWARD"
            # If by some logic final_target_ip became source_ip or dest_ip, re-evaluate
            elif final_target_device_ip == source_ip:
                chain = "OUTPUT"
            else:  # final_target_device_ip == destination_ip
                chain = "INPUT"
        elif source_ip:  # Only source specified
            if final_target_device_ip == source_ip:  # Rule on source, about its own outgoing traffic (dest implied as any)
                chain = "OUTPUT"
            else:  # Rule on other device, about incoming from source
                chain = "INPUT"
        elif destination_ip:  # Only destination specified
            # This case is a bit ambiguous without a source.
            # If "block http to WebServer" on Gateway, chain is INPUT (to WebServer) on Gateway.
            # If "block http to WebServer" on WebServer, chain is INPUT (to self) on WebServer.
            # The current logic defaults to INPUT if not explicitly OUTPUT or FORWARD.
            # If final_target_device_ip == destination_ip, it means a rule on the destination device itself.
            chain = "INPUT"  # Generally, if we're targeting a device with a rule "to X", it's input on that device.
            # Or if "on Gateway allow to X", it's FORWARD.
            # This depends heavily on how NLP sets target_device_ip.
            # Let's stick to the previous logic path carefully.
            if final_target_device_ip == destination_ip:
                # This typically means "on DeviceX allow/deny traffic to DeviceX"
                # This scenario needs careful thought based on NLP's output.
                # If NLP sets target_device_ip = destination_ip, and source is not specified, it's INPUT on destination_ip.
                pass  # Stays INPUT by default
            # else: # "on SomeOtherDevice allow/deny traffic to destination_ip"
            # This would be FORWARD if SomeOtherDevice is not destination_ip.
            # This path is less likely given NLP usually defaults target to source/dest if not explicit.

        log.debug(f"[Interpreter] Final Target: {final_target_device_ip}, Chain: {chain} for rule: {nlp_rule}")

        return {
            "final_target_ip": final_target_device_ip,
            "chain": chain,
            "action": action_verb,
            "service": service_name,
            "source_ip": source_ip,
            "destination_ip": destination_ip,
            "original_nlp_rule": nlp_rule  # For context if needed
        }