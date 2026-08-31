from __future__ import annotations

import hashlib
import struct
import time
import zlib
from typing import Any

from endstone import Player

from ..domain.model import PlayerProfile
from .identity import player_unique_id

_MAX_SKIN_SIDE = 256
_FACE_SIZE = 128


def capture_player_profile(
    player: Player,
    *,
    skin: Any | None = None,
    online: bool = True,
    joined: bool = False,
    quit: bool = False,
    observed_at: int | None = None,
) -> PlayerProfile:
    timestamp = int(time.time()) if observed_at is None else int(observed_at)
    xuid = _text(_read(player, "xuid"))
    chosen_skin = skin if skin is not None else _read(player, "skin")
    skin_id, skin_hash, width, height, rgba, cape_id = _capture_skin(chosen_skin)
    return PlayerProfile(
        unique_id=player_unique_id(player),
        last_name=str(player.name),
        xuid=xuid,
        locale=_text(_read(player, "locale")),
        device_os=_text(_read(player, "device_os")),
        game_version=_text(_read(player, "game_version")),
        game_mode=_enum_text(_read(player, "game_mode")),
        ping_ms=_integer(_read(player, "ping"), minimum=0),
        total_exp=_integer(_read(player, "total_exp"), minimum=0),
        exp_level=_integer(_read(player, "exp_level"), minimum=0),
        skin_id=skin_id,
        skin_hash=skin_hash,
        skin_width=width,
        skin_height=height,
        skin_rgba=rgba,
        cape_id=cape_id,
        first_seen_at=timestamp,
        last_seen_at=timestamp,
        last_joined_at=timestamp if joined else None,
        last_quit_at=timestamp if quit else None,
        skin_updated_at=timestamp if skin_hash else None,
        online=bool(online),
    )


def render_player_face_png(profile: PlayerProfile, size: int = _FACE_SIZE) -> bytes | None:
    if (profile.skin_id or "").lower().startswith("persona-"):
        return None

    width = profile.skin_width
    height = profile.skin_height
    rgba = profile.skin_rgba
    if (
        not rgba
        or width is None
        or height is None
        or width < 64
        or width % 64
        or height < width // 2
        or len(rgba) != width * height * 4
        or not 16 <= int(size) <= 256
    ):
        return None

    scale = width // 64
    source_size = 8 * scale
    if height < 16 * scale or width < 48 * scale:
        return None

    pixels = bytearray(source_size * source_size * 4)
    for y in range(source_size):
        for x in range(source_size):
            base = _pixel(rgba, width, 8 * scale + x, 8 * scale + y)
            overlay = _pixel(rgba, width, 40 * scale + x, 8 * scale + y)
            composed = _alpha_over(base, overlay)
            offset = (y * source_size + x) * 4
            pixels[offset : offset + 4] = composed

    output_size = int(size)
    resized = bytearray(output_size * output_size * 4)
    for y in range(output_size):
        source_y = y * source_size // output_size
        for x in range(output_size):
            source_x = x * source_size // output_size
            source = (source_y * source_size + source_x) * 4
            target = (y * output_size + x) * 4
            resized[target : target + 4] = pixels[source : source + 4]
    return _encode_rgba_png(output_size, output_size, bytes(resized))


def _capture_skin(
    skin: Any,
) -> tuple[str | None, str | None, int | None, int | None, bytes | None, str | None]:
    if skin is None:
        return None, None, None, None, None, None
    skin_id = _text(_read(skin, "id"))
    cape_id = _text(_read(skin, "cape_id"))
    image = _read(skin, "image")
    shape = getattr(image, "shape", ())
    try:
        height, width, channels = (int(value) for value in shape)
    except (TypeError, ValueError):
        return skin_id, None, None, None, None, cape_id
    if channels != 4 or not (1 <= width <= _MAX_SKIN_SIDE and 1 <= height <= _MAX_SKIN_SIDE):
        return skin_id, None, None, None, None, cape_id
    try:
        rgba = bytes(image.tobytes(order="C"))
    except (AttributeError, BufferError, TypeError, ValueError):
        return skin_id, None, None, None, None, cape_id
    if len(rgba) != width * height * 4:
        return skin_id, None, None, None, None, cape_id
    return skin_id, hashlib.sha256(rgba).hexdigest(), width, height, rgba, cape_id


def _read(value: Any, name: str) -> Any:
    if value is None:
        return None
    try:
        return getattr(value, name)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:128] if text else None


def _enum_text(value: Any) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if name:
        return str(name).lower()
    text = str(value).strip()
    return text.rsplit(".", 1)[-1].lower()[:64] if text else None


def _integer(value: Any, *, minimum: int) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number >= minimum else None


def _pixel(rgba: bytes, width: int, x: int, y: int) -> bytes:
    offset = (y * width + x) * 4
    return rgba[offset : offset + 4]


def _alpha_over(base: bytes, overlay: bytes) -> bytes:
    base_alpha = base[3]
    overlay_alpha = overlay[3]
    out_alpha = overlay_alpha + (base_alpha * (255 - overlay_alpha) + 127) // 255
    if out_alpha == 0:
        return bytes(4)
    channels = []
    for index in range(3):
        numerator = (
            overlay[index] * overlay_alpha * 255
            + base[index] * base_alpha * (255 - overlay_alpha)
        )
        channels.append((numerator + out_alpha * 127) // (out_alpha * 255))
    return bytes((*channels, out_alpha))


def _encode_rgba_png(width: int, height: int, rgba: bytes) -> bytes:
    rows = b"".join(
        b"\x00" + rgba[row * width * 4 : (row + 1) * width * 4] for row in range(height)
    )
    signature = b"\x89PNG\r\n\x1a\n"
    header = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    data = _png_chunk(b"IDAT", zlib.compress(rows, level=9))
    return signature + header + data + _png_chunk(b"IEND", b"")


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(
        ">I", zlib.crc32(kind + payload) & 0xFFFFFFFF
    )
