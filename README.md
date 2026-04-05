# FRG-100 Controller

Logiciel de contrôle PC pour le récepteur radio **Yaesu FRG-100**, via le protocole CAT (Computer Aided Transceiver) sur port série/USB.

Développé pour remplacer les solutions commerciales existantes par un outil simple, transparent et personnalisable.

---

## Contexte

Le Yaesu FRG-100 est un récepteur HF des années 90 (50 kHz – 30 MHz) équipé d'un port CAT permettant le pilotage depuis un ordinateur. Ce projet implémente le protocole CAT documenté dans le manuel officiel Yaesu, afin de contrôler l'appareil depuis Windows via un adaptateur USB-série.

---

## Fonctionnalités prévues

- Réglage de la fréquence d'écoute
- Changement de mode (AM, FM, LSB, USB, CW...)
- Rappel et gestion des canaux mémoire
- Lecture du S-Mètre
- Contrôle du verrouillage, du VFO, de la puissance
- Interface graphique simple (tkinter)

---

## Protocole CAT — rappel technique

Les commandes sont envoyées en **blocs de 5 octets** (de gauche à droite) :

```
[Arg4] [Arg3] [Arg2] [Arg1] [Opcode]
```

**Paramètres série :** 4800 baud, 8 data bits, no parity, 2 stop bits

Les fréquences sont encodées en **BCD packed decimal**, en ordre inverse (centaines de MHz en premier).

**Exemple — syntoniser 14.250 MHz :**
```
01h 00h 42h 50h 00h → opcode 0Ah (Set Operating Frequency)
```

---

## Structure du projet

```
frg100-controller/
│
├── frg100/
│   ├── cat.py          # Couche série : envoi/réception des blocs CAT
│   ├── commands.py     # Implémentation des commandes du manuel
│   └── config.py       # Configuration (port COM, baudrate...)
│
├── gui/
│   └── app.py          # Interface graphique tkinter
│
├── main.py             # Point d'entrée
├── requirements.txt
└── README.md
```

---

## Prérequis

- Python 3.8+
- `pyserial` — communication série

```bash
pip install pyserial
```

---

## Configuration

Par défaut, l'appareil est attendu sur **COM26** (Windows). Modifiable dans `frg100/config.py`.

---

## Matériel

- **Récepteur :** Yaesu FRG-100
- **Connexion :** Port CAT arrière (TTL 0/+5V) → adaptateur USB-série → PC Windows
- **Port détecté :** COM26

---

## Références

- *Yaesu FRG-100 Operating Manual* — section "CAT Control System" (pp. 36–39)
- Protocole CAT Yaesu (19 opcodes, blocs 5 octets)

---

*Projet personnel — développé pour comprendre et maîtriser le protocole CAT du FRG-100, sans dépendre d'un logiciel tiers.*
