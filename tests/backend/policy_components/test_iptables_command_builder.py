# tests/backend/policy_components/test_iptables_command_builder.py

import unittest
import sys
import os
import logging
from unittest.mock import patch  # We might use this if we wanted to mock service_mapper

# Add the project root to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.policy_components.iptables_command_builder import IPTablesCommandBuilder, ACTION_TO_IPTABLES_TARGET, \
    SERVICES_TO_IGNORE
# We will use the actual service_mapper, assuming services.json is correctly configured and tested.
from backend import service_mapper

# Enable logging for the command builder module
log = logging.getLogger('backend.policy_components.iptables_command_builder')
log.setLevel(logging.DEBUG)
if not log.hasHandlers():
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    log.addHandler(console_handler)
    log.propagate = False


class TestIPTablesCommandBuilder(unittest.TestCase):

    def setUp(self):
        self.builder = IPTablesCommandBuilder()
        # Base interpreted rule structure for convenience
        self.base_interpreted_rule = {
            "chain": "INPUT",  # Default chain
            "action": "deny",  # Default action
            "service": "any",  # Default service
            "source_ip": None,
            "destination_ip": None,
            "final_target_ip": "1.2.3.4"  # Needed by interpreter, not directly by builder for command string
        }
        # Ensure service_mapper cache is clear for consistent testing if it matters (it shouldn't here)
        service_mapper._service_mappings = None

    def create_interpreted_rule(self, **kwargs):
        """Helper to create an interpreted rule dict, overriding defaults."""
        rule = self.base_interpreted_rule.copy()
        rule.update(kwargs)
        return rule

    def assertCommandsEqual(self, generated_cmds, expected_cmds):
        """Helper to compare lists of commands, ignoring order by using sets."""
        self.assertEqual(set(generated_cmds), set(expected_cmds),
                         f"Generated: {generated_cmds}, Expected: {expected_cmds}")

    # --- Basic Action and Chain Tests ---
    def test_build_simple_deny_input(self):
        rule = self.create_interpreted_rule(source_ip="10.0.0.1")
        expected_cmds = ["iptables -A INPUT -s 10.0.0.1 -j DROP"]
        cmds = self.builder.build_commands(rule)
        self.assertCommandsEqual(cmds, expected_cmds)

    def test_build_simple_allow_output(self):
        rule = self.create_interpreted_rule(action="allow", chain="OUTPUT", destination_ip="10.0.0.2")
        expected_cmds = ["iptables -A OUTPUT -d 10.0.0.2 -j ACCEPT"]
        cmds = self.builder.build_commands(rule)
        self.assertCommandsEqual(cmds, expected_cmds)

    def test_build_forward_with_source_and_dest(self):
        rule = self.create_interpreted_rule(chain="FORWARD", source_ip="1.1.1.1", destination_ip="2.2.2.2")
        expected_cmds = ["iptables -A FORWARD -s 1.1.1.1 -d 2.2.2.2 -j DROP"]
        cmds = self.builder.build_commands(rule)
        self.assertCommandsEqual(cmds, expected_cmds)

    # --- Service-Specific Tests ---
    def test_build_service_ssh(self):
        rule = self.create_interpreted_rule(service="ssh", source_ip="10.0.0.3", action="allow")
        expected_cmds = ["iptables -A INPUT -s 10.0.0.3 -p tcp --dport 22 -j ACCEPT"]
        cmds = self.builder.build_commands(rule)
        self.assertCommandsEqual(cmds, expected_cmds)

    def test_build_service_http_with_dest(self):
        rule = self.create_interpreted_rule(service="http", destination_ip="10.0.0.4", action="block")
        expected_cmds = ["iptables -A INPUT -d 10.0.0.4 -p tcp --dport 80 -j DROP"]
        cmds = self.builder.build_commands(rule)
        self.assertCommandsEqual(cmds, expected_cmds)

    def test_build_service_dns_multiple_commands(self):
        # DNS maps to TCP/53 and UDP/53
        rule = self.create_interpreted_rule(service="dns", source_ip="any_device", destination_ip="8.8.8.8",
                                            action="permit")
        # "any_device" is not an IP, so it should be omitted by builder if not a valid IP.
        # Let's assume for this test, source_ip is a placeholder that builder should handle gracefully or omit.
        # For strictness, let's use a real IP here.
        rule_with_ip = self.create_interpreted_rule(service="dns", source_ip="192.168.1.100", destination_ip="8.8.8.8",
                                                    action="permit")
        expected_cmds = [
            "iptables -A INPUT -s 192.168.1.100 -d 8.8.8.8 -p udp --dport 53 -j ACCEPT",
            "iptables -A INPUT -s 192.168.1.100 -d 8.8.8.8 -p tcp --dport 53 -j ACCEPT"
        ]
        cmds = self.builder.build_commands(rule_with_ip)
        self.assertCommandsEqual(cmds, expected_cmds)

    def test_build_service_ping_icmp(self):
        rule = self.create_interpreted_rule(service="ping", source_ip="1.1.1.1", destination_ip="2.2.2.2",
                                            action="allow")
        expected_cmds = ["iptables -A INPUT -s 1.1.1.1 -d 2.2.2.2 -p icmp -j ACCEPT"]
        cmds = self.builder.build_commands(rule)
        self.assertCommandsEqual(cmds, expected_cmds)

    # --- Tests for SERVICES_TO_IGNORE ---
    def test_build_service_any(self):
        rule = self.create_interpreted_rule(service="any", source_ip="1.2.3.4")
        expected_cmds = ["iptables -A INPUT -s 1.2.3.4 -j DROP"]  # No -p or --dport
        cmds = self.builder.build_commands(rule)
        self.assertCommandsEqual(cmds, expected_cmds)

    def test_build_service_all_traffic(self):
        rule = self.create_interpreted_rule(service="all traffic", source_ip="1.2.3.4", action="allow")
        expected_cmds = ["iptables -A INPUT -s 1.2.3.4 -j ACCEPT"]
        cmds = self.builder.build_commands(rule)
        self.assertCommandsEqual(cmds, expected_cmds)

    def test_build_service_none(self):  # service=None should behave like "any"
        rule = self.create_interpreted_rule(service=None, source_ip="1.2.3.4")
        expected_cmds = ["iptables -A INPUT -s 1.2.3.4 -j DROP"]
        cmds = self.builder.build_commands(rule)
        self.assertCommandsEqual(cmds, expected_cmds)

    # --- Edge Cases and Invalid Inputs for Builder ---
    def test_build_unknown_service_with_ips(self):
        # If service is unknown, but IPs are present, it should create an IP-only rule
        rule = self.create_interpreted_rule(service="unknownservice", source_ip="5.5.5.5", action="allow")
        expected_cmds = ["iptables -A INPUT -s 5.5.5.5 -j ACCEPT"]
        cmds = self.builder.build_commands(rule)
        self.assertCommandsEqual(cmds, expected_cmds)

    def test_build_unknown_service_no_ips(self):
        # If service is unknown AND no IPs, it should probably generate no commands or an error.
        # Current builder logic: if no param_list from service_mapper AND no (source_ip or dest_ip),
        # it logs a warning and returns [].
        rule = self.create_interpreted_rule(service="unknownservice")  # No IPs
        expected_cmds = []
        cmds = self.builder.build_commands(rule)
        self.assertCommandsEqual(cmds, expected_cmds)

    def test_build_no_action(self):
        rule = self.create_interpreted_rule(action=None, source_ip="1.2.3.4")
        cmds = self.builder.build_commands(rule)
        self.assertEqual(cmds, [])  # Should return empty list if no action

    def test_build_no_chain(self):
        rule = self.create_interpreted_rule(chain=None, source_ip="1.2.3.4")
        cmds = self.builder.build_commands(rule)
        self.assertEqual(cmds, [])  # Should return empty list if no chain

    def test_build_no_ips_and_specific_service(self):
        # e.g., "allow ssh" but RuleInterpreter couldn't determine target/source/dest
        # The builder should not generate a command like "iptables -A INPUT -p tcp --dport 22 -j ACCEPT"
        # as it's too broad and dangerous without IP context.
        # Current builder logic might still generate this if service_mapper returns params.
        # This tests if it's handled gracefully.
        rule = self.create_interpreted_rule(service="ssh")  # No IPs
        # Depending on builder logic:
        # If it strictly requires IPs for specific services, expected_cmds = []
        # If it generates "iptables -A INPUT -p tcp --dport 22 -j ACCEPT", this is a broad rule.
        # Let's assume the current builder logic will produce the broad rule based on service params.
        expected_cmds = ["iptables -A INPUT -p tcp --dport 22 -j DROP"]  # Default action is deny
        cmds = self.builder.build_commands(rule)
        self.assertCommandsEqual(cmds, expected_cmds)
        # This test might reveal if you want to add stricter checks in the builder
        # to prevent rules without any IP specifiers unless the service is "any" or "all".


if __name__ == '__main__':
    unittest.main()