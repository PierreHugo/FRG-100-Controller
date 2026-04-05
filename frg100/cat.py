"""
frg100/cat.py
-------------
Couche bas niveau : communication série avec le Yaesu FRG-100 via le protocole CAT.

Toutes les commandes sont des blocs de 5 octets envoyés sur le port série :
    [Arg4] [Arg3] [Arg2] [Arg1] [Opcode]

Paramètres série : 4800 baud, 8 data bits, no parity, 2 stop bits (cf. manuel p.36)
"""

import serial
import time
import logging

logger = logging.getLogger(__name__)


class CATError(Exception):
    """Erreur de communication avec le FRG-100."""
    pass


class CATConnection:
    """
    Gère la connexion série avec le FRG-100.

    Exemple d'utilisation :
        with CATConnection("COM26") as cat:
            cat.send_command(0x0A, [0x01, 0x00, 0x42, 0x50])
    """

    BAUDRATE    = 4800
    BYTESIZE    = serial.EIGHTBITS
    PARITY      = serial.PARITY_NONE
    STOPBITS    = serial.STOPBITS_TWO
    TIMEOUT     = 2.0   # secondes — délai max pour lire une réponse
    BLOCK_SIZE  = 5     # toutes les commandes CAT font 5 octets

    def __init__(self, port: str):
        self.port = port
        self._serial: serial.Serial | None = None

    # ------------------------------------------------------------------
    # Gestion de la connexion
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Ouvre le port série vers le FRG-100."""
        try:
            self._serial = serial.Serial(
                port     = self.port,
                baudrate = self.BAUDRATE,
                bytesize = self.BYTESIZE,
                parity   = self.PARITY,
                stopbits = self.STOPBITS,
                timeout  = self.TIMEOUT,
            )
            logger.info(f"Connecté au FRG-100 sur {self.port}")
        except serial.SerialException as e:
            raise CATError(f"Impossible d'ouvrir le port {self.port} : {e}") from e

    def disconnect(self) -> None:
        """Ferme le port série proprement."""
        if self._serial and self._serial.is_open:
            self._serial.close()
            logger.info("Déconnecté du FRG-100")

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    # Support du context manager (with CATConnection(...) as cat:)
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    # ------------------------------------------------------------------
    # Construction et envoi des blocs CAT
    # ------------------------------------------------------------------

    def _build_block(self, opcode: int, args: list[int]) -> bytes:
        """
        Construit un bloc de 5 octets à partir de l'opcode et des arguments.

        Format (envoyé de gauche à droite, cf. manuel) :
            [Arg4] [Arg3] [Arg2] [Arg1] [Opcode]

        Les arguments manquants sont complétés à 0x00 (padding).

        Args:
            opcode : octet de commande (ex: 0x0A pour Set Freq)
            args   : liste de 0 à 4 octets d'arguments (ordre : arg1 en premier)

        Returns:
            bytes de longueur 5
        """
        if len(args) > 4:
            raise CATError(f"Trop d'arguments ({len(args)}) — maximum 4")

        # On complète à 4 arguments avec des zéros (padding)
        padded = list(args) + [0x00] * (4 - len(args))

        # Le bloc est envoyé [Arg4, Arg3, Arg2, Arg1, Opcode]
        # Donc on inverse les args pour respecter l'ordre du manuel
        block = list(reversed(padded)) + [opcode]

        logger.debug(f"Bloc CAT : {[hex(b) for b in block]}")
        return bytes(block)

    def send_command(self, opcode: int, args: list[int] = None) -> None:
        """
        Envoie une commande CAT au FRG-100 (sans attendre de réponse).

        Args:
            opcode : identifiant de la commande (cf. commands.py)
            args   : paramètres de la commande (optionnel)
        """
        if not self.is_connected():
            raise CATError("Non connecté — appelez connect() d'abord")

        block = self._build_block(opcode, args or [])
        self._serial.write(block)
        self._serial.flush()

    def send_command_read(self, opcode: int, args: list[int] = None,
                          expected_bytes: int = 5,
                          read_timeout: float = None) -> bytes:
        """
        Envoie une commande et lit la réponse du FRG-100.

        Utilisé pour les commandes qui retournent des données
        (ex: Status Update, Read S-Meter, Read Flags).

        Args:
            opcode         : identifiant de la commande
            args           : paramètres (optionnel)
            expected_bytes : nombre d'octets attendus en réponse (5 par défaut)
            read_timeout   : timeout de lecture en secondes (None = utilise self.TIMEOUT)

        Returns:
            bytes lus depuis le FRG-100
        """
        self.send_command(opcode, args)

        # Délai d'attente avant lecture — le FRG-100 peut être lent à répondre
        # Le manuel mentionne que la réponse peut être retardée par le PACING
        time.sleep(0.15)

        # Timeout de lecture personnalisable
        old_timeout = self._serial.timeout
        if read_timeout is not None:
            self._serial.timeout = read_timeout

        response = self._serial.read(expected_bytes)

        if read_timeout is not None:
            self._serial.timeout = old_timeout

        if len(response) < expected_bytes:
            logger.warning(
                f"Réponse incomplète : {len(response)}/{expected_bytes} octets reçus"
            )
        logger.debug(f"Réponse reçue : {[hex(b) for b in response]}")
        return response

    def flush(self) -> None:
        """Vide le buffer série (utile avant une nouvelle séquence de commandes)."""
        if self.is_connected():
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
