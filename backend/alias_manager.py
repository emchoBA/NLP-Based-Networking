"""
alias_manager.py

Manages in-memory storage and lookup of IP address aliases.
"""
import logging

log = logging.getLogger(__name__)

# In-memory storage for aliases: { "alias_name": "ip_address" }
# And reverse lookup: { "ip_address": "alias_name" } for display
_aliases_to_ip = {}
_ip_to_aliases = {}

def add_alias(ip_address: str, alias_name: str) -> bool:
    """
    Adds or updates an alias for an IP address.
    Alias names are case-insensitive for storage (converted to lowercase).
    """
    if not ip_address or not alias_name:
        log.warning("[Alias] Attempted to add empty IP or alias.")
        return False

    alias_name_lower = alias_name.lower()

    # Remove any existing alias for this IP (if it's changing)
    if ip_address in _ip_to_aliases:
        old_alias = _ip_to_aliases[ip_address]
        if old_alias in _aliases_to_ip:
            del _aliases_to_ip[old_alias]
        log.debug(f"[Alias] Removing old alias '{old_alias}' for IP {ip_address}.")

    # Remove any existing IP for this alias name (if it's being reassigned)
    if alias_name_lower in _aliases_to_ip:
        old_ip = _aliases_to_ip[alias_name_lower]
        if old_ip in _ip_to_aliases and _ip_to_aliases[old_ip] == alias_name_lower:
            del _ip_to_aliases[old_ip]
        log.debug(f"[Alias] Alias '{alias_name_lower}' was previously assigned to {old_ip}.")

    _aliases_to_ip[alias_name_lower] = ip_address
    _ip_to_aliases[ip_address] = alias_name_lower # Store the lowercase alias for consistency
    log.info(f"[Alias] Added/Updated alias: '{alias_name}' -> {ip_address}")
    return True

def remove_alias_for_ip(ip_address: str) -> bool:
    """Removes any alias associated with the given IP address."""
    if ip_address in _ip_to_aliases:
        alias_name_lower = _ip_to_aliases.pop(ip_address) # Remove from IP-to-alias
        if alias_name_lower in _aliases_to_ip:
            _aliases_to_ip.pop(alias_name_lower) # Remove from alias-to-IP
            log.info(f"[Alias] Removed alias '{alias_name_lower}' for IP {ip_address}.")
            return True
    log.warning(f"[Alias] No alias found to remove for IP {ip_address}.")
    return False

def get_ip_for_alias(alias_name: str) -> str | None:
    """
    Resolves an alias name (case-insensitive) to an IP address.
    """
    return _aliases_to_ip.get(alias_name.lower())

def get_alias_for_ip(ip_address: str) -> str | None:
    """
    Retrieves the alias name for a given IP address.
    Returns the stored (lowercase) alias.
    """
    return _ip_to_aliases.get(ip_address)

def get_all_aliases() -> dict:
    """Returns a copy of the alias to IP mapping."""
    return _aliases_to_ip.copy()

# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    add_alias("192.168.1.11", "Device 1")
    add_alias("192.168.1.12", "Server Alpha")
    add_alias("192.168.1.12", "WebServer") # Update alias for 1.12

    print(f"IP for 'device 1': {get_ip_for_alias('device 1')}")
    print(f"IP for 'Device 1': {get_ip_for_alias('Device 1')}")
    print(f"IP for 'WebServer': {get_ip_for_alias('WebServer')}")
    print(f"IP for 'server alpha': {get_ip_for_alias('server alpha')}") # Should be None

    print(f"Alias for 192.168.1.11: {get_alias_for_ip('192.168.1.11')}")
    print(f"Alias for 192.168.1.12: {get_alias_for_ip('192.168.1.12')}")

    remove_alias_for_ip("192.168.1.11")
    print(f"Alias for 192.168.1.11 after removal: {get_alias_for_ip('192.168.1.11')}")
    print(f"All aliases: {get_all_aliases()}")