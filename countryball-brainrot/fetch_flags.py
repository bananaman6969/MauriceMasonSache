"""Refresh bundled flag assets from FlagCDN; no network needed at runtime."""
import io
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent / 'assets'


def fetch(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)


def main():
    countries = json.loads(fetch('https://flagcdn.com/en/codes.json'))
    countries = {code.upper(): name for code, name in countries.items() if len(code) == 2 and code not in ('eu', 'un')}
    countries = dict(sorted(countries.items(), key=lambda item: item[1]))
    (ROOT / 'flags').mkdir(parents=True, exist_ok=True)

    def download(code):
        data = fetch(f'https://flagcdn.com/w320/{code.lower()}.png')
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        (ROOT / 'flags' / f'{code}.png').write_bytes(data)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(download, countries))
    (ROOT / 'countries.json').write_text(json.dumps(countries, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Bundled {len(countries)} flags')


if __name__ == '__main__':
    main()
