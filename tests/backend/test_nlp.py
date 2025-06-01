# tests/backend/test_nlp.py

import unittest
import sys
import os
import logging  # To potentially silence or check logs from nlp.py if needed
from unittest.mock import patch, call
# Add the parent directory of 'backend' to the Python path
# This allows us to import modules from the 'backend' package
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(
    os.path.dirname(current_dir))  # Go up two levels (tests/backend -> tests -> project_root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Now import from the backend package
from backend import nlp
from backend import alias_manager


class TestNLPPreprocessing(unittest.TestCase):

    def setUp(self):
        """
        Set up for each test. Clear any existing aliases to ensure test isolation.
        """
        alias_manager._aliases_to_ip.clear()
        alias_manager._ip_to_aliases.clear()

        # Optional: Configure logging for nlp.py if you want to suppress or check its output during tests
        # For example, to suppress INFO logs from nlp.py during these specific tests:
        # self.nlp_logger_preprocess = logging.getLogger('backend.nlp') # Use a different attribute name
        # self.original_level_preprocess = self.nlp_logger_preprocess.level
        # self.nlp_logger_preprocess.setLevel(logging.WARNING) # Suppress INFO and DEBUG

    def tearDown(self):
        """
        Clean up after each test if necessary.
        """
        # If you changed logging levels in setUp:
        # if hasattr(self, 'nlp_logger_preprocess') and hasattr(self, 'original_level_preprocess'):
        #     self.nlp_logger_preprocess.setLevel(self.original_level_preprocess)
        pass

    def test_text_cleaning(self):
        """Test basic text cleaning: lowercase, strip, space normalization, comma removal."""
        raw_text = "  Allow SSH,  From  DeviceA  "
        expected_cleaned = "allow ssh from devicea"
        # Test cleaning without any aliases defined
        processed_text = nlp.preprocess_and_resolve_aliases(raw_text)
        self.assertEqual(processed_text, expected_cleaned)

        raw_text_2 = "DenyALL HTTP"
        expected_cleaned_2 = "denyall http"
        processed_text_2 = nlp.preprocess_and_resolve_aliases(raw_text_2)
        self.assertEqual(processed_text_2, expected_cleaned_2)

    def test_alias_resolution_simple(self):
        """Test alias resolution with a single, simple alias."""
        alias_manager.add_alias("192.168.1.10", "WebServer")
        raw_text = "allow http to WebServer"
        expected_processed = "allow http to 192.168.1.10"
        processed_text = nlp.preprocess_and_resolve_aliases(raw_text)
        self.assertEqual(processed_text, expected_processed)

    def test_alias_resolution_multiple_aliases(self):
        """Test alias resolution with multiple different aliases in the text."""
        alias_manager.add_alias("10.0.0.1", "Gateway")
        alias_manager.add_alias("10.0.0.5", "UserPC")
        raw_text = "deny all from UserPC to Gateway"
        expected_processed = "deny all from 10.0.0.5 to 10.0.0.1"
        processed_text = nlp.preprocess_and_resolve_aliases(raw_text)
        self.assertEqual(processed_text, expected_processed)

    def test_alias_resolution_case_insensitivity_in_text(self):
        """Test that aliases in text are resolved regardless of their case."""
        alias_manager.add_alias("172.16.0.1", "FirewallDevice")  # Alias stored as 'firewalldevice'
        raw_text = "on FIREWALLDEVICE block http"
        expected_processed = "on 172.16.0.1 block http"
        processed_text = nlp.preprocess_and_resolve_aliases(raw_text)
        self.assertEqual(processed_text, expected_processed)

    def test_alias_resolution_with_no_matching_aliases(self):
        """Test text processing when defined aliases don't match any text."""
        alias_manager.add_alias("192.168.1.10", "UnusedAlias")
        raw_text = "allow ssh from SomeOtherDevice"
        expected_processed = "allow ssh from someotherdevice"  # Only cleaning should occur
        processed_text = nlp.preprocess_and_resolve_aliases(raw_text)
        self.assertEqual(processed_text, expected_processed)

    def test_alias_resolution_with_no_aliases_defined(self):
        """Test text processing when no aliases are defined in alias_manager."""
        # setUp already clears aliases
        raw_text = "allow ssh from DeviceAlpha to DeviceBeta"
        expected_processed = "allow ssh from devicealpha to devicebeta"
        processed_text = nlp.preprocess_and_resolve_aliases(raw_text)
        self.assertEqual(processed_text, expected_processed)

    def test_alias_resolution_overlapping_aliases(self):
        """Test correct resolution when aliases might overlap (longer should take precedence)."""
        alias_manager.add_alias("10.0.0.10", "Server")
        alias_manager.add_alias("10.0.0.20", "Main Server")  # Longer, should be checked first

        raw_text_1 = "connect to Main Server"
        expected_1 = "connect to 10.0.0.20"
        processed_1 = nlp.preprocess_and_resolve_aliases(raw_text_1)
        self.assertEqual(processed_1, expected_1)

        raw_text_2 = "connect to Server"  # Should match the shorter "Server"
        expected_2 = "connect to 10.0.0.10"
        processed_2 = nlp.preprocess_and_resolve_aliases(raw_text_2)
        self.assertEqual(processed_2, expected_2)

        raw_text_3 = "block Main Server and also ServiceX"
        expected_3 = "block 10.0.0.20 and also servicex"
        processed_3 = nlp.preprocess_and_resolve_aliases(raw_text_3)
        self.assertEqual(processed_3, expected_3)

    def test_alias_resolution_with_punctuation_around_alias(self):
        """Test alias resolution when aliases are adjacent to punctuation (after cleaning)."""
        alias_manager.add_alias("192.168.5.5", "Printer")
        raw_text = "allow access to Printer, from any"
        expected_processed = "allow access to 192.168.5.5 from any"
        processed_text = nlp.preprocess_and_resolve_aliases(raw_text)
        self.assertEqual(processed_text, expected_processed)

    def test_empty_string_input(self):
        """Test preprocessing with an empty string."""
        self.assertEqual(nlp.preprocess_and_resolve_aliases(""), "")
        self.assertEqual(nlp.preprocess_and_resolve_aliases("   "), "")


class TestNLPParseSingle(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """
        Load NLP model once for all tests in this class if not already loaded by nlp.py.
        Configure logging for nlp.py to DEBUG to see detailed parsing steps.
        """
        if not nlp.nlp_model:
            print(f"WARNING: spaCy model (nlp.nlp_model) not loaded prior to TestNLPParseSingle. "
                  f"nlp.py should handle lazy loading if possible. Tests may fail if model remains unavailable.")
            # Attempting to use any nlp_model dependent function here would trigger its load if lazy loaded.
            # For example, nlp.nlp_model("test") would do it.
            # But it's better if nlp.py's import or first use handles this.

        cls.nlp_logger = logging.getLogger('backend.nlp')  # As defined in nlp.py
        cls.original_level = cls.nlp_logger.level
        cls.nlp_logger.setLevel(logging.DEBUG)

        # Add a handler if running this test file directly and nlp.py's logger has no handlers
        if not cls.nlp_logger.hasHandlers() or \
                not any(
                    isinstance(h, logging.StreamHandler) and h.stream == sys.stdout for h in cls.nlp_logger.handlers):
            # Check if we ALREADY have a stdout handler to avoid duplicates if tests are run multiple times in same session
            cls.test_handler_added = True  # Flag that we added it
            console_handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            cls.nlp_logger.addHandler(console_handler)
            cls.nlp_logger.propagate = False  # Prevent double logging to root
        else:
            cls.test_handler_added = False

    @classmethod
    def tearDownClass(cls):
        """Restore original logging level after all tests in this class."""
        if hasattr(cls, 'nlp_logger') and hasattr(cls, 'original_level'):
            cls.nlp_logger.setLevel(cls.original_level)
        if hasattr(cls, 'test_handler_added') and cls.test_handler_added:
            # Attempt to remove the handler we added
            for handler in cls.nlp_logger.handlers[:]:  # Iterate over a copy
                if isinstance(handler,
                              logging.StreamHandler) and handler.formatter._fmt == '%(asctime)s - %(name)s - %(levelname)s - %(message)s':
                    cls.nlp_logger.removeHandler(handler)
                    break  # Assuming we only added one such handler
            cls.nlp_logger.propagate = True

    def setUp(self):
        """Clear aliases before each test and check for NLP model."""
        alias_manager._aliases_to_ip.clear()
        alias_manager._ip_to_aliases.clear()
        if not nlp.nlp_model:
            self.skipTest("SpaCy NLP model (nlp.nlp_model) not loaded, skipping parse_single tests.")

    # --- Action Verb Tests ---
    def test_parse_single_action_verb_simple(self):
        result = nlp.parse_single("deny ssh from 1.2.3.4")
        self.assertEqual(result.get("action"), "deny")

    def test_parse_single_action_verb_different_verb(self):
        result = nlp.parse_single("allow http to 1.2.3.5")
        self.assertEqual(result.get("action"), "allow")

    def test_parse_single_action_verb_at_end(self):
        result = nlp.parse_single("from 1.2.3.4 allow ssh")
        self.assertEqual(result.get("action"), "allow")
        result_multi = nlp.parse_single("deny http but allow ssh")
        self.assertEqual(result_multi.get("action"), "allow")

    def test_parse_single_no_action_verb(self):
        result = nlp.parse_single("ssh from 1.2.3.4")
        self.assertEqual(result, {}, "Should return empty dict if no action verb")

    # --- Service Identification Tests ---
    def test_parse_single_service_after_action(self):
        result = nlp.parse_single("block ftp to 2.3.4.5")
        self.assertEqual(result.get("service"), "ftp")

    def test_parse_single_service_before_action(self):
        result = nlp.parse_single("http allow from 3.4.5.6")
        self.assertEqual(result.get("service"), "http")

    def test_parse_single_service_with_skippable_words(self):
        result = nlp.parse_single("deny all incoming ssh traffic from 1.1.1.1")
        self.assertEqual(result.get("service"), "ssh")
        result2 = nlp.parse_single("permit any outgoing traffic for service dns to 8.8.8.8")
        self.assertEqual(result2.get("service"), "dns")

    def test_parse_single_no_specific_service_defaults_to_any(self):
        result = nlp.parse_single("block 1.2.3.4")
        self.assertEqual(result.get("service"), "any")
        result2 = nlp.parse_single("allow from 1.2.3.5 to 1.2.3.6")
        self.assertEqual(result2.get("service"), "any")

    # --- IP Role Assignment Tests ---
    def test_parse_single_source_ip_only(self):
        result = nlp.parse_single("deny ssh from 10.0.0.1")
        self.assertEqual(result.get("source_ip"), "10.0.0.1")
        self.assertIsNone(result.get("destination_ip"))
        self.assertEqual(result.get("target_device_ip"), "10.0.0.1")

    def test_parse_single_destination_ip_only(self):
        result = nlp.parse_single("allow http to 10.0.0.2")
        self.assertIsNone(result.get("source_ip"))
        self.assertEqual(result.get("destination_ip"), "10.0.0.2")
        self.assertEqual(result.get("target_device_ip"), "10.0.0.2")

    def test_parse_single_source_and_destination_ips(self):
        result = nlp.parse_single("block ftp from 10.0.0.3 to 10.0.0.4")
        self.assertEqual(result.get("source_ip"), "10.0.0.3")
        self.assertEqual(result.get("destination_ip"), "10.0.0.4")
        self.assertEqual(result.get("target_device_ip"), "10.0.0.4")

    def test_parse_single_explicit_target_device_ip(self):
        result = nlp.parse_single("on 192.168.1.1 deny ssh from 10.0.0.5")
        self.assertEqual(result.get("target_device_ip"), "192.168.1.1")
        self.assertEqual(result.get("source_ip"), "10.0.0.5")
        self.assertIsNone(result.get("destination_ip"))

    def test_parse_single_explicit_target_with_source_and_dest(self):
        result = nlp.parse_single("on 192.168.1.1 allow http from 10.0.0.6 to 10.0.0.7")
        self.assertEqual(result.get("target_device_ip"), "192.168.1.1")
        self.assertEqual(result.get("source_ip"), "10.0.0.6")
        self.assertEqual(result.get("destination_ip"), "10.0.0.7")

    def test_parse_single_no_ips_no_explicit_target_fails(self):
        result = nlp.parse_single("block ssh")
        self.assertEqual(result, {}, "Should fail if no IPs and no explicit target")

    def test_parse_single_one_ip_no_preposition(self):
        result = nlp.parse_single("block 1.2.3.4")
        self.assertEqual(result.get("source_ip"), "1.2.3.4")
        self.assertIsNone(result.get("destination_ip"))
        self.assertEqual(result.get("target_device_ip"), "1.2.3.4")

    # --- Combined and Edge Cases ---
    def test_parse_single_full_sentence_ip_resolved(self):
        result = nlp.parse_single("on 192.168.1.50 deny tcp from 10.0.0.10 to 10.0.0.11")
        self.assertEqual(result.get("action"), "deny")
        self.assertEqual(result.get("service"), "tcp")
        self.assertEqual(result.get("target_device_ip"), "192.168.1.50")
        self.assertEqual(result.get("source_ip"), "10.0.0.10")
        self.assertEqual(result.get("destination_ip"), "10.0.0.11")

    def test_parse_single_empty_input(self):
        result = nlp.parse_single("")
        self.assertEqual(result, {})
        result_space = nlp.parse_single("   ")
        self.assertEqual(result_space, {})


class TestNLPParseCommandsOrchestration(unittest.TestCase):

    def setUp(self):
        """
        Ensure nlp_model is available, otherwise skip tests that depend on it.
        """
        if not nlp.nlp_model:
            self.skipTest("SpaCy NLP model (nlp.nlp_model) not loaded, skipping parse_commands orchestration tests.")

    @patch('backend.nlp.parse_single')  # Mock parse_single within the nlp module
    @patch('backend.nlp.preprocess_and_resolve_aliases')  # Mock preprocess_and_resolve_aliases
    def test_parse_commands_single_sentence(self, mock_preprocess, mock_parse_single):
        """Test parse_commands with a single sentence input."""
        raw_text = "deny ssh from 1.2.3.4"
        preprocessed_text = "deny ssh from 1.2.3.4"  # Assume preprocess returns this
        mock_preprocess.return_value = preprocessed_text

        # Make parse_single return a known dummy dictionary
        dummy_parsed_intent = {"action": "deny", "service": "ssh", "source_ip": "1.2.3.4"}
        mock_parse_single.return_value = dummy_parsed_intent

        result = nlp.parse_commands(raw_text)

        mock_preprocess.assert_called_once_with(raw_text)
        mock_parse_single.assert_called_once_with(
            preprocessed_text)  # spaCy might slightly change text, but for one sentence, it's usually the same
        self.assertEqual(result, [dummy_parsed_intent])

    @patch('backend.nlp.parse_single')
    @patch('backend.nlp.preprocess_and_resolve_aliases')
    def test_parse_commands_multiple_sentences(self, mock_preprocess, mock_parse_single):
        """Test parse_commands with multiple sentences, ensuring parse_single is called for each."""
        raw_text = "allow http to serverA. deny ftp from clientB."
        preprocessed_text = "allow http to servera. deny ftp from clientb."  # Example preprocessed
        mock_preprocess.return_value = preprocessed_text

        # Define what parse_single should return for each call
        # Note: spaCy's sentence splitter is quite good.
        # The exact text of sentences after spaCy's processing might have subtle differences
        # if punctuation or casing was odd. For this test, we assume clean sentences.
        sentence1_text = "allow http to servera."  # This is what spaCy's senter might yield
        sentence2_text = "deny ftp from clientb."

        dummy_intent1 = {"action": "allow", "service": "http", "target_device_ip": "servera"}
        dummy_intent2 = {"action": "deny", "service": "ftp", "source_ip": "clientb"}

        # Configure mock_parse_single to return different values for sequential calls
        mock_parse_single.side_effect = [dummy_intent1, dummy_intent2]

        result = nlp.parse_commands(raw_text)

        mock_preprocess.assert_called_once_with(raw_text)

        # Check calls to parse_single
        # We need to be careful here, spaCy's `sent.text` might be slightly different from
        # our manually defined sentence1_text and sentence2_text if the original preprocessed_text
        # had leading/trailing spaces for sentences after splitting, etc.
        # A more robust check is the number of calls and the sequence of returns.
        self.assertEqual(mock_parse_single.call_count, 2)

        # To assert specific calls if spaCy's sentence splitting is perfectly predictable:
        # calls = [call(sentence1_text), call(sentence2_text)] # This can be fragile
        # mock_parse_single.assert_has_calls(calls, any_order=False)

        self.assertEqual(result, [dummy_intent1, dummy_intent2])

    @patch('backend.nlp.parse_single')
    @patch('backend.nlp.preprocess_and_resolve_aliases')
    def test_parse_commands_empty_input(self, mock_preprocess, mock_parse_single):
        """Test parse_commands with empty string input."""
        raw_text = ""
        preprocessed_text = ""
        mock_preprocess.return_value = preprocessed_text

        # parse_single should not be called if there are no sentences
        # spaCy on an empty string yields a doc with 0 sents.

        result = nlp.parse_commands(raw_text)

        mock_preprocess.assert_called_once_with(raw_text)
        mock_parse_single.assert_not_called()
        self.assertEqual(result, [])

    @patch('backend.nlp.parse_single')
    @patch('backend.nlp.preprocess_and_resolve_aliases')
    def test_parse_commands_one_sentence_parse_single_returns_empty(self, mock_preprocess, mock_parse_single):
        """Test when parse_single returns an empty dict (invalid clause)."""
        raw_text = "this is an unparsable sentence."
        preprocessed_text = "this is an unparsable sentence."
        mock_preprocess.return_value = preprocessed_text
        mock_parse_single.return_value = {}  # Simulate parse_single failing for this sentence

        result = nlp.parse_commands(raw_text)

        mock_preprocess.assert_called_once_with(raw_text)
        mock_parse_single.assert_called_once()  # It should still be called once
        self.assertEqual(result, [])  # parse_commands should filter out empty results

    @patch('backend.nlp.parse_single')
    @patch('backend.nlp.preprocess_and_resolve_aliases')
    def test_parse_commands_mixed_valid_invalid_clauses(self, mock_preprocess, mock_parse_single):
        """Test with multiple sentences where some are valid and some are not."""
        raw_text = "allow ssh. this is garbage. deny http."
        preprocessed_text = "allow ssh. this is garbage. deny http."  # Assume this for simplicity
        mock_preprocess.return_value = preprocessed_text

        valid_intent1 = {"action": "allow", "service": "ssh"}
        invalid_intent_result = {}  # parse_single returns empty for the garbage sentence
        valid_intent2 = {"action": "deny", "service": "http"}

        mock_parse_single.side_effect = [valid_intent1, invalid_intent_result, valid_intent2]

        result = nlp.parse_commands(raw_text)

        mock_preprocess.assert_called_once_with(raw_text)
        self.assertEqual(mock_parse_single.call_count, 3)
        self.assertEqual(result, [valid_intent1, valid_intent2])  # Only valid intents should be in the final list


if __name__ == '__main__':
    # This allows running all tests defined in this file when executing it directly.
    unittest.main()