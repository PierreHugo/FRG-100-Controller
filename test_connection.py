"""
test_connection.py
------------------
Script de test en ligne de commande pour vérifier la communication
série avec le FRG-100 avant de lancer l'interface graphique.

Usage :
    python test_connection.py
    python test_connection.py --port COM3
    python test_connection.py --port COM26 --freq 7100000 --mode USB
"""

import argparse
import logging
import sys
import time

# On configure les logs pour voir ce qui se passe dans cat.py
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s : %(message)s",
)

from frg100 import CATConnection, CATError
from frg100 import set_frequency, set_mode, read_smeter, read_status, lock
from frg100.config import DEFAULT_PORT


def test_connection(port: str) -> bool:
    """Tente d'ouvrir le port série. Retourne True si OK."""
    print(f"\n{'='*50}")
    print(f"  TEST 1 — Ouverture du port {port}")
    print(f"{'='*50}")
    try:
        with CATConnection(port) as cat:
            print(f"  ✓ Port {port} ouvert avec succès")
            print(f"    Baudrate : 4800 | 8N2 (sans parité, 2 stop bits)")
        return True
    except CATError as e:
        print(f"  ✗ Échec : {e}")
        print()
        print("  Pistes de résolution :")
        print("  - Vérifiez que l'appareil est allumé")
        print("  - Vérifiez le port dans le Gestionnaire de périphériques")
        print("  - Essayez : python test_connection.py --port COM3")
        return False


def test_frequency(cat: CATConnection, freq_hz: int) -> None:
    """Envoie une commande Set Frequency et vérifie visuellement."""
    freq_mhz = freq_hz / 1_000_000
    print(f"\n  → Syntonisation sur {freq_mhz:.3f} MHz ...", end=" ")
    try:
        set_frequency(cat, freq_hz)
        print("✓ Commande envoyée")
        print(f"    Vérifiez que l'afficheur du FRG-100 indique {freq_mhz:.3f} MHz")
    except CATError as e:
        print(f"✗ Erreur : {e}")


def test_mode(cat: CATConnection, mode: str) -> None:
    """Envoie une commande Mode."""
    print(f"\n  → Mode {mode} ...", end=" ")
    try:
        set_mode(cat, mode)
        print("✓ Commande envoyée")
    except CATError as e:
        print(f"✗ Erreur : {e}")


def test_smeter(cat: CATConnection) -> None:
    """Tente de lire le S-Mètre."""
    print(f"\n  → Lecture S-Mètre ...", end=" ")
    try:
        value = read_smeter(cat)
        print(f"✓ Valeur brute : {value}")
    except CATError as e:
        print(f"✗ Erreur (normal si le FRG-100 ne répond pas encore) : {e}")


def test_lock_unlock(cat: CATConnection) -> None:
    """Test verrouillage/déverrouillage du panneau."""
    print(f"\n  → Verrouillage panneau ...", end=" ")
    try:
        lock(cat, True)
        print("✓  (panneau verrouillé)", end="")
        time.sleep(1)
        lock(cat, False)
        print(" → déverrouillé ✓")
    except CATError as e:
        print(f"✗ Erreur : {e}")


def run_all_tests(port: str, freq_hz: int, mode: str) -> None:

    # Test 1 : ouverture du port
    if not test_connection(port):
        sys.exit(1)

    # Tests 2–5 : commandes réelles
    print(f"\n{'='*50}")
    print(f"  TESTS 2–5 — Commandes CAT")
    print(f"{'='*50}")

    try:
        with CATConnection(port) as cat:
            test_frequency(cat, freq_hz)
            time.sleep(0.2)

            test_mode(cat, mode)
            time.sleep(0.2)

            test_smeter(cat)
            time.sleep(0.2)

            test_lock_unlock(cat)

    except CATError as e:
        print(f"\n  ✗ Erreur de connexion pendant les tests : {e}")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"  Tests terminés.")
    print(f"  Si les commandes ont été envoyées (✓) mais que l'appareil")
    print(f"  n'a pas réagi, vérifiez le câblage du port CAT arrière.")
    print(f"{'='*50}\n")


# ------------------------------------------------------------------
# Point d'entrée
# ------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test de connexion CAT avec le Yaesu FRG-100"
    )
    parser.add_argument(
        "--port", default=DEFAULT_PORT,
        help=f"Port série (défaut : {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--freq", type=int, default=14_250_000,
        help="Fréquence de test en Hz (défaut : 14250000 = 14.250 MHz)"
    )
    parser.add_argument(
        "--mode", default="USB",
        help="Mode de réception (défaut : USB)"
    )
    args = parser.parse_args()

    run_all_tests(args.port, args.freq, args.mode)
