"""
frg100/commands.py
------------------
Implémentation des 19 commandes CAT du Yaesu FRG-100 (cf. manuel p.37-39).

Chaque fonction construit les bons arguments et délègue l'envoi à CATConnection.
Les fréquences sont encodées en BCD packed decimal, en ordre inverse (cf. manuel).

Table des opcodes :
    0x00  Set Operating Frequency   (alias 0x0A dans certaines docs)
    0x02  Memory Channel Recall
    0x03  VFO → M (store to memory)
    0x04  Lock
    0x05  VFO Operation
    0x06  M → VFO
    0x07  UP ▲ (FAST)
    0x08  DOWN ▼ (FAST)
    0x0A  Set Operating Frequency
    0x0C  Mode
    0x0E  Pacing
    0x10  Status Update
    0x20  Power
    0x21  Clock Set
    0x22  Timer Set
    0x80  Scan Skip Set
    0x8E  Step Operating Frequency
    0xF7  Read S-Meter
    0xF8  DIM
    0xFA  Read Flags
"""

from .cat import CATConnection, CATError


# ------------------------------------------------------------------
# Constantes
# ------------------------------------------------------------------

# Opcodes (hexadécimal, cf. table manuel)
OP_SET_FREQ     = 0x0A
OP_MEM_RECALL   = 0x02
OP_VFO_TO_MEM   = 0x03
OP_LOCK         = 0x04
OP_VFO_OP       = 0x05
OP_MEM_TO_VFO   = 0x06
OP_UP_FAST      = 0x07
OP_DOWN_FAST    = 0x08
OP_MODE         = 0x0C
OP_PACING       = 0x0E
OP_STATUS       = 0x10
OP_POWER        = 0x20
OP_CLOCK_SET    = 0x21
OP_TIMER_SET    = 0x22
OP_SCAN_SKIP    = 0x80
OP_STEP_FREQ    = 0x8E
OP_READ_SMETER  = 0xF7
OP_DIM          = 0xF8
OP_READ_FLAGS   = 0xFA

# Modes de réception (valeur M pour la commande MODE)
MODE = {
    "LSB" : 0,
    "USB" : 1,
    "CW"  : 2,
    "AM"  : 3,
    "FM"  : 4,
    "WFM" : 6,  # Wide FM
}


# ------------------------------------------------------------------
# Encodage des fréquences
# ------------------------------------------------------------------

def freq_to_bcd(freq_hz: int) -> list[int]:
    """
    Encode une fréquence en Hz en BCD packed decimal, ordre inverse.

    Le manuel encode la fréquence en dixièmes de Hz, sur 4 octets BCD,
    envoyés du moins significatif au plus significatif.

    Exemple : 14.250 MHz = 142 500 000 Hz = 1 425 000 000 dixièmes de Hz
        → BCD: 01 42 50 00 → envoyé comme [0x00, 0x50, 0x42, 0x01]

    Args:
        freq_hz : fréquence en Hz (ex: 14_250_000 pour 14.250 MHz)

    Returns:
        Liste de 4 octets [arg1, arg2, arg3, arg4]
    """
    # Conversion en dixièmes de Hz (résolution minimale du FRG-100)
    freq_tenths = freq_hz * 10  # 1 Hz → 10 dixièmes

    # Représentation décimale sur 8 chiffres, packée en 4 octets BCD
    # Chaque octet contient 2 chiffres décimaux
    freq_str = f"{freq_tenths:08d}"  # ex: "01425000" pour 142.5 kHz

    # On groupe par paires de droite à gauche, puis on inverse
    pairs = [freq_str[i:i+2] for i in range(0, 8, 2)]  # ['01','42','50','00']
    bcd_bytes = [int(p) for p in pairs]                 # [1, 42, 50, 0]

    # Le manuel envoie en ordre inverse (centaines de MHz en premier dans le bloc)
    return list(reversed(bcd_bytes))                    # [0, 50, 42, 1]


def bcd_to_freq(bcd_bytes: list[int]) -> int:
    """
    Décode 4 octets BCD (ordre inverse) en fréquence Hz.
    Inverse de freq_to_bcd — utilisé pour lire la réponse Status Update.
    """
    normal_order = list(reversed(bcd_bytes))
    freq_str = "".join(f"{b:02d}" for b in normal_order)
    freq_tenths = int(freq_str)
    return freq_tenths // 10


# ------------------------------------------------------------------
# Commandes CAT
# ------------------------------------------------------------------

def set_frequency(cat: CATConnection, freq_hz: int) -> None:
    """
    Syntonise le FRG-100 sur la fréquence donnée.

    Args:
        cat     : connexion CAT active
        freq_hz : fréquence cible en Hz (ex: 14_250_000 pour 14.250 MHz)

    Exemple:
        set_frequency(cat, 7_100_000)   # 7.1 MHz
        set_frequency(cat, 198_000)     # 198 kHz (France Inter GO)
    """
    if not (50_000 <= freq_hz <= 30_000_000):
        raise CATError(
            f"Fréquence hors limites : {freq_hz} Hz "
            f"(plage FRG-100 : 50 kHz – 30 MHz)"
        )
    args = freq_to_bcd(freq_hz)
    cat.send_command(OP_SET_FREQ, args)


def set_mode(cat: CATConnection, mode: str) -> None:
    """
    Change le mode de réception.

    Args:
        cat  : connexion CAT active
        mode : "LSB", "USB", "CW", "AM", "FM", ou "WFM"
    """
    mode = mode.upper()
    if mode not in MODE:
        raise CATError(
            f"Mode inconnu : '{mode}' — valeurs valides : {list(MODE.keys())}"
        )
    cat.send_command(OP_MODE, [MODE[mode]])


def memory_recall(cat: CATConnection, channel: int) -> None:
    """
    Rappelle un canal mémoire (1–50).

    Args:
        channel : numéro de canal (1 à 50 inclus)
    """
    if not (1 <= channel <= 50):
        raise CATError(f"Canal invalide : {channel} (plage : 1–50)")
    cat.send_command(OP_MEM_RECALL, [channel])


def vfo_to_memory(cat: CATConnection, channel: int, function: int = 0) -> None:
    """
    Stocke la fréquence VFO courante dans un canal mémoire.

    Args:
        channel  : canal cible (1–50)
        function : F1=canal SET, F2=canal CLEAR (0 par défaut = SET)
    """
    if not (1 <= channel <= 50):
        raise CATError(f"Canal invalide : {channel}")
    cat.send_command(OP_VFO_TO_MEM, [channel, function])


def memory_to_vfo(cat: CATConnection, channel: int) -> None:
    """Copie un canal mémoire vers le VFO."""
    if not (1 <= channel <= 50):
        raise CATError(f"Canal invalide : {channel}")
    cat.send_command(OP_MEM_TO_VFO, [channel])


def lock(cat: CATConnection, locked: bool = True) -> None:
    """
    Verrouille ou déverrouille le panneau avant.

    Args:
        locked : True = verrouillé, False = déverrouillé
    """
    cat.send_command(OP_LOCK, [0x01 if locked else 0x00])


def vfo_operation(cat: CATConnection) -> None:
    """Sélectionne le mode VFO."""
    cat.send_command(OP_VFO_OP)


def step_up(cat: CATConnection, steps: int = 1) -> None:
    """Monte la fréquence d'un ou plusieurs pas rapides."""
    cat.send_command(OP_UP_FAST, [steps])


def step_down(cat: CATConnection, steps: int = 1) -> None:
    """Descend la fréquence d'un ou plusieurs pas rapides."""
    cat.send_command(OP_DOWN_FAST, [steps])


def set_pacing(cat: CATConnection, delay_ms: int) -> None:
    """
    Règle le délai entre réponses consécutives du FRG-100 (PACING).

    Utile si le logiciel envoie des commandes trop vite.

    Args:
        delay_ms : délai en millisecondes (0–255)
    """
    if not (0 <= delay_ms <= 255):
        raise CATError("Délai de pacing hors plage (0–255 ms)")
    cat.send_command(OP_PACING, [delay_ms])


def power(cat: CATConnection, on: bool) -> None:
    """Allume ou éteint le récepteur via CAT."""
    cat.send_command(OP_POWER, [0x01 if on else 0x00])


def set_dim(cat: CATConnection, on: bool) -> None:
    """Active ou désactive le rétroéclairage LCD."""
    cat.send_command(OP_DIM, [0x01 if on else 0x00])


# ------------------------------------------------------------------
# Commandes de lecture (retournent des données)
# ------------------------------------------------------------------

def read_status(cat: CATConnection) -> dict:
    """
    Demande une mise à jour de statut complète (Status Update).

    Retourne jusqu'à 283 octets décrivant l'état interne du FRG-100.
    Pour l'instant on lit les 5 premiers octets (fréquence + flags de base).

    Returns:
        dict avec les champs décodés
    """
    response = cat.send_command_read(OP_STATUS, expected_bytes=5)
    if len(response) < 5:
        raise CATError("Réponse Status trop courte")

    # Les 4 premiers octets = fréquence en BCD inversé
    freq_bytes = list(response[:4])
    freq_hz = bcd_to_freq(freq_bytes)

    return {
        "freq_hz"   : freq_hz,
        "freq_mhz"  : freq_hz / 1_000_000,
        "raw"       : list(response),
    }


def read_smeter(cat: CATConnection) -> int:
    """
    Lit la valeur du S-Mètre (force du signal reçu).

    Returns:
        Valeur brute du S-Mètre (0–18, 19 ou 283 selon le manuel)
    """
    response = cat.send_command_read(OP_READ_SMETER, expected_bytes=5)
    if not response:
        raise CATError("Pas de réponse du S-Mètre")
    return response[0]


def read_flags(cat: CATConnection) -> dict:
    """
    Lit les flags d'état du FRG-100 (Read Flags).

    Returns:
        dict avec les flags décodés (5 octets, 24 bits de statut)
    """
    response = cat.send_command_read(OP_READ_FLAGS, expected_bytes=5)
    return {
        "raw"  : list(response),
        "bytes": [hex(b) for b in response],
    }
