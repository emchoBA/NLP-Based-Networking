import sys
from PyQt6.QtWidgets import QApplication # Keep Qt import here or in admin.py

from admin_app.admin import AdminGUI

from backend import admin_connect, policy_engine, service_mapper, alias_manager, nlp
import logging


if __name__ == "__main__":
    # Basic logging setup for the main application itself, if not captured by Qt handler
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - [%(name)s] %(message)s',
                        datefmt='%H:%M:%S')

    # Ensure backend modules are available (similar to what was in admin.py's __main__)
    if not all([admin_connect, policy_engine, service_mapper, nlp, alias_manager]):
        logging.critical("Essential backend modules failed to load from main.py. Exiting application.")
        # You might want a QMessageBox here if QApplication is already running or can be started
        sys.exit(1)


    if not QApplication.instance():
        app = QApplication(sys.argv)
    else:
        app = QApplication.instance()

    main_window = AdminGUI()
    main_window.show()
    sys.exit(app.exec())