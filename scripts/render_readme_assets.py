#!/usr/bin/env python3
"""Render deterministic README screenshots from the real EntropySilo GUI."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["ENTROPYSILO_DIRECT_FB"] = "0"

PROJECT = Path(__file__).resolve().parents[1]
PREVIEW_HOME = PROJECT / "build" / "readme-preview-home"
PREVIEW_HOME.mkdir(parents=True, exist_ok=True)
(PREVIEW_HOME / "settings.json").write_text(json.dumps({
    "language": "en",
    "setupComplete": True,
    "theme": "phosphor",
    "uiMode": "advanced",
}), encoding="utf-8")
os.environ["HOME"] = str(PREVIEW_HOME)
sys.path.insert(0, str(PROJECT / "apps"))

import pygame
from wallet_gui import Cancelled, WalletGUI

OUTPUT = PROJECT / "docs" / "assets"
OUTPUT.mkdir(parents=True, exist_ok=True)
app = WalletGUI()
app.lang = "en"
app.settings.update({"language": "en", "theme": "phosphor", "setupComplete": True})


def capture_first(method, filename: str) -> None:
    """Capture the first fully drawn frame and exit the interactive method."""
    original = app.present
    captured = False

    def present_once():
        nonlocal captured
        original()
        if not captured:
            pygame.image.save(app.screen, str(OUTPUT / filename))
            captured = True
            pygame.event.post(pygame.event.Event(
                pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0,
            ))

    app.present = present_once
    try:
        method()
    except Cancelled:
        pass
    finally:
        app.present = original
        pygame.event.clear()


def capture_cards() -> None:
    """Select sample cards through the actual keyboard path, then capture it."""
    original = app.present
    actions = [
        (pygame.K_RETURN, ""),
        (pygame.K_RIGHT, ""), (pygame.K_RETURN, ""),
        (pygame.K_RIGHT, ""), (pygame.K_RETURN, ""),
        (pygame.K_RIGHT, ""), (pygame.K_RETURN, ""),
        (pygame.K_DOWN, ""), (pygame.K_RETURN, ""),
        (pygame.K_LEFT, ""), (pygame.K_RETURN, ""),
    ]
    frame = 0

    def drive():
        nonlocal frame
        original()
        if frame < len(actions):
            key, unicode_value = actions[frame]
            pygame.event.post(pygame.event.Event(
                pygame.KEYDOWN, key=key, unicode=unicode_value, mod=0,
            ))
        elif frame == len(actions):
            pygame.image.save(app.screen, str(OUTPUT / "card-entropy.png"))
            pygame.event.post(pygame.event.Event(
                pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0,
            ))
        frame += 1

    app.present = drive
    try:
        app.collect_deck(1)
    except Cancelled:
        pass
    finally:
        app.present = original
        pygame.event.clear()


def capture_wallet_map() -> None:
    catalog = [
        {"name": "ROOT-CARDS", "source": "generated-cards", "wordCount": 24,
         "parent": None, "hidden": False, "restorable": False},
        {"name": "DAILY-BIP85", "source": "bip85-child", "wordCount": 24,
         "parent": "ROOT-CARDS", "bip85Index": 0, "hidden": False, "restorable": True},
        {"name": "SAVINGS-BIP85", "source": "bip85-child", "wordCount": 24,
         "parent": "ROOT-CARDS", "bip85Index": 1, "hidden": False, "restorable": True},
    ]
    original_catalog = app.wallet_catalog
    app.wallet_catalog = lambda include_hidden=False: catalog
    try:
        capture_first(app.wallet_map, "wallet-map.png")
    finally:
        app.wallet_catalog = original_catalog


def capture_address_types() -> None:
    types = [
        {"purpose": 84, "label": "Native SegWit", "bip": "BIP84",
         "path": "m/84'/0'/0'/0/0", "address": "bc1q9example7silo3public0address"},
        {"purpose": 49, "label": "Nested SegWit", "bip": "BIP49",
         "path": "m/49'/0'/0'/0/0", "address": "3EntropySiloExampleAddress"},
        {"purpose": 86, "label": "Taproot", "bip": "BIP86",
         "path": "m/86'/0'/0'/0/0", "address": "bc1pexample7silo3taproot0address"},
        {"purpose": 44, "label": "Legacy", "bip": "BIP44",
         "path": "m/44'/0'/0'/0/0", "address": "1EntropySiloExampleAddress"},
    ]
    capture_first(lambda: app.address_type_menu(types, 84), "address-standards.png")


def capture_psbt_review() -> None:
    body = (
        "WALLET: DAILY-BIP85\n"
        "HD ACCOUNT: #0\n"
        "FINGERPRINT: 7A3C91E2\n"
        "INPUTS: 1\n"
        "TOTAL OUTPUTS: 125000 sat\n"
        "FEE: 420 sat\n\n"
        "OUTPUT 0: 100000 sat\n"
        "bc1q…verify-on-screen"
    )
    capture_first(lambda: app.show("VERIFY TRANSACTION", body), "psbt-review.png")


capture_first(lambda: app.menu("ENTROPYSILO", [
    "WALLET EXPLORER",
    "SIGN PSBT",
    "WALLETS / MAP",
    "NEW • TWO CARD DECKS",
]), "main-menu.png")
capture_cards()
capture_address_types()
capture_wallet_map()
capture_psbt_review()

app.hardware.close()
pygame.quit()
print(f"Rendered README assets in {OUTPUT}")
