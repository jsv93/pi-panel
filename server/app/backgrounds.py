"""Small, immutable backgrounds stored beside the database and cached by panels."""
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from . import db

MAX_UPLOAD = 10 * 1024 * 1024
MAX_ASSET = 2 * 1024 * 1024
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
COLOUR = re.compile(r"#[0-9a-fA-F]{6}\Z")


def asset_path(digest):
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise ValueError("Invalid background image reference")
    return Path(os.environ.get("PANEL_BACKGROUNDS", str(Path(db.DB_PATH).parent / "backgrounds"))) / (digest + ".webp")


def validate(value):
    if not isinstance(value, dict) or set(value) - {"mode", "colour", "image"}:
        raise ValueError("Background must contain mode, colour and an optional image")
    if value.get("mode") not in ("solid", "image", "room", "pattern"):
        raise ValueError("Choose solid, image, room or pattern")
    if not isinstance(value.get("colour", "#2b2018"), str) or not COLOUR.fullmatch(value.get("colour", "#2b2018")):
        raise ValueError("Background colour must be a six-digit hex colour")
    digest = value.get("image", "")
    if not isinstance(digest, str):
        raise ValueError("Invalid background image reference")
    if digest:
        asset_path(digest)
    if value["mode"] == "image" and (not digest or not asset_path(digest).is_file()):
        raise ValueError("Upload a background image before saving")


def store_image(data):
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError("Choose an image smaller than 10 MB")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("Choose a JPEG, PNG or WebP image")
            if source.width * source.height > 16_000_000:
                raise ValueError("Choose an image with at most 16 megapixels")
            if getattr(source, "is_animated", False):
                raise ValueError("Choose a still image")
            source.load()
            picture = ImageOps.exif_transpose(source)
            profile = picture.info.get("icc_profile")
            if profile:
                picture = ImageCms.profileToProfile(picture,
                    ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                    ImageCms.createProfile("sRGB"),
                    outputMode="RGBA" if picture.mode == "RGBA" else "RGB")
            # Flatten transparency and drop metadata rather than serving the upload.
            if picture.mode in ("RGBA", "LA") or "transparency" in picture.info:
                rgba = picture.convert("RGBA")
                picture = Image.new("RGB", rgba.size, "#2b2018")
                picture.paste(rgba, mask=rgba.getchannel("A"))
            else:
                picture = picture.convert("RGB")
            picture.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            picture.save(output, "WEBP", quality=82, method=4)
            encoded = output.getvalue()
    except (UnidentifiedImageError, OSError, ImageCms.PyCMSError, Image.DecompressionBombError) as error:
        raise ValueError("This image could not be read") from error
    if len(encoded) > MAX_ASSET:
        raise ValueError("This image is too complex; choose a smaller image")
    digest = hashlib.sha256(encoded).hexdigest()
    target = asset_path(digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Content-addressed names make repeated uploads idempotent.
    if not target.exists():
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".tmp", delete=False) as pending:
            pending.write(encoded)
            temporary = Path(pending.name)
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return {"image": digest, "width": picture.width, "height": picture.height, "bytes": len(encoded)}
