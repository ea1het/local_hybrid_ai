#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Restore-owned compatibility for Gitea dump validation helpers.

This package-local module intentionally duplicates the small validation surface
needed by restore. It must not import the recovery command package.
"""
from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path, PurePosixPath


class Stack4BackupError(RuntimeError):
    pass


def validate_zip_member(name: str) -> None:
    if not name or "\\" in name:
        raise Stack4BackupError("Gitea dump contains an invalid ZIP member path")
    path = PurePosixPath(name)
    if path.is_absolute():
        raise Stack4BackupError("Gitea dump contains an absolute ZIP member path")
    normalized = posixpath.normpath(name)
    if normalized == ".." or normalized.startswith("../"):
        raise Stack4BackupError("Gitea dump contains a parent-traversal ZIP member path")


def validate_gitea_dump(path: Path) -> list[str]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise Stack4BackupError("Gitea native dump is missing or empty")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            if not names:
                raise Stack4BackupError("Gitea native dump ZIP contains no members")
            for name in names:
                validate_zip_member(name)
            bad = archive.testzip()
            if bad is not None:
                raise Stack4BackupError(f"Gitea native dump ZIP CRC validation failed: {bad}")
    except zipfile.BadZipFile as exc:
        raise Stack4BackupError("Gitea native dump is not a valid ZIP archive") from exc
    return names

__all__ = ["Stack4BackupError", "validate_zip_member", "validate_gitea_dump"]
