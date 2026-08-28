from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import shutil
import time

import bpy


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _replace_with_retry(source: Path, target: Path, attempts: int = 6,
                        delay_s: float = 0.4) -> None:
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay_s * (attempt + 1))


def backup_existing(path: str | Path, backup_dir: str | Path) -> Path | None:
    source = Path(path)
    if not source.exists():
        return None
    backup_root = Path(backup_dir)
    backup_root.mkdir(parents=True, exist_ok=True)
    target = backup_root / f"{source.stem}_{_timestamp()}{source.suffix}"
    counter = 1
    while target.exists():
        target = backup_root / f"{source.stem}_{_timestamp()}_{counter:02d}{source.suffix}"
        counter += 1
    shutil.copy2(source, target)
    print(f"[backup] {source} -> {target}")
    return target


def atomic_save_blend(target: str | Path, backup_dir: str | Path) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_existing(target, backup_dir)
    temp = target.with_name(f".{target.stem}.new{target.suffix}")
    if temp.exists():
        temp.unlink()
    bpy.ops.wm.save_as_mainfile(filepath=str(temp))
    _replace_with_retry(temp, target)
    print(f"[blend] wrote {target}")
    return target


def atomic_export_glb(
    target: str | Path,
    *,
    use_selection: bool = False,
    export_extras: bool = True,
) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.stem}.new{target.suffix}")
    if temp.exists():
        temp.unlink()
    bpy.ops.export_scene.gltf(
        filepath=str(temp),
        export_format="GLB",
        export_apply=True,
        export_extras=export_extras,
        use_selection=use_selection,
        use_visible=True,
    )
    _replace_with_retry(temp, target)
    print(f"[glb] wrote {target}")
    return target


def atomic_publish(source: str | Path, target: str | Path) -> Path:
    source = Path(source)
    target = Path(target)
    if not source.exists():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.stem}.new{target.suffix}")
    if temp.exists():
        temp.unlink()
    shutil.copy2(source, temp)
    _replace_with_retry(temp, target)
    print(f"[publish] {source} -> {target}")
    return target
