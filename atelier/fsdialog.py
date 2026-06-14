"""Native macOS filesystem helpers (osascript / open). Degrade gracefully off macOS."""

import os
import shutil
import subprocess
import sys


def available():
    """True only where the native 'choose folder' dialog can actually run."""
    return sys.platform == "darwin" and shutil.which("osascript") is not None


def choose_folder(default=None):
    """Open the native macOS 'choose folder' dialog.

    Returns the absolute POSIX path, or None if cancelled / unavailable.
    """
    prompt = 'choose folder with prompt "Select photo folder"'
    # Never interpolate a path that could break out of the AppleScript string literal
    # into `do shell script ...`. Real folder paths never contain these characters.
    if default and os.path.isdir(default) and not any(c in default for c in '"\\\n\r'):
        prompt += f' default location POSIX file "{default}"'
    try:
        out = subprocess.run(
            ["osascript", "-e", f"POSIX path of ({prompt})"], capture_output=True, text=True, timeout=300
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:  # user pressed Cancel -> osascript exits 1
        return None
    path = out.stdout.strip()
    return path or None


def reveal(path):
    """Reveal a file or folder in Finder. Returns True on success."""
    if not path or not os.path.exists(path):
        return False
    try:
        subprocess.run(["open", "-R", path], timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
