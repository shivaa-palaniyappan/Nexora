"""
github.py — Clones a GitHub repo and walks its files.
Auto-detects the real code root even if code is in a subfolder.
"""

import subprocess
import os
import shutil
import logging
from typing import Iterator, List
from app.core.chunker import should_skip, prioritize_files

logger = logging.getLogger(__name__)

CLONE_BASE       = os.getenv("CLONE_DIR", "./data/repos")
MAX_FILE_SIZE_KB = int(os.getenv("MAX_FILE_SIZE_KB", "300"))
BATCH_SIZE       = int(os.getenv("BATCH_SIZE", "10"))

CODE_EXTS = {
    '.py', '.js', '.ts', '.tsx', '.jsx', '.java',
    '.go', '.rs', '.cpp', '.c', '.rb', '.php',
    '.cs', '.kt', '.swift', '.mjs', '.cjs',
}


def sanitize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("https://github.com/"):
        raise ValueError("Only GitHub URLs (https://github.com/...) are supported.")
    bad_chars = [";", "&", "|", "`", "$", "(", ")", "<", ">"]
    for ch in bad_chars:
        if ch in url:
            raise ValueError(f"Invalid character in URL: {ch}")
    return url


def clone_repo(repo_id: str, github_url: str) -> str:
    url  = sanitize_url(github_url)
    dest = os.path.join(CLONE_BASE, repo_id)

    if os.path.exists(dest):
        shutil.rmtree(dest)

    os.makedirs(CLONE_BASE, exist_ok=True)
    logger.info(f"Cloning {url} → {dest}")

    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--single-branch", url, dest],
        capture_output=True, text=True, timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Git clone failed: {result.stderr}")

    logger.info(f"Clone complete: {dest}")
    return dest


def _count_code_files(path: str) -> int:
    """Count direct code files in a directory (non-recursive)."""
    count = 0
    try:
        for f in os.listdir(path):
            if os.path.isfile(os.path.join(path, f)):
                ext = os.path.splitext(f)[1].lower()
                if ext in CODE_EXTS:
                    count += 1
    except Exception:
        pass
    return count


def _get_subfolders(path: str) -> List[str]:
    """Get meaningful subfolders (skips hidden, generated, binary folders)."""
    skip = {
        'node_modules', '.git', 'target', 'build',
        'dist', '.next', 'local_model', '__pycache__',
        'venv', '.venv', 'vendor', 'public',
    }
    try:
        return [
            os.path.join(path, d)
            for d in os.listdir(path)
            if os.path.isdir(os.path.join(path, d))
            and not d.startswith('.')
            and d not in skip
        ]
    except Exception:
        return []


def _find_code_root(repo_path: str) -> str:
    """
    Auto-detect the real code root inside a cloned repo.

    Handles any structure:
      repo/                        → returns repo/
      repo/project/                → returns repo/project/
      repo/project/app/            → returns repo/project/
      repo/Redactless/data-privacy → returns that folder

    Logic: walk up to 3 levels deep, go into the subfolder
    that has the most code files.
    """
    current = repo_path

    for _ in range(3):
        code_count = _count_code_files(current)
        subfolders = _get_subfolders(current)

        # If this level already has code files — this is the root
        if code_count >= 3:
            return current

        # No subfolders to explore
        if not subfolders:
            return current

        # Pick the subfolder with the most direct code files
        best = max(subfolders, key=_count_code_files, default=None)
        if best and _count_code_files(best) > 0:
            current = best
            continue

        # Subfolders exist but none have direct code files —
        # go one level deeper into the first one
        if len(subfolders) == 1:
            current = subfolders[0]
            continue

        break

    return current


def collect_files(repo_path: str) -> List[str]:
    """
    Walk the cloned repo and return all code file paths.
    Auto-detects the real code root if all code is in a subfolder.
    Returns relative paths (relative to the detected code root).
    """
    all_files = []

    # Auto-detect real code root
    real_root = _find_code_root(repo_path)
    if real_root != repo_path:
        logger.info(f"Code root auto-detected: {real_root}")

    for root, dirs, files in os.walk(real_root):
        rel_root = os.path.relpath(root, real_root)

        dirs[:] = [
            d for d in dirs
            if not should_skip(os.path.join(rel_root, d))
            and not d.startswith(".")
        ]

        for fname in files:
            abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(abs_path, real_root)
            rel_path = rel_path.replace("\\", "/")

            if should_skip(rel_path):
                continue

            try:
                size_kb = os.path.getsize(abs_path) / 1024
                if size_kb > MAX_FILE_SIZE_KB:
                    logger.debug(f"Skipping large file: {rel_path} ({size_kb:.0f}KB)")
                    continue
            except OSError:
                continue

            all_files.append(rel_path)

    logger.info(f"Collected {len(all_files)} files from {real_root}")
    return prioritize_files(all_files)


def read_file_safe(repo_path: str, rel_path: str) -> str | None:
    # Try both from repo_path and from detected real_root
    real_root = _find_code_root(repo_path)
    for base in [real_root, repo_path]:
        abs_path = os.path.join(base, rel_path)
        if os.path.exists(abs_path):
            try:
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            except Exception as e:
                logger.debug(f"Cannot read {rel_path}: {e}")
                return None
    return None


def iter_batches(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def cleanup_repo(repo_id: str):
    """Delete the cloned repo folder after indexing to save disk space."""
    dest = os.path.join(CLONE_BASE, repo_id)
    if not os.path.exists(dest):
        return

    # Windows fix: .git files are read-only, must remove that flag first
    import stat

    def remove_readonly(func, path, _):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    try:
        shutil.rmtree(dest, onerror=remove_readonly)
        logger.info(f"Cleaned up clone: {dest}")
    except Exception as e:
        logger.warning(f"Could not fully clean up {dest}: {e}")
