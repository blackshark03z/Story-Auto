"""Runtime isolation and project-relative path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import re


_PROJECT_ID = re.compile(r"^prj_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class ProjectPathError(ValueError):
    """Raised when a runtime or durable artifact path violates isolation."""

    failure_class = "PROJECT_INVALID"


def _safe_relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise ProjectPathError("project-relative path must be non-empty text")
    normalized = value.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or ":" in value:
        raise ProjectPathError("durable artifact paths must be project-relative")
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise ProjectPathError("project-relative path cannot escape its project")
    return posix


@dataclass(frozen=True)
class RuntimeLayout:
    """Story Auto's dedicated runtime root, separate from source and providers."""

    root: Path

    @classmethod
    def from_root(cls, root: Path | str) -> "RuntimeLayout":
        return cls(Path(root).expanduser().resolve())

    @property
    def projects(self) -> Path:
        return self.root / "projects"

    @property
    def flow_profile(self) -> Path:
        return self.root / "browser" / "flow-profile"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def temp(self) -> Path:
        return self.root / "temp"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def evidence(self) -> Path:
        return self.root / "evidence"

    @property
    def locks(self) -> Path:
        return self.root / "locks"

    def ensure(self) -> "RuntimeLayout":
        """Create the frozen Story Auto runtime layout without provider actions."""

        for directory in (
            self.projects,
            self.flow_profile,
            self.cache,
            self.temp,
            self.logs,
            self.evidence,
            self.locks,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class ProjectPaths:
    """Filesystem paths for one stable Story Auto project identity."""

    runtime: RuntimeLayout
    project_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.project_id, str) or not _PROJECT_ID.fullmatch(self.project_id):
            raise ProjectPathError("project_id must be a stable prj_<opaque> identity")

    @property
    def root(self) -> Path:
        return self.runtime.projects / self.project_id

    @property
    def project_file(self) -> Path:
        return self.root / "project.json"

    @property
    def content_file(self) -> Path:
        return self.root / "content.md"

    def artifact_path(self, relative_path: str) -> Path:
        """Resolve a durable project-relative artifact without allowing escape."""

        relative = _safe_relative_path(relative_path)
        root = self.root.resolve()
        candidate = root.joinpath(*relative.parts).resolve()
        if not candidate.is_relative_to(root):
            raise ProjectPathError("artifact path resolves outside the project")
        return candidate
