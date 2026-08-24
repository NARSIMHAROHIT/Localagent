from pathlib import Path

from config import WORKSPACE_DIR
from .registry import tool

# The one folder these tools may touch. Change it with AGENT_WORKSPACE.
ROOT = WORKSPACE_DIR
ROOT.mkdir(parents=True, exist_ok=True)

MAX_FILE_BYTES = 200_000
MAX_LIST_ENTRIES = 300
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".DS_Store"}


class SandboxError(Exception):
    pass


def _resolve(relpath: str) -> Path:
    """Map a model-supplied path to a real path, or refuse it.

    This is THE security boundary. Everything below assumes it ran.
    """
    if relpath in ("", ".", "./"):
        return ROOT
    p = Path(relpath)
    if p.is_absolute():
        raise SandboxError(
            f"absolute paths are not allowed. Use a path relative to the workspace root."
        )
    target = (ROOT / p).resolve()          # resolve() also follows symlinks
    if not target.is_relative_to(ROOT):
        raise SandboxError(f"path '{relpath}' escapes the workspace and was blocked.")
    return target


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT)) or "."


@tool
def list_files(path: str = ".", recursive: bool = True) -> str:
    """List files and folders in the workspace. Call this FIRST when you need to
    work with files, so you know what actually exists instead of guessing names.

    Args:
        path: Folder relative to the workspace root. Use "." for the root.
        recursive: Whether to include files in subfolders.
    """
    base = _resolve(path)
    if not base.is_dir():
        raise SandboxError(f"'{path}' is not a folder.")

    rows, count = [], 0
    walker = base.rglob("*") if recursive else base.glob("*")
    for entry in sorted(walker):
        if any(part in SKIP_DIRS or part.startswith(".") for part in entry.parts):
            continue
        count += 1
        if count > MAX_LIST_ENTRIES:
            rows.append(f"...[stopped at {MAX_LIST_ENTRIES} entries]")
            break
        if entry.is_dir():
            rows.append(f"{_rel(entry)}/")
        else:
            rows.append(f"{_rel(entry)}  ({entry.stat().st_size} bytes)")

    return "\n".join(rows) if rows else f"(no files in '{path}')"


@tool
def read_file(path: str, max_lines: int = 400) -> str:
    """Read a text file from the workspace. Output is prefixed with line numbers
    for reference only — they are NOT part of the file contents.

    Args:
        path: File path relative to the workspace root.
        max_lines: Stop after this many lines.
    """
    target = _resolve(path)
    if not target.is_file():
        raise SandboxError(f"no such file: '{path}'. Use list_files to see what exists.")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise SandboxError(f"'{path}' is {target.stat().st_size} bytes; too large to read.")

    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise SandboxError(f"'{path}' is not a UTF-8 text file (probably binary).")

    lines = text.splitlines()
    shown = lines[:max_lines]
    body = "\n".join(f"{i:>4}| {ln}" for i, ln in enumerate(shown, 1))
    if len(lines) > max_lines:
        body += f"\n...[{len(lines) - max_lines} more lines]"
    return body or "(empty file)"


@tool
def write_file(path: str, content: str, overwrite: bool = False) -> str:
    """Create a new file, or fully replace one. To change part of an existing
    file, prefer edit_file — it will not destroy the rest of the content.

    Args:
        path: File path relative to the workspace root.
        content: The full text to write.
        overwrite: Must be true to replace a file that already exists.
    """
    target = _resolve(path)
    if target.exists() and not overwrite:
        raise SandboxError(
            f"'{path}' already exists. Use edit_file to modify it, "
            f"or call write_file again with overwrite=true to replace it entirely."
        )
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp = target.with_suffix(target.suffix + ".tmp")     # atomic-ish write
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target)
    return f"Wrote {len(content)} chars to '{path}'."


@tool
def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace an exact snippet of text in a file. old_text must appear EXACTLY
    once — include enough surrounding context to make it unique. Read the file
    first so you copy the text exactly.

    Args:
        path: File path relative to the workspace root.
        old_text: The exact existing text to replace, including whitespace.
        new_text: The replacement text.
    """
    target = _resolve(path)
    if not target.is_file():
        raise SandboxError(f"no such file: '{path}'.")

    text = target.read_text(encoding="utf-8")
    hits = text.count(old_text)
    if hits == 0:
        raise SandboxError(
            f"old_text was not found in '{path}'. Read the file again and copy "
            f"the text exactly, including indentation."
        )
    if hits > 1:
        raise SandboxError(
            f"old_text appears {hits} times in '{path}'. Add surrounding lines "
            f"to make it unique."
        )

    target.write_text(text.replace(old_text, new_text), encoding="utf-8")
    return f"Replaced 1 occurrence in '{path}'."


@tool
def search_files(query: str, path: str = ".") -> str:
    """Find which files contain a phrase, with matching line numbers. Use this
    to locate content instead of reading every file.

    Args:
        query: Case-insensitive text to search for.
        path: Folder to search, relative to the workspace root.
    """
    base = _resolve(path)
    needle, hits = query.lower(), []
    for entry in sorted(base.rglob("*")):
        if not entry.is_file():
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in entry.parts):
            continue
        try:
            text = entry.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if needle in line.lower():
                hits.append(f"{_rel(entry)}:{i}: {line.strip()[:160]}")
                if len(hits) >= 50:
                    return "\n".join(hits) + "\n...[more matches not shown]"
    return "\n".join(hits) if hits else f"No matches for '{query}'."
@tool
def delete_file(path: str) -> str:
    """Delete a file from the workspace. This cannot be undone, so only use it
    when the user has clearly asked for that exact file to be removed.

    Args:
        path: File path relative to the workspace root.
    """
    target = _resolve(path)
    if not target.is_file():
        raise SandboxError(f"no such file: '{path}'.")
    size = target.stat().st_size
    target.unlink()
    return f"Deleted '{path}' ({size} bytes)."