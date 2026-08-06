#!/usr/bin/env python3
"""Headless ARM test of keyboard navigation, PIN confirmation and Caps Lock."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["ENTROPYSILO_DIRECT_FB"] = "0"
test_home = Path(tempfile.mkdtemp(prefix="entropysilo-gui-test-"))
os.environ["HOME"] = str(test_home)
(test_home / "settings.json").write_text(json.dumps({"setupComplete": True}), encoding="utf-8")

project = Path(__file__).resolve().parent.parent
app_dir = Path(os.environ.get("ENTROPYSILO_TEST_APP_DIR", str(project / "apps")))
sys.path.insert(0, str(app_dir))

import pygame
from wallet_gui import LinuxInputBridge, WalletGUI

try:
    from evdev import ecodes
except ImportError:
    ecodes = None


def key(key_code, unicode=""):
    return pygame.event.Event(pygame.KEYDOWN, key=key_code, unicode=unicode, mod=0)


def drive(app, method, events):
    queue = list(events)
    original_present = app.present

    def present_and_send():
        original_present()
        if queue:
            pygame.event.post(queue.pop(0))

    app.present = present_and_send
    try:
        result = method()
        assert not queue, f"unconsumed GUI events: {len(queue)}"
        return result
    finally:
        app.present = original_present
        pygame.event.clear()


app = WalletGUI()
try:
    assert drive(
        app,
        lambda: app.ask("TEXT", "navigation test"),
        [
            key(pygame.K_RIGHT),                    # select virtual "2"
            key(pygame.K_RETURN),                   # activate selected "2"
            key(pygame.K_a, "A"),                  # physical USB input selects OK
            key(pygame.K_RETURN),                   # activate OK
        ],
    ) == "2A"

    assert drive(
        app,
        lambda: app.ask("TEXT", "initial value", initial="wallet1"),
        [key(pygame.K_RETURN)],                     # initial text starts on OK
    ) == "wallet1"

    pin_events = [key(pygame.K_RIGHT), key(pygame.K_RETURN)]
    pin_events += [key(getattr(pygame, f"K_{digit}"), digit) for digit in "12345678901"]
    pin_events += [key(pygame.K_RETURN)]             # physical digits leave focus on OK
    assert drive(app, lambda: app.ask_pin("PIN", "12 digits"), pin_events) == "212345678901"

    if ecodes is not None:
        bridge = LinuxInputBridge.__new__(LinuxInputBridge)
        bridge.shift_keys, bridge.caps_lock = set(), False
        emitted = []
        original_post = pygame.event.post
        pygame.event.post = emitted.append
        try:
            bridge._keyboard(type("E", (), {"code": ecodes.KEY_CAPSLOCK, "value": 1})())
            bridge._keyboard(type("E", (), {"code": ecodes.KEY_A, "value": 1})())
            assert emitted.pop().unicode == "A"
            bridge._keyboard(type("E", (), {"code": ecodes.KEY_LEFTSHIFT, "value": 1})())
            bridge._keyboard(type("E", (), {"code": ecodes.KEY_A, "value": 1})())
            assert emitted.pop().unicode == "a"      # Caps XOR Shift
        finally:
            pygame.event.post = original_post

    # Explorer must allow choosing any visible wallet, not only the session wallet.
    original_select, original_pin, original_run = app.select_wallet, app.ask_pin, app.run_json
    calls = []
    try:
        app.session_wallet, app.session_pin = "root", "111111111111"
        app.select_wallet = lambda include_hidden=False, title=None: {
            "name": "legacy_swd2", "source": "legacy-from-swd2", "hidden": False,
        }
        app.ask_pin = lambda title, prompt: "222222222222"
        app.run_json = lambda args, data: calls.append((args, data)) or {"unlocked": True}
        name, pin, entry = app.choose_wallet_credentials()
        assert name == "legacy_swd2" and pin == "222222222222"
        assert entry["hidden"] is False
        assert calls == [(["verify"], {"name": "legacy_swd2", "passphrase": "222222222222"})]
        assert app.session_wallet == "legacy_swd2"
    finally:
        app.select_wallet, app.ask_pin, app.run_json = original_select, original_pin, original_run

    original_menu = app.menu
    try:
        app.menu = lambda title, items, footer="": 2
        assert app.choose_address_standard() == 86
    finally:
        app.menu = original_menu

    app.lang = "pl"
    polish_simple = app.simple_main_items()
    assert polish_simple[0] == "ODBIERZ BITCOIN • ADRES I QR"
    assert polish_simple[-1] == "WYŁĄCZ"
    app.lang = "en"
    english_simple = app.simple_main_items()
    assert english_simple[0] == "RECEIVE BITCOIN • ADDRESS AND QR"
    assert english_simple[-1] == "POWER OFF"

    print("GUI_NAVIGATION_CAPS_PIN_WALLET_SELECTION_OK")
finally:
    app.hardware.close()
    pygame.quit()
    shutil.rmtree(test_home, ignore_errors=True)
