from pathlib import Path


IMAGE_DIR = Path(__file__).resolve().parent / "image"

BRAND_LOGO = IMAGE_DIR / "swasthik_logo.png"
BRAND_WORDMARK = IMAGE_DIR / "swasthik_wordmark.png"

PRODUCT_IMAGES = {
    "Whipped Coffee": IMAGE_DIR / "whipped_coffee.png",
    "Filter Coffee": IMAGE_DIR / "filter_coffee.png",
    "Cold Coffee": IMAGE_DIR / "cold_coffee.png",
    "Butterscotch Coffee": IMAGE_DIR / "butterscotch_coffee.png",
    "Authentic Espresso": IMAGE_DIR / "authentic_espresso.png",
    "Cappuccino Coffee": IMAGE_DIR / "cappuccino_coffee.png",
    "Iced Coffee": IMAGE_DIR / "iced_coffee.png",
    "Coffee Coffee": IMAGE_DIR / "coffee_coffee.png",
    "Latte Coffee": IMAGE_DIR / "coffee_coffee.png",
    "Tea": IMAGE_DIR / "tea.png",
    "Samosa": IMAGE_DIR / "samosa.png",
    "Veg Puff": IMAGE_DIR / "veg_puff.png",
    "Sandwich": IMAGE_DIR / "sandwich.png",
}


def product_image_path(item_name: str, fallback: str | None = None) -> str:
    if fallback:
        fallback_path = Path(fallback)
        if fallback_path.exists():
            return str(fallback_path)
    path = PRODUCT_IMAGES.get(item_name)
    if path and path.exists():
        return str(path)
    return ""


def brand_logo_path() -> str:
    return str(BRAND_LOGO) if BRAND_LOGO.exists() else ""


def brand_wordmark_path() -> str:
    return str(BRAND_WORDMARK) if BRAND_WORDMARK.exists() else ""
