"""Locate the normative resources shipped with the installed package."""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path, PurePosixPath


def resource_root() -> Path:
    """Return installed resources, independently of the current directory.

    Standard wheel installations unpack package data onto the filesystem. A
    filesystem path is required because the freeze step records source hashes
    and resolves links relative to each original resource file.
    """
    resource = files("rea_backend").joinpath("resources")
    if not isinstance(resource, Path):
        raise RuntimeError("REA-Backend resources require an unpacked package installation")
    root = resource.resolve()
    if not root.is_dir():
        raise FileNotFoundError("REA-Backend package resources are missing; reinstall the package")
    return root


def resource_file(relative: str) -> Path:
    """Return one existing package resource using a canonical relative path."""
    path = PurePosixPath(relative)
    if (not relative or path.is_absolute() or ".." in path.parts or "\\" in relative
            or str(path) != relative):
        raise ValueError(f"Invalid package resource path: {relative}")
    target = resource_root() / relative
    if not target.is_file() or target.is_symlink():
        raise FileNotFoundError(f"REA-Backend package resource is missing: {relative}")
    return target
