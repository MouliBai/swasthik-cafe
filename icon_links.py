from pathlib import Path


ICON_DIR = Path(__file__).resolve().parent / "icon"

ICONS = {
    "search": ICON_DIR / "search.svg",
    "cart": ICON_DIR / "cart.svg",
    "refresh": ICON_DIR / "refresh.svg",
    "receipt": ICON_DIR / "receipt.svg",
    "bell": ICON_DIR / "bell.svg",
    "print": ICON_DIR / "print.svg",
    "back": ICON_DIR / "back.svg",
    "cash": ICON_DIR / "cash.svg",
    "card": ICON_DIR / "card.svg",
    "wallet": ICON_DIR / "wallet.svg",
    "delete": ICON_DIR / "delete.svg",
}


def icon_path(name: str) -> str:
    path = ICONS.get(name)
    return str(path) if path and path.exists() else ""
