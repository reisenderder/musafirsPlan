from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
import shutil


SAFE_NAME_RE = re.compile(r"[^\w.()\- ]+", re.UNICODE)


def safe_file_name(name: str | None, fallback: str = "material.bin") -> str:
    candidate = Path(name or fallback).name
    candidate = SAFE_NAME_RE.sub("_", candidate).strip(" .")
    return candidate[:180] or fallback


def digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store_download(content: bytes, files_dir: Path, item_id: int, name: str | None) -> tuple[Path, str]:
    target_dir = files_dir / f"{item_id:08d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_file_name(name)
    target.write_bytes(content)
    return target, sha256(content).hexdigest()


def store_manual(source: Path, files_dir: Path, item_id: int) -> tuple[Path, str]:
    target_dir = files_dir / f"{item_id:08d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_file_name(source.name)
    shutil.copy2(source, target)
    return target, digest_file(target)
