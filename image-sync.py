#!/usr/bin/env python3
# image_sync.py
# Downloads, processes, uploads and archives graphics with a 14 day auto-delete

import os
import sys
import json
import hashlib
import logging
import ftplib
import time
import threading
import schedule
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import requests
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
import shutil

# Global configuration and state
CONFIG_FILE = "config.json"
DOWNLOAD_DIR = "downloads"
PROCESSED_DIR = "processed"
ARCHIVE_DIR = "archive"
LOG_FILE = "image_processor.log"

# Initialize directories
for d in [DOWNLOAD_DIR, PROCESSED_DIR, ARCHIVE_DIR]:
    os.makedirs(d, exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class ImageProcessor:
    def __init__(self):
        self.config = self.load_config()
        self.ftp_lock = threading.Lock()
        self.processed_hashes = {}
        self.load_processed_hashes()
        # optional runtime counter for cycle-based forcing (not used by default)
        self.run_counter = 0

    def load_config(self):
        """Load configuration from config.json"""
        if not os.path.exists(CONFIG_FILE):
            logger.error(f"Configuration file {CONFIG_FILE} not found. Please create it.")
            sys.exit(1)
        
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    def load_processed_hashes(self):
        """Load previously processed image hashes from file (backwards-compatible)"""
        hash_file = os.path.join(ARCHIVE_DIR, "processed_hashes.json")
        if os.path.exists(hash_file):
            try:
                with open(hash_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # If older format (url -> hash string), convert to new dict format
                now_iso = datetime.now().isoformat()
                normalized = {}
                for k, v in data.items():
                    if isinstance(v, str):
                        normalized[k] = {"hash": v, "timestamp": now_iso}
                    elif isinstance(v, dict) and "hash" in v:
                        normalized[k] = v
                    else:
                        # Unexpected format: skip
                        logger.warning(f"Unexpected processed_hashes entry for {k}: {v}")
                self.processed_hashes = normalized
            except Exception as e:
                logger.warning(f"Could not load processed hashes: {e}")
                self.processed_hashes = {}

    def save_processed_hashes(self):
        """Save processed image hashes to file"""
        hash_file = os.path.join(ARCHIVE_DIR, "processed_hashes.json")
        try:
            with open(hash_file, 'w', encoding='utf-8') as f:
                json.dump(self.processed_hashes, f, indent=4)
        except Exception as e:
            logger.error(f"Could not save processed hashes: {e}")

    def calculate_file_hash(self, filepath):
        """Calculate SHA256 hash of a file"""
        sha256_hash = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.error(f"Error calculating hash for {filepath}: {e}")
            return None

    def _normalize_image_config(self, image_config):
        """
        Ensure image_config is a dict with keys:
          - url (string)
          - filename (optional)
          - settings (optional dict)
        Accepts either a string (URL) or a dict.
        """
        if isinstance(image_config, str):
            url = image_config.strip()
            filename = os.path.basename(urlparse(url).path) or None
            return {"url": url, "filename": filename, "settings": {}}
        elif isinstance(image_config, dict):
            url = image_config.get("url")
            if not url and isinstance(image_config.get("source"), str):
                # accept alternate key 'source' if present
                url = image_config.get("source")
            if not url:
                raise ValueError("image_config missing 'url' key")
            filename = image_config.get("filename") or os.path.basename(urlparse(url).path)
            settings = image_config.get("settings", {})
            return {"url": url.strip(), "filename": filename, "settings": settings}
        else:
            raise TypeError("image_config must be a dict or a string URL")

    def download_image(self, image_config):
        """Download an image with retry logic"""
        # Accept either dict or string input
        try:
            cfg = self._normalize_image_config(image_config)
        except Exception as e:
            logger.error(f"Invalid image_config passed to download_image: {image_config} ({e})")
            return None

        url = cfg["url"]
        filename = cfg.get("filename") or f"image_{hash(url)}.jpg"

        # Ensure we have the right extension for processing
        base_name = os.path.splitext(filename)[0]
        local_filename = f"{base_name}.original"
        local_path = os.path.join(DOWNLOAD_DIR, local_filename)
        
        headers = {'User-Agent': self.config.get("download", {}).get("user_agent", "ImageProcessor/1.0")}
        max_retries = int(self.config.get("download", {}).get("max_retries", 2))
        timeout = float(self.config.get("download", {}).get("timeout", 30))
        
        for attempt in range(max_retries + 1):
            try:
                logger.debug(f"Downloading {url} (attempt {attempt + 1})")
                response = requests.get(url, headers=headers, timeout=timeout, stream=True)
                response.raise_for_status()
                
                # Calculate hash of downloaded content
                content_hash = hashlib.sha256()
                temp_file = local_path + ".tmp"
                
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            content_hash.update(chunk)
                
                current_hash = content_hash.hexdigest()
                
                # Check if already downloaded and unchanged (time-based force-redownload)
                info = self.processed_hashes.get(url)
                if info and info.get("hash") == current_hash:
                    # parse timestamp safely
                    try:
                        last_download = datetime.fromisoformat(info.get("timestamp"))
                    except Exception:
                        last_download = datetime.now() - timedelta(days=365)
                    max_age_hours = int(self.config.get("download", {}).get("force_redownload_hours", 6))
                    if datetime.now() - last_download < timedelta(hours=max_age_hours):
                        logger.info(f"Skipping {url} - no changes detected and downloaded recently")
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                        return None  # No need to process
                
                # Move temp file to final location
                if os.path.exists(temp_file):
                    if os.path.exists(local_path):
                        os.remove(local_path)
                    os.rename(temp_file, local_path)
                
                # Update hash record
                self.processed_hashes[url] = {
                    "hash": current_hash,
                    "timestamp": datetime.now().isoformat()
                }
                self.save_processed_hashes()
                
                logger.info(f"Downloaded {url} to {local_path}")
                return local_path
                
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}. Retrying...")
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(f"Failed to download {url} after {max_retries + 1} attempts: {e}")
                    # Record failure for diagnostics
                    failure_log = os.path.join(ARCHIVE_DIR, "download_failures.log")
                    try:
                        with open(failure_log, "a", encoding="utf-8") as f:
                            f.write(f"{datetime.now().isoformat()} - Failed to download {url} - {e}\n")
                    except Exception as write_err:
                        logger.warning(f"Could not write failure log: {write_err}")
                return None
       
        return None

    def process_image(self, image_path, image_config):
        """Process an image according to its specific settings"""
        try:
            # Normalize image_config (so we can accept strings upstream)
            try:
                cfg = self._normalize_image_config(image_config)
            except Exception:
                # If normalization fails, create a minimal cfg using the file path
                cfg = {"url": None, "filename": os.path.basename(image_path), "settings": {}}

            # Get settings with fallback to defaults
            settings = cfg.get("settings", {}) or {}
            
            # Merge with defaults
            default_settings = self.config.get("processing", {})
            merged_settings = self.merge_settings(default_settings, settings)
            
            # Open image
            img = Image.open(image_path)
            
            # Convert to RGB if necessary (for formats like GIF or PNG with transparency)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    try:
                        img = img.convert('RGBA')
                    except Exception:
                        img = img.convert('RGB')
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[-1])  # Use alpha channel as mask
                else:
                    background.paste(img)
                img = background
            
            original_size = img.size
            logger.info(f"Processing {os.path.basename(image_path)} - Original size: {original_size}")
            
            # Apply crop if specified
            crop_box = merged_settings.get("crop_box")
            if crop_box and isinstance(crop_box, list) and len(crop_box) == 4:
                try:
                    img = img.crop(crop_box)
                    logger.info(f"Cropped to: {img.size}")
                except Exception as e:
                    logger.warning(f"Could not apply crop {crop_box}: {e}")
            
            # Resize logic: Scale up to 4000px (while keeping the aspect ratio)
            current_width, current_height = img.size
            max_dim = int(merged_settings.get("max_processing_dimension", 4000))
            # only scale up the largest dimension to avoid blowing out the other side
            scale_factor = max_dim / max(current_width, current_height)
            if scale_factor > 1.0:
                new_width = int(current_width * scale_factor)
                new_height = int(current_height * scale_factor)
                try:
                    img = img.resize((new_width, new_height), Image.LANCZOS)
                    logger.info(f"Scaled up to {new_width}x{new_height}")
                except Exception as e:
                    logger.warning(f"Could not scale up image: {e}")
            
            # Apply auto contrast if requested
            enhancements = merged_settings.get("enhancements", {}) or {}
            if enhancements.get("apply_autocontrast", False):
                try:
                    img = ImageOps.autocontrast(img)
                    logger.info("Applied auto contrast")
                except Exception as e:
                    logger.warning(f"Could not apply auto contrast: {e}")
            
            # Apply other enhancements
            enhancers = {
                "sharpness": ImageEnhance.Sharpness,
                "contrast": ImageEnhance.Contrast,
                "brightness": ImageEnhance.Brightness,
                "color": ImageEnhance.Color
            }
            
            for enhancer_name, enhancer_class in enhancers.items():
                factor = enhancements.get(enhancer_name, 1.0)
                if factor != 1.0:
                    try:
                        enhancer = enhancer_class(img)
                        img = enhancer.enhance(factor)
                        logger.info(f"Applied {enhancer_name} with factor {factor}")
                    except Exception as e:
                        logger.warning(f"Could not apply {enhancer_name}: {e}")
            
            # Apply unsharp mask if specified (keeps your original approach but guarded)
            unsharp_mask = merged_settings.get("unsharp_mask")
            if unsharp_mask:
                try:
                    radius = unsharp_mask.get("radius", 2)
                    percent = unsharp_mask.get("percent", 150)
                    threshold = unsharp_mask.get("threshold", 3)
                    
                    blurred = img.filter(ImageFilter.GaussianBlur(radius))
                    mask = Image.blend(img, blurred, 1.0 - percent / 100.0)
                    img = Image.blend(img, mask, 1.0)
                    logger.info(f"Applied unsharp mask with radius={radius}, percent={percent}, threshold={threshold}")
                except Exception as e:
                    logger.warning(f"Could not apply unsharp mask: {e}")
            
            # Resize down to final size (default 1920px max dimension)
            resize_to = merged_settings.get("resize_to", [1920, 1920])
            if isinstance(resize_to, list) and len(resize_to) == 2:
                target_width, target_height = int(resize_to[0]), int(resize_to[1])
                current_width, current_height = img.size
                scale_factor = min(target_width / current_width, target_height / current_height)
                if scale_factor < 1.0:
                    new_width = int(current_width * scale_factor)
                    new_height = int(current_height * scale_factor)
                    try:
                        img = img.resize((new_width, new_height), Image.LANCZOS)
                        logger.info(f"Resized down to {new_width}x{new_height}")
                    except Exception as e:
                        logger.warning(f"Could not resize down image: {e}")
            
            # Prepare output filename
            out_filename = cfg.get("filename") or os.path.splitext(os.path.basename(image_path))[0] + ".webp"
            if not out_filename.endswith(".webp"):
                out_filename = os.path.splitext(out_filename)[0] + ".webp"
            
            output_path = os.path.join(PROCESSED_DIR, out_filename)
            
            # Save as WebP
            quality = int(merged_settings.get("quality", 60))
            try:
                img.save(output_path, "WEBP", quality=quality, method=6)
                logger.info(f"Saved processed image to {output_path}")
            except Exception as e:
                logger.error(f"Failed to save processed image to {output_path}: {e}")
                return None
            
            return output_path

        except Exception as e:
            logger.error(f"Error processing {image_path}: {e}")
            return None

    def merge_settings(self, default, specific):
        """Merge default settings with image-specific settings"""
        if not isinstance(specific, dict):
            return default.copy()
        
        result = {}
        
        # Handle nested dictionaries
        for key, value in default.items():
            if key in specific:
                if isinstance(value, dict) and isinstance(specific[key], dict):
                    result[key] = self.merge_settings(value, specific[key])
                else:
                    result[key] = specific[key]
            else:
                result[key] = value
        
        # Add any keys in specific that aren't in default
        for key, value in specific.items():
            if key not in result:
                result[key] = value
        
        return result

    def upload_via_ftp(self, local_path, remote_filename):
        """Upload a file via FTP with retry logic"""
        ftp_config = self.config.get("ftp", {})
        max_retries = int(ftp_config.get("max_retries", 2))
        timeout = float(ftp_config.get("timeout", 30))
        
        for attempt in range(max_retries + 1):
            ftp = None
            try:
                ftp = ftplib.FTP()
                ftp.connect(ftp_config["host"], ftp_config.get("port", 21), timeout=timeout)
                ftp.login(ftp_config["username"], ftp_config["password"])
                
                # Change to remote directory
                remote_dir = ftp_config.get("remote_directory", "/")
                try:
                    ftp.cwd(remote_dir)
                except Exception:
                    # Try to create directory if it doesn't exist
                    dirs = remote_dir.strip('/').split('/')
                    current_path = ''
                    for dir_name in dirs:
                        if dir_name:
                            current_path += '/' + dir_name
                            try:
                                ftp.cwd(current_path)
                            except Exception:
                                try:
                                    ftp.mkd(current_path)
                                    ftp.cwd(current_path)
                                except Exception:
                                    pass
                
                # Upload file
                with open(local_path, 'rb') as f:
                    ftp.storbinary(f'STOR {remote_filename}', f)
                
                if ftp:
                    ftp.quit()
                
                logger.info(f"Successfully uploaded {local_path} to {remote_filename}")
                return True
                
            except Exception as e:
                if ftp:
                    try:
                        ftp.quit()
                    except Exception:
                        pass
                
                if attempt < max_retries:
                    logger.warning(f"FTP upload attempt {attempt + 1} failed for {local_path}: {e}. Retrying...")
                    time.sleep(2 ** attempt)
                else:
                    logger.error(f"Failed to upload {local_path} after {max_retries + 1} attempts: {e}")
                    return False
        
        return False

    def cleanup_old_files(self):
        """Delete files older than retention period (only for downloads and processed dirs)"""
        # Only clean up download and processed directories, NOT archive
        retention_days = int(self.config.get("retention", {}).get("days_to_keep", 14))
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        directories = [DOWNLOAD_DIR, PROCESSED_DIR]  # Exclude ARCHIVE_DIR
        
        for directory in directories:
            if os.path.exists(directory):
                for filename in os.listdir(directory):
                    filepath = os.path.join(directory, filename)
                    try:
                        mod_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                        if mod_time < cutoff_date:
                            os.remove(filepath)
                            logger.info(f"Deleted old file: {filepath}")
                    except Exception as e:
                        logger.warning(f"Could not delete {filepath}: {e}")

    def cleanup_old_archive_files(self):
        """Delete archive files older than 14 days"""
        retention_days = int(self.config.get("retention", {}).get("archive_days", 14))
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        if os.path.exists(ARCHIVE_DIR):
            for filename in os.listdir(ARCHIVE_DIR):
                filepath = os.path.join(ARCHIVE_DIR, filename)
                try:
                    mod_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                    if mod_time < cutoff_date:
                        os.remove(filepath)
                        logger.info(f"Deleted old archive file: {filepath}")
                except Exception as e:
                    logger.warning(f"Could not delete {filepath}: {e}")

    def get_timestamped_filename(self, original_filename):
        """Add timestamp to filename to prevent overwrites"""
        # Get current timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Split filename and extension
        name, ext = os.path.splitext(original_filename)
        
        # Add timestamp before the extension
        return f"{name}_{timestamp}{ext}"

    def process_single_image(self, image_config):
        """Process a single image from download to upload"""
        try:
            # Normalize image_config
            try:
                cfg = self._normalize_image_config(image_config)
            except Exception as e:
                logger.error(f"Invalid image_config in process_single_image: {image_config} ({e})")
                return False

            # Download image
            downloaded_path = self.download_image(cfg)
            if not downloaded_path:
                return False
            
            # Process image
            processed_path = self.process_image(downloaded_path, cfg)
            if not processed_path:
                return False
            
            # Get remote filename (based on cfg)
            remote_filename = cfg.get("filename") or os.path.basename(cfg.get("url") or processed_path)
            if not remote_filename.endswith(".webp"):
                remote_filename = os.path.splitext(remote_filename)[0] + ".webp"
            
            # Upload via FTP
            upload_success = self.upload_via_ftp(processed_path, remote_filename)
            
            # Cleanup if configured - ONLY move to archive after successful upload
            if upload_success and self.config.get("retention", {}).get("delete_after_upload", True):
                try:
                    if os.path.exists(downloaded_path):
                        os.remove(downloaded_path)
                    
                    if os.path.exists(processed_path):
                        # Add timestamp to prevent overwrites in archive
                        timestamped_filename = self.get_timestamped_filename(os.path.basename(processed_path))
                        archive_path = os.path.join(ARCHIVE_DIR, timestamped_filename)
                        
                        # Move processed image to archive with timestamp
                        shutil.move(processed_path, archive_path)
                        logger.info(f"Moved {processed_path} to archive with timestamp: {timestamped_filename}")
                except Exception as e:
                    logger.warning(f"Could not clean up files after upload: {e}")
            
            return upload_success
            
        except Exception as e:
            # Best-effort: log the URL if available
            try:
                url_for_log = image_config.get("url", "unknown") if isinstance(image_config, dict) else image_config
            except Exception:
                url_for_log = "unknown"
            logger.error(f"Error processing image {url_for_log}: {e}")
            return False

    def run(self):
        """Main execution method"""
        logger.info("Starting image processing workflow")
        
        # Cleanup old files if configured (only downloads and processed dirs)
        if self.config.get("retention", {}).get("cleanup_on_start", True):
            self.cleanup_old_files()
        
        # Cleanup archive files older than configured days
        self.cleanup_old_archive_files()
        
        images = self.config.get("images", []) or []
        # normalize images to a list
        if not isinstance(images, list):
            images = [images]
        
        if not images:
            logger.warning("No images configured for processing")
            return
        
        # Process images concurrently
        max_workers = int(self.config.get("ftp", {}).get("concurrent_uploads", 5))
        success_count = 0
        total_count = len(images)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_image = {
                executor.submit(self.process_single_image, image_config): image_config 
                for image_config in images
            }
            
            # Wait for completion
            for future in as_completed(future_to_image):
                image_config = future_to_image[future]
                try:
                    success = future.result()
                    if success:
                        success_count += 1
                except Exception as e:
                    # Best-effort to extract URL for logging
                    try:
                        url_for_log = image_config.get("url", "unknown") if isinstance(image_config, dict) else image_config
                    except Exception:
                        url_for_log = "unknown"
                    logger.error(f"Exception processing {url_for_log}: {e}")
        
        logger.info(f"Workflow completed: {success_count}/{total_count} images processed successfully")

def main():
    """Main function to run the processor and scheduler"""
    processor = ImageProcessor()
    
    # Set log level from config
    log_level = processor.config.get("logging", {}).get("level", "INFO").upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    # Run once immediately
    processor.run()
    
    # Schedule subsequent runs
    interval_minutes = int(processor.config.get("schedule", {}).get("interval_minutes", 10))
    schedule.every(interval_minutes).minutes.do(processor.run)
    
    # Schedule daily cleanup of archive files (every day at midnight)
    schedule.every().day.at("00:00").do(processor.cleanup_old_archive_files)
    
    logger.info(f"Scheduler started. Next run in {interval_minutes} minutes.")
    
    # Keep the script running
    while True:
        schedule.run_pending()
        time.sleep(300)  # Check every 5 minutes

if __name__ == "__main__":
    main()
