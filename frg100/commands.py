"""
frg100/commands.py
------------------
Implémentation des 19 commandes CAT du Yaesu FRG-100 (cf. manuel p.37-39).

Chaque fonction construit les bons arguments et délègue l'envoi à CATConnection.
Les fréquences sont encodées en BCD packed decimal, en ordre inverse (cf. manuel).

Corrections v2 (d'après scan manuel haute qualité) :
  - BCD : fréquence en dizaines de Hz (pas dixièmes), fix du calcul
  - UP/DOWN FAST : S et D sont en position 2 (byte 2), pas 1
  - Memory Recall : plage étendue à 52 canaux (+ Lo=0x33, Hi=0x34)
  - VFO → M : F2 a 3 valeurs (00h=SET, 01h=MEM CLEAR, 02h=recall)
  - memory_to_vfo : plage corrigée à 52 canaux
  - DIM : L=00h OFF, L=01h ON (était inversé)
  - Scan Skip Set : opcode corrigé 0x8D (était 0x80)
  - Step Oper. Frequency : D=0 monte, D=1 descend (step fin 10/100 Hz)
  - Read S-Meter : 4 octets répétés + 0xF7 en dernier

Table des opcodes (hex / décimal) :
    02 ( 2)  Memory Channel Recall
    03 ( 3)  VFO → M
    04 ( 4)  LOCK
    05 ( 5)  VFO Operation
    06 ( 6)  M → VFO
    07 ( 7)  UP ▲ (FAST)
    08 ( 8)  DOWN ▼ (FAST)
    0A (10)  Set Operating Frequency
    0C (12)  MODE
    0E (14)  PACING
    10 (16)  Status Update
    20 (32)  POWER
    21 (33)  Clock Set
    22 (34)  Timer Set
    8D (141) Scan Skip Set
    8E (142) Step Oper. Frequency
    F7 (247) Read S-Meter
    F8 (248) DIM
    FA (250) Read Flags
"""

from .cat import CATConnection, CATError


# ------------------------------------------------------------------
# Constantes — opcodes
# ------------------------------------------------------------------

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
OP_SCAN_SKIP    = 0x8D   # corrigé : était 0x80
OP_STEP_FREQ    = 0x8E
OP_READ_SMETER  = 0xF7
OP_DIM          = 0xF8
OP_READ_FLAGS   = 0xFA

# Modes de réception — valeur M pour la commande MODE (opcode 0Ch)
# Valeurs exactes du manuel : LSB=0, USB=1, CW=2, CW Wide=3,
# AW Wide=4, AM Narrow=5, FM=6 or 7
MODE = {
    "LSB"  : 0,
    "USB"  : 1,
    "CW"   : 2,
    "CWW"  : 3,   # CW Wide
    "AM"   : 4,   # AM Wide  (était 3 = CW Wide, erreur corrigée)
    "AMN"  : 5,   # AM Narrow
    "FM"   : 6,
    "WFM"  : 7,   # FM Wide
}

# Canaux mémoire spéciaux (en plus des canaux 1–50)
MEM_LO = 0x33   # canal Lo (51)
MEM_HI = 0x34   # canal Hi (52)

# Fonctions pour VFO → M (paramètre F2)
VFO_TO_MEM_SET    = 0x00   # stocker la fréquence
VFO_TO_MEM_CLEAR  = 0x01   # effacer le canal
VFO_TO_MEM_RECALL = 0x02   # rappeler le canal


# ------------------------------------------------------------------
# Encodage / décodage des fréquences (BCD packed decimal)
# ------------------------------------------------------------------

def freq_to_bcd(freq_hz: int) -> list[int]:
    """
    Encode une fréquence en Hz en BCD packed decimal (vraie valeur hex).

    BCD packed signifie que chaque octet contient 2 chiffres décimaux
    encodés en hexadécimal : "42" → 0x42 (66 decimal), PAS int("42")=42=0x2A.

    Exemple confirmé par l'exemple GW Basic du manuel (p.39) :
        14.25000 MHz → bloc envoyé : 00h 50h 42h 01h 0Ah (opcode)

        14 250 000 Hz ÷ 10 = 1 425 000
        → 8 chiffres décimaux : "01425000"
        → BCD : "01"→0x01, "42"→0x42, "50"→0x50, "00"→0x00
        → args [arg1..arg4] = [0x01, 0x42, 0x50, 0x00]
        → _build_block inverse → [0x00, 0x50, 0x42, 0x01] sur le fil ✓

    Args:
        freq_hz : fréquence en Hz

    Returns:
        Liste [arg1, arg2, arg3, arg4] en valeurs hex BCD
    """
    freq_tens = freq_hz // 10
    freq_str  = f"{freq_tens:08d}"
    # int("42", 16) = 0x42 = 66 — c'est le BCD packed correct
    return [int(freq_str[i:i+2], 16) for i in range(0, 8, 2)]


def bcd_to_freq(bcd_bytes: list[int]) -> int:
    """
    Décode 4 octets BCD [arg1..arg4] en fréquence Hz.
    Inverse de freq_to_bcd.
    Ex : [0x01, 0x42, 0x50, 0x00] → "01425000" → 1 425 000 × 10 = 14 250 000 Hz
    """
    freq_str  = "".join(f"{b:02x}" for b in bcd_bytes)
    freq_tens = int(freq_str)
    return freq_tens * 10


# ------------------------------------------------------------------
# Commandes CAT — écriture
# ------------------------------------------------------------------

def set_frequency(cat: CATConnection, freq_hz: int) -> None:
    """
    Syntonise le FRG-100 sur la fréquence donnée.

    Args:
        cat     : connexion CAT active
        freq_hz : fréquence en Hz (ex: 14_250_000 pour 14.250 MHz)

    Exemples :
        set_frequency(cat, 7_100_000)   # 7.100 MHz (40m)
        set_frequency(cat, 198_000)     # 198 kHz   (France Inter GO)
        set_frequency(cat, 9_790_000)   # 9.790 MHz (RFI ondes courtes)
    """
    if not (50_000 <= freq_hz <= 30_000_000):
        raise CATError(
            f"Fréquence hors limites : {freq_hz} Hz "
            f"(plage FRG-100 : 50 kHz – 30 MHz)"
        )
    cat.send_command(OP_SET_FREQ, freq_to_bcd(freq_hz))


def set_mode(cat: CATConnection, mode: str) -> None:
    """
    Change le mode de réception.

    Args:
        mode : "LSB", "USB", "CW", "AM", "AMN", "FM", "WFM"
    """
    mode = mode.upper()
    if mode not in MODE:
        raise CATError(
            f"Mode inconnu : '{mode}' — valeurs valides : {list(MODE.keys())}"
        )
    # Le paramètre M est en position 1 (byte 1 du bloc)
    cat.send_command(OP_MODE, [MODE[mode]])


def memory_recall(cat: CATConnection, channel: int) -> None:
    """
    Rappelle un canal mémoire.

    Args:
        channel : 1–50 (canaux normaux), 51 = Lo, 52 = Hi
                  CH = 01h–32h (1–50), 33h (Lo), 34h (Hi)
    """
    if channel == 51:
        ch_byte = MEM_LO
    elif channel == 52:
        ch_byte = MEM_HI
    elif 1 <= channel <= 50:
        ch_byte = channel
    else:
        raise CATError(f"Canal invalide : {channel} (plage : 1–52, Lo=51, Hi=52)")
    cat.send_command(OP_MEM_RECALL, [ch_byte])


def vfo_to_memory(cat: CATConnection, channel: int,
                  function: int = VFO_TO_MEM_SET) -> None:
    """
    Opération sur un canal mémoire depuis le VFO.

    Args:
        channel  : canal cible (1–52, voir memory_recall)
        function : VFO_TO_MEM_SET (0x00)    → stocker la fréquence
                   VFO_TO_MEM_CLEAR (0x01)  → effacer le canal
                   VFO_TO_MEM_RECALL (0x02) → rappeler le canal
    """
    if channel == 51:
        ch_byte = MEM_LO
    elif channel == 52:
        ch_byte = MEM_HI
    elif 1 <= channel <= 50:
        ch_byte = channel
    else:
        raise CATError(f"Canal invalide : {channel}")

    if function not in (VFO_TO_MEM_SET, VFO_TO_MEM_CLEAR, VFO_TO_MEM_RECALL):
        raise CATError(f"Fonction invalide : {function} (0=SET, 1=CLEAR, 2=RECALL)")

    # F1 = canal (byte 1), F2 = fonction (byte 2)
    cat.send_command(OP_VFO_TO_MEM, [ch_byte, function])


def memory_to_vfo(cat: CATConnection, channel: int) -> None:
    """
    Copie un canal mémoire vers le VFO.

    Args:
        channel : 1–52 (voir memory_recall)
    """
    if channel == 51:
        ch_byte = MEM_LO
    elif channel == 52:
        ch_byte = MEM_HI
    elif 1 <= channel <= 50:
        ch_byte = channel
    else:
        raise CATError(f"Canal invalide : {channel}")
    cat.send_command(OP_MEM_TO_VFO, [ch_byte])


def lock(cat: CATConnection, locked: bool = True) -> None:
    """
    Verrouille (P=1) ou déverrouille (P=0) le panneau avant / bouton de syntonisation.
    """
    cat.send_command(OP_LOCK, [0x01 if locked else 0x00])


def vfo_operation(cat: CATConnection) -> None:
    """Sélectionne le mode VFO (aucun paramètre requis)."""
    cat.send_command(OP_VFO_OP)


def step_up(cat: CATConnection, large: bool = False) -> None:
    """
    Monte la fréquence d'un grand pas (UP FAST).

    Args:
        large : False = +100 kHz (S=0), True = +1 MHz (S=1)

    Note : c'est un saut rapide. Pour un step fin (10/100 Hz),
           utiliser step_fine().
    """
    # S est en position 2 (byte 2 du bloc, cf. tableau manuel)
    s = 0x01 if large else 0x00
    cat.send_command(OP_UP_FAST, [0x00, s])


def step_down(cat: CATConnection, large: bool = False) -> None:
    """
    Descend la fréquence d'un grand pas (DOWN FAST).

    Args:
        large : False = -100 kHz (D=0), True = -1 MHz (D=1)
    """
    # D est en position 2 (byte 2 du bloc, cf. tableau manuel)
    d = 0x01 if large else 0x00
    cat.send_command(OP_DOWN_FAST, [0x00, d])


def step_fine(cat: CATConnection, direction: str = "up",
              step_100hz: bool = False) -> None:
    """
    Step fin de fréquence (Step Oper. Frequency, opcode 8Eh).

    Args:
        direction  : "up" (D=0) ou "down" (D=1)
        step_100hz : False = step 10 Hz, True = step 100 Hz
    """
    d = 0x00 if direction == "up" else 0x01
    cat.send_command(OP_STEP_FREQ, [d])


def set_pacing(cat: CATConnection, delay_ms: int) -> None:
    """
    Règle le délai entre octets de réponse du FRG-100 (PACING).

    Augmenter si les réponses arrivent trop vite et sont tronquées.

    Args:
        delay_ms : délai en millisecondes (0–255, 0=OFFh)
    """
    if not (0 <= delay_ms <= 255):
        raise CATError("Délai de pacing hors plage (0–255 ms)")
    cat.send_command(OP_PACING, [delay_ms])


def power(cat: CATConnection, on: bool) -> None:
    """
    Allume (P=01h) ou éteint (P=00h) le récepteur via CAT.
    """
    cat.send_command(OP_POWER, [0x01 if on else 0x00])


def set_dim(cat: CATConnection, on: bool) -> None:
    """
    Active (L=01h) ou désactive (L=00h) le rétroéclairage LCD.
    (corrigé : était inversé dans v1)
    """
    cat.send_command(OP_DIM, [0x01 if on else 0x00])


def scan_skip_set(cat: CATConnection, channel: int, skip: bool = True) -> None:
    """
    Marque un canal à ignorer (ou non) pendant le scanning.

    Args:
        channel : canal à configurer (1–50)
        skip    : True = Skip On (Y=00h), False = Skip Off (Y=01h)
    """
    if not (1 <= channel <= 50):
        raise CATError(f"Canal invalide : {channel}")
    y = 0x00 if skip else 0x01
    # X = canal (byte 1), Y = skip on/off (byte 2)
    cat.send_command(OP_SCAN_SKIP, [channel, y])


# ------------------------------------------------------------------
# Commandes de lecture (retournent des données)
# ------------------------------------------------------------------

def read_status(cat: CATConnection) -> dict:
    """
    Demande une mise à jour de statut (Status Update, opcode 10h).

    Le FRG-100 peut retourner 1, 18, 19 ou 283 octets selon U.
    On envoie U=00h pour obtenir la réponse courte (1 octet = ACK),
    ou U=01h pour 18/19 octets incluant la fréquence courante.

    Returns:
        dict avec freq_hz, freq_mhz, raw
    """
    # U=01h → réponse avec fréquence (18 ou 19 octets selon firmware)
    response = cat.send_command_read(OP_STATUS, args=[0x01], expected_bytes=5)
    if len(response) < 5:
        raise CATError("Réponse Status trop courte")

    freq_bytes = list(response[:4])
    freq_hz = bcd_to_freq(freq_bytes)

    return {
        "freq_hz"  : freq_hz,
        "freq_mhz" : freq_hz / 1_000_000,
        "raw"      : list(response),
    }


def read_smeter(cat: CATConnection) -> int:
    """
    Lit la valeur du S-Mètre (opcode F7h).

    Le FRG-100 retourne 4 octets identiques (valeur 0–0FFh)
    suivis du filler 0F7h. Ex : [05, 05, 05, 05, F7] → S = 5.

    Note : la réponse peut être lente selon le PACING configuré.
    On tolère un filler absent si les 4 premiers octets sont cohérents.

    Returns:
        Valeur du S-Mètre (0–255, en pratique 0–0F0h max)

    Raises:
        CATError si pas de réponse du tout
    """
    response = cat.send_command_read(OP_READ_SMETER, expected_bytes=5)
    if len(response) == 0:
        raise CATError("Pas de réponse du S-Mètre")
    if len(response) < 5:
        raise CATError(f"Réponse S-Mètre incomplète : {len(response)}/5 octets")
    # Le dernier octet est normalement 0xF7 (filler)
    # On log un warning si ce n'est pas le cas mais on retourne quand même
    if response[4] != 0xF7:
        import logging
        logging.getLogger(__name__).warning(
            f"S-Mètre : filler inattendu {hex(response[4])} (attendu 0xF7)"
        )
    return response[0]


def read_flags(cat: CATConnection) -> dict:
    """
    Lit les 24 bits de flags d'état du FRG-100 (opcode FAh).

    Retourne 5 octets contenant les Status Flags (cf. pages suivantes
    du manuel pour le détail bit à bit).

    Returns:
        dict avec raw (liste d'ints) et bytes (liste de strings hex)
    """
    response = cat.send_command_read(OP_READ_FLAGS, expected_bytes=5)
    return {
        "raw"  : list(response),
        "bytes": [hex(b) for b in response],
    }
