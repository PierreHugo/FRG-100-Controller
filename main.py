"""
main.py
-------
Point d'entrée du FRG-100 Controller.

Usage :
    python main.py
"""

import logging
from gui.app import FRG100App

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s : %(message)s",
)

if __name__ == "__main__":
    app = FRG100App()
    app.mainloop()
