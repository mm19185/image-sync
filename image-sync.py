import os
import json
import hashlib
import requests
from ftplib import FTP
from pathlib import Path
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
from io import BytesIO
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import threading  # Import the threading module

# === CONFIGURATION ===
CONFIG_FILE = '/path/to/image_sync/config.json'

with open(CONFIG_FILE, 'r') as f:
    config = json.load(f)

IMAGE_URLS = config["image_urls"]
CROP_COORDS = config.get("crop", {})
FTP_HOST = config["ftp"]["host"]
FTP_USER = config["ftp"]["username"]
FTP_PASS = config["ftp"]["password"]
FTP_UPLOAD_PATH = config["ftp"]["upload_path"]
APPLY_AUTOCONTRAST = config.get("apply_autocontrast", True)
LOG_FILE = config["log_file"].replace("{{timestamp}}", datetime.now().strftime('%Y-%m-%d_%H-%M-%S'))
ARCHIVE_DIR = Path(config.get("archive_dir", "/path/to/image_sync/archive"))
HASHES_FILE = config.get("hashes_file", "/path/to/image_sync/image_hashes.json")

# === DIRECTORIES ===
OUTPUT_DIR = Path("/path/to/image_sync/output")
TEMP_DIR = Path("/path/to/image_sync/temp")
for d in [OUTPUT_DIR, TEMP_DIR, ARCHIVE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# === LOGGING ===
logger = logging.getLogger("ImageProcessor")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# === HASH STORAGE ===
if os.path.exists(HASHES_FILE):
    with open(HASHES_FILE, 'r') as f:
        saved_hashes = json.load(f)
else:
    saved_hashes = {}


def get_image_hash(content):
    return hashlib.sha256(content).hexdigest()


def download_image(url):
    try:
        logger.info(f"Checking {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        return None


def process_image(url, content):
    try:
        filename = os.path.basename(url).split('?')[0]
        name, _ = os.path.splitext(filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unsharp_cfg = config.get("unsharp_mask", {})
        radius = unsharp_cfg.get("radius", 30)
        percent = unsharp_cfg.get("percent", 40)
        threshold = unsharp_cfg.get("threshold", 5)

        img = Image.open(BytesIO(content)).convert("RGB")

        resize_to = config.get("resize_to")
        if resize_to:
                img = ImageOps.contain(img, tuple(resize_to), method=Image.LANCZOS)
        
        # enhancement settings
        sharpness_factor = config.get("sharpness_factor", 1.1)
        contrast_factor = config.get("contrast_factor", 1.0)
        brightness_factor = config.get("brightness_factor", 1.0)
        color_factor = config.get("color_factor", 1.05)
                   
        if APPLY_AUTOCONTRAST:
                img = ImageOps.autocontrast(img, cutoff=0.5, preserve_tone=True, mask=None, ignore=None)
                
        # Apply enhancements
        if sharpness_factor != 1.0:
                img = ImageEnhance.Sharpness(img).enhance(sharpness_factor)
        if contrast_factor != 1.0:
                img = ImageEnhance.Contrast(img).enhance(contrast_factor)
        if brightness_factor != 1.0:
                img = ImageEnhance.Brightness(img).enhance(brightness_factor)
        if color_factor != 1.0:
                img = ImageEnhance.Color(img).enhance(color_factor)

        if radius > 0:
                img = img.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold))        
                                                
        temp_path = TEMP_DIR / filename
        output_path = OUTPUT_DIR / f"{name}.webp"
        archive_path = ARCHIVE_DIR / f"{name}_{timestamp}.webp"

        img.save(output_path, "WEBP", quality=25)
        img.save(archive_path, "WEBP", quality=25)
        
        logger.info(f"Processed and saved {output_path.name}")
        return output_path
    except Exception as e:
        logger.error(f"Error processing {url}: {e}")
        return None

def upload_to_ftp(filepath):
    try:
        with FTP(FTP_HOST) as ftp:
            ftp.login(FTP_USER, FTP_PASS)
            for folder in FTP_UPLOAD_PATH.strip("/").split("/"):
                try:
                    ftp.cwd(folder)
                except Exception:
                    ftp.mkd(folder)
                    ftp.cwd(folder)
                with open(filepath, 'rb') as f:
                    ftp.storbinary(f"STOR {filepath.name}", f)
            logger.info(f"Uploaded {filepath.name} to FTP")
    except Exception as e:
        logger.error(f"FTP upload failed for {filepath.name}: {e}")

def main():
    threads = []  # Create a list to hold our threads

    for url in IMAGE_URLS:
        content = download_image(url)
        if not content:
            continue

        image_hash = get_image_hash(content)

        logger.info(f"Processing {url} regardless of hash")
        output_file = process_image(url, content)
        if output_file:
            upload_to_ftp(output_file)
            saved_hashes[url] = image_hash

    with open(HASHES_FILE, 'w') as f:
        json.dump(saved_hashes, f)
    logger.info("Script completed.")


if __name__ == "__main__":
    main()
