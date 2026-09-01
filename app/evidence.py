import os
import uuid
import base64
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS


def extract_exif(image_path: str) -> dict:
    """Extract GPS geotag and capture timestamp from image EXIF. Returns dict."""
    result = {"geotag_lat": None, "geotag_lon": None, "taken_at": None}
    try:
        img = Image.open(image_path)
        exif = img.getexif()
        if not exif:
            return result

        gps_ifd = exif.get_ifd(0x8825)
        gps_data = {}
        for tag_id, value in gps_ifd.items():
            tag = GPSTAGS.get(tag_id, tag_id)
            gps_data[tag] = value

        # DateTimeOriginal
        dt = exif.get(0x9003)  # DateTimeOriginal
        if dt:
            result["taken_at"] = dt

        if gps_data.get("GPSLatitude") and gps_data.get("GPSLongitude"):
            lat = _dms_to_dd(gps_data["GPSLatitude"], gps_data.get("GPSLatitudeRef"))
            lon = _dms_to_dd(gps_data["GPSLongitude"], gps_data.get("GPSLongitudeRef"))
            result["geotag_lat"] = lat
            result["geotag_lon"] = lon

    except Exception:
        pass
    return result


def _dms_to_dd(dms, ref=None):
    try:
        d, m, s = [float(x) for x in dms]
        dd = d + m / 60.0 + s / 3600.0
        if ref in ("S", "W"):
            dd = -dd
        return round(dd, 6)
    except Exception:
        return None


def save_photo(upload_file, upload_dir: str = "uploads") -> str:
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(upload_file.filename or "")[1] or ".jpg"
    if ext.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    fname = f"{uuid.uuid4().hex}{ext.lower()}"
    path = os.path.join(upload_dir, fname)
    with open(path, "wb") as f:
        f.write(upload_file.file.read())
    return path


def save_photo_base64(data_url: str, upload_dir: str = "uploads") -> str:
    """Save a base64 data URL (from in-browser camera capture) to a JPEG file."""
    os.makedirs(upload_dir, exist_ok=True)
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    raw = base64.b64decode(data_url)
    fname = f"{uuid.uuid4().hex}.jpg"
    with open(os.path.join(upload_dir, fname), "wb") as f:
        f.write(raw)
    return fname
