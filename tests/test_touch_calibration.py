"""Host-side test for touch math without requiring SDL/Pygame."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


pygame_stub = types.ModuleType("pygame")
for index, name in enumerate(
    "K_UP K_DOWN K_LEFT K_RIGHT K_RETURN K_KP_ENTER K_ESCAPE K_BACKSPACE K_SPACE K_TAB KMOD_SHIFT KMOD_CAPS".split(),
    start=1,
):
    setattr(pygame_stub, name, index)
pygame_stub.USEREVENT = 1000
sys.modules.setdefault("pygame", pygame_stub)

from apps.wallet_gui import FONT_SIZE, LARGE_FONT_SIZE, SMALL_FONT_SIZE, map_display_position, solve_touch_calibration


def test_affine_touch_calibration():
    assert (FONT_SIZE, SMALL_FONT_SIZE, LARGE_FONT_SIZE) == (32, 24, 40)
    samples = [
        (100, 200, 42, 72),
        (3900, 200, 438, 72),
        (3900, 3800, 438, 276),
        (100, 3800, 42, 276),
        (2000, 2000, 240, 174),
    ]
    result = solve_touch_calibration(samples)
    assert result["version"] == 1
    assert len(result["matrix"]) == 6
    assert result["rmsPixels"] < 0.01


def test_live_display_pointer_mapping():
    assert map_display_position((0, 0), (1920, 1080)) == (0, 0)
    assert map_display_position((960, 540), (1920, 1080)) == (240, 160)
    assert map_display_position((1919, 1079), (1920, 1080)) == (479, 319)
    assert map_display_position((683, 384), (1366, 768)) == (240, 160)


if __name__ == "__main__":
    test_affine_touch_calibration()
    test_live_display_pointer_mapping()
    print("TOUCH_AFFINE_OK")
