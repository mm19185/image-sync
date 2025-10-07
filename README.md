# 📦 Release 2.0 — Major Refactor & New Features

This is a complete overhaul. The new version introduces a class-based architecture, vastly improved reliability, richer configuration options, smarter processing logic, and many new features designed for production-grade automation.

---

## ✨ Highlights

- 🚀 Major refactor from a single-file procedural script to a modular, class-based design.
- 📁 Configuration-driven workflow with per-image customization.
- ⚡ Multi-threaded processing and FTP upload for better performance.
- 🔁 Robust retry, timeout, and error-handling mechanisms.
- 📸 Advanced image processing with cropping, scaling, and enhancement controls.
- 🗃️ Smart archiving, retention policies, and automated cleanup.
- 🧠 Built-in scheduling support — no cron required.

---

## 🛠️ Improvements & Fixes

### 🧱 Architecture
- Migrated from a single monolithic script to an `ImageProcessor` class with cleanly separated methods.
- Moved all settings into a structured `config.json` file, enabling global and per-image overrides.
- Implemented thread pooling via `concurrent.futures` for concurrent downloads, processing, and uploads.
- Added built-in scheduling (`schedule` library) with automatic daily cleanup support.

### 🌐 Download & Caching
- Added robust retry logic with exponential backoff for downloads and uploads.
- Introduced hash tracking with timestamps to intelligently skip unchanged files.
- Per-image download configuration, including custom HTTP headers and URL-specific settings.
- Improved error handling for network timeouts and broken URLs.

### 🖼️ Image Processing
- Enhanced pre-processing pipeline with:
  - Optional cropping
  - Smart upscaling before enhancement
  - Final downscale to configurable resolution
- Added per-image quality, output naming, and enhancement controls.
- Auto-conversion of unsupported modes (e.g., `RGBA`, `P`) to `RGB`.
- Fine-grained control over sharpness, contrast, brightness, color, and auto-contrast.
- Robust unsharp masking with graceful fallback on errors.

### 📤 Uploads & FTP
- FTP uploads now retry on failure and respect configurable timeouts.
- Automatic recursive creation of remote directories.
- Parallel uploads for faster performance.
- Optional post-upload cleanup of processed files.

### 🗃️ Archiving & Cleanup
- Timestamped archives to prevent overwrites.
- Automated cleanup of:
  - Old processed/downloaded files
  - Archived images beyond a retention threshold
- Improved `processed_hashes.json` with structured metadata and backward compatibility.

### 📊 Logging & Monitoring
- Unified structured logging with configurable verbosity and dual output (console + file).
- Dedicated `download_failures.log` for easier troubleshooting.
- Graceful exception handling — one failed image no longer halts the process.

---

## ❌ Removed / Deprecated

| Old Behavior | New Replacement |
|--------------|------------------|
| Hardcoded constants | Fully configurable `config.json` |
| Global hash tracking (no timestamps) | Timestamped hash records |
| One-size-fits-all enhancement logic | Per-image + global overrides |
| No retry or timeout support | Robust retry system with backoff |
| Manual cron-only scheduling | Built-in `schedule` integration |
| Static archive directory | Timestamped, auto-cleaned archive system |

---

## 📦 Migration Notes

- Old hash files are automatically converted to the new structured format.
- Review and update your `config.json` — new fields are now available for download, processing, FTP, and retention.
- Script can now run continuously as a daemon, or manually via CLI or cron.

---

## ✅ Summary

Release **2.0** transforms the image sync script from a simple downloader into a **fully automated, production-ready image processing and upload pipeline**. It’s more reliable, more flexible, and easier to extend — ready for long-term use in automated workflows.

---
