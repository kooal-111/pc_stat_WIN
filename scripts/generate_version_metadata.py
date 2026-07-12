from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_stat_win.version import APP_VERSION  # noqa: E402


DEFAULT_OUTPUT = ROOT / "build" / "PCStat_version_info.txt"
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def version_tuple(version: str = APP_VERSION) -> tuple[int, int, int, int]:
    match = SEMVER_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"APP_VERSION must be MAJOR.MINOR.PATCH, got {version!r}")
    return tuple(map(int, match.groups())) + (0,)


def render_version_info(version: str = APP_VERSION) -> str:
    numeric_version = version_tuple(version)
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numeric_version!r},
    prodvers={numeric_version!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'PC Stat'),
          StringStruct('FileDescription', 'PC Stat activity tracker'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', 'PCStat'),
          StringStruct('OriginalFilename', 'PCStat.exe'),
          StringStruct('ProductName', 'PC Stat'),
          StringStruct('ProductVersion', '{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def generate_version_info(output: Path = DEFAULT_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_version_info(), encoding="utf-8", newline="\n")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PC Stat build version metadata.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print-version", action="store_true")
    args = parser.parse_args()

    if args.print_version:
        version_tuple()
        print(APP_VERSION)
        return 0

    print(generate_version_info(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
