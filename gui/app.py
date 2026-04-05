"""
gui/app.py
----------
Interface graphique tkinter pour le contrôle du Yaesu FRG-100.

Organisée en 3 zones :
  - Barre de connexion  (port COM, bouton connecter)
  - Afficheur principal (fréquence style radio, mode, S-mètre)
  - Panneau de contrôle (saisie fréquence, mode, mémoires, step)
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import logging

from frg100 import CATConnection, CATError
from frg100 import (
    set_frequency, set_mode,
    step_up, step_down, step_fine,
    lock, read_smeter, set_pacing,
    memory_recall, vfo_to_memory,
    MODE,
)
from frg100.config import DEFAULT_PORT, FREQ_MIN_HZ, FREQ_MAX_HZ

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Constantes visuelles
# ------------------------------------------------------------------

FONT_DISPLAY   = ("Courier New", 56, "bold")   # afficheur fréquence — grand
FONT_LABEL     = ("Segoe UI", 13)
FONT_LABEL_B   = ("Segoe UI", 13, "bold")
FONT_BUTTON    = ("Segoe UI", 13)
FONT_SMALL     = ("Segoe UI", 11)

COLOR_BG       = "#1c1c1e"   # fond général (sombre, style radio)
COLOR_PANEL    = "#2c2c2e"   # fond des panneaux
COLOR_DISPLAY  = "#0a0a0a"   # fond afficheur LCD
COLOR_FREQ     = "#00ff88"   # vert LCD pour la fréquence
COLOR_UNIT     = "#00aa55"   # vert atténué pour "MHz"
COLOR_TEXT     = "#e5e5ea"   # texte général clair
COLOR_MUTED    = "#8e8e93"   # texte secondaire gris
COLOR_ACCENT   = "#0a84ff"   # bleu accent (bouton connecter)
COLOR_DANGER   = "#ff453a"   # rouge (déconnecter, verrou)
COLOR_SUCCESS  = "#30d158"   # vert (connecté)
COLOR_BORDER   = "#3a3a3c"   # bordures subtiles

SMETER_COLORS  = [           # gradient vert → orange → rouge pour le S-mètre
    "#30d158", "#30d158", "#30d158", "#30d158",
    "#30d158", "#30d158", "#ffd60a", "#ffd60a",
    "#ff9f0a", "#ff9f0a", "#ff453a", "#ff453a",
]


class FRG100App(tk.Tk):
    """Fenêtre principale de l'application."""

    def __init__(self):
        super().__init__()

        self.title("FRG-100 Controller")
        self.configure(bg=COLOR_BG)
        # Plein écran au démarrage
        self.state("zoomed")   # Windows : fenêtre maximisée

        # État de l'application
        self.cat: CATConnection | None = None
        self.connected = False
        self.smeter_job = None          # référence au polling S-mètre
        self.locked = False
        self.current_freq_hz = 14_250_000  # fréquence courante trackée localement

        # Variables tkinter
        self.var_port       = tk.StringVar(value=DEFAULT_PORT)
        self.var_freq_input = tk.StringVar(value="14.250")
        self.var_mode       = tk.StringVar(value="USB")
        self.var_status     = tk.StringVar(value="Non connecté")
        self.var_freq_disp  = tk.StringVar(value="--.--.--")
        self.var_smeter     = tk.IntVar(value=0)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------

    def _build_ui(self):
        """Assemble les trois zones de l'interface."""
        self._build_connection_bar()
        self._build_display()
        self._build_controls()
        self._build_statusbar()

    def _build_connection_bar(self):
        """Barre du haut : port COM + bouton connexion."""
        bar = tk.Frame(self, bg=COLOR_PANEL, pady=8, padx=12)
        bar.pack(fill="x", padx=0, pady=0)

        tk.Label(bar, text="Port :", bg=COLOR_PANEL, fg=COLOR_TEXT,
                 font=FONT_LABEL).pack(side="left")

        entry_port = tk.Entry(bar, textvariable=self.var_port, width=8,
                              bg=COLOR_DISPLAY, fg=COLOR_TEXT,
                              insertbackground=COLOR_TEXT,
                              relief="flat", font=FONT_LABEL)
        entry_port.pack(side="left", padx=(4, 16))

        self.btn_connect = tk.Button(
            bar, text="Connecter", font=FONT_BUTTON,
            bg=COLOR_ACCENT, fg="white", relief="flat",
            padx=12, pady=4, cursor="hand2",
            command=self._toggle_connection,
        )
        self.btn_connect.pack(side="left")

        # Indicateur de statut connexion (rond coloré)
        self.lbl_conn_status = tk.Label(
            bar, text="●  Non connecté",
            bg=COLOR_PANEL, fg=COLOR_MUTED, font=FONT_LABEL,
        )
        self.lbl_conn_status.pack(side="left", padx=16)

    def _build_display(self):
        """Afficheur principal : fréquence style LCD + S-mètre."""
        frame = tk.Frame(self, bg=COLOR_DISPLAY, padx=20, pady=16)
        frame.pack(fill="x", padx=12, pady=(12, 0))

        # Fréquence
        freq_row = tk.Frame(frame, bg=COLOR_DISPLAY)
        freq_row.pack()

        self.lbl_freq = tk.Label(
            freq_row, textvariable=self.var_freq_disp,
            font=FONT_DISPLAY, bg=COLOR_DISPLAY, fg=COLOR_FREQ,
        )
        self.lbl_freq.pack(side="left")

        tk.Label(freq_row, text=" MHz", font=("Courier New", 28),
                 bg=COLOR_DISPLAY, fg=COLOR_UNIT).pack(side="left", pady=(22, 0))

        # S-mètre (12 segments)
        smeter_frame = tk.Frame(frame, bg=COLOR_DISPLAY, pady=10)
        smeter_frame.pack()

        tk.Label(smeter_frame, text="S-Mètre", font=FONT_SMALL,
                 bg=COLOR_DISPLAY, fg=COLOR_MUTED).pack(anchor="w")

        self.smeter_canvas = tk.Canvas(
            smeter_frame, width=480, height=24,
            bg=COLOR_DISPLAY, highlightthickness=0,
        )
        self.smeter_canvas.pack()
        self._draw_smeter(0)

        # Mode affiché
        self.lbl_mode_disp = tk.Label(
            frame, text="MODE : --",
            font=FONT_LABEL_B, bg=COLOR_DISPLAY, fg=COLOR_MUTED,
        )
        self.lbl_mode_disp.pack(anchor="e")

    def _draw_smeter(self, level: int):
        """Redessine les segments du S-mètre (0–12)."""
        self.smeter_canvas.delete("all")
        seg_w, seg_h, gap = 34, 20, 4
        for i in range(12):
            x1 = i * (seg_w + gap)
            color = SMETER_COLORS[i] if i < level else COLOR_BORDER
            self.smeter_canvas.create_rectangle(
                x1, 0, x1 + seg_w, seg_h,
                fill=color, outline="",
            )

    def _build_controls(self):
        """Panneau de commandes : fréquence, mode, step, verrou."""
        outer = tk.Frame(self, bg=COLOR_BG, padx=12, pady=12)
        outer.pack(fill="x")

        # --- Ligne 1 : saisie fréquence + steps ---
        row1 = tk.LabelFrame(outer, text=" Fréquence ", bg=COLOR_PANEL,
                             fg=COLOR_MUTED, font=FONT_SMALL,
                             bd=1, relief="flat", padx=10, pady=8)
        row1.pack(fill="x", pady=(0, 8))

        # Saisie + bouton Aller
        left = tk.Frame(row1, bg=COLOR_PANEL)
        left.pack(side="left")

        tk.Label(left, text="MHz :", bg=COLOR_PANEL,
                 fg=COLOR_TEXT, font=FONT_LABEL).pack(side="left")

        entry_freq = tk.Entry(
            left, textvariable=self.var_freq_input, width=8,
            bg=COLOR_DISPLAY, fg=COLOR_FREQ,
            insertbackground=COLOR_FREQ,
            relief="flat", font=("Courier New", 14),
        )
        entry_freq.pack(side="left", padx=8)
        entry_freq.bind("<Return>", lambda _: self._send_frequency())

        tk.Button(
            left, text="Aller →", font=FONT_BUTTON,
            bg=COLOR_ACCENT, fg="white", relief="flat",
            padx=10, pady=2, cursor="hand2",
            command=self._send_frequency,
        ).pack(side="left")

        # Séparateur
        tk.Label(row1, text="", bg=COLOR_PANEL, width=3).pack(side="left")

        # Steps — boutons avec labels en dessous dans un Frame vertical
        step_outer = tk.Frame(row1, bg=COLOR_PANEL)
        step_outer.pack(side="left")

        step_btns = tk.Frame(step_outer, bg=COLOR_PANEL)
        step_btns.pack()

        tk.Button(step_btns, text="◀◀", font=FONT_BUTTON, width=3,
                  bg=COLOR_PANEL, fg=COLOR_TEXT, relief="flat",
                  cursor="hand2", command=lambda: self._step_fast(False),
                  ).pack(side="left", padx=1)
        tk.Button(step_btns, text="◀", font=FONT_BUTTON, width=3,
                  bg=COLOR_PANEL, fg=COLOR_TEXT, relief="flat",
                  cursor="hand2", command=lambda: self._step_fine("down"),
                  ).pack(side="left", padx=1)
        tk.Button(step_btns, text="▶", font=FONT_BUTTON, width=3,
                  bg=COLOR_PANEL, fg=COLOR_TEXT, relief="flat",
                  cursor="hand2", command=lambda: self._step_fine("up"),
                  ).pack(side="left", padx=1)
        tk.Button(step_btns, text="▶▶", font=FONT_BUTTON, width=3,
                  bg=COLOR_PANEL, fg=COLOR_TEXT, relief="flat",
                  cursor="hand2", command=lambda: self._step_fast(True),
                  ).pack(side="left", padx=1)

        tk.Label(step_outer, text="100kHz  10Hz  10Hz  100kHz",
                 bg=COLOR_PANEL, fg=COLOR_MUTED, font=FONT_SMALL,
                 ).pack()

        # --- Ligne 2 : mode + verrou ---
        row2 = tk.LabelFrame(outer, text=" Mode & Contrôles ", bg=COLOR_PANEL,
                             fg=COLOR_MUTED, font=FONT_SMALL,
                             bd=1, relief="flat", padx=10, pady=8)
        row2.pack(fill="x")

        tk.Label(row2, text="Mode :", bg=COLOR_PANEL,
                 fg=COLOR_TEXT, font=FONT_LABEL).pack(side="left")

        mode_menu = ttk.Combobox(
            row2, textvariable=self.var_mode,
            values=["LSB", "USB", "CW", "CWW", "AM", "AMN", "FM", "WFM"],
            state="readonly",
            width=6, font=FONT_LABEL,
        )
        mode_menu.pack(side="left", padx=8)
        mode_menu.bind("<<ComboboxSelected>>", lambda _: self._send_mode())

        tk.Button(
            row2, text="Appliquer", font=FONT_BUTTON,
            bg=COLOR_PANEL, fg=COLOR_TEXT, relief="flat",
            padx=8, pady=2, cursor="hand2",
            command=self._send_mode,
        ).pack(side="left")

        tk.Label(row2, text="   ", bg=COLOR_PANEL).pack(side="left")

        self.btn_lock = tk.Button(
            row2, text="🔓 Déverrouillé", font=FONT_BUTTON,
            bg=COLOR_PANEL, fg=COLOR_TEXT, relief="flat",
            padx=8, pady=2, cursor="hand2",
            command=self._toggle_lock,
        )
        self.btn_lock.pack(side="left", padx=8)

    def _build_statusbar(self):
        """Barre de statut en bas."""
        bar = tk.Frame(self, bg=COLOR_BORDER, pady=4, padx=12)
        bar.pack(fill="x", side="bottom")
        tk.Label(bar, textvariable=self.var_status,
                 bg=COLOR_BORDER, fg=COLOR_MUTED, font=FONT_SMALL,
                 anchor="w").pack(fill="x")

    # ------------------------------------------------------------------
    # Gestion de la connexion
    # ------------------------------------------------------------------

    def _toggle_connection(self):
        if self.connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        port = self.var_port.get().strip()
        try:
            self.cat = CATConnection(port)
            self.cat.connect()
            self.connected = True

            # Pacing : on demande 10ms entre chaque octet de réponse
            # Sans ça, le FRG-100 répond immédiatement (délai=0)
            # et les octets arrivent avant qu'on soit prêt à lire
            set_pacing(self.cat, 10)
            time.sleep(0.1)

            self.btn_connect.config(text="Déconnecter", bg=COLOR_DANGER)
            self.lbl_conn_status.config(
                text=f"●  Connecté ({port})", fg=COLOR_SUCCESS
            )
            self._set_status(f"Connecté sur {port} — 4800 baud, 8N2 — pacing 10ms")

            # Lecture initiale de la fréquence et du mode réels
            self._read_status_from_radio()
            self._start_smeter_polling()

        except CATError as e:
            messagebox.showerror("Erreur de connexion", str(e))
            self._set_status(f"Erreur : {e}")

    def _disconnect(self):
        self._stop_smeter_polling()
        if self.cat:
            self.cat.disconnect()
        self.connected = False
        self.cat = None

        self.btn_connect.config(text="Connecter", bg=COLOR_ACCENT)
        self.lbl_conn_status.config(text="●  Non connecté", fg=COLOR_MUTED)
        self.var_freq_disp.set("-- --- ---")
        self._draw_smeter(0)
        self._set_status("Déconnecté")

    def _on_close(self):
        self._disconnect()
        self.destroy()

    # ------------------------------------------------------------------
    # Actions CAT
    # ------------------------------------------------------------------

    def _send_frequency(self):
        if not self._check_connected():
            return
        try:
            raw = self.var_freq_input.get().strip().replace(",", ".")

            # Accepte deux formats :
            #   "7.100"      → MHz avec décimales
            #   "7.100.00"   → MHz.kHz.dizaines_Hz (format afficheur)
            parts = raw.split(".")
            if len(parts) == 3:
                # Format 7.100.00 → on reconstruit en MHz flottant
                mhz_str = f"{parts[0]}.{parts[1]}{parts[2]}"
                freq_hz = int(float(mhz_str) * 1_000)  # en kHz * 1000 → Hz
                # En fait plus simple : MHz.kHz → freq_hz directement
                freq_hz = int(parts[0]) * 1_000_000 \
                        + int(parts[1]) * 1_000 \
                        + int(parts[2]) * 10
            elif len(parts) <= 2:
                # Format 7.100 → MHz flottant classique
                freq_hz = int(float(raw) * 1_000_000)
            else:
                raise ValueError("format inattendu")

            set_frequency(self.cat, freq_hz)
            self.current_freq_hz = freq_hz
            self._update_freq_display(freq_hz)
            mhz = freq_hz / 1_000_000
            self._set_status(f"Fréquence réglée : {mhz:.3f} MHz")

        except (ValueError, IndexError):
            messagebox.showwarning(
                "Fréquence invalide",
                "Formats acceptés :\n  7.100  ou  7.100.00\n(en MHz)"
            )
        except CATError as e:
            self._show_cat_error(e)

    def _send_mode(self):
        if not self._check_connected():
            return
        mode = self.var_mode.get()
        try:
            set_mode(self.cat, mode)
            self.lbl_mode_disp.config(text=f"MODE : {mode}")
            self._set_status(f"Mode : {mode}")
        except CATError as e:
            self._show_cat_error(e)

    def _step_fast(self, up: bool):
        """Step rapide ±100 kHz (UP/DOWN FAST)."""
        if not self._check_connected():
            return
        try:
            delta = 100_000
            if up:
                step_up(self.cat, large=False)
                self.current_freq_hz = min(self.current_freq_hz + delta, FREQ_MAX_HZ)
                self._set_status("Step ▶▶ +100 kHz")
            else:
                step_down(self.cat, large=False)
                self.current_freq_hz = max(self.current_freq_hz - delta, FREQ_MIN_HZ)
                self._set_status("Step ◀◀ -100 kHz")
            self._update_freq_display(self.current_freq_hz)
        except CATError as e:
            self._show_cat_error(e)

    def _step_fine(self, direction: str):
        """Step fin ±10 Hz (Step Oper. Frequency)."""
        if not self._check_connected():
            return
        try:
            step_fine(self.cat, direction=direction)
            delta = 10
            if direction == "up":
                self.current_freq_hz = min(self.current_freq_hz + delta, FREQ_MAX_HZ)
                self._set_status("Step ▶ +10 Hz")
            else:
                self.current_freq_hz = max(self.current_freq_hz - delta, FREQ_MIN_HZ)
                self._set_status("Step ◀ -10 Hz")
            self._update_freq_display(self.current_freq_hz)
        except CATError as e:
            self._show_cat_error(e)

    def _toggle_lock(self):
        if not self._check_connected():
            return
        try:
            self.locked = not self.locked
            lock(self.cat, self.locked)
            if self.locked:
                self.btn_lock.config(text="🔒 Verrouillé", fg=COLOR_DANGER)
                self._set_status("Panneau verrouillé")
            else:
                self.btn_lock.config(text="🔓 Déverrouillé", fg=COLOR_TEXT)
                self._set_status("Panneau déverrouillé")
        except CATError as e:
            self._show_cat_error(e)

    def _recall_memory(self, channel: int):
        if not self._check_connected():
            return
        try:
            memory_recall(self.cat, channel)
            self._set_status(f"Mémoire {channel} rappelée")
        except CATError as e:
            self._show_cat_error(e)

    def _store_memory(self):
        if not self._check_connected():
            return
        try:
            ch = int(self.var_mem_target.get())
            vfo_to_memory(self.cat, ch)
            self._set_status(f"VFO stocké → mémoire {ch}")
        except (ValueError, CATError) as e:
            self._show_cat_error(e)

    # ------------------------------------------------------------------
    # Polling S-mètre (thread séparé pour ne pas bloquer l'UI)
    # ------------------------------------------------------------------

    def _start_smeter_polling(self):
        self._polling = True
        self._poll_thread = threading.Thread(
            target=self._poll_smeter, daemon=True
        )
        self._poll_thread.start()

    def _stop_smeter_polling(self):
        self._polling = False

    def _poll_smeter(self):
        """
        Lit le S-mètre toutes les 500ms et rafraîchit le status toutes les 5s.
        Le pacing (10ms) configuré à la connexion permet de recevoir les réponses.
        S'arrête silencieusement si le S-mètre ne répond pas après 3 tentatives.
        """
        failures = 0
        MAX_FAILURES = 3
        ticks = 0

        while self._polling and self.connected:
            # Rafraîchissement fréquence/mode toutes les 5s (10 ticks de 500ms)
            ticks += 1
            if ticks % 10 == 0:
                self.after(0, self._read_status_from_radio)

            try:
                response = self.cat.send_command_read(
                    0xF7, expected_bytes=5, read_timeout=3.0
                )
                if len(response) == 5 and response[4] == 0xF7:
                    failures = 0
                    value = response[0]
                    self.after(0, self._draw_smeter, min(value, 12))
                else:
                    raise CATError("réponse invalide")
            except CATError:
                failures += 1
                if failures >= MAX_FAILURES:
                    logger.info("S-mètre non disponible — polling désactivé")
                    return
            time.sleep(0.5)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_connected(self) -> bool:
        if not self.connected:
            messagebox.showinfo("Non connecté",
                                "Connectez-vous d'abord au FRG-100.")
            return False
        return True

    def _read_status_from_radio(self) -> None:
        """
        Lit la fréquence et le mode réels depuis le FRG-100.

        Envoie Status Update avec U=2 → 19 octets en retour.
        Structure du 19-byte Operating Data Record (p.38 manuel) :
          Byte 0    : memory flag (padding)
          Bytes 1   : padding
          Bytes 2-4 : fréquence BCD (3 octets, MSB en premier, dizaines de Hz)
          Bytes 5-6 : padding
          Byte 7    : mode (0=LSB,1=USB,2=CW,3=AM,4=FM)
          Byte 8    : VFO/MEM flags
          Bytes 9-18: padding
        """
        try:
            response = self.cat.send_command_read(
                0x10, args=[0x02], expected_bytes=19, read_timeout=3.0
            )
            if len(response) < 9:
                logger.warning(f"Status Update trop court : {len(response)} octets")
                return

            # Fréquence : 3 octets BCD à l'offset 2-4, MSB en premier
            # Ex : [0x14, 0x25, 0x00] → "142500" → × 10 = 14.250.00 MHz
            b2, b3, b4 = response[2], response[3], response[4]
            freq_str = f"{b2:02x}{b3:02x}{b4:02x}"  # BCD hex → string décimale
            freq_tens = int(freq_str)
            freq_hz = freq_tens * 10

            # Mode à l'offset 7
            mode_byte = response[7]
            mode_names = {0: "LSB", 1: "USB", 2: "CW", 3: "AM", 4: "FM"}
            mode_str = mode_names.get(mode_byte, f"?({mode_byte})")

            if 50_000 <= freq_hz <= 30_000_000:
                self.current_freq_hz = freq_hz
                self._update_freq_display(freq_hz)
                self.lbl_mode_disp.config(text=f"MODE : {mode_str}")
                self.var_mode.set(mode_str if mode_str in MODE else "USB")
                logger.info(f"Status lu : {freq_hz/1e6:.3f} MHz, mode={mode_str}")
            else:
                logger.warning(f"Fréquence hors plage dans Status Update : {freq_hz}")

        except CATError as e:
            logger.warning(f"Status Update échoué : {e}")

    def _update_freq_display(self, freq_hz: int) -> None:
        """Met à jour le LCD vert et le champ de saisie."""
        self.var_freq_disp.set(self._format_freq(freq_hz))
        # Champ de saisie : format MHz simple à 3 décimales (ex: 7.100)
        # On évite les zéros superflus : 7.100 pas 7.10000
        mhz = freq_hz / 1_000_000
        self.var_freq_input.set(f"{mhz:.3f}")

    def _show_cat_error(self, e: Exception):
        messagebox.showerror("Erreur CAT", str(e))
        self._set_status(f"Erreur : {e}")

    def _set_status(self, msg: str):
        self.var_status.set(msg)

    @staticmethod
    def _format_freq(freq_hz: int) -> str:
        """Formate en '14.250.00' — comme l'afficheur du FRG-100 (résolution 10 Hz)."""
        mhz    = freq_hz // 1_000_000
        khz    = (freq_hz % 1_000_000) // 1_000
        dix_hz = (freq_hz % 1_000) // 10
        return f"{mhz:2d}.{khz:03d}.{dix_hz:02d}"
