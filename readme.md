# Intent-Based Networking (IBN) Controller & Device Agent

This project demonstrates a simplified Intent-Based Networking system. It consists of an **Admin Controller GUI** that allows administrators to express network policy intents in natural language, and a **Device Agent** designed to run on Raspberry Pi devices (or other Linux systems) to receive and apply these policies as `iptables` firewall rules.

## Project Concept

The core idea of IBN is to abstract away the complexities of low-level network configuration. Instead of manually crafting `iptables` rules, an administrator can state their intent, such as:

*   "On DeviceA deny ssh from 192.168.1.100"
*   "Allow http to WebServer from any"
*   "Block all traffic from MaliciousIP on Gateway"

This system then:
1.  **Parses** the natural language intent.
2.  **Translates** it into specific `iptables` commands.
3.  **Dispatches** these commands to the target device(s).
4.  Allows **previewing** of generated commands before deployment.

## Features

**Admin Controller:**
*   **Graphical User Interface (PyQt6):** For managing connections and policies.
*   **Device Discovery:** Discovers devices on the network via UDP broadcasts.
*   **TCP Command Channel:** Establishes TCP connections to discovered devices for sending commands.
*   **Natural Language Processing (NLP):** Uses spaCy to parse policy intents expressed in English.
*   **Alias Management:** Assign friendly names (aliases) to IP addresses for easier intent expression (e.g., "WebServer" instead of "192.168.0.5").
*   **Policy Engine:**
    *   Interprets parsed NLP rules to determine target devices and `iptables` chains (INPUT, OUTPUT, FORWARD).
    *   Resolves service names (e.g., "ssh", "http") to specific ports and protocols using `services.json`.
    *   Constructs `iptables` command strings.
*   **Preview & Deploy:** Allows administrators to preview generated `iptables` commands before sending them to devices.
*   **Live Logging:** Displays logs from various components directly in the GUI.

**Device Agent:**
*   **Discovery Listener:** Listens for UDP discovery broadcasts from the Admin Controller.
*   **TCP Connection to Admin:** Connects back to the Admin Controller upon discovery.
*   **Command Reception:** Receives `iptables` command strings over the TCP connection.
*   **Command Execution:**
    *   Validates received commands (basic sanitization).
    *   Executes `iptables` commands using `sudo` (requires pre-configuration on the device).
*   **Console Logging:** Prints received commands and execution status.

## Setup and Installation

**Prerequisites:**
*   Python 3.8+
*   `pip` (Python package installer)
*   On the machine running the Admin Controller:
    *   `PyQt6` for the GUI.
    *   `spacy` and the `en_core_web_sm` model for NLP.
*   On the Raspberry Pi / Target Device:
    *   `iptables` command-line utility.
    *   `sudo` configured for passwordless execution of `iptables` by the user running the device agent.

**Installation Steps:**

1.  **Navigate to your project's root directory** (the one containing `admin_app/`, `backend/`, etc.).
    ```bash
    cd path/to/your/project_root
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python -m venv .venv
    # Windows
    .\.venv\Scripts\activate
    # macOS/Linux
    source .venv/bin/activate
    ```

3.  **Install Python dependencies for Admin Controller:**
    (Ensure your terminal is in the project root directory and the virtual environment is active)
    ```bash
    pip install PyQt6 spacy
    python -m spacy download en_core_web_sm
    ```

4.  **Configure Raspberry Pi / Target Device:**
    *   Ensure `iptables` is installed.
    *   Configure passwordless `sudo` for `iptables`:
        1.  Run `sudo visudo` on the Pi.
        2.  Add the line (replace `pi` with your username and verify the path to `iptables` with `which iptables`, common paths are `/usr/sbin/iptables` or `/sbin/iptables`):
            ```
            pi ALL=(ALL) NOPASSWD: /usr/sbin/iptables
            ```
        3.  Save and exit.
    *   Copy the `device_app/` directory (containing `device.py`, `network_handler.py`, `command_executor.py`, and `__init__.py`) to the Pi.
    *   Verify the `IPTABLES_PATH` constant in `device_app/command_executor.py` matches the output of `which iptables` on the Pi.

## Usage

1.  **Start the Admin Controller:**
    *   Navigate to your project's root directory in your terminal.
    *   Ensure your virtual environment is activated.
    *   Run:
        ```bash
        python -m admin_app.admin
        ```
    *   Click "Start Server" in the GUI. This initiates device discovery.

2.  **Start the Device Agent on Raspberry Pi(s):**
    *   SSH into your Raspberry Pi.
    *   Navigate to the directory where you placed the `device_app/` package (e.g., if `device_app` is in `/home/pi/my_project/`, then `cd /home/pi/my_project/`).
    *   Run:
        ```bash
        python -m device_app.device
        ```
    *   The device agent will listen for discovery broadcasts and connect to the admin controller. Connected devices will appear in the Admin GUI.

3.  **Define and Deploy Policies:**
    *   In the Admin GUI, select a target device from the list if your intent isn't explicit about the target (e.g., "on DeviceX..."). The selected device will be preferred if the NLP doesn't find an explicit target.
    *   Type your natural language policy in the "Policy Command(s)" field (e.g., `on MyPi deny ssh from 10.0.0.5`).
    *   Click "Parse & Preview" to see the generated `iptables` commands.
    *   If satisfied, click "Send Policy" to deploy the commands to the target device.

## Key Project Modules

(The descriptions of the modules remain the same, only the understanding of their location relative to the project root changes.)

*   **`admin_app/` (Package):** Contains all code for the Admin GUI application, including UI setup, managers for different GUI sections, and GUI-specific logic.
    *   `admin.py`: Main `QMainWindow` and orchestrator for the GUI.
*   **`backend/` (Package):** Houses the core logic for processing intents and generating network commands.
    *   `admin_connect.py`: Admin-side network discovery and TCP server.
    *   `nlp.py`: Parses natural language.
    *   `alias_manager.py`: Manages IP-to-alias mappings.
    *   `service_mapper.py` (and `services.json`): Define and map service names to ports/protocols.
    *   `policy_engine.py`: Orchestrates the NLP rule to `iptables` command translation, using components from:
    *   `policy_components/`: Sub-modules for rule interpretation and `iptables` command construction.
*   **`device_app/` (Package):** Contains all code for the device-side agent.
    *   `device.py`: Main runner for the device agent.
    *   `network_handler.py`: Device-side UDP listening and TCP client connection.
    *   `command_executor.py`: Validates and executes received `iptables` commands on the device.

## Future Enhancements / Considerations

*   **Enhanced Security:** Implement TLS/SSL, device authentication, and more robust command sanitization.
*   **Two-Way Communication:** Device status/acknowledgment back to the admin.
*   **Policy Persistence & State Management:** Store applied policies and device states.
*   **More Complex NLP:** Support for logical operators, time-based rules, etc.
*   **Rule Deletion/Modification:** Allow intents to remove or modify existing rules.
*   **Configuration Files:** Externalize settings like ports and paths.

## Troubleshooting

*   **`ModuleNotFoundError`:**
    *   Ensure you are running commands from your project's root directory (the one containing `admin_app/`, `backend/`).
    *   Make sure your Python virtual environment (if used) is activated.
    *   Verify that all package directories (`admin_app`, `backend`, `device_app`, and their subdirectories like `policy_components`) have an `__init__.py` file.
*   **Device Not Discovered:** Check network connectivity and firewall settings on both admin and device machines. Ensure they are on the same network segment that allows UDP broadcasts.
*   **`iptables` Execution Errors on Pi:**
    *   Double-check the `IPTABLES_PATH` in `device_app/command_executor.py`.
    *   Confirm that passwordless `sudo` for `iptables` is correctly configured for the user running the `device_app.device` script. Test this manually on the Pi with `sudo /path/to/iptables -L`.
    *   Review the device agent's console logs for detailed error messages from `subprocess`.
*   **NLP Model Not Found (`en_core_web_sm`):** Ensure you have run `python -m spacy download en_core_web_sm` in the Python environment used by the Admin Controller.