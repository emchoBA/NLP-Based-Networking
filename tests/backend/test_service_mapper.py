# tests/backend/test_service_mapper.py

import unittest
import sys
import os
import json  # To potentially create a mock services.json for testing if needed

# Add the parent directory of 'backend' to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend import service_mapper

# Define the expected path to services.json relative to the project root
# This assumes service_mapper.py correctly locates services.json in the backend/ directory
# If service_mapper._load_mappings() uses a different pathing logic, adjust this or mock it.
SERVICES_JSON_PATH_IN_BACKEND = os.path.join(project_root, "backend", "services.json")


class TestServiceMapper(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """
        Set up for all tests in this class.
        We can try to load mappings once to see if the file exists.
        Alternatively, for truly isolated unit tests, we might mock _load_mappings
        or temporarily replace services.json with a test version.
        For now, let's assume services.json exists and is valid for these tests.
        """
        # Reset the internal cache in service_mapper before tests run
        # to ensure fresh loading or consistent state if tests modify it (though they shouldn't)
        service_mapper._service_mappings = None

        # Check if the actual services.json can be loaded.
        # This isn't a strict unit test of _load_mappings logic, but a prerequisite check.
        if not os.path.exists(SERVICES_JSON_PATH_IN_BACKEND):
            raise FileNotFoundError(
                f"CRITICAL: services.json not found at expected location for testing: "
                f"{SERVICES_JSON_PATH_IN_BACKEND}. Tests cannot proceed."
            )
        # Attempt an initial load to catch JSON errors early, if any.
        # If this fails, tests requiring actual data will fail.
        service_mapper._load_mappings()  # This will print errors if file is malformed
        if service_mapper._service_mappings is None or not service_mapper._service_mappings:
            print(f"WARNING: service_mapper._service_mappings is empty or None after initial load attempt. "
                  f"Tests relying on services.json content might fail.")

    def setUp(self):
        """
        Called before each test. We ensure _service_mappings is reset so each
        test either reloads or uses the class-loaded version consistently.
        """
        # To ensure each test gets a fresh load if it needs it, or if a previous
        # test somehow manipulated the module-level cache (which it shouldn't).
        service_mapper._service_mappings = None
        # Force a reload for each test to ensure isolation if _load_mappings itself is tested implicitly
        # or if we want to test behavior when the file is missing/corrupt in specific tests (more advanced).
        # For now, we assume it's loaded once in setUpClass or reloaded by get_service_params.
        # The get_service_params function itself handles lazy loading.

    def test_get_known_service_ssh(self):
        """Test retrieving parameters for 'ssh'."""
        params = service_mapper.get_service_params("ssh")
        self.assertIsNotNone(params)
        self.assertIsInstance(params, list)
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0], {"proto": "tcp", "dport": 22})

    def test_get_known_service_http(self):
        """Test retrieving parameters for 'http'."""
        params = service_mapper.get_service_params("http")
        self.assertIsNotNone(params)
        self.assertEqual(params, [{"proto": "tcp", "dport": 80}])

    def test_get_known_service_dns(self):
        """Test retrieving parameters for 'dns' (multiple entries)."""
        params = service_mapper.get_service_params("dns")
        self.assertIsNotNone(params)
        self.assertIsInstance(params, list)
        self.assertEqual(len(params), 2)
        # Order might not be guaranteed by dict.get, so check for presence
        self.assertIn({"proto": "udp", "dport": 53}, params)
        self.assertIn({"proto": "tcp", "dport": 53}, params)

    def test_get_known_service_web(self):
        """Test retrieving parameters for 'web' (multiple entries)."""
        params = service_mapper.get_service_params("web")
        self.assertIsNotNone(params)
        self.assertIsInstance(params, list)
        self.assertEqual(len(params), 2)
        self.assertIn({"proto": "tcp", "dport": 80}, params)
        self.assertIn({"proto": "tcp", "dport": 443}, params)

    def test_get_known_service_ping(self):
        """Test retrieving parameters for 'ping' (no dport)."""
        params = service_mapper.get_service_params("ping")
        self.assertIsNotNone(params)
        self.assertEqual(params, [{"proto": "icmp"}])

    def test_get_service_case_insensitivity(self):
        """Test that service name lookup is case-insensitive."""
        params_lower = service_mapper.get_service_params("ssh")
        params_upper = service_mapper.get_service_params("SSH")
        params_mixed = service_mapper.get_service_params("Ssh")
        self.assertEqual(params_lower, [{"proto": "tcp", "dport": 22}])
        self.assertEqual(params_upper, [{"proto": "tcp", "dport": 22}])
        self.assertEqual(params_mixed, [{"proto": "tcp", "dport": 22}])

    def test_get_unknown_service(self):
        """Test retrieving an unknown service."""
        params = service_mapper.get_service_params("nonexistentservice")
        self.assertIsNone(params)  # Expecting None for unknown service

    def test_get_none_service(self):
        """Test passing None as service name."""
        params = service_mapper.get_service_params(None)
        self.assertIsNone(params)

    def test_lazy_loading_behavior(self):
        """Test that mappings are loaded lazily on first call."""
        service_mapper._service_mappings = None  # Ensure it's not loaded
        self.assertIsNone(service_mapper._service_mappings)
        service_mapper.get_service_params("http")  # This call should trigger _load_mappings
        self.assertIsNotNone(service_mapper._service_mappings)
        self.assertTrue(len(service_mapper._service_mappings) > 0)  # Check it loaded something

    # More advanced tests could involve mocking `open` to simulate
    # FileNotFoundError or JSONDecodeError during _load_mappings.
    # For now, we assume a valid services.json exists for these tests.


if __name__ == '__main__':
    # This allows running the tests directly from this file
    unittest.main()