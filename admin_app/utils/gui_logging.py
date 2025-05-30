import logging
import sys
from PyQt6.QtCore import QObject, pyqtSignal

# --- QtLogHandler ---
class QtLogHandler(logging.Handler, QObject):
    log_signal = pyqtSignal(str)

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)

    def emit(self, record):
        try:
            msg = self.format(record)
            # noinspection PyUnresolvedReferences
            self.log_signal.emit(msg)
        except Exception:
            self.handleError(record)

# --- StreamRedirector ---
class StreamRedirector(QObject):
    write_signal = pyqtSignal(str)

    def __init__(self, stream_name):
        super().__init__()
        self.stream_name = stream_name

    def write(self, text):
        if text.strip():
            # noinspection PyUnresolvedReferences
            self.write_signal.emit(f"[{self.stream_name}] {text.strip()}")

    def flush(self):
        pass

# --- Setup Function ---
def setup_gui_logging(log_view_append_slot):
    """
    Configures and connects Qt-specific logging.
    Returns stdout_redirector, stderr_redirector, and the log_handler.
    """
    log_handler = QtLogHandler()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(name)s] %(message)s', datefmt='%H:%M:%S')
    log_handler.setFormatter(formatter)

    # Add handler to the loggers we want to capture
    loggers_to_capture = [
        "admin_connect", "policy_engine", "service_mapper",
        "nlp", "alias_manager"
    ]
    for logger_name in loggers_to_capture:
        logger = logging.getLogger(logger_name)
        logger.addHandler(log_handler)
        logger.setLevel(logging.INFO) # Set default level for these loggers

    stdout_redirector = StreamRedirector('stdout')
    stderr_redirector = StreamRedirector('stderr')

    # Connect signals to the log view's append method
    log_handler.log_signal.connect(log_view_append_slot)
    stdout_redirector.write_signal.connect(log_view_append_slot)
    stderr_redirector.write_signal.connect(log_view_append_slot)

    # Redirect stdout/stderr
    sys.stdout = stdout_redirector
    sys.stderr = stderr_redirector

    return stdout_redirector, stderr_redirector, log_handler