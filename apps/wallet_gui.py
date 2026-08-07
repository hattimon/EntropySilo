#!/usr/bin/env python3
"""EntropySilo fullscreen GUI for touchscreens and USB keyboards."""
from __future__ import annotations

import json
import base64
import hashlib
import os
import re
import select
import socket
import subprocess
import sys
import textwrap
import threading
import time
import secrets
from pathlib import Path

DIRECT_FB = os.environ.get("ENTROPYSILO_DIRECT_FB", "0") == "1"
DESKTOP_MODE = os.environ.get("ENTROPYSILO_DESKTOP", "0") == "1"
if DIRECT_FB:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import numpy as np

try:
    from evdev import InputDevice, ecodes, list_devices
except ImportError:
    InputDevice = None

WIDTH, HEIGHT = 480, 320
RAW_TOUCH_EVENT = pygame.USEREVENT + 17
FONT_SIZE, SMALL_FONT_SIZE, LARGE_FONT_SIZE = 32, 24, 40
CONTENT_TOP, FOOTER_Y = 88, 289
BLACK, WHITE, GRAY, DARK = (0, 0, 0), (242, 239, 220), (115, 115, 105), (25, 27, 24)
PHOSPHOR = (166, 230, 156)
CARD_RED = (245, 90, 90)


def map_display_position(position, display_size):
    """Map a physical Live-USB pointer position to the 480x320 logical canvas."""
    display_width, display_height = display_size
    if display_width <= 0 or display_height <= 0:
        return 0, 0
    x = int(position[0] * WIDTH / display_width)
    y = int(position[1] * HEIGHT / display_height)
    return max(0, min(WIDTH - 1, x)), max(0, min(HEIGHT - 1, y))
THEMES = {
    "mono": {"bg": (0, 0, 0), "text": (242, 239, 220), "accent": (242, 239, 220), "dim": (115, 115, 105), "panel": (25, 27, 24), "shadow": (55, 55, 50), "style": "outline"},
    "phosphor": {"bg": (1, 10, 4), "text": (166, 230, 156), "accent": (94, 255, 128), "dim": (55, 130, 72), "panel": (8, 31, 14), "shadow": (2, 65, 18), "style": "crt"},
    "amber": {"bg": (12, 6, 0), "text": (255, 214, 120), "accent": (255, 174, 45), "dim": (145, 91, 35), "panel": (45, 23, 4), "shadow": (86, 42, 4), "style": "bevel"},
    "cobalt": {"bg": (0, 7, 18), "text": (195, 235, 255), "accent": (80, 200, 255), "dim": (70, 112, 145), "panel": (7, 27, 48), "shadow": (3, 60, 95), "style": "bevel"},
    "crimson": {"bg": (14, 0, 3), "text": (255, 215, 210), "accent": (255, 75, 70), "dim": (145, 65, 64), "panel": (47, 8, 12), "shadow": (90, 8, 15), "style": "pixel"},
}
ROOT = Path(__file__).resolve().parent.parent
NODE = os.environ.get("ENTROPYSILO_NODE", "/usr/local/bin/node")
CLI = ROOT / "apps" / "wallet-cli.js"
QR = ROOT / "apps" / "qr-tx.js"
QR_DECODE = ROOT / "apps" / "qr-decode.js"
SWD_BIN = Path(os.environ.get("ENTROPYSILO_SWD_BIN", "/usr/local/bin"))
PRIVILEGED_SOCKET = os.environ.get("ENTROPYSILO_PRIVILEGED_SOCKET", "/run/entropysilo-privileged/control.sock")


class Cancelled(Exception):
    pass

class Locked(Exception):
    pass


def solve_touch_calibration(samples):
    """Wyznacza przeksztalcenie afiniczne raw evdev -> ekran GUI."""
    if len(samples) < 4:
        raise ValueError("Touch calibration needs at least four points.")
    raw = np.array([[sample[0], sample[1], 1.0] for sample in samples], dtype=np.float64)
    target = np.array([[sample[2], sample[3]] for sample in samples], dtype=np.float64)
    coefficients, _, rank, _ = np.linalg.lstsq(raw, target, rcond=None)
    if rank < 3:
        raise ValueError("Touch calibration points are degenerate.")
    predicted = raw @ coefficients
    rms = float(np.sqrt(np.mean(np.sum((predicted - target) ** 2, axis=1))))
    if not np.isfinite(rms) or rms > 35.0:
        raise ValueError(f"Touch calibration error is too large ({rms:.1f}px).")
    return {
        "version": 1,
        "matrix": [
            float(coefficients[0, 0]), float(coefficients[1, 0]), float(coefficients[2, 0]),
            float(coefficients[0, 1]), float(coefficients[1, 1]), float(coefficients[2, 1]),
        ],
        "rmsPixels": round(rms, 2),
    }


class LinuxInputBridge:
    """Przekazuje evdev do kolejki Pygame, gdy SDL działa bez X/Wayland."""
    KEY_MAP = {
        "KEY_UP": pygame.K_UP, "KEY_DOWN": pygame.K_DOWN,
        "KEY_LEFT": pygame.K_LEFT, "KEY_RIGHT": pygame.K_RIGHT,
        "KEY_ENTER": pygame.K_RETURN, "KEY_KPENTER": pygame.K_KP_ENTER,
        "KEY_ESC": pygame.K_ESCAPE, "KEY_BACKSPACE": pygame.K_BACKSPACE,
        "KEY_SPACE": pygame.K_SPACE, "KEY_TAB": pygame.K_TAB,
    }
    PUNCT = {
        "KEY_MINUS": ("-", "_"), "KEY_EQUAL": ("=", "+"),
        "KEY_SLASH": ("/", "?"), "KEY_DOT": (".", ">"),
        "KEY_COMMA": (",", "<"), "KEY_SEMICOLON": (";", ":"),
        "KEY_APOSTROPHE": ("'", '"'),
    }
    SHIFT_DIGITS = ")!@#$%^&*("

    def __init__(self):
        self.devices = []
        self.device_paths = set()
        self.blocked_keyboard_paths = set()
        self.touch = {}
        self.calibration_path = Path(os.environ.get(
            "ENTROPYSILO_TOUCH_CALIBRATION",
            str(Path(os.environ.get("HOME", "/var/lib/entropysilo")) / "touch-calibration.json"),
        ))
        self.calibration = None
        self.shift_keys = set()
        self.caps_lock = False
        self.running = True
        self.allow_keyboard_until = 0.0
        self.reload_calibration()
        if InputDevice is None:
            print("EntropySilo input: python3-evdev missing; USB/touch input unavailable", flush=True)
            self.thread = None
            return
        self._discover(allow_keyboards=True)
        if not self.devices:
            print("EntropySilo input: no evdev device yet; hot-plug detection active", flush=True)
        self.thread = threading.Thread(target=self._run, name="entropysilo-evdev", daemon=True)
        self.thread.start()

    def _discover(self, allow_keyboards=False):
        if InputDevice is None:
            return
        for device_path in list_devices():
            if device_path in self.device_paths: continue
            try:
                device = InputDevice(device_path)
                caps = device.capabilities(absinfo=True)
                if ecodes.EV_KEY not in caps and ecodes.EV_ABS not in caps:
                    device.close(); continue
                absolute = dict(caps.get(ecodes.EV_ABS, []))
                x_code = ecodes.ABS_X if ecodes.ABS_X in absolute else ecodes.ABS_MT_POSITION_X
                y_code = ecodes.ABS_Y if ecodes.ABS_Y in absolute else ecodes.ABS_MT_POSITION_Y
                is_touch = x_code in absolute and y_code in absolute
                is_keyboard = ecodes.EV_KEY in caps and not is_touch
                keyboard_allowed = allow_keyboards or time.monotonic() < self.allow_keyboard_until
                if is_keyboard and not keyboard_allowed:
                    device.close()
                    if device_path not in self.blocked_keyboard_paths:
                        print(f"EntropySilo security: blocked hot-plug HID keyboard {device_path}", flush=True)
                        self.blocked_keyboard_paths.add(device_path)
                    continue
                self.devices.append(device)
                self.device_paths.add(device_path)
                if is_touch:
                    self.touch[device.fd] = {
                        "x": 0, "y": 0, "xcode": x_code, "ycode": y_code,
                        "xmin": absolute[x_code].min, "xmax": absolute[x_code].max,
                        "ymin": absolute[y_code].min, "ymax": absolute[y_code].max,
                    }
            except (OSError, PermissionError):
                continue

    def allow_next_keyboard(self, seconds=60):
        self.allow_keyboard_until = time.monotonic() + max(5, int(seconds))
        self.blocked_keyboard_paths.clear()

    @staticmethod
    def _name(code):
        value = ecodes.KEY.get(code, "")
        return value[0] if isinstance(value, list) else value

    def _keyboard(self, event):
        name = self._name(event.code)
        if name in ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"):
            if event.value:
                self.shift_keys.add(name)
            else:
                self.shift_keys.discard(name)
            return
        if name == "KEY_CAPSLOCK" and event.value == 1:
            self.caps_lock = not self.caps_lock
            return
        if event.value not in (1, 2):
            return
        key = self.KEY_MAP.get(name)
        char = ""
        shift = bool(self.shift_keys)
        if name.startswith("KEY_") and len(name) == 5 and name[-1].isalpha():
            char = name[-1].upper() if shift ^ self.caps_lock else name[-1].lower(); key = ord(name[-1].lower())
        elif name.startswith("KEY_") and len(name) == 5 and name[-1].isdigit():
            digit = int(name[-1]); char = self.SHIFT_DIGITS[digit] if shift else str(digit); key = ord(str(digit))
        elif name.startswith("KEY_KP") and name[-1:].isdigit():
            char = name[-1]; key = ord(char)
        elif name in self.PUNCT:
            char = self.PUNCT[name][1 if shift else 0]; key = ord(self.PUNCT[name][0])
        elif name == "KEY_SPACE": char = " "
        if key is not None:
            modifiers = (pygame.KMOD_SHIFT if shift else 0) | (pygame.KMOD_CAPS if self.caps_lock else 0)
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, unicode=char, mod=modifiers))

    @staticmethod
    def _scale(value, minimum, maximum, size):
        if maximum <= minimum: return 0
        return max(0, min(size - 1, int((value - minimum) * (size - 1) / (maximum - minimum))))

    @property
    def has_touch(self):
        return bool(self.touch)

    def reload_calibration(self):
        self.calibration = None
        try:
            value = json.loads(self.calibration_path.read_text(encoding="utf-8"))
            if value.get("version") == 1 and len(value.get("matrix", [])) == 6:
                self.calibration = value
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    def set_calibration(self, value):
        self.calibration = value

    def _touch_event(self, device, event):
        state = self.touch.get(device.fd)
        if not state: return False
        if event.type == ecodes.EV_ABS and event.code == state["xcode"]: state["x"] = event.value
        elif event.type == ecodes.EV_ABS and event.code == state["ycode"]: state["y"] = event.value
        released = (event.type == ecodes.EV_KEY and event.code in (ecodes.BTN_TOUCH, ecodes.BTN_TOOL_FINGER) and event.value == 0)
        released = released or (event.type == ecodes.EV_ABS and event.code == ecodes.ABS_PRESSURE and event.value == 0)
        if released:
            raw_x, raw_y = state["x"], state["y"]
            xmin, xmax, ymin, ymax = state["xmin"], state["xmax"], state["ymin"], state["ymax"]
            pygame.event.post(pygame.event.Event(
                RAW_TOUCH_EVENT, raw_x=raw_x, raw_y=raw_y,
                xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax,
            ))
            matrix = self.calibration.get("matrix") if self.calibration else None
            if matrix:
                x = int(round(matrix[0] * raw_x + matrix[1] * raw_y + matrix[2]))
                y = int(round(matrix[3] * raw_x + matrix[4] * raw_y + matrix[5]))
                x, y = max(0, min(WIDTH - 1, x)), max(0, min(HEIGHT - 1, y))
            else:
                if os.environ.get("ENTROPYSILO_TOUCH_SWAP", "0") == "1":
                    raw_x, raw_y, xmin, xmax, ymin, ymax = raw_y, raw_x, ymin, ymax, xmin, xmax
                xmin = int(os.environ.get("ENTROPYSILO_TOUCH_X_MIN", xmin))
                xmax = int(os.environ.get("ENTROPYSILO_TOUCH_X_MAX", xmax))
                ymin = int(os.environ.get("ENTROPYSILO_TOUCH_Y_MIN", ymin))
                ymax = int(os.environ.get("ENTROPYSILO_TOUCH_Y_MAX", ymax))
                x = self._scale(raw_x, xmin, xmax, WIDTH)
                y = self._scale(raw_y, ymin, ymax, HEIGHT)
                if os.environ.get("ENTROPYSILO_TOUCH_INVERT_X", "0") == "1": x = WIDTH - 1 - x
                if os.environ.get("ENTROPYSILO_TOUCH_INVERT_Y", "0") == "1": y = HEIGHT - 1 - y
            position = (x, y)
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=position, button=1))
        return True

    def _run(self):
        last_discovery = 0.0
        while self.running:
            try:
                if time.monotonic() - last_discovery > 1.0:
                    self._discover(); last_discovery = time.monotonic()
                if not self.devices:
                    time.sleep(0.25); continue
                ready, _, _ = select.select(self.devices, [], [], 0.5)
                for device in ready:
                    for event in device.read():
                        if not self._touch_event(device, event) and event.type == ecodes.EV_KEY:
                            self._keyboard(event)
            except (OSError, ValueError):
                if self.running: time.sleep(0.2)

    def close(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        for device in self.devices:
            try: device.close()
            except OSError: pass


class DirectFramebuffer:
    """Kopiuje programowy ekran SDL do 16-bitowego RGB565 fbdev."""
    def __init__(self, screen):
        self.screen = screen
        self.handle = None
        self.input = None
        self.rotate = 0
        self.bpp = 16
        if not DIRECT_FB: return
        requested = os.environ.get("SDL_FBDEV", "")
        candidates = ([Path(requested)] if requested.startswith("/dev/") else []) + [Path("/dev/fb1"), Path("/dev/fb0")]
        path = None
        detected = []
        for candidate in dict.fromkeys(candidates):
            if not candidate.exists():
                continue
            try:
                sysfb = Path("/sys/class/graphics") / candidate.name
                candidate_bpp = int((sysfb / "bits_per_pixel").read_text().strip())
                candidate_virtual = (sysfb / "virtual_size").read_text().strip()
                candidate_dimensions = tuple(int(value) for value in candidate_virtual.split(","))
                detected.append(f"{candidate}={candidate_virtual}/{candidate_bpp}bpp")
                if candidate_bpp in (16, 24, 32) and candidate_dimensions in ((WIDTH, HEIGHT), (HEIGHT, WIDTH)):
                    path, bpp, virtual, dimensions = candidate, candidate_bpp, candidate_virtual, candidate_dimensions
                    break
            except (OSError, ValueError):
                detected.append(f"{candidate}=unreadable")
        if path is None:
            details = ", ".join(detected) if detected else "none present"
            raise RuntimeError(f"No compatible framebuffer (need 480x320 or 320x480, 16/24/32bpp): {details}")
        self.rotate = 90 if dimensions == (HEIGHT, WIDTH) else 0
        self.bpp = bpp
        self.handle = path.open("r+b", buffering=0)
        print(f"EntropySilo GUI framebuffer: {path} {virtual} {bpp}bpp", flush=True)
        self.input = LinuxInputBridge()

    def present(self):
        pygame.display.flip()
        if not self.handle: return
        surface = pygame.transform.rotate(self.screen, self.rotate) if self.rotate else self.screen
        rgb8 = pygame.surfarray.array3d(surface).transpose(1, 0, 2).astype(np.uint8, copy=False)
        self.handle.seek(0)
        if self.bpp == 16:
            rgb = rgb8.astype(np.uint16)
            packed = ((rgb[:, :, 0] >> 3) << 11) | ((rgb[:, :, 1] >> 2) << 5) | (rgb[:, :, 2] >> 3)
            payload = packed.astype("<u2", copy=False).tobytes()
        elif self.bpp == 24:
            payload = rgb8[:, :, ::-1].tobytes()  # typowy fbdev BGR888
        else:
            bgra = np.zeros((rgb8.shape[0], rgb8.shape[1], 4), dtype=np.uint8)
            bgra[:, :, 0] = rgb8[:, :, 2]
            bgra[:, :, 1] = rgb8[:, :, 1]
            bgra[:, :, 2] = rgb8[:, :, 0]
            payload = bgra.tobytes()  # typowy fbdev XRGB8888 little-endian
        self.handle.write(payload)

    def close(self):
        if self.input: self.input.close()
        if self.handle: self.handle.close()


class WalletGUI:
    def __init__(self):
        pygame.init()
        pygame.mouse.set_visible(DESKTOP_MODE)
        self.fullscreen = DESKTOP_MODE
        if DESKTOP_MODE:
            # X11/SDL scaling is inconsistent without a desktop environment.  Keep
            # the application on a deterministic 480x320 canvas and explicitly
            # stretch that canvas to the active native display mode in present().
            self.output = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            self.screen = pygame.Surface((WIDTH, HEIGHT)).convert()
            print(f"EntropySilo Live display: {self.output.get_width()}x{self.output.get_height()} -> {WIDTH}x{HEIGHT} logical", flush=True)
        else:
            self.screen = pygame.display.set_mode((WIDTH, HEIGHT), 0)
            self.output = self.screen
        self.hardware = DirectFramebuffer(self.screen)
        pygame.display.set_caption("EntropySilo Offline")
        self.font = pygame.font.SysFont("DejaVu Sans Mono", FONT_SIZE)
        self.small = pygame.font.SysFont("DejaVu Sans Mono", SMALL_FONT_SIZE)
        self.large = pygame.font.SysFont("DejaVu Sans Mono", LARGE_FONT_SIZE, bold=True)
        self.clock = pygame.time.Clock()
        self.running = True
        self.session_wallet = None
        self.session_entry = None
        self.session_pin = None
        self.last_activity = time.monotonic()
        self.auto_lock_enabled = False
        self.settings_path = Path(os.environ.get("HOME", "/var/lib/entropysilo")) / "settings.json"
        self.settings = {"language": "en", "setupComplete": False, "network": "bitcoin", "purpose": 84,
                         "autoLock": 120, "maxFeeSats": 100000, "allowUnknownFee": False,
                         "expert": False, "theme": "mono", "uiMode": "advanced"}
        if self.settings_path.exists():
            try: self.settings.update(json.loads(self.settings_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError): pass
        self.lang = self.settings.get("language", "en")
        self.boot_animation()
        calibration_loaded = bool(self.hardware.input and self.hardware.input.calibration)
        if not DESKTOP_MODE and not self.settings.get("setupComplete") and not calibration_loaded:
            self.calibrate_touch(automatic=True)

    def present(self):
        if DESKTOP_MODE:
            pygame.transform.scale(self.screen, self.output.get_size(), self.output)
            pygame.display.flip()
        else:
            self.hardware.present()

    def tr(self, pl, en):
        return en if self.lang == "en" else pl

    def localize_error(self, message):
        """Translate backend errors without changing technical identifiers or secret data."""
        text = str(message)
        pairs = (
            ("Obsługiwane sieci: bitcoin, testnet, signet.", "Supported networks: bitcoin, testnet, signet."),
            ("PIN musi mieć dokładnie 12 cyfr (brak secure elementu uniemożliwia bezpieczny krótki PIN).", "The PIN must contain exactly 12 digits (without a secure element, a short PIN is not safe)."),
            ("Nieobsługiwany format skarbca.", "Unsupported vault format."),
            ("Niebezpieczne albo nieobsługiwane parametry KDF.", "Unsafe or unsupported KDF parameters."),
            ("Uszkodzony nagłówek skarbca.", "Corrupted vault header."),
            ("Skarbiec nie zawiera obsługiwanego sekretu.", "The vault does not contain a supported secret."),
            ("Nieprawidłowe hasło albo uszkodzony skarbiec.", "Incorrect PIN or corrupted vault."),
            ("Hasło backupu musi mieć co najmniej 12 znaków.", "The backup password must contain at least 12 characters."),
            ("Nieobsługiwany format backupu.", "Unsupported backup format."),
            ("Nieprawidłowe parametry KDF backupu.", "Invalid backup KDF parameters."),
            ("Uszkodzony nagłówek backupu.", "Corrupted backup header."),
            ("Błędne hasło albo uszkodzony backup.", "Incorrect password or corrupted backup."),
            ("Obsługiwane standardy: BIP44, BIP49, BIP84, BIP86.", "Supported standards: BIP44, BIP49, BIP84, BIP86."),
            ("Nieprawidłowy numer konta.", "Invalid account number."),
            ("change musi wynosić 0 albo 1.", "The change value must be 0 or 1."),
            ("Nieprawidłowy indeks adresu.", "Invalid address index."),
            ("Nieprawidłowy klucz prywatny WIF dla wybranej sieci.", "Invalid WIF private key for the selected network."),
            ("Obsługiwane są wyłącznie skompresowane klucze WIF.", "Only compressed WIF keys are supported."),
            ("Surowy klucz prywatny musi mieć dokładnie 64 znaki hex.", "A raw private key must contain exactly 64 hexadecimal characters."),
            ("Surowy klucz prywatny jest poza zakresem secp256k1.", "The raw private key is outside the secp256k1 range."),
            ("PSBT ma ujemną opłatę — odrzucono.", "The PSBT has a negative fee and was rejected."),
            ("Brak klucza prywatnego dla Taproot.", "No private key is available for Taproot."),
            ("Nie udało się utworzyć klucza Taproot.", "Could not create the Taproot key."),
            ("Taproot script-path nie jest obecnie obsługiwany.", "Taproot script-path spending is not currently supported."),
            ("PSBT nie zawiera wejść należących do tego portfela albo brakuje danych BIP32 derivation.", "The PSBT contains no inputs owned by this wallet, or BIP32 derivation data is missing."),
            ("PSBT nie zawiera wejść należących do zaimportowanego klucza WIF.", "The PSBT contains no inputs owned by the imported WIF key."),
            ("Nazwa: 1-32 znaków a-z, A-Z, 0-9, _ lub -.", "Name: 1–32 characters using a-z, A-Z, 0-9, _ or -."),
            ("Nieobsługiwany sekret w skarbcu.", "Unsupported secret in the vault."),
            ("Generowanie: system albo cards. Import używa osobnego polecenia recover.", "Generation method must be system or cards. Import uses the separate recover command."),
            ("Wallet Decoder legacy obsługuje 12 albo 24 słowa.", "Legacy Wallet Decoder supports 12 or 24 words."),
            ("Reset wymaga dokładnego potwierdzenia FACTORY RESET.", "Reset requires the exact FACTORY RESET confirmation."),
            ("Brak portfeli do backupu.", "There are no wallets to back up."),
            ("Nieprawidłowa zawartość backupu.", "Invalid backup contents."),
            ("Zakres adresów jest nieprawidłowy.", "The address range is invalid."),
            ("Podpis wymaga confirm:true po sprawdzeniu wszystkich wyjść i opłaty.", "Signing requires confirm:true after all outputs and the fee have been verified."),
            ("Brak danych QR.", "No QR data was provided."),
            ("Nieprawidłowa klatka RGB.", "Invalid RGB frame."),
            ("Nieprawidłowy rozmiar obrazu QR.", "Invalid QR image size."),
            ("Obsługiwany jest tylko PNG albo JPEG.", "Only PNG or JPEG is supported."),
            ("Nieprawidłowe wymiary obrazu QR.", "Invalid QR image dimensions."),
            ("Nie znaleziono kodu QR na obrazie.", "No QR code was found in the image."),
            ("Dane QR są zbyt duże.", "The QR data is too large."),
            ("Entropia BIP-39 musi mieć 128, 160, 192, 224 albo 256 bitów.", "BIP39 entropy must contain 128, 160, 192, 224, or 256 bits."),
            ("Nowe portfele są generowane wyłącznie z pełnych 256 bitów (24 słowa).", "New wallets are generated only from the full 256 bits (24 words)."),
            ("Nieprawidłowa liczba słów BIP-39.", "Invalid BIP39 word count."),
            ("Suma kontrolna mnemonika BIP-39 jest błędna.", "The BIP39 mnemonic checksum is invalid."),
            ("Losowość systemowa musi mieć 256 bitów.", "System randomness must contain 256 bits."),
            ("BIP-85 wymaga prywatnego klucza root.", "BIP85 requires a private root key."),
            ("Indeks BIP-85 poza zakresem 0..2147483647.", "The BIP85 index is outside the 0..2147483647 range."),
            ("EntropySilo tworzy potomne mnemoniki BIP-85 wyłącznie 24-wyrazowe.", "EntropySilo creates only 24-word BIP85 child mnemonics."),
            ("Nie wszystkie kwoty wejściowe są dostępne; nie można zweryfikować opłaty.", "Not all input amounts are available; the fee cannot be verified."),
            ("PSBT przekracza limit 256 wejść albo 256 wyjść.", "The PSBT exceeds the limit of 256 inputs or 256 outputs."),
            ("(skrypt niestandardowy)", "(non-standard script)"),
        )
        for pl, en in pairs:
            source, target = (pl, en) if self.lang == "en" else (en, pl)
            if text == source:
                return target
        if self.lang == "en":
            prefixes = (
                ("Słowo nie występuje na angielskiej liście BIP-39: ", "The word is not in the English BIP39 list: "),
                ("Backup zawiera uszkodzony skarbiec: ", "The backup contains a corrupted vault: "),
                ("Portfel ", "Wallet "),
                ("Wejście ", "Input "),
                ("Usunięcie wymaga potwierdzenia ", "Deletion requires the confirmation "),
                ("SWD zakończył się kodem ", "SWD exited with code "),
                ("Losowanie 1: ", "Draw 1: "),
                ("Losowanie 2: ", "Draw 2: "),
                ("Pozostawiono częściowo podpisany PSBT: ", "A partially signed PSBT was produced: "),
            )
            for source, target in prefixes:
                if text.startswith(source):
                    text = target + text[len(source):]
                    break
            text = text.replace(" już istnieje.", " already exists.")
            text = text.replace("wymagane jest dokładnie 25 kolejnych kart.", "exactly 25 consecutive cards are required.")
            text = text.replace("25 kart musi być prawidłowych i nie może się powtarzać.", "all 25 cards must be valid and unique.")
            text = text.replace("public key nie zgadza się ze ścieżką.", "the public key does not match the derivation path.")
            text = text.replace("klucz Taproot nie zgadza się ze ścieżką.", "the Taproot key does not match the derivation path.")
        return text

    def save_settings(self, complete=None):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.settings["language"] = self.lang
        if complete is not None: self.settings["setupComplete"] = bool(complete)
        temporary = self.settings_path.with_suffix(".new")
        temporary.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600); temporary.replace(self.settings_path)

    def restart_gui(self, post_onboarding=True):
        pygame.quit()
        arguments = [sys.executable, str(Path(__file__).resolve())]
        if post_onboarding:
            arguments.append("--post-onboarding")
        os.execv(sys.executable, arguments)

    def ask_bip39_passphrase(self, root_label=None):
        prompt = self.tr(
            "Pozostaw puste, jeśli nigdy nie ustawiałeś dodatkowej passphrase („25. słowa”).",
            "Leave empty if you never set an additional passphrase (the “25th word”).",
        )
        if root_label:
            prompt = f"{root_label} • {prompt}"
        value = self.ask("BIP-39 PASSPHRASE", prompt, True, allow_reveal=True, default_ok=True)
        if not value:
            return ""
        repeated = self.ask(
            self.tr("POWTÓRZ BIP39 PASSPHRASE", "REPEAT BIP39 PASSPHRASE"),
            self.tr("Literówka tworzy zupełnie inny portfel.", "A typo creates a completely different wallet."),
            True,
            allow_reveal=True,
        )
        if value != repeated:
            raise ValueError(self.tr("Passphrase nie są identyczne.", "Passphrases do not match."))
        return value

    @property
    def touch_calibration_path(self):
        return self.settings_path.parent / "touch-calibration.json"

    def calibrate_touch(self, automatic=False):
        """Kalibracja nie blokuje startu: ESC/ENTER zawsze pomija caly etap."""
        bridge = self.hardware.input
        detection_deadline = time.monotonic() + (4.0 if automatic else 30.0)
        while not bridge or not bridge.has_touch:
            self.frame(self.tr("KALIBRACJA DOTYKU", "TOUCH CALIBRATION"), self.tr("OPCJONALNA • MOŻNA POMINĄĆ", "OPTIONAL • SAFE TO SKIP"))
            self.text(self.tr("OCZEKIWANIE NA", "WAITING FOR"), 112, 110, self.font)
            self.text(self.tr("EKRAN DOTYKOWY…", "TOUCHSCREEN…"), 91, 150, self.font)
            self.text(self.tr("ESC / ENTER = POMIŃ", "ESC / ENTER = SKIP"), 101, 225, self.small, PHOSPHOR)
            self.present()
            for event in self.events():
                if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE):
                    return False
            if time.monotonic() >= detection_deadline:
                return False
            self.clock.tick(30)

        targets = [(38, 103), (442, 103), (442, 267), (38, 267), (240, 184)]
        samples = []
        pygame.event.clear(RAW_TOUCH_EVENT)
        for index, (target_x, target_y) in enumerate(targets):
            while True:
                self.frame(self.tr("KALIBRACJA DOTYKU", "TOUCH CALIBRATION"), self.tr(f"PUNKT {index + 1}/{len(targets)}", f"POINT {index + 1}/{len(targets)}"))
                pygame.draw.circle(self.screen, PHOSPHOR, (target_x, target_y), 15, 2)
                pygame.draw.line(self.screen, PHOSPHOR, (target_x - 22, target_y), (target_x + 22, target_y), 1)
                pygame.draw.line(self.screen, PHOSPHOR, (target_x, target_y - 22), (target_x, target_y + 22), 1)
                self.text(self.tr("DOTKNIJ KRZYŻYKA", "TOUCH CROSSHAIR"), 122, 238, self.small)
                self.text(self.tr("ESC / ENTER = POMIŃ", "ESC / ENTER = SKIP"), 101, FOOTER_Y, self.small, GRAY)
                self.present()
                accepted = False
                for event in self.events():
                    if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE):
                        return False
                    if event.type == RAW_TOUCH_EVENT:
                        samples.append((event.raw_x, event.raw_y, target_x, target_y))
                        accepted = True
                        break
                if accepted:
                    pygame.time.delay(180)
                    pygame.event.clear(RAW_TOUCH_EVENT)
                    break
                self.clock.tick(30)
        try:
            calibration = solve_touch_calibration(samples)
            calibration["createdAt"] = int(time.time())
            self.touch_calibration_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = self.touch_calibration_path.with_suffix(".new")
            temporary.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(self.touch_calibration_path)
            bridge.set_calibration(calibration)
            self.show(self.tr("DOTYK SKALIBROWANY", "TOUCH CALIBRATED"), self.tr(f"Dokładność: {calibration['rmsPixels']:.1f}px\nENTER / dotyk = dalej", f"Accuracy: {calibration['rmsPixels']:.1f}px\nENTER / touch = continue"))
            return True
        except (OSError, ValueError) as error:
            self.show(self.tr("BŁĄD KALIBRACJI", "CALIBRATION FAILED"), str(error) + "\n" + self.tr("Klawiatura USB pozostaje aktywna.", "USB keyboard remains active."))
            return False

    @property
    def accent(self):
        return self.palette["accent"]

    @property
    def palette(self):
        return THEMES.get(self.settings.get("theme", "mono"), THEMES["mono"])

    @property
    def text_color(self): return self.palette["text"]

    @property
    def background(self): return self.palette["bg"]

    @property
    def panel_color(self): return self.palette["panel"]

    def draw_panel(self, rect, active=False, dangerous=False):
        palette = self.palette; accent = CARD_RED if dangerous else palette["accent"]
        if palette["style"] in ("bevel", "pixel"):
            pygame.draw.rect(self.screen, palette["shadow"], rect.move(4, 4), 0)
        pygame.draw.rect(self.screen, accent if active else palette["panel"], rect, 0)
        pygame.draw.rect(self.screen, palette["text"] if active else accent, rect, 2)
        if palette["style"] == "bevel":
            pygame.draw.line(self.screen, palette["text"], rect.topleft, rect.topright, 2)
            pygame.draw.line(self.screen, palette["text"], rect.topleft, rect.bottomleft, 2)
            pygame.draw.line(self.screen, palette["shadow"], rect.bottomleft, rect.bottomright, 3)
            pygame.draw.line(self.screen, palette["shadow"], rect.topright, rect.bottomright, 3)
        elif palette["style"] == "pixel":
            for offset in (6, 12):
                pygame.draw.line(self.screen, palette["shadow"], (rect.x + offset, rect.bottom - 4), (rect.right - 4, rect.bottom - 4), 1)

    def draw_eye_icon(self, rect, color, revealed=False):
        center_x, center_y = rect.center
        eye = pygame.Rect(center_x - 16, center_y - 9, 32, 18)
        pygame.draw.ellipse(self.screen, color, eye, 2)
        pygame.draw.circle(self.screen, color, (center_x, center_y), 5, 0 if revealed else 2)
        if not revealed:
            pygame.draw.line(self.screen, color, (center_x - 18, center_y + 11), (center_x + 18, center_y - 11), 3)

    def boot_animation(self):
        messages = ["ENTROPYSILO BIOS 0.3", "VERIFYING AIR-GAP...", "ENTROPY SOURCE: KERNEL+CROSSCHECK", "VAULT CIPHER: AES-256-GCM", "NETWORK RADIOS: DISABLED", "READY"]
        self.screen.fill(BLACK)
        for index, message in enumerate(messages):
            shown = self.wrapped_for_font("> " + message, self.small, WIDTH - 28, 1)[0]
            self.text(shown, 14, 15 + index * 49, self.small, PHOSPHOR)
            pygame.draw.rect(self.screen, PHOSPHOR, (14, 43 + index * 49, min(440, (index + 1) * 72), 3))
            self.present(); pygame.time.delay(90)
        pygame.time.delay(180)

    def text(self, value, x, y, font=None, color=None):
        self.screen.blit((font or self.font).render(str(value), True, color or self.text_color), (x, y))

    @staticmethod
    def wrapped_for_font(value, font, width, max_lines=None):
        words = []
        for original in str(value).split():
            word = original
            while word and font.size(word)[0] > width:
                cut = 1
                while cut < len(word) and font.size(word[:cut + 1])[0] <= width: cut += 1
                words.append(word[:cut]); word = word[cut:]
            if word: words.append(word)
        lines, current = [], ""
        for word in words:
            candidate = word if not current else current + " " + word
            if font.size(candidate)[0] <= width:
                current = candidate
            else:
                if current: lines.append(current)
                current = word
        if current or not lines: lines.append(current)
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]
            while lines[-1] and font.size(lines[-1] + "…")[0] > width:
                lines[-1] = lines[-1][:-1]
            lines[-1] += "…"
        return lines

    def frame(self, title, subtitle="OFFLINE • BITCOIN"):
        self.screen.fill(self.background)
        scan = tuple(min(255, channel + 6) for channel in self.background)
        for y in range(3, HEIGHT, 5): pygame.draw.line(self.screen, scan, (5, y), (WIDTH - 5, y))
        pygame.draw.rect(self.screen, self.accent, (4, 4, WIDTH - 8, HEIGHT - 8), 2)
        pygame.draw.rect(self.screen, self.accent, (8, 8, 9, 9), 1)
        title_line = self.wrapped_for_font(title, self.large, WIDTH - 42, 1)[0]
        self.text(title_line, 22, 5, self.large, self.accent)
        pygame.draw.line(self.screen, self.accent, (12, 51), (WIDTH - 12, 51), 1)
        subtitle_line = self.wrapped_for_font(subtitle, self.small, 315, 1)[0]
        self.text(subtitle_line, 14, 56, self.small, self.palette["dim"])
        self.text("[AIR-GAP]", 345, 56, self.small, self.palette["dim"])

    def toggle_fullscreen(self):
        # Live USB only: the logical canvas is unchanged; only its physical target
        # switches between the native full screen and a resizable diagnostic window.
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.output = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.output = pygame.display.set_mode((960, 640), pygame.RESIZABLE)

    def events(self):
        timeout = int(self.settings.get("autoLock", 120))
        if self.auto_lock_enabled and timeout > 0 and self.session_pin and time.monotonic() - self.last_activity > timeout:
            self.session_pin = None; self.session_wallet = None; self.session_entry = None
            raise Locked()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                raise Cancelled()
            if DESKTOP_MODE and event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN and (event.mod & (pygame.KMOD_ALT)):
                self.toggle_fullscreen()
                continue
            if DESKTOP_MODE and event.type == pygame.VIDEORESIZE and not self.fullscreen:
                self.output = pygame.display.set_mode((max(WIDTH, event.w), max(HEIGHT, event.h)), pygame.RESIZABLE)
                continue
            if DESKTOP_MODE and event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                attributes = dict(event.dict)
                attributes["pos"] = map_display_position(event.pos, self.output.get_size())
                event = pygame.event.Event(event.type, attributes)
            if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN): self.last_activity = time.monotonic()
            yield event

    def menu(self, title, items, footer=None):
        if footer is None:
            footer = self.tr("↑↓ / DOTYK • ENTER", "↑↓ / TOUCH • ENTER")
        selected = 0
        while self.running:
            self.frame(title)
            visible_count = 3
            first = min(max(0, selected - visible_count + 1), max(0, len(items) - visible_count))
            visible = list(enumerate(items))[first:first + visible_count]
            y = CONTENT_TOP
            rects = []
            height = 64
            for index, label in visible:
                rect = pygame.Rect(14, y, WIDTH - 28, height - 5)
                rects.append(rect)
                self.draw_panel(rect, index == selected)
                color = self.background if index == selected else self.text_color
                lines = self.wrapped_for_font(f"{index + 1:02d} {label}", self.small, rect.width - 16, 2)
                for line_index, line in enumerate(lines):
                    self.text(line, rect.x + 8, rect.y + 2 + line_index * 27, self.small, color)
                y += height
            page = f"{first + 1}-{first + len(visible)}/{len(items)}"
            footer_line = self.wrapped_for_font(footer, self.small, 330, 1)[0]
            self.text(footer_line, 15, FOOTER_Y, self.small, GRAY)
            page_width = self.small.size(page)[0]
            self.text(page, WIDTH - 15 - page_width, FOOTER_Y, self.small, GRAY)
            self.present()
            for event in self.events():
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE): raise Cancelled()
                    if event.key in (pygame.K_UP, pygame.K_LEFT): selected = (selected - 1) % len(items)
                    elif event.key in (pygame.K_DOWN, pygame.K_RIGHT): selected = (selected + 1) % len(items)
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER): return selected
                    elif pygame.K_1 <= event.key <= pygame.K_9 and event.key - pygame.K_1 < len(items): return event.key - pygame.K_1
                if event.type == pygame.MOUSEBUTTONDOWN:
                    for (index, _), rect in zip(visible, rects):
                        if rect.collidepoint(event.pos): return index
            self.clock.tick(30)
        raise Cancelled()

    def confirm(self, title, body, dangerous=False):
        choice = self.menu(title, [self.tr("POTWIERDZAM", "CONFIRM") if dangerous else self.tr("TAK", "YES"), self.tr("ANULUJ", "CANCEL")], footer=body[:44])
        return choice == 0

    def show(self, title, body, secret=False):
        pages = []
        lines = []
        for raw in str(body).splitlines() or [""]:
            lines.extend(textwrap.wrap(raw, width=31, replace_whitespace=False, drop_whitespace=False) or [""])
        lines_per_page = 7
        for offset in range(0, len(lines), lines_per_page): pages.append(lines[offset:offset + lines_per_page])
        pages = pages or [[""]]
        page = 0
        while True:
            self.frame(title, self.tr("SEKRET • NIE FOTOGRAFUJ", "SECRET • DO NOT PHOTOGRAPH") if secret else "OFFLINE")
            for index, line in enumerate(pages[page]): self.text(line, 12, CONTENT_TOP + index * 28, self.small)
            footer = self.tr(
                f"{page + 1}/{len(pages)}  ←→  ENTER=OK",
                f"{page + 1}/{len(pages)}  ←→  ENTER=OK",
            )
            self.text(footer, 12, FOOTER_Y, self.small, GRAY)
            self.present()
            for event in self.events():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE: raise Cancelled()
                    if event.key in (pygame.K_RIGHT, pygame.K_DOWN): page = min(len(pages) - 1, page + 1)
                    elif event.key in (pygame.K_LEFT, pygame.K_UP): page = max(0, page - 1)
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if page < len(pages) - 1: page += 1
                        else: return
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if page < len(pages) - 1: page += 1
                    else: return
            self.clock.tick(30)

    def ask(self, title, prompt, secret=False, initial="", allow_reveal=False, default_ok=False):
        value, shift, revealed = initial, False, False
        key_rows = ["1234567890", "qwertyuiop", "asdfghjkl:", "zxcvbnm-_./"]
        action_values = ["shift", "space", "back"] + (["eye"] if secret and allow_reveal else []) + ["ok"]
        focus = (4, len(action_values) - 1) if value or default_ok else (0, 0)

        def row_length(row):
            return len(key_rows[row]) if row < 4 else len(action_values)

        def move_focus(row_delta=0, col_delta=0):
            nonlocal focus
            old_row, old_col = focus
            if row_delta:
                new_row = (old_row + row_delta) % 5
                old_max, new_max = row_length(old_row) - 1, row_length(new_row) - 1
                new_col = round((old_col / max(1, old_max)) * new_max)
                focus = (new_row, new_col)
            else:
                focus = (old_row, (old_col + col_delta) % row_length(old_row))

        def activate(key):
            nonlocal value, shift, revealed, focus
            if key == "shift": shift = not shift
            elif key == "space": value += " "
            elif key == "back": value = value[:-1]
            elif key == "eye": revealed = not revealed
            elif key == "ok": return value.strip()
            elif len(value) < 20000:
                value += key
            return None

        while True:
            self.frame(title, prompt)
            shown = "•" * len(value) if secret and not revealed else value
            shown_line = self.wrapped_for_font(shown[-100:], self.small, WIDTH - 28, 1)[0]
            self.text(shown_line, 14, 88, self.small)
            rect_map = []
            y = 119
            for row_index, row in enumerate(key_rows):
                key_width = int((WIDTH - 28) / len(row))
                x = 14
                for col_index, key in enumerate(row):
                    output_key = key.upper() if shift and key.isalpha() else key
                    rect = pygame.Rect(x, y, key_width - 2, 31)
                    rect_map.append((rect, output_key, row_index, col_index))
                    active = focus == (row_index, col_index)
                    self.draw_panel(rect, active)
                    rendered = self.small.render(output_key, True, self.background if active else self.text_color)
                    self.screen.blit(rendered, rendered.get_rect(center=rect.center))
                    x += key_width
                y += 34
            action_labels = {
                "shift": "SHIFT",
                "space": self.tr("SPACJA", "SPACE"),
                "back": self.tr("USUŃ", "DEL"),
                "eye": "",
                "ok": "OK",
            }
            action_width = (WIDTH - 28) // len(action_values)
            for col_index, action in enumerate(action_values):
                label = action_labels[action]
                rect = pygame.Rect(14 + col_index * action_width, 255, action_width - 3, 32)
                rect_map.append((rect, action, 4, col_index))
                active = focus == (4, col_index)
                self.draw_panel(rect, active)
                icon_color = self.background if active else self.text_color
                if action == "eye":
                    self.draw_eye_icon(rect, icon_color, revealed)
                else:
                    rendered = self.small.render(label, True, icon_color)
                    self.screen.blit(rendered, rendered.get_rect(center=rect.center))
            self.text(self.tr("STRZAŁKI + ENTER", "ARROWS + ENTER"), 14, FOOTER_Y, self.small, GRAY)
            self.present()
            for event in self.events():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE: raise Cancelled()
                    if event.key == pygame.K_LEFT: move_focus(col_delta=-1)
                    elif event.key == pygame.K_RIGHT: move_focus(col_delta=1)
                    elif event.key == pygame.K_UP: move_focus(row_delta=-1)
                    elif event.key == pygame.K_DOWN: move_focus(row_delta=1)
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        row, col = focus
                        key = (key_rows[row][col].upper() if shift and key_rows[row][col].isalpha() else key_rows[row][col]) if row < 4 else action_values[col]
                        result = activate(key)
                        if result is not None: return result
                    elif event.key == pygame.K_BACKSPACE:
                        value = value[:-1]; focus = (4, len(action_values) - 1)
                    elif event.unicode and event.unicode.isprintable() and len(value) < 20000:
                        value += event.unicode; focus = (4, len(action_values) - 1)
                if event.type == pygame.MOUSEBUTTONDOWN:
                    for rect, key, row, col in rect_map:
                        if not rect.collidepoint(event.pos): continue
                        focus = (row, col)
                        result = activate(key)
                        if result is not None: return result
                        break
            self.clock.tick(30)

    def password_twice(self):
        first = self.ask_pin(self.tr("USTAW PIN", "SET PIN"), self.tr("dokładnie 12 cyfr", "exactly 12 digits"))
        second = self.ask_pin(self.tr("POWTÓRZ PIN", "REPEAT PIN"), self.tr("wpisz identycznie", "enter the same PIN"))
        if first != second: raise ValueError(self.tr("PIN-y nie są identyczne.", "PINs do not match."))
        return first

    def backup_password_twice(self):
        first = self.ask(self.tr("HASŁO BACKUPU", "BACKUP PASSWORD"), self.tr("minimum 12 znaków", "minimum 12 characters"), True, allow_reveal=True)
        if len(first) < 12: raise ValueError(self.tr("Hasło backupu musi mieć co najmniej 12 znaków.", "Backup password must contain at least 12 characters."))
        second = self.ask(self.tr("POWTÓRZ HASŁO", "REPEAT PASSWORD"), self.tr("wpisz identycznie", "enter exactly the same"), True, allow_reveal=True)
        if first != second: raise ValueError(self.tr("Hasła nie są identyczne.", "Passwords do not match."))
        return first

    def ask_pin(self, title, prompt):
        value, selected = "", 0
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "←", "0", "OK"]
        validation_message_until = 0.0
        while True:
            subtitle = self.tr("PIN MUSI MIEĆ 12 CYFR", "PIN MUST HAVE 12 DIGITS") if time.monotonic() < validation_message_until else prompt
            self.frame(title, subtitle)
            dots = "●" * len(value)
            self.text(dots, 18, 86, self.font)
            count = f"{len(value)}/12"
            self.text(count, WIDTH - 18 - self.small.size(count)[0], 91, self.small, GRAY)
            rects = []
            for index, key in enumerate(keys):
                row, col = divmod(index, 4); rect = pygame.Rect(16 + col * 113, 119 + row * 55, 105, 48)
                rects.append(rect); active = index == selected
                self.draw_panel(rect, active)
                rendered = self.font.render(key, True, self.background if active else self.text_color)
                self.screen.blit(rendered, rendered.get_rect(center=rect.center))
            self.text(self.tr("STRZAŁKI + ENTER", "ARROWS + ENTER"), 16, FOOTER_Y, self.small, GRAY)
            self.present()
            pressed = None
            for event in self.events():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE: raise Cancelled()
                    if event.key == pygame.K_LEFT: selected = (selected - 1) % 12
                    elif event.key == pygame.K_RIGHT: selected = (selected + 1) % 12
                    elif event.key == pygame.K_UP: selected = (selected - 4) % 12
                    elif event.key == pygame.K_DOWN: selected = (selected + 4) % 12
                    elif event.key == pygame.K_BACKSPACE: pressed = "←"; selected = 11
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER): pressed = keys[selected]
                    elif event.unicode and event.unicode in "0123456789": pressed = event.unicode; selected = 11
                if event.type == pygame.MOUSEBUTTONDOWN:
                    for index, rect in enumerate(rects):
                        if rect.collidepoint(event.pos): selected = index; pressed = keys[index]; break
            if pressed == "←": value = value[:-1]
            elif pressed == "OK":
                if len(value) == 12: return value
                validation_message_until = time.monotonic() + 1.5
            elif pressed and len(value) < 12: value += pressed
            self.clock.tick(30)

    def unlock(self):
        entries = self.wallet_catalog(False)
        if not entries: return
        entry = entries[0] if len(entries) == 1 else self.select_wallet()
        name = entry["name"]
        while True:
            pin = self.ask_pin(self.tr("ODBLOKUJ", "UNLOCK"), name)
            try:
                self.run_json(["verify"], {"name": name, "passphrase": pin})
                self.session_wallet, self.session_entry, self.session_pin = name, entry, pin; self.last_activity = time.monotonic(); return
            except RuntimeError:
                self.show(self.tr("BŁĘDNY PIN", "WRONG PIN"), self.tr("Odczekaj i spróbuj ponownie.", "Wait and try again."))
                time.sleep(2)

    def credentials(self):
        if not self.session_pin: self.unlock()
        if not self.session_pin: raise ValueError(self.tr("Brak odblokowanego portfela.", "No unlocked wallet."))
        return self.session_wallet, self.session_pin

    def choose_wallet_credentials(self, title=None):
        entry = self.select_wallet(False, title or self.tr("WYBIERZ PORTFEL", "SELECT WALLET"))
        return self.credentials_for_entry(entry)

    def credentials_for_entry(self, entry):
        name = entry["name"]
        if self.session_wallet == name and self.session_pin:
            self.session_entry = entry
            return name, self.session_pin, entry
        pin = self.ask_pin(self.tr("ODBLOKUJ PORTFEL", "UNLOCK WALLET"), name)
        self.run_json(["verify"], {"name": name, "passphrase": pin})
        self.session_wallet, self.session_entry, self.session_pin = name, entry, pin
        self.last_activity = time.monotonic()
        return name, pin, entry

    def run_json(self, args, data):
        command = [NODE, str(CLI), *args]
        if args and args[0] in ("list", "catalog"):
            completed = subprocess.run(command, input=json.dumps(data), text=True, capture_output=True, timeout=30, check=False)
        else:
            completed = self.run_busy_process(command, json.dumps(data), 180, self.tr("BEZPIECZNA OPERACJA", "SECURE OPERATION"))
        output = completed.stdout.strip() or completed.stderr.strip()
        try: parsed = json.loads(output)
        except json.JSONDecodeError: raise RuntimeError(output or self.tr("Brak odpowiedzi programu.", "No response from the program."))
        if completed.returncode != 0 or "error" in parsed: raise RuntimeError(parsed.get("error", output))
        return parsed

    def usb_call(self, action, input_bytes=b"", timeout=60):
        if not isinstance(input_bytes, bytes): raise TypeError("Privileged input must be bytes.")
        request = json.dumps({"action": action, "size": len(input_bytes)}, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(timeout); connection.connect(PRIVILEGED_SOCKET)
                connection.sendall(request + input_bytes); connection.shutdown(socket.SHUT_WR)
                stream = connection.makefile("rb")
                header_line = stream.readline(4097)
                if not header_line or len(header_line) > 4096: raise RuntimeError("Invalid privileged response header.")
                header = json.loads(header_line); size = header.get("size")
                if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > 16 * 1024 * 1024: raise RuntimeError("Invalid privileged response size.")
                chunks, remaining = [], size
                while remaining:
                    chunk = stream.read(min(65536, remaining))
                    if not chunk: raise RuntimeError("Incomplete privileged response.")
                    chunks.append(chunk); remaining -= len(chunk)
                payload = b"".join(chunks)
                if not header.get("ok"):
                    raise RuntimeError(header.get("error") or self.tr("Błąd bezpiecznej obsługi USB.", "Secure USB operation failed."))
                return payload
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError(self.tr("Usługa bezpiecznych operacji jest niedostępna: ", "Secure operation service is unavailable: ") + str(error)) from error

    def decode_qr_bytes(self, image_bytes, image_format):
        request = {"format": image_format, "dataBase64": base64.b64encode(image_bytes).decode("ascii")}
        result = self.run_busy_process([NODE, str(QR_DECODE)], json.dumps(request), 90, self.tr("DEKODOWANIE QR", "DECODING QR"))
        output = result.stdout.strip() or result.stderr.strip()
        try: parsed = json.loads(output)
        except json.JSONDecodeError: raise RuntimeError(output or self.tr("Dekoder QR nie odpowiedział.", "QR decoder failed."))
        if result.returncode != 0 or parsed.get("error"): raise RuntimeError(parsed.get("error", output))
        return parsed["data"].strip()

    def qr_from_usb_image(self):
        image_format = ["png", "jpg"][self.menu(self.tr("OBRAZ QR NA USB", "USB QR IMAGE"), [
            "/EntropySilo/unsigned-qr.png", "/EntropySilo/unsigned-qr.jpg"])]
        data = self.usb_call("read-qr-" + image_format, timeout=90)
        return self.decode_qr_bytes(data, image_format)

    @staticmethod
    def enable_uvc_autofocus(device):
        tool = "/usr/bin/v4l2-ctl"
        if not Path(tool).exists(): return False
        for control in ("focus_automatic_continuous=1", "focus_auto=1"):
            completed = subprocess.run([tool, "-d", str(device), "--set-ctrl", control],
                capture_output=True, timeout=4, check=False)
            if completed.returncode == 0: return True
        return False

    @staticmethod
    def camera_focus_score(frame):
        sample = pygame.transform.smoothscale(frame, (160, 120))
        pixels = pygame.surfarray.array3d(sample).astype(np.int16)
        gray = (pixels[:, :, 0] * 3 + pixels[:, :, 1] * 6 + pixels[:, :, 2]) // 10
        horizontal = np.abs(np.diff(gray, axis=0)).mean()
        vertical = np.abs(np.diff(gray, axis=1)).mean()
        return float(horizontal + vertical)

    @staticmethod
    def camera_device_label(device):
        name = Path(str(device)).name
        sys_name = Path("/sys/class/video4linux") / name / "name"
        try:
            label = sys_name.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            label = "UVC CAMERA"
        return f"{label} • {device}"

    @staticmethod
    def camera_capture_devices(devices):
        tool = "/usr/bin/v4l2-ctl"
        normalized = [item.decode("utf-8", "replace") if isinstance(item, bytes) else str(item) for item in devices]
        if not Path(tool).exists():
            return normalized
        capture = []
        for device in normalized:
            try:
                completed = subprocess.run([tool, "-d", device, "--get-fmt-video"],
                    capture_output=True, timeout=4, check=False)
                if completed.returncode == 0:
                    capture.append(device)
            except (OSError, subprocess.SubprocessError):
                continue
        return capture or normalized

    @staticmethod
    def camera_resolutions(device):
        """Return conservative V4L2 modes, preferring sizes practical on Pi 2."""
        preferred = [(640, 480), (800, 600), (1280, 720), (1920, 1080)]
        tool = "/usr/bin/v4l2-ctl"
        detected = []
        if Path(tool).exists():
            try:
                completed = subprocess.run([tool, "-d", str(device), "--list-formats-ext"],
                    capture_output=True, text=True, timeout=6, check=False)
                if completed.returncode == 0:
                    import re
                    for width, height in re.findall(r"\b(\d{2,5})x(\d{2,5})\b", completed.stdout):
                        mode = (int(width), int(height))
                        if 160 <= mode[0] <= 1920 and 120 <= mode[1] <= 1080 and mode not in detected:
                            detected.append(mode)
            except (OSError, subprocess.SubprocessError):
                pass
        ordered = [mode for mode in preferred if mode in detected]
        ordered += sorted((mode for mode in detected if mode not in ordered), key=lambda mode: mode[0] * mode[1])
        # Some UVC drivers can scale to 640x480 even when it is not advertised.
        if (640, 480) not in ordered: ordered.insert(0, (640, 480))
        return (ordered or preferred)[:6]

    def confirm_camera_qr(self, frame, data, focus_score):
        digest = hashlib.sha256(data.encode("utf-8")).hexdigest()[:16].upper()
        normalized = data.strip()
        if normalized.startswith("cHNidP"): data_type = "PSBT • BASE64"
        elif normalized.lower().startswith("70736274ff"): data_type = "PSBT • HEX"
        elif normalized.lower().startswith("bitcoin:"): data_type = "BITCOIN URI"
        else: data_type = "QR TEXT"
        confirm_rect, retry_rect = pygame.Rect(12, 250, 220, 34), pygame.Rect(248, 250, 220, 34)
        selected = 0
        while True:
            self.frame(self.tr("QR WYKRYTY", "QR DETECTED"), self.tr("ZAMROŻONY KADR • POTWIERDŹ", "FROZEN FRAME • CONFIRM"))
            preview = pygame.transform.smoothscale(frame, (220, 150)); self.screen.blit(preview, (12, 88))
            pygame.draw.rect(self.screen, PHOSPHOR, (12, 88, 220, 150), 3)
            self.text(data_type, 247, 92, self.small, PHOSPHOR)
            self.text(f"LEN: {len(data)}", 247, 125, self.small)
            self.text(f"FOCUS: {focus_score:.1f}", 247, 158, self.small)
            self.text("SHA256:", 247, 191, self.small, self.palette["dim"])
            self.text(digest, 247, 217, self.small, self.palette["dim"])
            for index, (rect, label) in enumerate(((confirm_rect, self.tr("UŻYJ", "USE")), (retry_rect, self.tr("PONÓW", "RETRY")))):
                self.draw_panel(rect, index == selected)
                color = self.background if index == selected else self.text_color
                rendered = self.small.render(label, True, color); self.screen.blit(rendered, rendered.get_rect(center=rect.center))
            self.text("←→ • ENTER • R=RETRY • ESC", 12, FOOTER_Y, self.small, self.palette["dim"])
            self.present()
            for event in self.events():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE: raise Cancelled()
                    if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_TAB): selected = 1 - selected
                    elif event.key in (pygame.K_r, pygame.K_BACKSPACE): return False
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER): return selected == 0
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if confirm_rect.collidepoint(event.pos): return True
                    if retry_rect.collidepoint(event.pos): return False
            self.clock.tick(30)

    def qr_from_uvc_camera(self):
        try:
            import pygame.camera
            pygame.camera.init(); devices = pygame.camera.list_cameras()
        except Exception as error: raise RuntimeError(self.tr("Brak obsługi kamery UVC: ", "UVC camera unavailable: ") + str(error))
        if not devices:
            devices = [str(path) for path in sorted(Path("/dev").glob("video*"))]
        if not devices: raise RuntimeError(self.tr("Nie wykryto kamery zgodnej z UVC (/dev/video*).", "No UVC-compatible camera detected (/dev/video*)."))
        devices = self.camera_capture_devices(devices)
        camera = None; device_index = -1; autofocus = False; camera_mode = (0, 0); frame = None

        def switch_camera(start_index):
            nonlocal camera, device_index, autofocus, camera_mode, frame
            if camera is not None:
                try: camera.stop()
                except Exception: pass
                camera = None
            errors = []
            for offset in range(len(devices)):
                candidate_index = (start_index + offset) % len(devices)
                candidate = devices[candidate_index]
                for resolution in self.camera_resolutions(candidate):
                    opened = None
                    try:
                        self.frame(self.tr("KAMERA / HDMI", "CAMERA / HDMI"), self.tr("TEST ŹRÓDŁA • ESC=ANULUJ", "TESTING SOURCE • ESC=CANCEL"))
                        label = self.camera_device_label(candidate)
                        self.text(self.wrapped_for_font(label, self.small, WIDTH - 32, 2)[0], 16, 125, self.small, PHOSPHOR)
                        self.text(f"{resolution[0]}x{resolution[1]}", 16, 178, self.font, WHITE)
                        self.present()
                        for event in self.events():
                            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: raise Cancelled()
                        opened = pygame.camera.Camera(candidate, resolution)
                        opened.start()
                        deadline = time.monotonic() + 3.0
                        while time.monotonic() < deadline:
                            for event in self.events():
                                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: raise Cancelled()
                            query = getattr(opened, "query_image", None)
                            if query is None or query():
                                frame = opened.get_image()
                                break
                            time.sleep(0.05)
                        if frame is None: raise RuntimeError("no video frames")
                        camera, device_index, camera_mode = opened, candidate_index, frame.get_size()
                        autofocus = self.enable_uvc_autofocus(candidate)
                        return
                    except Exception as error:
                        errors.append(f"{candidate} {resolution[0]}x{resolution[1]}: {error}")
                        frame = None
                        try:
                            if opened is not None: opened.stop()
                        except Exception: pass
            raise RuntimeError(self.tr("Nie udało się otworzyć żadnego źródła kamery. ", "Could not open any camera source. ") + " | ".join(errors))

        self.frame(self.tr("KAMERA / HDMI", "CAMERA / HDMI"), self.tr("WYKRYWANIE ŹRÓDŁA WIDEO…", "DETECTING VIDEO SOURCE…"))
        self.text(self.tr("Może potrwać kilka sekund", "This may take a few seconds"), 76, 150, self.small, PHOSPHOR)
        self.present()
        switch_camera(0)
        last_scan = 0.0; force_scan = False; focus_score = 0.0
        status = self.tr("USTAW QR W RAMCE", "ALIGN QR INSIDE FRAME")
        try:
            while True:
                try:
                    frame = camera.get_image(frame)
                except Exception:
                    if len(devices) < 2: raise
                    switch_camera(device_index + 1); frame = None
                    status = self.tr("AUTOMATYCZNIE ZMIENIONO ŹRÓDŁO", "CAMERA SOURCE CHANGED AUTOMATICALLY")
                    continue
                focus_score = self.camera_focus_score(frame)
                focus_label = self.tr("AUTO", "AUTO") if autofocus else self.tr("HDMI / KAMERA", "HDMI / CAMERA")
                camera_label = self.camera_device_label(devices[device_index]) + f" • {camera_mode[0]}x{camera_mode[1]}"
                self.frame(self.tr("SKANUJ QR", "SCAN QR"), f"{status} • AF:{focus_label} • {focus_score:.1f}")
                preview = pygame.transform.smoothscale(frame, (288, 192)); self.screen.blit(preview, (96, 82))
                pygame.draw.rect(self.screen, self.accent, (132, 101, 216, 154), 3)
                pygame.draw.line(self.screen, self.accent, (132, 101), (158, 101), 5)
                pygame.draw.line(self.screen, self.accent, (322, 255), (348, 255), 5)
                source_rect = pygame.Rect(8, 281, 205, 31)
                source_text = self.tr("C/TAB=ŹRÓDŁO", "C/TAB=SOURCE")
                self.text(source_text, 13, FOOTER_Y, self.small, self.palette["dim"])
                short_label = self.wrapped_for_font(camera_label, self.small, 245, 1)[0]
                self.text(short_label, 222, FOOTER_Y, self.small, self.palette["dim"])
                self.present()
                for event in self.events():
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: raise Cancelled()
                    if event.type == pygame.KEYDOWN and event.key in (pygame.K_c, pygame.K_TAB):
                        switch_camera(device_index + 1); frame = None
                        status = self.tr("ZMIENIONO ŹRÓDŁO", "CAMERA SOURCE CHANGED")
                        continue
                    if event.type == pygame.MOUSEBUTTONDOWN and source_rect.collidepoint(event.pos):
                        switch_camera(device_index + 1); frame = None
                        status = self.tr("ZMIENIONO ŹRÓDŁO", "CAMERA SOURCE CHANGED")
                        continue
                    if (event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER)) or event.type == pygame.MOUSEBUTTONDOWN: force_scan = True
                now = time.monotonic()
                if force_scan or now - last_scan >= 0.9:
                    force_scan = False; last_scan = now
                    scan_frame = frame
                    width, height = scan_frame.get_size()
                    if width > 960 or height > 540:
                        scale = min(960 / width, 540 / height)
                        scan_frame = pygame.transform.smoothscale(scan_frame, (max(1, int(width * scale)), max(1, int(height * scale))))
                    width, height = scan_frame.get_size(); rgb = pygame.image.tostring(scan_frame, "RGB")
                    request = {"format": "rgb", "width": width, "height": height, "dataBase64": base64.b64encode(rgb).decode("ascii")}
                    completed = subprocess.run([NODE, str(QR_DECODE)], input=json.dumps(request), text=True,
                        capture_output=True, timeout=20, check=False)
                    output = completed.stdout.strip() or completed.stderr.strip()
                    try: parsed = json.loads(output)
                    except json.JSONDecodeError: parsed = {"error": output or "QR decoder failed"}
                    if completed.returncode == 0 and parsed.get("data"):
                        decoded = parsed["data"].strip(); frozen = frame.copy()
                        if self.confirm_camera_qr(frozen, decoded, focus_score): return decoded
                        status = self.tr("PONOWNE SKANOWANIE", "SCANNING AGAIN"); last_scan = time.monotonic()
                        continue
                    status = self.tr("NIE WYKRYTO • PRZYSUŃ / ODDAL QR", "NOT DETECTED • MOVE QR CLOSER / FARTHER")
                self.clock.tick(12)
        finally:
            if camera is not None:
                try: camera.stop()
                except Exception: pass
            pygame.camera.quit()

    def import_secret_usb(self, first_run=False):
        self.show(self.tr("IMPORT USB", "USB IMPORT"), self.tr(
            "Umieść JEDEN sekret w /EntropySilo/import.txt: 12 lub 24 słowa BIP39; swd1:hasło:liczba[:12/:24]; swd2:hasło:liczba[:12/:24]; WIF; albo 64 znaki hex klucza prywatnego. Bez końcówki SWD domyślne są 24 słowa. Plik nie zostanie uruchomiony ani skopiowany.",
            "Put ONE secret in /EntropySilo/import.txt: 12 or 24 BIP39 words; swd1:password:number[:12/:24]; swd2:password:number[:12/:24]; WIF; or a 64-character private-key hex. SWD defaults to 24 words without a suffix. The file will not be executed or copied."))
        raw = self.usb_call("read-secret", timeout=90)
        try: value = raw.decode("utf-8-sig").strip()
        except UnicodeDecodeError: raise ValueError(self.tr("import.txt musi być tekstem UTF-8.", "import.txt must be UTF-8 text."))
        lowered = value.lower()
        for prefix in ("mnemonic:", "seed:", "wif:", "private-key:", "private_key:"):
            if lowered.startswith(prefix): value = value[len(prefix):].strip(); lowered = value.lower(); break
        words = value.split()
        if lowered.startswith(("swd1:", "swd2:")):
            value = value.replace("[:12]", ":12").replace("[:24]", ":24")
            parts = [part.strip() for part in value.split(":")]; value = ":".join(parts)
            if len(parts) == 3: value += ":24"
            if len(value.split(":")) != 4 or value.split(":")[-1] not in ("12", "24"):
                raise ValueError(self.tr("SWD: użyj swd1/swd2:hasło:liczba[:12/:24].", "SWD: use swd1/swd2:password:number[:12/:24]."))
            count = value.rsplit(':', 1)[-1]
            detected, command, secret_key = self.tr(f"{value.split(':', 1)[0].upper()} • {count} SŁÓW", f"{value.split(':', 1)[0].upper()} • {count} WORDS"), "recover-swd", "recoveryCode"
        elif len(words) in (12, 15, 18, 21, 24):
            detected, command, secret_key = self.tr(f"BIP39 • {len(words)} SŁÓW", f"BIP39 • {len(words)} WORDS"), "recover", "mnemonic"
        elif len(value) == 64 and all(character in "0123456789abcdefABCDEF" for character in value):
            detected, command, secret_key = self.tr("KLUCZ PRYWATNY • HEX • SKOMPRESOWANY", "PRIVATE KEY • HEX • COMPRESSED"), "recover-private-key", "privateKeyHex"
        elif 50 <= len(value) <= 52 and value[0] in "5KLc9":
            detected, command, secret_key = self.tr("KLUCZ PRYWATNY • WIF", "PRIVATE KEY • WIF"), "recover-wif", "wif"
        else: raise ValueError(self.tr("Nie rozpoznano obsługiwanego sekretu w import.txt.", "No supported secret was recognized in import.txt."))
        self.show(self.tr("WYKRYTO", "DETECTED"), detected + "\n" + self.tr("Sekret pozostaje zamaskowany.", "The secret remains masked."))
        name = self.ask(self.tr("NAZWA PORTFELA", "WALLET NAME"), "a-z A-Z 0-9 _ -")
        pin = self.password_twice(); request = {"name": name, "passphrase": pin, secret_key: value, "network": self.settings.get("network", "bitcoin")}
        result = self.run_json([command], request)
        first = result.get("firstAddress") or (result.get("types") or [{}])[0]
        self.session_wallet, self.session_pin = name, pin
        address_label = self.tr("ADRES", "ADDRESS")
        self.show(self.tr("ZAIMPORTOWANO", "IMPORTED"), f"{name}\n{detected}\n{address_label}:\n{first.get('address', 'N/A')}")
        if not first_run:
            self.restart_gui()
        return True

    def backup_to_usb(self):
        entries = self.wallet_catalog(True)
        if not entries: raise ValueError(self.tr("Brak portfeli do backupu.", "There are no wallets to back up."))
        self.show(self.tr("BACKUP USB", "USB BACKUP"), self.tr(
            "Podłącz jeden pendrive FAT32/exFAT. Zapis nastąpi tylko w /EntropySilo. Istniejące pliki nie będą kasowane ani nadpisywane; kolejna kopia otrzyma następny numer.",
            "Connect one FAT32/exFAT USB drive. Only /EntropySilo will be written. Existing files will not be deleted or overwritten; the next backup gets the next number."))
        password = self.backup_password_twice()
        backup = self.run_json(["backup-export"], {"backupPassphrase": password})
        encoded = (json.dumps(backup, separators=(",", ":")) + "\n").encode("utf-8")
        path = self.usb_call("write-backup", encoded, 180).decode("utf-8", "replace").strip()
        self.show(self.tr("BACKUP ZAPISANY", "BACKUP SAVED"), self.tr(
            f"Zapisano: {path}\nPortfele: {len(entries)}\nDo odtworzenia potrzebne są ten plik i hasło backupu.",
            f"Saved: {path}\nWallets: {len(entries)}\nThis file and the backup password are required for recovery."))

    def backup_choices(self):
        raw = self.usb_call("list-backups").decode("utf-8", "replace")
        choices = []
        for line in raw.splitlines():
            fields = line.split("\t")
            if len(fields) != 4: continue
            name, number_text, size_text, modified_text = fields
            if not re.fullmatch(r"backup\d*\.(?:eswb|rpwb)", name): continue
            try:
                number, size, modified = int(number_text), int(size_text), int(modified_text)
                date = time.strftime("%Y-%m-%d %H:%M", time.localtime(modified))
            except (ValueError, OverflowError, OSError): continue
            choices.append({"name": name, "number": number, "size": size, "date": date})
        choices.sort(key=lambda item: item["number"])
        if not choices: raise ValueError(self.tr("Nie znaleziono backupów w /EntropySilo ani w starszym /RPiWallet.", "No backups were found in /EntropySilo or the legacy /RPiWallet folder."))
        return choices

    def psbt_choices(self):
        raw = self.usb_call("list-psbts", timeout=90).decode("utf-8", "replace")
        choices = []
        for line in raw.splitlines():
            fields = line.split("\t")
            if len(fields) != 3:
                continue
            name, size_text, modified_text = fields
            if not name.endswith(".psbt"):
                continue
            try:
                size, modified = int(size_text), int(modified_text)
                date = time.strftime("%Y-%m-%d %H:%M", time.localtime(modified))
            except (ValueError, OverflowError, OSError):
                continue
            choices.append({"name": name, "size": size, "date": date})
        if not choices:
            raise ValueError(self.tr(
                "Nie znaleziono plików .psbt w folderze /EntropySilo na pendrivie.",
                "No .psbt files were found in the /EntropySilo folder on the USB drive.",
            ))
        return choices

    def select_psbt_from_usb(self):
        self.show(self.tr("WYBIERZ TRANSAKCJĘ", "SELECT TRANSACTION"), self.tr(
            "Odczytane zostaną tylko zwykłe pliki .psbt z folderu /EntropySilo. Żaden plik nie zostanie uruchomiony ani zmieniony.",
            "Only regular .psbt files from /EntropySilo will be read. No file will be executed or modified.",
        ))
        choices = self.psbt_choices()
        labels = [f"{item['name']} • {(item['size'] + 1023) // 1024} KiB • {item['date']}" for item in choices]
        selected = choices[self.menu(self.tr("PLIK DO PODPISU", "FILE TO SIGN"), labels)]
        payload = self.usb_call("read-selected-psbt", (selected["name"] + "\n").encode("ascii"), 90)
        try:
            return payload.decode("ascii").strip(), selected["name"]
        except UnicodeDecodeError as error:
            raise ValueError(self.tr("Plik PSBT musi zawierać Base64 albo hex ASCII.", "The PSBT file must contain ASCII Base64 or hex.")) from error

    def restore_backup_usb(self, first_run=False):
        self.show(self.tr("ODTWARZANIE USB", "USB RESTORE"), self.tr(
            "Podłącz DRUGI pendrive FAT32/exFAT — nośnik startowy Live jest celowo wykluczony. Odczytane zostaną pliki /EntropySilo/backup[liczba].eswb, starsze .rpwb oraz kopie ze starszego katalogu /RPiWallet.",
            "Connect a SECOND FAT32/exFAT USB drive—the Live boot medium is deliberately excluded. /EntropySilo/backup[number].eswb, legacy .rpwb and backups in the old /RPiWallet folder are supported."))
        choices = self.backup_choices()
        labels = [f"{item['name']} • {(item['size'] + 1023) // 1024} KiB • {item['date']}" for item in choices]
        selected = choices[self.menu(self.tr("WYBIERZ BACKUP", "SELECT BACKUP"), labels,
            footer=self.tr("Największy numer = najnowszy", "Highest number = newest"))]
        encrypted = self.usb_call("read-backup", (selected["name"] + "\n").encode("ascii"), 90)
        try: backup = json.loads(encrypted.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError): raise ValueError(self.tr("Wybrany plik nie jest prawidłowym backupem EntropySilo.", "The selected file is not a valid EntropySilo backup."))
        password = self.ask(self.tr("HASŁO BACKUPU", "BACKUP PASSWORD"), selected["name"], True, allow_reveal=True)
        result = self.run_json(["backup-import"], {"backup": backup, "backupPassphrase": password})
        names = ", ".join(result.get("restored", []))
        self.session_pin = None; self.session_wallet = None; self.session_entry = None
        self.show(self.tr("BACKUP ODTWORZONY", "BACKUP RESTORED"), self.tr(
            f"Plik: {selected['name']}\nPrzywrócono: {names}\nPortfele zachowały swoje dotychczasowe PIN-y.",
            f"File: {selected['name']}\nRestored: {names}\nWallets retain their existing PINs."))
        return bool(result.get("count"))

    def run_swd(self, wrapper, value):
        completed = self.run_busy_process([str(SWD_BIN / wrapper)], value, 180, self.tr("DEKODOWANIE SWD", "DECODING SWD"))
        if completed.returncode != 0: raise RuntimeError(completed.stderr.strip())
        return json.loads(completed.stdout)

    def run_busy_process(self, command, input_text, timeout, label):
        result = {}
        def worker():
            try:
                result["completed"] = subprocess.run(command, input=input_text, text=True, capture_output=True, timeout=timeout, check=False)
            except Exception as error:
                result["error"] = error
        thread = threading.Thread(target=worker, name="entropysilo-operation", daemon=True)
        thread.start(); started = time.monotonic()
        while thread.is_alive():
            self.frame(label, self.tr("PROSZĘ CZEKAĆ • OCHRONA KDF AKTYWNA", "PLEASE WAIT • KDF PROTECTION ACTIVE"))
            phase = int((time.monotonic() - started) * 8) % 18
            self.text(self.tr("PRACA", "WORKING"), 142, 126, self.font, self.accent)
            for index in range(18):
                color = self.accent if index <= phase else DARK
                pygame.draw.rect(self.screen, color, (24 + index * 24, 190, 17, 24), 0)
            self.text(self.tr("NIE WYŁĄCZAJ", "DO NOT POWER OFF"), 110, 244, self.small, GRAY)
            self.present(); pygame.event.pump(); self.clock.tick(20)
        pygame.event.clear(pygame.KEYDOWN); pygame.event.clear(pygame.MOUSEBUTTONDOWN)
        if "error" in result: raise result["error"]
        return result["completed"]

    def wallets(self):
        return self.select_wallet()["name"]

    def wallet_catalog(self, include_hidden=False):
        return self.run_json(["catalog"], {"includeHidden": include_hidden}).get("wallets", [])

    def source_label(self, entry):
        labels = {
            "generated-cards": self.tr("ROOT • KARTY", "ROOT • CARDS"),
            "generated-csprng": self.tr("ROOT • CSPRNG", "ROOT • CSPRNG"),
            "imported-bip39": self.tr("IMPORT • BIP39", "IMPORT • BIP39"),
            "imported-swd1": self.tr("IMPORT • SWD1", "IMPORT • SWD1"),
            "imported-swd2": self.tr("IMPORT • SWD2", "IMPORT • SWD2"),
            "imported-wif": self.tr("IMPORT • WIF", "IMPORT • WIF"),
            "imported-private-key": self.tr("IMPORT • KLUCZ PRYWATNY", "IMPORT • PRIVATE KEY"),
            "legacy-manual-password-number": self.tr("LEGACY • RĘCZNIE", "LEGACY • MANUAL"),
            "legacy-from-swd1": self.tr("LEGACY • Z SWD1", "LEGACY • FROM SWD1"),
            "legacy-from-swd2": self.tr("LEGACY • Z SWD2", "LEGACY • FROM SWD2"),
            "bip85-child": self.tr("BIP85 • POTOMNY", "BIP85 • CHILD"),
            "unknown": self.tr("STARY REKORD", "LEGACY RECORD"),
            "damaged-metadata": self.tr("BŁĄD METADANYCH", "METADATA ERROR"),
        }
        label = labels.get(entry.get("source"), str(entry.get("source", "UNKNOWN")).upper())
        words = entry.get("wordCount")
        if words: label += self.tr(f" • {words} SŁÓW", f" • {words} WORDS")
        if entry.get("hidden"): label += self.tr(" • UKRYTY", " • HIDDEN")
        return label

    def select_wallet(self, include_hidden=False, title=None):
        entries = self.wallet_catalog(include_hidden)
        if not entries: raise ValueError(self.tr("Brak widocznych portfeli.", "No visible wallets."))
        labels = [f"{entry['name']} • {self.source_label(entry)}" for entry in entries]
        return entries[self.menu(title or self.tr("WYBIERZ PORTFEL", "SELECT WALLET"), labels)]

    def collect_deck(self, number):
        ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
        suits = [("S", "♠", WHITE), ("H", "♥", CARD_RED), ("D", "♦", CARD_RED), ("C", "♣", WHITE)]
        chosen, timings, cursor, last = [], [], [0, 0], time.monotonic_ns()
        while len(chosen) < 25:
            self.frame(
                self.tr(f"LOSOWANIE {number}: {len(chosen)}/25", f"DRAW {number}: {len(chosen)}/25"),
                self.tr("PEŁNA TALIA • 7x RIFFLE • KOLEJNO", "FULL DECK • 7x RIFFLE • IN ORDER"),
            )
            rects = []
            first_rank = min(max(0, cursor[0] - 1), len(ranks) - 3)
            visible_ranks = list(enumerate(ranks))[first_rank:first_rank + 3]
            for visible_row, (row, rank) in enumerate(visible_ranks):
                for col, (suit_code, suit_symbol, suit_color) in enumerate(suits):
                    card = rank + suit_code; rect = pygame.Rect(12 + col * 116, 94 + visible_row * 60, 108, 53)
                    rects.append((rect, card, row, col))
                    used = card in chosen; active = cursor == [row, col]
                    if used:
                        pygame.draw.rect(self.screen, self.palette["panel"], rect)
                        pygame.draw.rect(self.screen, PHOSPHOR, rect, 6)
                        pygame.draw.line(self.screen, PHOSPHOR, (rect.right - 26, rect.y + 14), (rect.right - 19, rect.y + 22), 3)
                        pygame.draw.line(self.screen, PHOSPHOR, (rect.right - 19, rect.y + 22), (rect.right - 8, rect.y + 8), 3)
                    else:
                        pygame.draw.rect(self.screen, self.palette["panel"] if active else BLACK, rect)
                        pygame.draw.rect(self.screen, PHOSPHOR if active else WHITE, rect, 6 if active else 2)
                        if active:
                            pygame.draw.rect(self.screen, WHITE, rect.inflate(-10, -10), 2)
                    rendered = self.font.render(rank + suit_symbol, True, PHOSPHOR if used else suit_color)
                    self.screen.blit(rendered, rendered.get_rect(center=rect.center))
            page = self.tr(
                f"FIGURY {first_rank + 1}-{first_rank + len(visible_ranks)}/13",
                f"RANKS {first_rank + 1}-{first_rank + len(visible_ranks)}/13",
            )
            self.text(page, 14, FOOTER_Y, self.small, GRAY)
            self.text(self.tr("STRZAŁKI+ENTER", "ARROWS+ENTER"), 270, FOOTER_Y, self.small, GRAY)
            self.present()
            for event in self.events():
                card = None
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE: raise Cancelled()
                    if event.key == pygame.K_UP: cursor[0] = (cursor[0] - 1) % 13
                    elif event.key == pygame.K_DOWN: cursor[0] = (cursor[0] + 1) % 13
                    elif event.key == pygame.K_LEFT: cursor[1] = (cursor[1] - 1) % 4
                    elif event.key == pygame.K_RIGHT: cursor[1] = (cursor[1] + 1) % 4
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER): card = ranks[cursor[0]] + suits[cursor[1]][0]
                if event.type == pygame.MOUSEBUTTONDOWN:
                    for rect, candidate, row, col in rects:
                        if rect.collidepoint(event.pos): card, cursor = candidate, [row, col]; break
                if card and card not in chosen:
                    now = time.monotonic_ns(); timings.append(now - last); last = now; chosen.append(card)
            self.clock.tick(30)
        return chosen, timings

    def verify_backup(self, words):
        indexes = sorted(secrets.SystemRandom().sample(range(len(words)), min(4, len(words))))
        while True:
            correct = True
            for index in indexes:
                answer = self.ask(self.tr("TEST BACKUPU", "BACKUP TEST"), self.tr(f"Wpisz słowo nr {index + 1}", f"Enter word number {index + 1}"), True)
                if answer.strip().lower() != words[index]: correct = False
            if correct:
                self.show(self.tr("BACKUP POTWIERDZONY", "BACKUP VERIFIED"), self.tr("Test 4 losowych pozycji zakończony poprawnie.", "Four random word positions verified successfully."))
                return
            self.show(self.tr("BŁĘDNY BACKUP", "BACKUP FAILED"), self.tr("Co najmniej jedno słowo jest błędne. Sprawdź zapis i wykonaj test ponownie.", "At least one word is wrong. Check your written backup and repeat the test."))

    def create_wallet(self, cards=False, wizard=False):
        default_name = "wallet1" if wizard else ""
        name = self.ask(self.tr("NOWY PORTFEL", "NEW WALLET"), self.tr("nazwa: a-z A-Z 0-9 _ -", "name: a-z A-Z 0-9 _ -"), initial=default_name)
        password = self.password_twice()
        request = {"name": name, "passphrase": password, "generation": "cards" if cards else "system"}
        if cards:
            self.show(self.tr("PRZYGOTOWANIE", "PREPARATION"), self.tr("Potasuj pełną talię 52 kart co najmniej 7 razy metodą riffle. Odkrywaj i wybieraj kolejno pierwsze 25 kart. Potem zbierz całą talię, ponownie ją potasuj i wykonaj drugie niezależne losowanie 25 kart.", "Shuffle a complete 52-card deck with at least seven riffle shuffles. Reveal and enter the first 25 cards in order. Then gather the full deck, reshuffle it, and perform a second independent 25-card draw."))
            deck1, timing1 = self.collect_deck(1)
            self.show(self.tr("PONOWNE TASOWANIE", "RESHUFFLE"), self.tr("Włóż wszystkie 52 karty z powrotem do talii i potasuj ją od nowa co najmniej 7 razy. Wybierz pierwsze 25 kart. Druga sekwencja musi pochodzić z nowego tasowania.", "Return all 52 cards to the deck and reshuffle from scratch at least seven times. Enter the first 25 cards. The second sequence must come from a fresh shuffle."))
            deck2, timing2 = self.collect_deck(2)
            salt = self.ask(self.tr("DODATKOWE HASŁO ENTROPII", "EXTRA ENTROPY PHRASE"), self.tr("opcjonalne • zostanie wtopione w seed", "optional • mixed permanently into seed"), True, allow_reveal=True, default_ok=True)
            request["cards"] = {"deck1": deck1, "deck2": deck2, "timings": timing1 + timing2, "salt": salt}
        result = self.run_json(["create"], request)
        self.session_wallet, self.session_pin = name, password
        words = result["mnemonic"].split()
        numbered = "\n".join(f"{index + 1:02d}. {word}" for index, word in enumerate(words))
        self.show(self.tr("ZAPISZ SEED RAZ", "WRITE SEED ONCE"), numbered + "\n\n" + self.tr("Adres kontrolny:", "Check address:") + "\n" + result["firstAddress"]["address"], secret=True)
        self.verify_backup(words)
        if not wizard:
            del result, words, numbered
            self.restart_gui()

    def first_run(self):
        settings = {}
        if self.settings_path.exists():
            try: settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): pass
        if settings.get("setupComplete"): return
        language = self.menu("LANGUAGE / JĘZYK", ["English (default)", "Polski"])
        self.lang = "en" if language == 0 else "pl"; self.save_settings(False)
        interface_mode = self.menu(self.tr("TRYB INTERFEJSU", "INTERFACE MODE"), [
            self.tr("PROSTY • PROWADZI KROK PO KROKU", "SIMPLE • STEP-BY-STEP GUIDANCE"),
            self.tr("ZAAWANSOWANY • WSZYSTKIE FUNKCJE", "ADVANCED • ALL FEATURES"),
        ], footer=self.tr("Można zmienić później", "You can change this later"))
        self.settings["uiMode"] = "simple" if interface_mode == 0 else "advanced"
        self.save_settings(False)
        self.show(self.tr("WITAJ", "WELCOME"), self.tr(
            "Kreator utworzy portfel BIP-39 z 256 bitami entropii. Użyje dwóch niezależnych losowań po 25 kart z ponownie tasowanej pełnej talii, czasów interakcji, opcjonalnego hasła entropii i CSPRNG systemu. Zapisz 24 słowa offline i zalicz test backupu.",
            "This wizard creates a 256-bit BIP-39 wallet. It combines two independent 25-card draws from a freshly shuffled full deck, interaction timing, an optional entropy phrase, and the system CSPRNG. Write the 24 words offline and pass the backup test."))
        existing = self.run_json(["list"], {}).get("wallets", [])
        if existing:
            self.show(self.tr("PRZERWANY KREATOR", "SETUP INTERRUPTED"), self.tr(
                "Sekretu nie można ponownie wyświetlić. Wymagany jest reset i ponowne utworzenie lub import.",
                "The secret cannot be shown again. Reset and repeat create/import."))
            name = existing[0] if len(existing) == 1 else existing[self.menu(self.tr("PORTFEL DO RESETU", "WALLET TO RESET"), existing)]
            pin = self.ask_pin(self.tr("POTWIERDŹ PIN", "CONFIRM PIN"), name)
            self.run_json(["factory-reset"], {"name": name, "passphrase": pin, "confirm": "FACTORY RESET"})
            self.settings["setupComplete"] = False
            self.save_settings(False)
            return self.first_run()
        else:
            while True:
                try:
                    mode = self.menu(self.tr("KONFIGURACJA PORTFELA", "WALLET SETUP"), [
                        self.tr("UTWÓRZ • DWIE TALIE + CSPRNG", "CREATE • TWO DECKS + CSPRNG"),
                        self.tr("IMPORTUJ • BIP39 / SWD", "IMPORT • BIP39 / SWD"),
                        self.tr("IMPORTUJ Z USB • /EntropySilo/import.txt", "IMPORT FROM USB • /EntropySilo/import.txt"),
                        self.tr("ODTWÓRZ • BACKUP Z USB", "RESTORE • BACKUP FROM USB")])
                    if mode == 0: self.create_wallet(True, True)
                    elif mode == 1:
                        words = self.recover(first_run=True)
                        self.verify_backup(words)
                    elif mode == 2: self.import_secret_usb(first_run=True)
                    else: self.restore_backup_usb(first_run=True)
                    break
                except Cancelled:
                    continue
                except Exception as error:
                    self.show(self.tr("BŁĄD KONFIGURACJI", "SETUP ERROR"), self.localize_error(str(error)))
        self.save_settings(True)

    def recover(self, first_run=False):
        source = self.menu(self.tr("ODZYSKIWANIE", "RECOVERY"), [
            self.tr("12–24 SŁOWA BIP39", "12–24 BIP39 WORDS"),
            self.tr("KOD SWD1/SWD2", "SWD1/SWD2 CODE"),
        ])
        name = self.ask(self.tr("NAZWA PORTFELA", "WALLET NAME"), self.tr("nazwa nowego skarbca", "new vault name"))
        password = self.password_twice()
        if source == 0:
            mnemonic = self.ask("BIP39 MNEMONIC", self.tr("wpisz 12–24 słowa; USB zalecane", "enter 12–24 words; USB recommended"), True, allow_reveal=True)
            result = self.run_json(["recover"], {"name": name, "passphrase": password, "mnemonic": mnemonic})
            backup_words = mnemonic.strip().lower().split()
        else:
            word_choice = self.menu(self.tr("LICZBA SŁÓW SWD", "SWD WORD COUNT"), [
                self.tr("24 SŁOWA • DOMYŚLNIE", "24 WORDS • DEFAULT"),
                self.tr("12 SŁÓW", "12 WORDS"),
                self.tr("AUTO • Z KODU", "AUTO • FROM CODE"),
            ])
            code = self.ask(self.tr("KOD SWD", "SWD CODE"), self.tr("swd2:hasło:liczba + opcjonalnie :12/:24", "swd2:password:number + optional :12/:24"), True, allow_reveal=True)
            code = code.strip().replace("[:12]", ":12").replace("[:24]", ":24")
            if code.lower().startswith("sdw"):
                raise ValueError(self.tr("Prefiks to SWD1 albo SWD2 (nie SDW).", "The prefix is SWD1 or SWD2 (not SDW)."))
            parts = code.split(":")
            if len(parts) == 3 and word_choice in (0, 1): code += ":24" if word_choice == 0 else ":12"
            if len(parts) == 4 and parts[3] not in ("12", "24"):
                raise ValueError(self.tr("Końcówka SWD może wynosić wyłącznie :12 albo :24.", "The SWD suffix must be either :12 or :24."))
            if first_run:
                decoded = self.run_swd("swd-decode-json", code)
                backup_words = decoded["mnemonic"].split()
            else:
                backup_words = None
            result = self.run_json(["recover-swd"], {"name": name, "passphrase": password, "recoveryCode": code})
        self.session_wallet, self.session_pin = name, password
        self.show(self.tr("ODZYSKANO", "RECOVERED"), self.tr("Sprawdź pierwszy adres niezależnie:\n", "Verify the first address independently:\n") + result["firstAddress"]["address"])
        if not first_run:
            self.restart_gui()
        return backup_words

    def show_qr(self, data, title):
        target = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "entropysilo-qr"
        completed = subprocess.run([NODE, str(QR), "--output", str(target)], input=data, text=True, capture_output=True, timeout=60, check=True)
        info = json.loads(completed.stdout.strip().splitlines()[-1]); images = [pygame.image.load(path) for path in info["files"]]
        frame = 0; changed = time.monotonic()
        while True:
            self.frame(title, self.tr(f"QR {frame + 1}/{len(images)} • ENTER=KONIEC", f"QR {frame + 1}/{len(images)} • ENTER=DONE"))
            image = pygame.transform.smoothscale(images[frame], (190, 190))
            self.screen.blit(image, (145, 91))
            short_data = self.wrapped_for_font(data, self.small, WIDTH - 28, 1)[0]
            self.text(short_data, 14, FOOTER_Y, self.small, GRAY)
            self.present()
            if len(images) > 1 and time.monotonic() - changed > 1.0: frame = (frame + 1) % len(images); changed = time.monotonic()
            for event in self.events():
                if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_ESCAPE): return
                if event.type == pygame.MOUSEBUTTONDOWN: return
            self.clock.tick(20)

    def ask_hd_account(self):
        value = self.ask(self.tr("KONTO HD", "HD ACCOUNT"), self.tr(
            "0 = pierwsze konto; zakres 0–1000. To nie jest numer adresu.",
            "0 = first account; range 0–1000. This is not an address number.",
        ), initial="0")
        account = int(value or 0)
        if account < 0 or account > 1000:
            raise ValueError(self.tr("Numer konta musi być w zakresie 0–1000.", "Account number must be between 0 and 1000."))
        return account

    def address(self):
        name, password = self.credentials()
        hidden = self.ask_bip39_passphrase()
        purpose = [44, 49, 84, 86][self.menu(self.tr("TYP ADRESU", "ADDRESS TYPE"), ["BIP44 LEGACY", "BIP49 NESTED", "BIP84 NATIVE SEGWIT", "BIP86 TAPROOT"])]
        account = self.ask_hd_account()
        index_text = self.ask(self.tr("INDEKS ADRESU", "ADDRESS INDEX"), self.tr("0 dla pierwszego", "0 for the first address"), initial="0")
        result = self.run_json(["address"], {"name": name, "passphrase": password, "bip39Passphrase": hidden, "purpose": purpose, "account": account, "index": int(index_text or 0), "network": "bitcoin"})
        self.show_qr(result["address"], self.tr("ODBIERZ", "RECEIVE") + f" • {result['path']}")

    def address_type_menu(self, types, selected_purpose=84):
        selected = next((index for index, item in enumerate(types) if item["purpose"] == selected_purpose), 0)
        while True:
            self.frame(self.tr("TYPY ADRESÓW", "ADDRESS TYPES"), self.tr("PUBLICZNE • BEZ KLUCZY PRYWATNYCH", "PUBLIC • NO PRIVATE KEYS"))
            first = min(max(0, selected - 1), max(0, len(types) - 2))
            visible = list(enumerate(types))[first:first + 2]
            rects = []
            for visible_index, (index, item) in enumerate(visible):
                rect = pygame.Rect(12, 89 + visible_index * 94, WIDTH - 24, 87)
                rects.append((rect, index))
                active = index == selected
                self.draw_panel(rect, active)
                color = self.background if active else self.text_color
                self.text(f"{item['label'].upper()} • {item['bip']}", rect.x + 8, rect.y + 2, self.small, color)
                self.text(item["path"], rect.x + 8, rect.y + 29, self.small, color)
                short = item["address"][:16] + "…" + item["address"][-8:]
                self.text(short, rect.x + 8, rect.y + 56, self.small, color)
            self.text(self.tr("↑↓ • ENTER=WYBIERZ • ESC", "↑↓ • ENTER=SELECT • ESC"), 12, FOOTER_Y, self.small, GRAY)
            self.present()
            for event in self.events():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE: return None
                    if event.key in (pygame.K_UP, pygame.K_LEFT): selected = (selected - 1) % len(types)
                    elif event.key in (pygame.K_DOWN, pygame.K_RIGHT): selected = (selected + 1) % len(types)
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER): return types[selected]
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    for rect, index in rects:
                        if rect.collidepoint(event.pos): return types[index]
            self.clock.tick(30)

    def choose_address_standard(self):
        standards = [
            (84, "NATIVE SEGWIT • P2WPKH • BIP84", "m/84'/0'/0'/0/index • bc1q…"),
            (49, "NESTED SEGWIT • P2SH-P2WPKH • BIP49", "m/49'/0'/0'/0/index • 3…"),
            (86, "TAPROOT • P2TR • BIP86", "m/86'/0'/0'/0/index • bc1p…"),
            (44, "LEGACY • P2PKH • BIP44", "m/44'/0'/0'/0/index • 1…"),
        ]
        labels = [f"{label}\n{path}" for _, label, path in standards]
        return standards[self.menu(self.tr("STANDARD ADRESU", "ADDRESS STANDARD"), labels,
            footer=self.tr("Najpierw standard, potem portfel", "Standard first, then wallet"))][0]

    def wallet_explorer(self, entry=None):
        purpose = self.choose_address_standard()
        if entry is None:
            name, pin, entry = self.choose_wallet_credentials(self.tr("EKSPLORATOR • PORTFEL", "EXPLORER • WALLET"))
        else:
            name, pin, entry = self.credentials_for_entry(entry)
        hidden = self.ask_bip39_passphrase()
        account, change, index = self.ask_hd_account(), 0, 0
        while True:
            type_result = self.run_json(["address-types"], {"name": name, "passphrase": pin, "bip39Passphrase": hidden,
                "account": account, "change": change, "index": index, "network": self.settings.get("network", "bitcoin")})
            types = type_result["types"]
            result = next(item for item in types if item["purpose"] == purpose)
            short = result["address"][:12] + "..." + result["address"][-6:]
            choice = self.menu(f"{name} • {short}", [
                f"{result['label'].upper()} • {result['bip']} • {result['technical']}",
                self.tr("POKAŻ ADRES QR", "SHOW ADDRESS QR"),
                self.tr("NASTĘPNY ADRES", "NEXT ADDRESS"), self.tr("POPRZEDNI ADRES", "PREVIOUS ADDRESS"),
                self.tr("RECEIVE / CHANGE", "RECEIVE / CHANGE"),
                self.tr("LISTA 10 ADRESÓW", "LIST 10 ADDRESSES"), self.tr("KLUCZ WATCH-ONLY + QR", "WATCH-ONLY KEY + QR"),
                self.tr("SZCZEGÓŁY PUBLICZNE", "PUBLIC DETAILS"), self.tr("WSTECZ", "BACK")], footer=f"{self.source_label(entry)} • {result['path']}")
            if choice == 0:
                selected_type = self.address_type_menu(types, purpose)
                if selected_type is not None: purpose = selected_type["purpose"]
            elif choice == 1: self.show_qr(result["address"], f"{result['label'].upper()} • {result['path']}")
            elif choice == 2: index += 1
            elif choice == 3: index = max(0, index - 1)
            elif choice == 4: change = 1 - change; index = 0
            elif choice == 5:
                if not result.get("accountXpub"):
                    self.show(self.tr("POJEDYNCZY KLUCZ", "SINGLE KEY"), self.tr("WIF/surowy klucz ma po jednym adresie dla każdego standardu i nie tworzy listy HD.", "A WIF/raw key has one address per standard and does not create an HD list."))
                else:
                    batch = self.run_json(["addresses"], {"name": name, "passphrase": pin, "bip39Passphrase": hidden,
                        "purpose": purpose, "account": account, "change": change, "start": index, "count": 10,
                        "network": self.settings.get("network", "bitcoin")})
                    self.show(self.tr("ADRESY PUBLICZNE", "PUBLIC ADDRESSES"), "\n\n".join(f"#{item['index']} {item['address']}" for item in batch["addresses"]))
            elif choice == 6:
                if result.get("watchOnlyKey"):
                    export_choice = self.menu(self.tr("EKSPORT WATCH-ONLY", "WATCH-ONLY EXPORT"), [
                        self.tr("DESCRIPTOR + FINGERPRINT (ZALECANY)", "DESCRIPTOR + FINGERPRINT (RECOMMENDED)"),
                        self.tr("SUROWY ZPUB/YPUB/XPUB (TYLKO PODGLĄD)", "RAW ZPUB/YPUB/XPUB (VIEWING ONLY)"),
                    ])
                    if export_choice == 0: self.show_qr(result["descriptor"], f"DESCRIPTOR • {result['bip']} • {name}")
                    else: self.show_qr(result["watchOnlyKey"], f"{result['watchOnlyKey'][:4].upper()} • {result['bip']} • {name}")
                else: self.show(self.tr("BRAK KLUCZA HD", "NO HD KEY"), self.tr("Pojedynczy klucz WIF nie ma hierarchicznego klucza watch-only.", "A single WIF key has no hierarchical watch-only key."))
            elif choice == 7:
                self.show(self.tr("DANE PUBLICZNE", "PUBLIC DATA"), self.tr(
                    f"ETYKIETA: {name}\nTYP: {result['label']} • {result['technical']} • {result['bip']}\nSIEĆ: {result['network']}\nŚCIEŻKA: {result['path']}\nADRES:\n{result['address']}\nFINGERPRINT: {result.get('masterFingerprint') or 'N/D'}\nKLUCZ PUBLICZNY:\n{result['publicKey']}\nKLUCZ WATCH-ONLY:\n{result.get('watchOnlyKey') or 'N/D'}\nXPUB KONTA:\n{result.get('accountXpub') or 'N/D'}\nDESCRIPTOR:\n{result.get('descriptor') or 'N/D'}",
                    f"LABEL: {name}\nTYPE: {result['label']} • {result['technical']} • {result['bip']}\nNETWORK: {result['network']}\nPATH: {result['path']}\nADDRESS:\n{result['address']}\nFINGERPRINT: {result.get('masterFingerprint') or 'N/A'}\nPUBLIC KEY:\n{result['publicKey']}\nWATCH-ONLY KEY:\n{result.get('watchOnlyKey') or 'N/A'}\nACCOUNT XPUB:\n{result.get('accountXpub') or 'N/A'}\nDESCRIPTOR:\n{result.get('descriptor') or 'N/A'}",
                ))
            else: return

    def sign(self, entry=None):
        if entry is None:
            entry = self.select_wallet(False, self.tr("WYBIERZ PORTFEL PODPISUJĄCY", "SELECT SIGNING WALLET"))
            name, password, entry = self.credentials_for_entry(entry)
        else:
            name, password, entry = self.credentials_for_entry(entry)
        hidden = self.ask_bip39_passphrase()
        account = self.ask_hd_account()
        identity = self.run_json(["address"], {
            "name": name, "passphrase": password, "bip39Passphrase": hidden,
            "purpose": 84, "account": account, "change": 0, "index": 0,
            "network": self.settings.get("network", "bitcoin"),
        })
        source = self.menu(self.tr(f"PSBT • {name}", f"PSBT • {name}"), [
            self.tr("WYBIERZ PLIK .PSBT Z USB", "SELECT .PSBT FILE FROM USB"), self.tr("OBRAZ QR Z USB", "QR IMAGE FROM USB"),
            self.tr("KAMERA UVC", "UVC CAMERA"), self.tr("WPISZ / WKLEJ BASE64/HEX", "TYPE / PASTE BASE64/HEX")])
        source_name = None
        if source == 0:
            psbt, source_name = self.select_psbt_from_usb()
        elif source == 1: psbt = self.qr_from_usb_image()
        elif source == 2: psbt = self.qr_from_uvc_camera()
        else: psbt = self.ask("PSBT", self.tr("Base64/hex; klawiatura USB", "Base64/hex; USB keyboard"), True, allow_reveal=True)
        network = self.settings.get("network", "bitcoin")
        summary = self.run_json(["inspect"], {"psbt": psbt, "network": network})
        if summary["feeSats"] is None and not self.settings.get("allowUnknownFee", False):
            raise ValueError(self.tr("Polityka bezpieczeństwa odrzuca PSBT bez znanej opłaty.", "Security policy rejects PSBT with unknown fee."))
        if summary["feeSats"] is not None and int(summary["feeSats"]) > int(self.settings.get("maxFeeSats", 100000)):
            raise ValueError(self.tr("Opłata przekracza ustawiony limit.", "Fee exceeds configured limit."))
        unknown_fee = self.tr("NIEZNANA", "UNKNOWN")
        body = [
            self.tr(f"PORTFEL: {name}", f"WALLET: {name}"),
            self.tr(f"KONTO HD: #{account}", f"HD ACCOUNT: #{account}"),
            self.tr(f"FINGERPRINT: {identity.get('masterFingerprint') or 'N/D'}", f"FINGERPRINT: {identity.get('masterFingerprint') or 'N/A'}"),
            self.tr(f"WEJŚCIA: {summary['inputCount']}", f"INPUTS: {summary['inputCount']}"),
            self.tr(f"SUMA WYJŚĆ: {summary['totalOutputSats']} sat", f"TOTAL OUTPUTS: {summary['totalOutputSats']} sat"),
            self.tr(f"OPŁATA: {summary['feeSats'] or unknown_fee} sat", f"FEE: {summary['feeSats'] or unknown_fee} sat"),
            "",
        ]
        body += [self.tr(f"WYJŚCIE {item['index']}: {item['valueSats']} sat\n{item['address']}", f"OUTPUT {item['index']}: {item['valueSats']} sat\n{item['address']}") for item in summary["outputs"]]
        if summary.get("warning"): body.append(self.tr("OSTRZEŻENIE: ", "WARNING: ") + self.localize_error(summary["warning"]))
        self.show(self.tr("SPRAWDŹ TRANSAKCJĘ", "VERIFY TRANSACTION"), "\n".join(body))
        if not self.confirm(self.tr("PODPIS KRYPT.", "CRYPTOGRAPHIC SIGNATURE"), self.tr("Sprawdziłem KAŻDY adres i opłatę", "I verified EVERY address and the fee"), dangerous=True): return
        signed = self.run_json(["sign"], {"name": name, "passphrase": password, "bip39Passphrase": hidden, "account": account, "psbt": psbt, "network": network, "confirm": True, "finalize": True})
        if signed.get("compatibilityWarnings"):
            self.show(self.tr("ZGODNOŚĆ PSBT", "PSBT COMPATIBILITY"), "\n".join(self.localize_error(item) for item in signed["compatibilityWarnings"]))
        if signed.get("finalizeWarning"):
            self.show(self.tr("PODPIS CZĘŚCIOWY", "PARTIAL SIGNATURE"), self.localize_error(signed["finalizeWarning"]))
        export = signed.get("transactionHex") or signed["psbtBase64"]
        if self.confirm(self.tr("ZAPISAĆ NA USB?", "SAVE TO USB?"),
            "/EntropySilo/signed.txn" if signed.get("finalized") else "/EntropySilo/signed.psbt"):
            if source_name:
                action = "write-selected-signed-txn" if signed.get("finalized") else "write-selected-signed-psbt"
                output = (source_name + "\n" + export + "\n").encode("ascii")
            else:
                action = "write-signed-txn" if signed.get("finalized") else "write-signed-psbt"
                output = (export + "\n").encode("ascii")
            path = self.usb_call(action, output, 90).decode("utf-8", "replace").strip()
            self.show(self.tr("ZAPISANO PODPIS", "SIGNATURE SAVED"), path)
        self.show_qr(export, self.tr("PODPISANA TRANSAKCJA", "SIGNED TRANSACTION") if signed.get("finalized") else self.tr("PODPISANY PSBT", "SIGNED PSBT"))

    def swd(self):
        choice = self.menu("SEED DECODER SWD", [
            self.tr("LEGACY Z GŁÓWNEGO SEEDA", "LEGACY FROM ROOT SEED"),
            self.tr("LEGACY Z HASŁA + LICZBY", "LEGACY FROM PASSWORD + NUMBER"),
            self.tr("INFORMACJE O FORMATACH", "FORMAT INFORMATION"),
        ])
        if choice == 0:
            source, source_pin = self.credentials()
            name = self.ask(self.tr("ETYKIETA LEGACY", "LEGACY LABEL"), self.tr("nazwa nowego portfela", "new wallet name"))
            fmt = "swd2" if self.menu(self.tr("FORMAT ŹRÓDŁA", "SOURCE FORMAT"), [self.tr("SWD2 (ZALECANY)", "SWD2 (RECOMMENDED)"), self.tr("SWD1 (ZGODNOŚĆ)", "SWD1 (COMPATIBILITY)")]) == 0 else "swd1"
            result = self.run_json(["legacy-from-wallet"], {"sourceName": source, "sourcePin": source_pin, "name": name, "pin": source_pin, "format": fmt})
            self.show(self.tr("PORTFEL LEGACY", "LEGACY WALLET"), self.tr(f"Etykieta: {name}\nŹródło: {source}/{fmt}\nPierwszy adres:\n{result['legacyAddress']}", f"Label: {name}\nSource: {source}/{fmt}\nFirst address:\n{result['legacyAddress']}"))
        elif choice == 1:
            password = self.ask(self.tr("HASŁO WALLET DECODER", "WALLET DECODER PASSWORD"), self.tr("A-Z/a-z; zachowaj wielkość", "A-Z/a-z; preserve letter case"), True, allow_reveal=True)
            number = self.ask(self.tr("LICZBA WALLET DECODER", "WALLET DECODER NUMBER"), self.tr("liczba dziesiętna", "decimal number"), True, allow_reveal=True)
            name = self.ask(self.tr("ETYKIETA LEGACY", "LEGACY LABEL"), self.tr("nazwa nowego portfela", "new wallet name"))
            pin = self.password_twice()
            word_count = [24, 12][self.menu(self.tr("LICZBA SŁÓW LEGACY", "LEGACY WORD COUNT"), [self.tr("24 SŁOWA • DOMYŚLNIE", "24 WORDS • DEFAULT"), self.tr("12 SŁÓW", "12 WORDS")])]
            result = self.run_json(["legacy-create"], {"name": name, "pin": pin, "password": password, "number": number, "wordCount": word_count})
            self.show(self.tr("PORTFEL LEGACY", "LEGACY WALLET"), self.tr(f"Etykieta: {name}\nPierwszy adres:\n{result['legacyAddress']}", f"Label: {name}\nFirst address:\n{result['legacyAddress']}"))
        else:
            self.show("SWD1 / SWD2 / LEGACY", self.tr(
                "SWD1/SWD2 to odwracalny kodek z repozytorium. Skarbiec przechowuje wyłącznie jego zaszyfrowane hasło i liczbę. LEGACY to jednokierunkowy Wallet Decoder. Po pierwszej konfiguracji GUI nigdy nie ujawnia mnemonika, kodu SWD ani kluczy prywatnych.",
                "SWD1/SWD2 is the reversible codec from the repository. The vault stores only its encrypted password and number. LEGACY is the one-way Wallet Decoder. After initial setup, the GUI never reveals the mnemonic, SWD code, or private keys.",
            ))

    def usb_backup_menu(self):
        choice = self.menu(self.tr("BACKUP USB", "USB BACKUP"), [
            self.tr("UTWÓRZ NOWY BACKUP", "CREATE NEW BACKUP"),
            self.tr("ODTWÓRZ WYBRANY BACKUP", "RESTORE SELECTED BACKUP"),
            self.tr("IMPORTUJ import.txt", "IMPORT import.txt"),
            self.tr("ZASADY BEZPIECZEŃSTWA", "SECURITY RULES"),
            self.tr("WSTECZ", "BACK")])
        if choice == 0: self.backup_to_usb()
        elif choice == 1: self.restore_backup_usb()
        elif choice == 2: self.import_secret_usb()
        elif choice == 3:
            self.show(self.tr("BEZPIECZNY USB", "SAFE USB"), self.tr(
                "Nośnik jest montowany noexec,nosuid,nodev. Program nie uruchamia plików i używa wyłącznie ścisłych nazw w /EntropySilo. Backup jest zaszyfrowany AES-256-GCM; scrypt wzmacnia hasło. Istniejące pliki pozostają nietknięte.",
                "The drive is mounted noexec,nosuid,nodev. No files are executed and only strict names in /EntropySilo are used. The backup is encrypted with AES-256-GCM and a scrypt-hardened password. Existing files remain untouched."))

    def wallet_details(self, entry):
        parent = entry.get("parent") or self.tr("ROOT / IMPORT", "ROOT / IMPORT")
        state = self.tr("UKRYTY", "HIDDEN") if entry.get("hidden") else self.tr("WIDOCZNY", "VISIBLE")
        restorable = self.tr("TAK", "YES") if entry.get("restorable") else self.tr("NIE", "NO")
        fields = [
            self.tr(f"ETYKIETA: {entry.get('name')}", f"LABEL: {entry.get('name')}"),
            self.tr(f"ŹRÓDŁO: {self.source_label(entry)}", f"SOURCE: {self.source_label(entry)}"),
            self.tr(f"SŁOWA: {entry.get('wordCount') or 'N/D'}", f"WORDS: {entry.get('wordCount') or 'N/A'}"),
            self.tr(f"RODZIC: {parent}", f"PARENT: {parent}"),
            self.tr(f"INDEKS BIP85: {entry.get('bip85Index') if entry.get('bip85Index') is not None else 'N/D'}", f"BIP85 INDEX: {entry.get('bip85Index') if entry.get('bip85Index') is not None else 'N/A'}"),
            self.tr(f"ŚCIEŻKA BIP85: {entry.get('bip85Path') or 'N/D'}", f"BIP85 PATH: {entry.get('bip85Path') or 'N/A'}"),
            self.tr(f"STAN: {state}", f"STATE: {state}"),
            self.tr(f"ODTWARZALNY Z RODZICA: {restorable}", f"RESTORABLE FROM PARENT: {restorable}"),
        ]
        self.show(self.tr("SZCZEGÓŁY PORTFELA", "WALLET DETAILS"), "\n".join(fields))

    def create_bip85_child(self):
        parent = self.select_wallet(False, self.tr("RODZIC BIP85", "BIP85 PARENT"))
        parent_pin = self.ask_pin(self.tr("PIN RODZICA", "PARENT PIN"), parent["name"])
        hidden = self.ask_bip39_passphrase(parent["name"])
        index_text = self.ask(self.tr("INDEKS BIP85", "BIP85 INDEX"), "0..2147483647", initial="0")
        index = int(index_text)
        if index < 0 or index > 2147483647: raise ValueError(self.tr("Indeks BIP85: 0..2147483647", "BIP85 index: 0..2147483647"))
        name = self.ask(self.tr("NAZWA DZIECKA", "CHILD NAME"), "a-z A-Z 0-9 _ -")
        pin = self.password_twice()
        result = self.run_json(["bip85-create"], {"parentName": parent["name"], "parentPin": parent_pin,
            "parentBip39Passphrase": hidden, "index": index, "name": name, "pin": pin,
            "network": self.settings.get("network", "bitcoin")})
        self.show(self.tr("UTWORZONO BIP85", "BIP85 CREATED"), self.tr(
            f"POTOMNY: {name}\nRODZIC: {parent['name']}\nINDEKS: {index}\nŚCIEŻKA: {result['bip85Path']}\nADRES:\n{result['firstAddress']['address']}",
            f"CHILD: {name}\nPARENT: {parent['name']}\nINDEX: {index}\nPATH: {result['bip85Path']}\nADDRESS:\n{result['firstAddress']['address']}",
        ))

    def manage_wallet(self, entry):
        while True:
            action = self.menu(entry["name"], [
                self.tr("SZCZEGÓŁY POCHODZENIA", "ORIGIN DETAILS"),
                self.tr("POKAŻ" if entry.get("hidden") else "UKRYJ", "SHOW" if entry.get("hidden") else "HIDE"),
                self.tr("USUŃ PORTFEL", "DELETE WALLET"), self.tr("WSTECZ", "BACK")], footer=self.source_label(entry))
            if action == 0: self.wallet_details(entry)
            elif action == 1:
                pin = self.ask_pin(self.tr("POTWIERDŹ PIN", "CONFIRM PIN"), entry["name"])
                updated = self.run_json(["set-hidden"], {"name": entry["name"], "passphrase": pin, "hidden": not entry.get("hidden")})
                entry = {**entry, **updated.get("metadata", {})}
                self.show(self.tr("ZMIENIONO WIDOCZNOŚĆ", "VISIBILITY CHANGED"), self.source_label(entry))
            elif action == 2:
                warning = self.tr("Portfel zostanie trwale usunięty. Najpierw wykonaj backup.", "The wallet will be permanently deleted. Make a backup first.")
                if not self.confirm(self.tr("USUNĄĆ PORTFEL?", "DELETE WALLET?"), warning, dangerous=True): continue
                pin = self.ask_pin(self.tr("POTWIERDŹ PIN", "CONFIRM PIN"), entry["name"])
                self.run_json(["delete-wallet"], {"name": entry["name"], "passphrase": pin, "confirm": f"DELETE {entry['name']}"})
                if self.session_wallet == entry["name"]:
                    self.session_pin = None; self.session_wallet = None; self.session_entry = None
                self.show(self.tr("USUNIĘTO", "DELETED"), entry["name"]); return
            else: return

    def show_wallet_receive_qr(self, entry):
        purpose = self.choose_address_standard()
        name, pin, entry = self.credentials_for_entry(entry)
        hidden = self.ask_bip39_passphrase()
        result = self.run_json(["address"], {
            "name": name,
            "passphrase": pin,
            "bip39Passphrase": hidden,
            "purpose": purpose,
            "account": 0,
            "change": 0,
            "index": 0,
            "network": self.settings.get("network", "bitcoin"),
        })
        self.show_qr(result["address"], f"{result['label'].upper()} • {result['path']}")

    def wallet_map_actions(self, entry):
        while True:
            action = self.menu(entry["name"], [
                self.tr("SZCZEGÓŁY PUBLICZNE I POCHODZENIE", "PUBLIC DATA AND ORIGIN"),
                self.tr("EKSPLORATOR ADRESÓW", "ADDRESS EXPLORER"),
                self.tr("POKAŻ ADRES ODBIORCZY QR", "SHOW RECEIVE ADDRESS QR"),
                self.tr("PODPISZ PSBT TYM PORTFELEM", "SIGN PSBT WITH THIS WALLET"),
                self.tr("WSTECZ DO MAPY", "BACK TO MAP"),
            ], footer=self.source_label(entry))
            if action == 0:
                self.wallet_details(entry)
            elif action == 1:
                self.wallet_explorer(entry)
            elif action == 2:
                self.show_wallet_receive_qr(entry)
            elif action == 3:
                self.sign(entry)
            else:
                return

    def wallet_map(self):
        entries = self.wallet_catalog(True)
        if not entries: raise ValueError(self.tr("Brak portfeli.", "No wallets."))
        by_name = {entry["name"]: entry for entry in entries}; children = {name: [] for name in by_name}
        roots = []
        for entry in entries:
            parent = entry.get("parent")
            if parent in by_name: children[parent].append(entry["name"])
            else: roots.append(entry["name"])
        ordered, positions, row = [], {}, 0
        def visit(name, depth):
            nonlocal row
            positions[name] = (depth * 280, row * 112); ordered.append(name); row += 1
            for child in sorted(children[name]): visit(child, depth + 1)
        for root in sorted(roots): visit(root, 0)
        zoom, offset_x, offset_y, selected = 1.0, 18.0, 88.0, 0

        def fit():
            nonlocal zoom, offset_x, offset_y
            max_x = max((x for x, _ in positions.values()), default=0) + 250
            max_y = max((y for _, y in positions.values()), default=0) + 96
            zoom = max(0.18, min(1.0, min((WIDTH - 28) / max_x, 178 / max_y)))
            offset_x = 14.0 + max(0.0, ((WIDTH - 28) - max_x * zoom) / 2)
            offset_y = 83.0 + max(0.0, (178 - max_y * zoom) / 2)
        fit()
        while True:
            self.frame(self.tr("MAPA PORTFELI", "WALLET MAP"), self.tr("STRZAŁKI=PRZESUŃ • +/-=ZOOM", "ARROWS=PAN • +/-=ZOOM"))
            clip = pygame.Rect(8, 82, WIDTH - 16, 190); old_clip = self.screen.get_clip(); self.screen.set_clip(clip)
            rendered = {}
            for name in ordered:
                x, y = positions[name]; sx, sy = int(offset_x + x * zoom), int(offset_y + y * zoom)
                rect = pygame.Rect(sx, sy, max(45, int(250 * zoom)), max(18, int(96 * zoom))); rendered[name] = rect
            for child_name in ordered:
                parent = by_name[child_name].get("parent")
                if parent in rendered:
                    pygame.draw.line(self.screen, self.accent, rendered[parent].midright, rendered[child_name].midleft, max(1, int(2 * zoom)))
            for index, name in enumerate(ordered):
                rect = rendered[name]; entry = by_name[name]; active = index == selected
                self.draw_panel(rect, active)
                color = self.background if active else self.text_color
                font_size = max(7, min(24, int(24 * zoom)))
                while True:
                    node_font = pygame.font.Font(None, font_size)
                    name_lines = self.wrapped_for_font(name, node_font, max(8, rect.width - 8))
                    source_lines = self.wrapped_for_font(self.source_label(entry), node_font, max(8, rect.width - 8))
                    all_lines = name_lines + source_lines
                    if font_size <= 7 or len(all_lines) * node_font.get_linesize() <= rect.height - 4: break
                    font_size -= 1
                line_y = rect.y + 2
                for line_number, line in enumerate(all_lines):
                    line_color = color if line_number < len(name_lines) else (self.background if active else self.palette["dim"])
                    self.text(line, rect.x + 4, line_y, node_font, line_color)
                    line_y += node_font.get_linesize()
            self.screen.set_clip(old_clip)
            self.text(self.tr("TAB=WĘZEŁ • ENTER=MENU • 0=DOPASUJ", "TAB=NODE • ENTER=MENU • 0=FIT"), 11, FOOTER_Y, self.small, self.palette["dim"])
            self.present()
            for event in self.events():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE: return
                    if event.key == pygame.K_LEFT: offset_x += 28
                    elif event.key == pygame.K_RIGHT: offset_x -= 28
                    elif event.key == pygame.K_UP: offset_y += 24
                    elif event.key == pygame.K_DOWN: offset_y -= 24
                    elif event.key == pygame.K_TAB: selected = (selected + 1) % len(ordered)
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER): self.wallet_map_actions(by_name[ordered[selected]])
                    elif event.unicode in ("+", "="): zoom = min(1.8, zoom + 0.15)
                    elif event.unicode == "-": zoom = max(0.35, zoom - 0.15)
                    elif event.unicode == "0": fit()
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    hit = next((index for index, name in enumerate(ordered) if rendered[name].collidepoint(event.pos)), None)
                    if hit is not None:
                        selected = hit
                        self.wallet_map_actions(by_name[ordered[hit]])
            self.clock.tick(30)

    def wallet_management(self):
        while True:
            choice = self.menu(self.tr("PORTFELE", "WALLETS"), [
                self.tr("WYBIERZ / UKRYJ / USUŃ", "SELECT / HIDE / DELETE"),
                self.tr("MAPA HIERARCHII", "HIERARCHY MAP"),
                self.tr("NOWY PORTFEL BIP85", "NEW BIP85 CHILD"),
                self.tr("WSTECZ", "BACK")])
            if choice == 0: self.manage_wallet(self.select_wallet(True))
            elif choice == 1: self.wallet_map()
            elif choice == 2: self.create_bip85_child()
            else: return

    def simple_address_standard(self):
        purposes = [84, 86, 49, 44]
        labels = [
            self.tr("NATIVE SEGWIT • bc1q • ZALECANY", "NATIVE SEGWIT • bc1q • RECOMMENDED"),
            self.tr("TAPROOT • bc1p • NOWSZY STANDARD", "TAPROOT • bc1p • NEWER STANDARD"),
            self.tr("NESTED SEGWIT • 3… • ZGODNOŚĆ", "NESTED SEGWIT • 3… • COMPATIBILITY"),
            self.tr("LEGACY • 1… • STARSZE PORTFELE", "LEGACY • 1… • OLDER WALLETS"),
        ]
        choice = self.menu(self.tr("RODZAJ ADRESU", "ADDRESS TYPE"), labels,
            footer=self.tr("W razie wątpliwości wybierz bc1q", "If unsure, choose bc1q"))
        return purposes[choice]

    def simple_receive(self, entry=None):
        self.show(self.tr("ODBIERANIE BITCOIN", "RECEIVING BITCOIN"), self.tr(
            "Wybierz portfel i rodzaj adresu. Pokaż QR osobie wysyłającej. Przed przyjęciem większej kwoty porównaj cały adres na obu urządzeniach.",
            "Choose a wallet and address type. Show the QR to the sender. Before receiving a large amount, compare the full address on both devices.",
        ))
        if entry is None:
            entry = self.select_wallet(False, self.tr("PORTFEL ODBIORCZY", "RECEIVING WALLET"))
        name, pin, entry = self.credentials_for_entry(entry)
        purpose = self.simple_address_standard()
        account = self.ask_hd_account()
        hidden = self.ask_bip39_passphrase()
        index_text = self.ask(self.tr("NUMER ADRESU", "ADDRESS NUMBER"), self.tr(
            "0 = pierwszy. Użyj numeru zgodnego z portfelem watch-only w telefonie.",
            "0 = first. Use the number matching your phone's watch-only wallet.",
        ), initial="0")
        index = int(index_text or 0)
        if index < 0 or index > 1000000:
            raise ValueError(self.tr("Numer adresu musi być w zakresie 0–1000000.", "Address number must be between 0 and 1000000."))
        result = self.run_json(["address"], {
            "name": name, "passphrase": pin, "bip39Passphrase": hidden,
            "purpose": purpose, "account": account, "change": 0, "index": index,
            "network": self.settings.get("network", "bitcoin"),
        })
        self.show(self.tr("SPRAWDŹ ADRES", "VERIFY ADDRESS"), self.tr(
            f"Portfel: {name}\nKonto HD: #{account}\nStandard: {result['label']} • {result['bip']}\nNumer adresu: #{index}\nAdres:\n{result['address']}\n\nPorównaj cały adres przed użyciem.",
            f"Wallet: {name}\nHD account: #{account}\nStandard: {result['label']} • {result['bip']}\nAddress number: #{index}\nAddress:\n{result['address']}\n\nCompare the full address before use.",
        ))
        self.show_qr(result["address"], self.tr("ADRES ODBIORCZY", "RECEIVE ADDRESS") + f" • {result['label'].upper()}")

    def simple_watch_only(self):
        self.show(self.tr("POŁĄCZ TELEFON", "CONNECT A PHONE"), self.tr(
            "Telefon otrzyma wyłącznie rozszerzony klucz publiczny. Będzie widział saldo i tworzył PSBT, ale nie będzie mógł sam podpisać wydatku. Nie skanuj seeda ani klucza prywatnego.",
            "The phone receives only an extended public key. It can view the balance and create a PSBT, but cannot sign a spend by itself. Never scan the seed or a private key.",
        ))
        entry = self.select_wallet(False, self.tr("PORTFEL DLA TELEFONU", "WALLET FOR PHONE"))
        name, pin, entry = self.credentials_for_entry(entry)
        purpose = self.simple_address_standard()
        account = self.ask_hd_account()
        hidden = self.ask_bip39_passphrase()
        result = self.run_json(["address"], {
            "name": name, "passphrase": pin, "bip39Passphrase": hidden,
            "purpose": purpose, "account": account, "change": 0, "index": 0,
            "network": self.settings.get("network", "bitcoin"),
        })
        key = result.get("watchOnlyKey")
        if not key:
            raise ValueError(self.tr(
                "Ten portfel zawiera pojedynczy klucz i nie ma klucza HD watch-only.",
                "This wallet contains a single key and has no HD watch-only key.",
            ))
        self.show(self.tr("ZAPAMIĘTAJ ADRES KONTROLNY", "NOTE THE CHECK ADDRESS"), self.tr(
            f"Portfel: {name}\nKonto HD: #{account}\nStandard: {result['label']} • {result['bip']}\nEksport obejmuje wszystkie adresy #0, #1, #2… tego konta. BlueWallet: dodaj portfel → importuj → zeskanuj następny QR z descriptorem. Włącz użycie z portfelem sprzętowym. Adres #0 musi być identyczny:\n{result['address']}",
            f"Wallet: {name}\nHD account: #{account}\nStandard: {result['label']} • {result['bip']}\nThis export covers every address #0, #1, #2… of this account. BlueWallet: add wallet → import → scan the descriptor QR. Enable use with a hardware wallet. Address #0 must match exactly:\n{result['address']}",
        ))
        self.show_qr(result["descriptor"], f"DESCRIPTOR • {result['bip']} • {name}")

    def simple_sign(self, entry=None):
        self.show(self.tr("PODPISYWANIE TRANSAKCJI", "SIGNING A TRANSACTION"), self.tr(
            "Najpierw przygotuj transakcję w portfelu watch-only w telefonie. Wyeksportuj PSBT do QR albo do folderu /EntropySilo na pendrivie. Na następnym ekranie sprawdź KAŻDY adres i opłatę.",
            "First prepare the transaction in your phone's watch-only wallet. Export the PSBT as a QR or into /EntropySilo on a USB drive. On the next screen, verify EVERY address and the fee.",
        ))
        if entry is None:
            entry = self.select_wallet(False, self.tr("PORTFEL PODPISUJĄCY", "SIGNING WALLET"))
        self.sign(entry)

    def simple_wallet_view(self):
        entry = self.select_wallet(False, self.tr("WYBIERZ PORTFEL", "SELECT WALLET"))
        while True:
            choice = self.menu(entry["name"], [
                self.tr("POKAŻ ADRES ODBIORCZY I QR", "SHOW RECEIVE ADDRESS AND QR"),
                self.tr("SPRAWDŹ ADRESY I DANE PUBLICZNE", "CHECK ADDRESSES AND PUBLIC DATA"),
                self.tr("PODPISZ TRANSAKCJĘ TYM PORTFELEM", "SIGN A TRANSACTION WITH THIS WALLET"),
                self.tr("POCHODZENIE I SZCZEGÓŁY", "ORIGIN AND DETAILS"),
                self.tr("WSTECZ", "BACK"),
            ], footer=self.source_label(entry))
            if choice == 0: self.simple_receive(entry)
            elif choice == 1: self.wallet_explorer(entry)
            elif choice == 2: self.simple_sign(entry)
            elif choice == 3: self.wallet_details(entry)
            else: return

    def simple_add_recover(self):
        choice = self.menu(self.tr("DODAJ LUB ODZYSKAJ", "ADD OR RECOVER"), [
            self.tr("NOWY • BEZPIECZNA LOSOWOŚĆ SYSTEMOWA", "NEW • SECURE SYSTEM RANDOMNESS"),
            self.tr("NOWY • DWIE TALIE KART + SYSTEM", "NEW • TWO CARD DRAWS + SYSTEM"),
            self.tr("ODZYSKAJ Z BIP39 LUB SWD", "RECOVER FROM BIP39 OR SWD"),
            self.tr("IMPORTUJ SEKRET Z USB", "IMPORT A SECRET FROM USB"),
            self.tr("WSTECZ", "BACK"),
        ], footer=self.tr("Nowy portfel zawsze ma 24 słowa", "A new wallet always has 24 words"))
        if choice == 0: self.create_wallet(False)
        elif choice == 1: self.create_wallet(True)
        elif choice == 2: self.recover()
        elif choice == 3: self.import_secret_usb()

    def simple_help(self):
        self.show(self.tr("JAK TO DZIAŁA", "HOW IT WORKS"), self.tr(
            "ODBIERANIE: pokaż publiczny adres QR.\n\nWATCH-ONLY: telefon widzi saldo i przygotowuje transakcję, ale nie zna seeda.\n\nPODPIS: EntropySilo odczytuje PSBT, pokazuje adresy i opłatę, a po Twoim potwierdzeniu podpisuje offline.\n\nSEED/PIN: nigdy nie wpisuj ich do telefonu ani komputera. Zachowaj papierowy backup.\n\nDUŻA KWOTA: najpierw wykonaj małą transakcję testową i sprawdź możliwość odzyskania backupu.",
            "RECEIVE: show a public address QR.\n\nWATCH-ONLY: the phone sees the balance and prepares transactions, but does not know the seed.\n\nSIGN: EntropySilo reads a PSBT, shows addresses and the fee, then signs offline after your confirmation.\n\nSEED/PIN: never enter them into a phone or computer. Keep the paper backup.\n\nLARGE AMOUNT: first make a small test transaction and verify that your backup can be recovered.",
        ))

    def simple_main_items(self):
        return [
            self.tr("ODBIERZ BITCOIN • ADRES I QR", "RECEIVE BITCOIN • ADDRESS AND QR"),
            self.tr("PODPISZ PRZYGOTOWANĄ TRANSAKCJĘ", "SIGN A PREPARED TRANSACTION"),
            self.tr("POŁĄCZ TELEFON WATCH-ONLY", "CONNECT A WATCH-ONLY PHONE"),
            self.tr("WYBIERZ I SPRAWDŹ PORTFEL", "SELECT AND CHECK A WALLET"),
            self.tr("DODAJ LUB ODZYSKAJ PORTFEL", "ADD OR RECOVER A WALLET"),
            self.tr("LISTA I MAPA PORTFELI", "WALLET LIST AND MAP"),
            self.tr("POMOC I BEZPIECZEŃSTWO", "HELP AND SAFETY"),
            self.tr("PRZEJDŹ DO TRYBU ZAAWANSOWANEGO", "SWITCH TO ADVANCED MODE"),
            self.tr("ZABLOKUJ", "LOCK"),
            self.tr("WYŁĄCZ", "POWER OFF"),
        ]

    def simple_main_once(self):
        choice = self.menu(self.tr("ENTROPYSILO • TRYB PROSTY", "ENTROPYSILO • SIMPLE MODE"), self.simple_main_items())
        actions = [self.simple_receive, self.simple_sign, self.simple_watch_only, self.simple_wallet_view,
            self.simple_add_recover, self.wallet_management, self.simple_help]
        if choice < len(actions): actions[choice]()
        elif choice == 7:
            self.settings["uiMode"] = "advanced"; self.save_settings()
        elif choice == 8: self.lock()
        else: self.shutdown()

    def diagnostics(self):
        node = subprocess.run([NODE, "-v"], capture_output=True, text=True, check=False).stdout.strip()
        net = Path("/sys/class/net")
        interfaces = ", ".join(sorted(path.name for path in net.iterdir())) if net.exists() else "?"
        physical = self.output.get_size()
        self.show(self.tr("DIAGNOSTYKA", "DIAGNOSTICS"), self.tr(
            f"Node: {node}\nPython: {sys.version.split()[0]}\nInterfejsy: {interfaces}\nGUI: {WIDTH}x{HEIGHT} -> ekran {physical[0]}x{physical[1]}\nSkarbiec: AES-256-GCM + scrypt\nPolityka sieciowa powinna wynosić DROP/DROP.",
            f"Node: {node}\nPython: {sys.version.split()[0]}\nInterfaces: {interfaces}\nGUI: {WIDTH}x{HEIGHT} -> display {physical[0]}x{physical[1]}\nVault: AES-256-GCM + scrypt\nThe network policy should be DROP/DROP.",
        ))

    def change_pin(self):
        name, old_pin = self.credentials(); new_pin = self.password_twice()
        self.run_json(["change-pin"], {"name": name, "oldPin": old_pin, "newPin": new_pin})
        self.session_pin = new_pin
        self.show(self.tr("PIN ZMIENIONY", "PIN CHANGED"), name)

    def expert_settings(self):
        while True:
            unknown_fee_state = self.tr("ZEZWÓL", "ALLOW") if self.settings.get("allowUnknownFee") else self.tr("BLOKUJ", "BLOCK")
            choice = self.menu(self.tr("USTAWIENIA EKSPERCKIE", "EXPERT SETTINGS"), [
                self.tr(f"SIEĆ: {self.settings.get('network','bitcoin')}", f"NETWORK: {self.settings.get('network','bitcoin')}"),
                self.tr(f"DERYWACJA: BIP{self.settings.get('purpose',84)}", f"DERIVATION: BIP{self.settings.get('purpose',84)}"),
                self.tr(f"AUTOBLOKADA: {self.settings.get('autoLock',120)} s", f"AUTO-LOCK: {self.settings.get('autoLock',120)} s"),
                self.tr(f"MAKS. OPŁATA: {self.settings.get('maxFeeSats',100000)} sat", f"MAX FEE: {self.settings.get('maxFeeSats',100000)} sat"),
                self.tr(f"NIEZNANA OPŁATA: {unknown_fee_state}", f"UNKNOWN FEE: {unknown_fee_state}"),
                self.tr(f"MOTYW: {self.settings.get('theme','mono').upper()}", f"THEME: {self.settings.get('theme','mono').upper()}"), self.tr("ZMIEŃ PIN", "CHANGE PIN"),
                self.tr("KALIBRUJ DOTYK", "CALIBRATE TOUCH"), self.tr("ZEZWÓL NA NOWĄ KLAWIATURĘ USB", "ALLOW NEW USB KEYBOARD"),
                self.tr("ZMIEŃ JĘZYK", "CHANGE LANGUAGE"),
                self.tr("WSTECZ", "BACK")])
            if choice == 0: self.settings["network"] = ["bitcoin", "testnet", "signet"][self.menu(self.tr("SIEĆ", "NETWORK"), ["BITCOIN MAINNET", "TESTNET", "SIGNET"])]
            elif choice == 1: self.settings["purpose"] = [44, 49, 84, 86][self.menu(self.tr("DERYWACJA", "DERIVATION"), ["BIP44", "BIP49", "BIP84", "BIP86"])]
            elif choice == 2: self.settings["autoLock"] = [60, 120, 300, 0][self.menu(self.tr("AUTOBLOKADA", "AUTO-LOCK"), ["60 s", "120 s", "300 s", self.tr("WYŁĄCZONA (RYZYKO)", "DISABLED (RISK)")])]
            elif choice == 3: self.settings["maxFeeSats"] = int(self.ask(self.tr("MAKS. OPŁATA W SAT", "MAX FEE IN SAT"), self.tr("np. 100000", "e.g. 100000"), initial=str(self.settings.get("maxFeeSats", 100000))))
            elif choice == 4:
                if self.confirm(self.tr("NIEZNANA OPŁATA", "UNKNOWN FEE"), self.tr("Zmienić politykę PSBT?", "Change the PSBT policy?")): self.settings["allowUnknownFee"] = not self.settings.get("allowUnknownFee", False)
            elif choice == 5:
                names = list(THEMES)
                self.settings["theme"] = names[self.menu(self.tr("MOTYW GRAFICZNY", "GRAPHIC THEME"), [name.upper() for name in names])]
            elif choice == 6: self.change_pin()
            elif choice == 7: self.calibrate_touch()
            elif choice == 8:
                if self.hardware.input:
                    self.hardware.input.allow_next_keyboard(60)
                    self.show(self.tr("PAROWANIE HID", "HID PAIRING"), self.tr("Podłącz teraz jedną zaufaną klawiaturę. Okno zgody trwa 60 sekund.", "Connect one trusted keyboard now. The authorization window lasts 60 seconds."))
                else: raise ValueError(self.tr("Most wejścia evdev jest niedostępny.", "The evdev input bridge is unavailable."))
            elif choice == 9: self.lang = "en" if self.menu("LANGUAGE / JĘZYK", ["English", "Polski"]) == 0 else "pl"
            else: self.save_settings(); return
            self.save_settings()

    def factory_reset(self):
        name = self.session_wallet or self.wallets()
        password = self.ask_pin(self.tr("POTWIERDŹ PIN", "CONFIRM PIN"), name)
        phrase = self.ask(self.tr("RESET FABRYCZNY", "FACTORY RESET"), self.tr("Wpisz RESET", "Type RESET"))
        if phrase != "RESET": raise ValueError(self.tr("Nieprawidłowe potwierdzenie.", "Incorrect confirmation."))
        if not self.confirm(self.tr("USUNĄĆ PORTFELE?", "ERASE WALLETS?"), self.tr("Tego nie można cofnąć", "This cannot be undone"), dangerous=True): return
        self.run_json(["factory-reset"], {"name": name, "passphrase": password, "confirm": "FACTORY RESET"})
        self.session_pin = None; self.session_wallet = None; self.session_entry = None
        try: self.settings_path.unlink(missing_ok=True)
        except OSError: pass
        try: self.touch_calibration_path.unlink(missing_ok=True)
        except OSError: pass
        self.lang = "en"
        self.show(self.tr("RESET", "RESET"), self.tr("Reset urządzenia zakończony. Uruchomi się kreator pierwszej konfiguracji.", "Device reset complete. The first-run wizard will start now."))
        pygame.quit()
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve())])

    def lock(self):
        self.session_pin = None; self.session_wallet = None; self.session_entry = None
        self.unlock()

    def enable_simple_mode(self):
        self.settings["uiMode"] = "simple"
        self.save_settings()
        self.show(self.tr("TRYB PROSTY WŁĄCZONY", "SIMPLE MODE ENABLED"), self.tr(
            "Główne menu będzie teraz prowadzić krok po kroku. Wszystkie funkcje zaawansowane pozostają dostępne po ponownym przełączeniu trybu.",
            "The main menu will now provide step-by-step guidance. All advanced functions remain available after switching modes again.",
        ))

    def advanced_main_once(self):
        choice = self.menu("ENTROPYSILO", [
            self.tr("EKSPLORATOR PORTFELA", "WALLET EXPLORER"),
            self.tr("PODPISZ PSBT", "SIGN PSBT"),
            self.tr("PORTFELE / MAPA", "WALLETS / MAP"),
            self.tr("NOWY • DWIE TALIE KART", "NEW • TWO CARD DECKS"),
            self.tr("NOWY • LOSOWOŚĆ SYSTEMOWA", "NEW • SYSTEM RANDOMNESS"),
            self.tr("ODZYSKAJ BIP39 / SWD", "RECOVER BIP39 / SWD"),
            self.tr("NARZĘDZIA SWD", "SWD TOOLS"),
            self.tr("USTAWIENIA EKSPERCKIE", "EXPERT SETTINGS"),
            self.tr("USB • IMPORT / BACKUP", "USB • IMPORT / BACKUP"),
            self.tr("PRZEJDŹ DO TRYBU PROSTEGO", "SWITCH TO SIMPLE MODE"),
            self.tr("DIAGNOSTYKA", "DIAGNOSTICS"),
            self.tr("ZABLOKUJ", "LOCK"),
            self.tr("RESET FABRYCZNY", "FACTORY RESET"),
            self.tr("WYŁĄCZ", "POWER OFF"),
        ])
        actions = [self.wallet_explorer, self.sign, self.wallet_management,
            lambda: self.create_wallet(True), lambda: self.create_wallet(False), self.recover, self.swd,
            self.expert_settings, self.usb_backup_menu, self.enable_simple_mode, self.diagnostics,
            self.lock, self.factory_reset, self.shutdown]
        actions[choice]()

    def main(self):
        self.auto_lock_enabled = True
        if not self.session_pin: self.unlock()
        while self.running:
            try:
                if self.settings.get("uiMode") == "simple": self.simple_main_once()
                else: self.advanced_main_once()
            except Locked: self.unlock()
            except Cancelled: continue
            except Exception as error: self.show(self.tr("BŁĄD", "ERROR"), self.localize_error(str(error)))

    def shutdown(self):
        if self.confirm(self.tr("WYŁĄCZYĆ?", "POWER OFF?"), self.tr("Bezpieczne zamknięcie systemu", "Shut down the system safely")):
            self.auto_lock_enabled = False
            self.screen.fill(BLACK)
            self.text(self.tr("WYŁĄCZANIE…", "SHUTTING DOWN…"), 76, 96, self.large, PHOSPHOR)
            self.text(self.tr("NIE ODŁĄCZAJ ZASILANIA", "DO NOT REMOVE POWER"), 63, 158, self.small, WHITE)
            self.text(self.tr("CZEKAJ NA ZATRZYMANIE ACT LED", "WAIT UNTIL ACT LED STOPS"), 49, 207, self.small, GRAY)
            self.present()
            self.usb_call("poweroff", timeout=20)
            while True:
                self.present(); self.clock.tick(2)


if __name__ == "__main__" and "--self-test-touch" in sys.argv:
    test_samples = [
        (100, 200, 42, 72), (3900, 200, 438, 72),
        (3900, 3800, 438, 276), (100, 3800, 42, 276),
        (2000, 2000, 240, 174),
    ]
    test_result = solve_touch_calibration(test_samples)
    if test_result["rmsPixels"] > 0.01:
        raise SystemExit("touch calibration self-test failed")
    print("TOUCH_CALIBRATION_SELF_TEST_OK")
    raise SystemExit(0)


if __name__ == "__main__":
    app = WalletGUI()
    try:
        if not app.settings.get("setupComplete") and "--post-onboarding" not in sys.argv:
            app.first_run()
            pygame.quit()
            os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), "--post-onboarding"])
        app.main()
    finally:
        app.hardware.close()
        pygame.quit()
