# image_sync

A Python utility to **download, process, archive, and upload images** from configurable sources.  
Designed for weather/satellite/monitoring feeds, but easily adaptable for other use cases.

## ✨ Features
- Fetch images from a list of URLs
- Image processing with [Pillow](https://pillow.readthedocs.io/):
  - Resize with aspect ratio preservation
  - Auto contrast & enhancements (sharpness, contrast, brightness, color)
  - Optional unsharp mask
- Save in WebP format (optimized, small size)
- Archive with timestamped copies
- FTP upload with automatic directory creation
- Logging (console + rotating log files)
- Hash tracking to detect changes (avoids unnecessary uploads)
- Configurable via JSON

## 📂 Project Structure
```

image_sync/
├── image_sync.py        # Main script
├── config.json          # Configuration (URLs, FTP, enhancements)
├── output/              # Latest processed images
├── archive/             # Timestamped archived images
├── temp/                # Temporary files
└── logs/                # Log files

````

## ⚙️ Configuration
All settings are stored in `config.json`.

Example:
```json
{
  "image_urls": [
    "https://path/to/image.jpg"
  ],
  "resize_to": [1920, 1920],
  "unsharp_mask": {
    "radius": 30,
    "percent": 40,
    "threshold": 5
  },
  "enhancements": {
    "default": {
      "apply_autocontrast": true,
      "sharpness": 1.1,
      "contrast": 1.0,
      "brightness": 1.0,
      "color": 1.05
    }
  },
  "ftp": {
    "host": "ftp.example.com",
    "username": "user",
    "password": "password",
    "upload_path": "/upload/path/"
  },
  "log_file": "/path/to/logs/image_sync_{{timestamp}}.log",
  "archive_retention_days": 7
}
````

## 🚀 Usage

1. Clone this repo:

   ```bash
   git clone https://github.com/YOUR_USERNAME/image_sync.git
   cd image_sync
   ```
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```
3. Edit `config.json` with your URLs and FTP credentials.
4. Run:

   ```bash
   python image_sync.py
   ```

## 📦 Requirements

* Python 3.8+
* [Pillow](https://pypi.org/project/Pillow/)
* [Requests](https://pypi.org/project/requests/)

Install all with:

```bash
pip install pillow requests
```

--

## 🔹 Suggested additional files

```
pillow
requests
```


