"""
frg100/config.py
----------------
Configuration par défaut. Modifier ici le port COM si nécessaire.
"""

# Port série sur lequel le FRG-100 est détecté (adaptateur USB-série)
DEFAULT_PORT = "COM26"

# Plage de fréquences du FRG-100 (Hz)
FREQ_MIN_HZ = 50_000       # 50 kHz
FREQ_MAX_HZ = 30_000_000   # 30 MHz
