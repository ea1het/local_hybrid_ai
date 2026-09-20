#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Shared Gitea native-dump ZIP identity and safety validation.

Both the backup and restore command packages need to recognize the Stack4
Gitea recovery resource and validate a native-dump ZIP the same way: backup
validates what it just produced, restore validates what it is about to trust.
This module is the single, shared definition so neither package depends on
the other's internals for it.
"""
from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path, PurePosixPath

GITEA_RESOURCE_ID = "gitea-state"


class GiteaDumpError(RuntimeError):
    pass


def validate_zip_member(name: str) -> None:
    if not name or "\\" in name:
        raise GiteaDumpError("Gitea dump contains an invalid ZIP member path")
    path = PurePosixPath(name)
    if path.is_absolute():
        raise GiteaDumpError("Gitea dump contains an absolute ZIP member path")
    normalized = posixpath.normpath(name)
    if normalized == ".." or normalized.startswith("../"):
        raise GiteaDumpError("Gitea dump contains a parent-traversal ZIP member path")


def validate_gitea_dump(path: Path) -> list[str]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise GiteaDumpError("Gitea native dump is missing or empty")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            if not names:
                raise GiteaDumpError("Gitea native dump ZIP contains no members")
            for name in names:
                validate_zip_member(name)
            bad = archive.testzip()
            if bad is not None:
                raise GiteaDumpError(f"Gitea native dump ZIP CRC validation failed: {bad}")
    except zipfile.BadZipFile as exc:
        raise GiteaDumpError("Gitea native dump is not a valid ZIP archive") from exc
    return names
