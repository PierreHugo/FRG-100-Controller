"""
test_connection.py
------------------
Script de test en ligne de commande pour vérifier la communication
série avec le FRG-100 avant de lancer l'interface graphique.

Usage :
    python test_connection.py
    python test_connection.py --port COM26
    python test_connection.py --port COM26 --freq 7000000 --mode AM
"""

import argparse
import logging
import sys
import time

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s : %(message)s",
)

from frg100 import CATConnection, CATError
from frg100 import (
    set_frequency, set_mode, lock,
    step_up, step_down, step_fine,
    read_smeter, freq_to_bcd,
)
from frg100.config import DEFAULT_PORT


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def ok(msg: str) -> None:
    print(f"  ✓ {msg}")

def fail(msg: str) -> None:
    print(f"  ✗ {msg}")

def section(title: str) -> None:
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")


# ------------------------------------------------------------------
# Tests individuels
# ------------------------------------------------------------------

def test_ouverture_port(port: str) -> bool:
    section(f"TEST 1 — Ouverture du port {port}")
    try:
        with CATConnection(port) as cat:
            ok(f"Port {port} ouvert  |  4800 baud, 8N2")
        return True
    except CATError as e:
        fail(str(e))
        print()
        print("  Pistes :")
        print("  - L'appareil est-il allumé ?")
        print("  - Vérifiez le port dans le Gestionnaire de périphériques")
        print(f"  - Essayez : python test_connection.py --port COM3")
        return False


def test_encodage_bcd() -> bool:
    """
    Vérifie l'encodage BCD sans connexion série.
    L'exemple du manuel : 14.25000 MHz → bloc 00h 50h 42h 01h 0Ah
    """
    section("TEST 2 — Encodage BCD (pas de connexion requise)")

    cas = [
        (14_250_000, [0x00, 0x50, 0x42, 0x01], "14.250.00 MHz — exemple manuel"),
        ( 7_000_000, [0x00, 0x00, 0x70, 0x00], " 7.000.00 MHz"),
        (   198_000, [0x00, 0x98, 0x01, 0x00], " 0.198.00 MHz — France Inter GO"),
        ( 9_790_000, [0x00, 0x90, 0x97, 0x00], " 9.790.00 MHz — RFI"),
    ]

    all_ok = True
    for freq_hz, expected_wire, label in cas:
        args = freq_to_bcd(freq_hz)
        padded = list(args) + [0x00] * (4 - len(args))
        wire   = list(reversed(padded))
        if wire == expected_wire:
            ok(f"{label}  →  {[hex(b) for b in wire + [0x0a]]}")
        else:
            fail(f"{label}")
            print(f"       Attendu : {[hex(b) for b in expected_wire]}")
            print(f"       Obtenu  : {[hex(b) for b in wire]}")
            all_ok = False

    return all_ok


def test_frequence(cat: CATConnection, freq_hz: int) -> None:
    freq_fmt = f"{freq_hz//1_000_000}.{(freq_hz%1_000_000)//1_000:03d}.{(freq_hz%1_000)//10:02d}"
    print(f"\n  → Fréquence {freq_fmt} MHz ...", end=" ", flush=True)
    try:
        set_frequency(cat, freq_hz)
        ok(f"Commande envoyée — vérifiez l'afficheur : {freq_fmt}")
    except CATError as e:
        fail(str(e))


def test_mode(cat: CATConnection, mode: str) -> None:
    print(f"\n  → Mode {mode} ...", end=" ", flush=True)
    try:
        set_mode(cat, mode)
        ok("Commande envoyée")
    except CATError as e:
        fail(str(e))


def test_steps(cat: CATConnection) -> None:
    print(f"\n  → Step rapide ▶▶ +100 kHz ...", end=" ", flush=True)
    try:
        step_up(cat, large=False)
        ok("Commande envoyée")
    except CATError as e:
        fail(str(e))

    time.sleep(0.3)

    print(f"  → Step rapide ◀◀ -100 kHz ...", end=" ", flush=True)
    try:
        step_down(cat, large=False)
        ok("Commande envoyée")
    except CATError as e:
        fail(str(e))

    time.sleep(0.3)

    print(f"  → Step fin ▶ +10 Hz ...", end=" ", flush=True)
    try:
        step_fine(cat, direction="up")
        ok("Commande envoyée")
    except CATError as e:
        fail(str(e))

    time.sleep(0.3)

    print(f"  → Step fin ◀ -10 Hz ...", end=" ", flush=True)
    try:
        step_fine(cat, direction="down")
        ok("Commande envoyée")
    except CATError as e:
        fail(str(e))


def test_smeter(cat: CATConnection) -> None:
    print(f"\n  → Lecture S-Mètre (timeout 3s) ...", end=" ", flush=True)
    try:
        value = read_smeter(cat)
        ok(f"Valeur reçue : {value}  (0x{value:02X})")
    except CATError as e:
        print(f"— non disponible ({e})")
        print("    (normal selon la configuration du FRG-100)")


def test_lock(cat: CATConnection) -> None:
    print(f"\n  → Verrouillage panneau ...", end=" ", flush=True)
    try:
        lock(cat, True)
        print("verrouillé", end=" ", flush=True)
        time.sleep(1)
        lock(cat, False)
        ok("déverrouillé")
    except CATError as e:
        fail(str(e))


# ------------------------------------------------------------------
# Séquence complète
# ------------------------------------------------------------------

def run_all_tests(port: str, freq_hz: int, mode: str) -> None:

    test_encodage_bcd()

    if not test_ouverture_port(port):
        sys.exit(1)

    section("TESTS 3–7 — Commandes CAT")
    try:
        with CATConnection(port) as cat:
            test_frequence(cat, freq_hz)
            time.sleep(0.3)

            test_mode(cat, mode)
            time.sleep(0.3)

            test_steps(cat)
            time.sleep(0.3)

            test_smeter(cat)
            time.sleep(0.3)

            test_lock(cat)

    except CATError as e:
        fail(f"Erreur de connexion pendant les tests : {e}")
        sys.exit(1)

    section("Résumé")
    print("  Si toutes les commandes sont ✓ mais que l'appareil ne réagit pas,")
    print("  vérifiez le câblage du port CAT à l'arrière du FRG-100.")
    print()


# ------------------------------------------------------------------
# Point d'entrée
# ------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test de connexion CAT — Yaesu FRG-100"
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
        help="Mode de réception (défaut : USB) — LSB USB CW CWW AM AMN FM WFM"
    )
    args = parser.parse_args()

    run_all_tests(args.port, args.freq, args.mode)
