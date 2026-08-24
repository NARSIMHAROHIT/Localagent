"""Put a few sample files into the workspace so there is something to work with.

Run from the project root:   python scripts/seed_workspace.py
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PROJECT_ROOT, WORKSPACE_DIR  # noqa: E402

SAMPLES = PROJECT_ROOT / "samples"

(WORKSPACE_DIR / "docs").mkdir(parents=True, exist_ok=True)
(WORKSPACE_DIR / "notes.md").write_text(
    "title: Project Atlas\nowner: rohit\nstatus: draft\n", encoding="utf-8"
)
(WORKSPACE_DIR / "todo.txt").write_text(
    "TODO\n- ship the agent\n- write tests\n", encoding="utf-8"
)
(WORKSPACE_DIR / "docs" / "arch.md").write_text(
    "# Architecture\nThe agent uses a tool registry.\n", encoding="utf-8"
)
for sample in SAMPLES.glob("*.md"):
    shutil.copy(sample, WORKSPACE_DIR / sample.name)

print(f"seeded {WORKSPACE_DIR}")
