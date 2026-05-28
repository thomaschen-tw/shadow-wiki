import hashlib
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.config import get_settings
from scripts.db import get_known_file_hashes, push_event, update_file_hash

logger = logging.getLogger(__name__)


def _file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def scan_once() -> int:
    s = get_settings()
    scan_paths = [p.strip() for p in s.local_scan_paths.split(",")]
    extensions = {e.strip() for e in s.local_scan_extensions.split(",")}
    known = get_known_file_hashes()
    count = 0

    for scan_path in scan_paths:
        root = Path(scan_path)
        if not root.exists():
            logger.warning("Scan path does not exist: %s", scan_path)
            continue
        for file_path in root.rglob("*"):
            if file_path.suffix not in extensions or not file_path.is_file():
                continue
            str_path = str(file_path)
            try:
                current_hash = _file_hash(file_path)
            except OSError:
                continue
            if known.get(str_path) == current_hash:
                continue
            raw_json = json.dumps({
                "path": str_path,
                "content": file_path.read_text(errors="replace")[:5000],
            })
            push_event("local", "file_change", raw_json)
            update_file_hash(str_path, current_hash)
            count += 1

    if count:
        logger.info("Queued %d changed local files", count)
    return count


def run_local_scanner(poll_interval: int = 120) -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("Local scanner started (poll every %ds)", poll_interval)
    while True:
        try:
            scan_once()
        except Exception as exc:
            logger.error("Scan failed: %s", exc)
        time.sleep(poll_interval)


if __name__ == "__main__":
    from scripts.db import init_db
    init_db()
    run_local_scanner()
