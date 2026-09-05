"""Fail unless a Windows executable embeds Vortex's elevation contract."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pefile


def embedded_manifests(executable: Path) -> list[bytes]:
    """Return all RT_MANIFEST payloads embedded in *executable*."""
    pe = pefile.PE(str(executable), fast_load=True)
    try:
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
        )
        resources = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
        if resources is None:
            return []
        payloads: list[bytes] = []
        for resource_type in resources.entries:
            if resource_type.id != pefile.RESOURCE_TYPE["RT_MANIFEST"]:
                continue
            for resource_id in resource_type.directory.entries:
                for language in resource_id.directory.entries:
                    data = language.data.struct
                    payloads.append(pe.get_data(data.OffsetToData, data.Size))
        return payloads
    finally:
        pe.close()


def execution_level(payload: bytes) -> tuple[str | None, str | None]:
    """Read requestedExecutionLevel without depending on its XML prefix."""
    text = payload.decode("utf-8-sig", errors="strict").rstrip("\x00")
    root = ET.fromstring(text)
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "requestedExecutionLevel":
            return element.get("level"), element.get("uiAccess")
    return None, None


def verify(executable: Path) -> None:
    payloads = embedded_manifests(executable)
    if not payloads:
        raise ValueError("no RT_MANIFEST resource found")
    levels = [execution_level(payload) for payload in payloads]
    if ("requireAdministrator", "false") not in levels:
        raise ValueError(
            "requestedExecutionLevel must be requireAdministrator with uiAccess=false; "
            f"found {levels!r}"
        )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"Usage: {Path(argv[0]).name} EXE", file=sys.stderr)
        return 2
    executable = Path(argv[1]).resolve()
    try:
        verify(executable)
    except (OSError, ValueError, ET.ParseError, pefile.PEFormatError) as exc:
        print(f"Manifest verification failed for {executable}: {exc}", file=sys.stderr)
        return 1
    print(
        f"Manifest verified: {executable} requests requireAdministrator "
        "with uiAccess=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
