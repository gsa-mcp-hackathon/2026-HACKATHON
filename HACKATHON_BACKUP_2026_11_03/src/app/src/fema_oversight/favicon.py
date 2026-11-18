"""Favicon and app icons, all generated from one source image.

Source: ``static/dhs-seal.png`` next to this file (the DHS seal; square-ish,
transparent corners). On first request every icon is rendered in memory with
Pillow and cached for the life of the process:

    /favicon.ico                  16, 24, 32, 48, 64 px (multi-size ICO)
    /favicon-16x16.png            browser tab
    /favicon-32x32.png            browser tab (high-DPI)
    /favicon-48x48.png            Windows / search results
    /apple-touch-icon.png         180 px, white background (iOS fills
                                  transparency with black)
    /android-chrome-192x192.png   web app manifest
    /android-chrome-512x512.png   web app manifest / splash
    /site.webmanifest             manifest referencing the two above
    /title-seal-28.png            seal next to the page title (28 px)
    /title-seal-56.png            same, for high-DPI screens (2x)

If the source image is missing the routes return 404 and the app keeps
working; a single warning is logged.
"""

from __future__ import annotations

import io
import json
import logging
import threading
from pathlib import Path

from starlette.responses import Response

SOURCE = Path(__file__).with_name("static") / "dhs-seal.png"
APP_NAME = "FEMA Disaster Spending Check"
THEME_COLOR = "#005288"  # DHS seal blue
ICO_SIZES = (16, 24, 32, 48, 64)
PNG_ICONS = {
    "/favicon-16x16.png": (16, False),
    "/favicon-32x32.png": (32, False),
    "/favicon-48x48.png": (48, False),
    "/apple-touch-icon.png": (180, True),
    "/android-chrome-192x192.png": (192, False),
    "/android-chrome-512x512.png": (512, False),
    "/title-seal-28.png": (28, False),
    "/title-seal-56.png": (56, False),
}
HEADERS = {"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"}

# Paste inside <head> of every HTML page.
HEAD_LINKS = (
    '<link rel="icon" href="/favicon.ico" sizes="any">'
    '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">'
    '<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">'
    '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">'
    '<link rel="manifest" href="/site.webmanifest" crossorigin="use-credentials">'
    f'<meta name="theme-color" content="{THEME_COLOR}">'
)

log = logging.getLogger(__name__)
_lock = threading.Lock()
_cache: dict[str, tuple[bytes, str]] | None = None
_failed = False


def _square_source(img):
    """Trim transparent margins and pad to a centered transparent square."""
    from PIL import Image

    img = img.convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    if bbox:
        img = img.crop(bbox)
    side = max(img.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
    return square


def _resize(square, size: int, opaque: bool):
    from PIL import Image

    icon = square.resize((size, size), Image.Resampling.LANCZOS)
    if opaque:
        bg = Image.new("RGBA", (size, size), (255, 255, 255, 255))
        bg.alpha_composite(icon)
        icon = bg.convert("RGB")
    return icon


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def build_icons(source: Path = SOURCE) -> dict[str, tuple[bytes, str]]:
    """Render every icon from ``source``. Returns {path: (bytes, mime)}."""
    from PIL import Image

    with Image.open(source) as src:
        square = _square_source(src)
    icons: dict[str, tuple[bytes, str]] = {}
    for path, (size, opaque) in PNG_ICONS.items():
        icons[path] = (_png(_resize(square, size, opaque)), "image/png")
    # Downscale from a 256 px master so each ICO frame is sharp.
    ico_buf = io.BytesIO()
    _resize(square, 256, False).save(
        ico_buf, format="ICO", sizes=[(s, s) for s in ICO_SIZES]
    )
    icons["/favicon.ico"] = (ico_buf.getvalue(), "image/x-icon")
    manifest = {
        "name": APP_NAME,
        "short_name": "FEMA Check",
        "icons": [
            {"src": "/android-chrome-192x192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/android-chrome-512x512.png", "sizes": "512x512", "type": "image/png"},
        ],
        "theme_color": THEME_COLOR,
        "background_color": "#ffffff",
        "display": "browser",
        "start_url": "/",
    }
    icons["/site.webmanifest"] = (
        json.dumps(manifest, indent=2).encode("utf-8"),
        "application/manifest+json",
    )
    return icons


def _icons() -> dict[str, tuple[bytes, str]] | None:
    global _cache, _failed
    if _cache is not None or _failed:
        return _cache
    with _lock:
        if _cache is None and not _failed:
            try:
                _cache = build_icons()
            except Exception as exc:  # missing file, Pillow absent, bad image
                _failed = True
                log.warning("favicon unavailable (%s: %s)", type(exc).__name__, exc)
    return _cache


def register_favicon(server) -> None:
    """Register one GET route per icon path."""

    async def serve(request):
        icons = _icons()
        item = icons.get(request.url.path) if icons else None
        if item is None:
            return Response(status_code=404)
        data, mime = item
        return Response(data, media_type=mime, headers=HEADERS)

    for path in ["/favicon.ico", "/site.webmanifest", *PNG_ICONS]:
        server.custom_route(path, methods=["GET"])(serve)
