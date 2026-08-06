#!/usr/bin/env python3
"""Renderuje kontrolne ekrany GUI bez uruchamiania portfela ani generowania seeda."""
import os
import sys
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["ENTROPYSILO_DIRECT_FB"] = "0"
os.environ["HOME"] = "/tmp/entropysilo-preview-home"

project = Path("/mnt/project")
sys.path.insert(0, str(project / "apps"))
import pygame
from wallet_gui import Cancelled, WalletGUI

output = project / "build"
output.mkdir(parents=True, exist_ok=True)
app = WalletGUI()

def capture(method, filename):
    captured = False
    original = app.present
    def present_once():
        nonlocal captured
        original()
        if not captured:
            pygame.image.save(app.screen, str(output / filename))
            captured = True
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0))
    app.present = present_once
    try: method()
    except Cancelled: pass
    finally:
        app.present = original
        pygame.event.clear()

capture(lambda: app.menu("LANGUAGE / JĘZYK", ["English (default)", "Polski"]), "gui-preview-first-run.png")
capture(lambda: app.ask("NAZWA PORTFELA", "dotknij pola lub użyj klawiatury USB", initial="wallet1"), "gui-preview-keyboard.png")
capture(lambda: app.ask_pin("SET PIN", "exactly 12 digits"), "gui-preview-pin.png")
app.hardware.close()
pygame.quit()
print("Wyrenderowano 3 ekrany kontrolne 480x320.")
