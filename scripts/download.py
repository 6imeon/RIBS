"""Cached downloader. Hard rule #1: if a file exists on disk, use it. Never re-fetch."""
import sys
from pathlib import Path

import requests

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


def fetch(url: str, filename: str) -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / filename
    if dest.exists() and dest.stat().st_size > 0:
        print(f"CACHED  {filename}  ({dest.stat().st_size:,} bytes)")
        return dest

    print(f"FETCH   {url}")
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = 0
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
                total += len(chunk)
    tmp.rename(dest)  # atomic: a partial download never looks like a cache hit
    print(f"SAVED   {filename}  ({total:,} bytes)")
    return dest


if __name__ == "__main__":
    fetch(sys.argv[1], sys.argv[2])
