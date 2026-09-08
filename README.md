# Maurice Multi-Project Repository

Welcome to the central repository for automation, media processing, and AI tools.

## Projects

### 1. [Shorts Stealth Pipeline](shorts-stealth-pipeline/)
An automated, stealth-engineered YouTube Shorts scraping and anti-detection obfuscation pipeline with a real-time web dashboard and SSE progress monitoring.
- **Location:** `shorts-stealth-pipeline/`
- **Stack:** Python, FastAPI, yt-dlp, FFmpeg, SQLite, Tailwind CSS
- **Quickstart:**
  ```bash
  cd shorts-stealth-pipeline
  pip install -r requirements.txt
  python app.py
  ```
  Visit [http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## Adding New Projects

To add another project to this repository:
1. Create or paste a new folder in this root directory (e.g. `another-project/`).
2. Add the project files inside that directory.
3. Commit and push:
   ```bash
   git add another-project
   git commit -m "feat: add another-project"
   git push origin main
   ```
