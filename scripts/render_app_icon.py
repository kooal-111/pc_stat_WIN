"""Create packaged PNG/ICO assets from a square source image."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pc_stat_win.branding import write_packaged_icon_assets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        nargs="?",
        help="Source PNG/JPEG. When omitted, rebuild from pc_stat_win/assets/app.png.",
    )
    args = parser.parse_args()
    png, ico = write_packaged_icon_assets(args.source)
    print(f"PNG: {png}")
    print(f"ICO: {ico}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
