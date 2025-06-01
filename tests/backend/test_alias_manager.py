# tests/backend/test_alias_manager.py

import unittest
import sys
import os

# Add the parent directory of 'backend' to the Python path
# This allows us to import modules from the 'backend' package
# Assumes 'tests' is a sibling of 'backend' or that the project root is in PYTHONPATH
# For running `python -m unittest discover tests` from project root, this might not be strictly necessary
# but good for individual test file execution or some IDE runners.
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir)) # Go up two levels (tests/backend -> tests -> project_root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Now import from the backend package
from backend import alias_manager

class TestAliasManager(unittest.TestCase):

    def setUp(self):
        """
        This method is called before each test function.
        We clear the aliases to ensure tests are independent.
        """
        # Directly access and clear the internal dictionaries for a clean state.
        # This is a common pattern for testing module-level state.
        alias_manager._aliases_to_ip.clear()
        alias_manager._ip_to_aliases.clear()
        # Re-initialize logging for alias_manager if it logs during tests,
        # though for these tests, its direct logging might not be critical to observe.
        # import logging
        # logging.getLogger('backend.alias_manager').handlers.clear() # Optional: clear handlers if needed

    def test_add_and_get_alias(self):
        """Test adding an alias and retrieving IP/alias."""
        self.assertTrue(alias_manager.add_alias("192.168.1.10", "WebServer1"))
        self.assertEqual(alias_manager.get_ip_for_alias("WebServer1"), "192.168.1.10")
        self.assertEqual(alias_manager.get_ip_for_alias("webserver1"), "192.168.1.10") # Test case-insensitivity
        self.assertEqual(alias_manager.get_alias_for_ip("192.168.1.10"), "webserver1") # Stored as lowercase

    def test_add_empty_alias_or_ip(self):
        """Test adding empty alias or IP should fail."""
        self.assertFalse(alias_manager.add_alias("", "TestAlias"))
        self.assertFalse(alias_manager.add_alias("1.2.3.4", ""))
        self.assertFalse(alias_manager.add_alias("", ""))

    def test_get_non_existent_alias(self):
        """Test retrieving a non-existent alias."""
        self.assertIsNone(alias_manager.get_ip_for_alias("NonExistent"))
        self.assertIsNone(alias_manager.get_alias_for_ip("1.2.3.99"))

    def test_update_alias_for_ip(self):
        """Test updating an alias for an existing IP."""
        alias_manager.add_alias("192.168.1.20", "OldAlias")
        self.assertEqual(alias_manager.get_ip_for_alias("OldAlias"), "192.168.1.20")
        self.assertEqual(alias_manager.get_alias_for_ip("192.168.1.20"), "oldalias")

        self.assertTrue(alias_manager.add_alias("192.168.1.20", "NewAlias")) # Update alias for same IP
        self.assertEqual(alias_manager.get_ip_for_alias("NewAlias"), "192.168.1.20")
        self.assertEqual(alias_manager.get_alias_for_ip("192.168.1.20"), "newalias")
        self.assertIsNone(alias_manager.get_ip_for_alias("OldAlias")) # Old alias should be gone

    def test_update_ip_for_alias(self):
        """Test updating the IP for an existing alias name."""
        alias_manager.add_alias("192.168.1.30", "MyDevice")
        self.assertEqual(alias_manager.get_ip_for_alias("MyDevice"), "192.168.1.30")

        self.assertTrue(alias_manager.add_alias("192.168.1.31", "MyDevice")) # Update IP for same alias
        self.assertEqual(alias_manager.get_ip_for_alias("MyDevice"), "192.168.1.31") # Alias now points to new IP
        self.assertIsNone(alias_manager.get_alias_for_ip("192.168.1.30")) # Old IP should no longer have this alias

    def test_remove_alias_for_ip(self):
        """Test removing an alias."""
        alias_manager.add_alias("192.168.1.40", "TempAlias")
        self.assertIsNotNone(alias_manager.get_ip_for_alias("TempAlias"))

        self.assertTrue(alias_manager.remove_alias_for_ip("192.168.1.40"))
        self.assertIsNone(alias_manager.get_ip_for_alias("TempAlias"))
        self.assertIsNone(alias_manager.get_alias_for_ip("192.168.1.40"))

    def test_remove_non_existent_alias(self):
        """Test removing an alias that doesn't exist for an IP."""
        self.assertFalse(alias_manager.remove_alias_for_ip("192.168.1.50"))

    def test_get_all_aliases(self):
        """Test retrieving all aliases."""
        alias_manager.add_alias("1.1.1.1", "Alias1")
        alias_manager.add_alias("2.2.2.2", "Alias2")
        all_map = alias_manager.get_all_aliases()
        self.assertEqual(len(all_map), 2)
        self.assertEqual(all_map.get("alias1"), "1.1.1.1") # Stored as lowercase
        self.assertEqual(all_map.get("alias2"), "2.2.2.2")

    def test_case_insensitivity_on_add_and_get(self):
        """Test that adding with different cases results in one lowercase entry, get is case-insensitive."""
        alias_manager.add_alias("192.168.1.60", "MixedCaseAlias")
        self.assertEqual(alias_manager.get_ip_for_alias("mixedcasealias"), "192.168.1.60")
        self.assertEqual(alias_manager.get_ip_for_alias("MixedCaseAlias"), "192.168.1.60")
        self.assertEqual(alias_manager.get_ip_for_alias("MIXEDCASEALIAS"), "192.168.1.60")
        self.assertEqual(alias_manager.get_alias_for_ip("192.168.1.60"), "mixedcasealias")

        # Overwriting with different case should update the same entry
        alias_manager.add_alias("192.168.1.61", "MIXEDCASEALIAS") # This should update "mixedcasealias"
        self.assertEqual(alias_manager.get_ip_for_alias("mixedcasealias"), "192.168.1.61")
        self.assertEqual(alias_manager.get_alias_for_ip("192.168.1.61"), "mixedcasealias")
        self.assertIsNone(alias_manager.get_alias_for_ip("192.168.1.60")) # Old IP should no longer map to this alias

if __name__ == '__main__':
    unittest.main()