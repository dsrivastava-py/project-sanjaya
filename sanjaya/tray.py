"""System tray icon + menu (PRD §11). Featherweight: pystray + a Pillow-drawn
"Divya Drishti" eye glyph (gold on midnight). A paused badge overlays a dot.

The tray owns no logic — every menu item calls back into the app controller.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

# brand tokens (PRD §4.2)
_MIDNIGHT = (10, 13, 25)
_GOLD = (232, 180, 74)
_PAUSE = (224, 122, 63)


def make_image(paused: bool = False) -> Image.Image:
    """A minimal gold eye (almond + iris + rising arc) on midnight, 64px."""
    img = Image.new("RGBA", (64, 64), (*_MIDNIGHT, 255))
    d = ImageDraw.Draw(img)
    # almond eye outline
    d.ellipse((8, 20, 56, 44), outline=_GOLD, width=3)
    # iris
    d.ellipse((26, 24, 38, 40), fill=_GOLD)
    # rising arc above
    d.arc((16, 6, 48, 34), start=200, end=340, fill=_GOLD, width=3)
    if paused:
        d.ellipse((44, 44, 62, 62), fill=_PAUSE)
    return img


def build(controller) -> "object":
    """Create (but do not run) the pystray Icon for the given controller."""
    import pystray
    from pystray import Menu, MenuItem

    def _paused(_item):
        return controller.is_paused()

    def _autostart(_item):
        return controller.autostart_enabled()

    menu = Menu(
        MenuItem("Open Dashboard", lambda: controller.open_dashboard(), default=True),
        Menu.SEPARATOR,
        MenuItem("Pause", Menu(
            MenuItem("15 minutes", lambda: controller.pause(15)),
            MenuItem("1 hour", lambda: controller.pause(60)),
            MenuItem("Rest of day", lambda: controller.pause(None)),
        )),
        MenuItem("Resume", lambda: controller.resume(), visible=_paused),
        MenuItem("Summarize now", lambda: controller.summarize_now()),
        Menu.SEPARATOR,
        MenuItem("Start with Windows", lambda: controller.toggle_autostart(),
                 checked=_autostart),
        MenuItem("Quit", lambda: controller.quit()),
    )
    icon = pystray.Icon("sanjaya", make_image(False), "Sanjaya", menu)
    return icon
