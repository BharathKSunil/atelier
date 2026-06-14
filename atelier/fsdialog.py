"""Native macOS filesystem helpers (osascript / open). Degrade gracefully off macOS."""
import os
import subprocess


def choose_folder(default=None):
    """Open the native macOS 'choose folder' dialog.

    Returns the absolute POSIX path, or None if cancelled / unavailable.
    """
    prompt = 'choose folder with prompt "Select photo folder"'
    if default and os.path.isdir(default):
        prompt += f' default location POSIX file "{default}"'
    try:
        out = subprocess.run(
            ["osascript", "-e", f"POSIX path of ({prompt})"],
            capture_output=True, text=True, timeout=300)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:        # user pressed Cancel -> osascript exits 1
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
