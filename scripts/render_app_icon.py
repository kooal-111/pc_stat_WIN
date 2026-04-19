"""Generate pc_stat_win/assets/app.png and app.ico (run from repo root)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pc_stat_win.branding import write_packaged_icon_assets

if __name__ == "__main__":
    png, ico = write_packaged_icon_assets()
    print("Wrote:", png)
    print("Wrote:", ico)
