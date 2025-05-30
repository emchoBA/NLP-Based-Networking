import subprocess
import re
import logging

log = logging.getLogger(__name__)

# --- Command Execution Constants ---
# You MUST verify this path on your Raspberry Pi using 'which iptables'
IPTABLES_PATH = "/usr/sbin/iptables"
# Basic sanitization: allows letters, numbers, spaces, '.', '-', '/', '=', ':' (for ports), '*' (for any interface/IP)
# This is a basic measure. Robust sanitization for iptables is complex.
ALLOWED_IPTABLES_CHARS_PATTERN = re.compile(r"^[a-zA-Z0-9\s\.\-\/\=\:\*]+$")


def execute_firewall_command(command_string: str) -> tuple[bool, str]:
    """
    Validates and executes a firewall command string (expected to be iptables).

    Args:
        command_string: The command string to execute.

    Returns:
        A tuple (success: bool, output_message: str).
    """
    log.info(f"[CmdExec] Attempting to execute: {command_string}")

    # 1. Basic Validation: Must start with "iptables " (note the space)
    if not command_string.startswith("iptables "):
        msg = "Command does not start with 'iptables '."
        log.error(f"[CmdExec Validation] {msg}")
        return False, msg

    # 2. Basic Character Sanitization
    actual_command_args = command_string[len("iptables "):]
    if not ALLOWED_IPTABLES_CHARS_PATTERN.match(actual_command_args):
        msg = f"Command arguments contain disallowed characters: '{actual_command_args}'"
        log.error(f"[CmdExec Validation] {msg}")
        return False, msg

    # 3. Prepare command for subprocess
    try:
        cmd_list = ['sudo', IPTABLES_PATH] + actual_command_args.split()
        log.debug(f"[CmdExec] Prepared command list: {cmd_list}")
    except Exception as e:
        msg = f"Error preparing command list: {e}"
        log.exception(f"[CmdExec Preparation Error]") # Log with traceback
        return False, msg

    # 4. Execute the command
    try:
        result = subprocess.run(cmd_list, capture_output=True, text=True, check=False, timeout=15)

        if result.returncode == 0:
            output_msg = result.stdout.strip() if result.stdout else "Command executed successfully (no stdout)."
            log.info(f"[CmdExec Success] {output_msg}")
            return True, output_msg
        else:
            error_details = f"Return code: {result.returncode}."
            if result.stdout: # Sometimes errors also print to stdout
                error_details += f" Stdout: {result.stdout.strip()}."
            if result.stderr:
                error_details += f" Stderr: {result.stderr.strip()}."
            log.error(f"[CmdExec Failed] {error_details}")
            return False, error_details

    except FileNotFoundError:
        msg = f"Error: '{IPTABLES_PATH}' or 'sudo' not found. Ensure paths are correct and sudo is installed."
        log.critical(f"[CmdExec FileNotFoundError] {msg}") # More critical
        return False, msg
    except subprocess.TimeoutExpired:
        msg = "Error: Command execution timed out."
        log.error(f"[CmdExec Timeout] {msg}")
        return False, msg
    except Exception as e:
        msg = f"An unexpected error occurred during command execution: {e}"
        log.exception(f"[CmdExec Unexpected Error]") # Log with traceback
        return False, msg