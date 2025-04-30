#!/usr/bin/env python3
"""
service_mapper.py

Loads service-to-port/protocol definitions from services.json
and provides a function to look them up.
"""

import json
import os
import sys

SERVICE_MAP_FILE = 'services.json'
_service_mappings = None # Module-level cache for loaded mappings

def _load_mappings():
    """Internal function to load mappings from the JSON file."""
    global _service_mappings
    # Construct path relative to this script file
    # Correctly handles running from different directories
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        filepath = os.path.join(base_dir, SERVICE_MAP_FILE)
    except NameError: # __file__ might not be defined (e.g., interactive)
        filepath = SERVICE_MAP_FILE # Fallback to relative path

    print(f"[Mapper] Attempting to load service mappings from: {filepath}")
    try:
        with open(filepath, 'r') as f:
            _service_mappings = json.load(f)
        print(f"[Mapper] Successfully loaded {len(_service_mappings)} service definitions.")
        return True
    except FileNotFoundError:
        print(f"[Mapper ERROR] Service mapping file not found: {filepath}", file=sys.stderr)
        _service_mappings = {} # Ensure it's empty dict if load fails
        return False
    except json.JSONDecodeError as e:
        print(f"[Mapper ERROR] Failed to parse JSON from {filepath}: {e}", file=sys.stderr)
        _service_mappings = {}
        return False
    except Exception as e:
        print(f"[Mapper ERROR] An unexpected error occurred loading {filepath}: {e}", file=sys.stderr)
        _service_mappings = {}
        return False

def get_service_params(service_name: str | None) -> list | None:
    """
    Looks up the iptables parameters for a given service name.

    Args:
        service_name: The lowercase name of the service (e.g., 'ssh', 'dns').

    Returns:
        A list of parameter dictionaries (e.g., [{'proto': 'tcp', 'dport': 22}])
        if the service is found and defined, otherwise returns None.
        Returns None if mappings couldn't be loaded.
    """
    global _service_mappings
    if service_name is None:
        return None

    # Lazy load: Load mappings only on the first call
    if _service_mappings is None:
        if not _load_mappings():
            # Loading failed, subsequent calls will also fail until fixed
             print("[Mapper WARN] Service mappings unavailable.", file=sys.stderr)
             return None # Indicate failure or unavailability

    # Perform the lookup (case-insensitive although keys are lowercase)
    params = _service_mappings.get(service_name.lower())
    if params is None:
        # print(f"[Mapper DEBUG] Service '{service_name}' not found in mappings.")
        pass # Don't print debug for every miss
    elif not isinstance(params, list):
         print(f"[Mapper WARN] Definition for '{service_name}' in {SERVICE_MAP_FILE} is not a list. Ignoring.", file=sys.stderr)
         return None # Treat invalid definition as not found

    return params # Returns the list or None if not found

# Example usage (optional - for testing this module directly)
if __name__ == "__main__":
    print("\n--- Testing service_mapper ---")
    print(f"SSH params: {get_service_params('ssh')}")
    print(f"DNS params: {get_service_params('dns')}")
    print(f"HTTP params: {get_service_params('http')}")
    print(f"Web params: {get_service_params('web')}")
    print(f"Unknown params: {get_service_params('unknown')}")
    print(f"None params: {get_service_params(None)}")
    # Test loading failure (rename services.json temporarily)
    # original_name = SERVICE_MAP_FILE
    # temp_name = "temp_services.json"
    # try:
    #     if os.path.exists(original_name):
    #         os.rename(original_name, temp_name)
    #         _service_mappings = None # Reset cache
    #         print(f"\n--- Testing load failure ---")
    #         print(f"SSH params after rename: {get_service_params('ssh')}")
    # finally:
    #     if os.path.exists(temp_name):
    #          os.rename(temp_name, original_name)
    # print("\n--- Testing Complete ---")