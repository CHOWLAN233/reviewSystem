"""
Incremental state manager using MD5 hashes.

Tracks which files have already been processed so we only send
new or modified files to the LLM, saving API tokens and time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

STATE_VERSION = "1.0"


@dataclass
class FileRecord:
    """Metadata for one processed file stored in ``.sync_state.json``."""

    md5: str
    last_processed: str  # ISO-8601 timestamp
    classification: Optional[dict] = None
    output_path: Optional[str] = None  # relative to output_dir
    status: str = "processed"  # "processed" | "error" | "skipped"
    error_message: Optional[str] = None


class StateManager:
    """
    Manages ``.sync_state.json`` – the single source of truth for
    incremental processing.
    """

    def __init__(self, state_file: Path) -> None:
        self.state_file = state_file

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_state(self) -> dict[str, FileRecord]:
        """
        Load and return the state dictionary.

        Returns an empty dict if the state file is missing.
        If the state file is corrupt, attempts to recover from backup.
        """
        if not self.state_file.exists():
            logger.info("No existing state file – starting fresh.")
            return {}

        try:
            with open(self.state_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(f"State file corrupt: {exc}. Trying backup …")
            return self._recover_from_backup()

        version = data.get("version", "")
        if version != STATE_VERSION:
            logger.warning(
                f"State version mismatch: got {version!r}, expected {STATE_VERSION!r}. "
                f"Starting fresh."
            )
            return {}

        files_raw = data.get("files", {})
        records: dict[str, FileRecord] = {}
        for fname, meta in files_raw.items():
            try:
                records[fname] = FileRecord(
                    md5=meta.get("md5", ""),
                    last_processed=meta.get("last_processed", ""),
                    classification=meta.get("classification"),
                    output_path=meta.get("output_path"),
                    status=meta.get("status", "processed"),
                    error_message=meta.get("error_message"),
                )
            except (KeyError, TypeError) as exc:
                logger.warning(f"Skipping corrupt record for {fname!r}: {exc}")

        logger.info(f"Loaded state with {len(records)} tracked file(s).")
        return records

    def save_state(self, state: dict[str, FileRecord]) -> None:
        """
        Persist *state* to disk atomically:

        1. Back up the current state file (if it exists).
        2. Write to a temporary file.
        3. Atomically rename the temporary file to the target.
        """
        # Backup
        if self.state_file.exists():
            backup = Path(str(self.state_file) + ".backup")
            try:
                shutil.copy2(self.state_file, backup)
            except OSError as exc:
                logger.warning(f"Could not back up state file: {exc}")

        # Serialize
        files_dict: dict[str, dict[str, Any]] = {}
        for fname, record in state.items():
            files_dict[fname] = {
                "md5": record.md5,
                "last_processed": record.last_processed,
                "classification": record.classification,
                "output_path": record.output_path,
                "status": record.status,
                "error_message": record.error_message,
            }

        payload = {
            "version": STATE_VERSION,
            "last_run": datetime.now(timezone.utc).isoformat(),
            "files": files_dict,
        }

        # Atomic write: tmp → rename
        tmp = Path(str(self.state_file) + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.state_file)
            logger.info(f"State saved ({len(files_dict)} files).")
        except OSError:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise

    def compute_md5(self, filepath: Path) -> str:
        """Return the hex MD5 digest of *filepath*."""
        hasher = hashlib.md5()
        with open(filepath, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def find_new_or_changed(
        self, scanned: list[Path], state: dict[str, FileRecord]
    ) -> list[Path]:
        """
        Compare *scanned* files against *state*.

        Returns files that are either:
        - Not present in *state* (never processed), or
        - Whose MD5 hash differs from the stored record (modified since last run).
        """
        new_or_changed: list[Path] = []
        for fp in scanned:
            record = state.get(fp.name)
            if record is None:
                logger.debug(f"New file: {fp.name}")
                new_or_changed.append(fp)
                continue

            if record.status == "error":
                # Reprocess files that errored last time
                logger.debug(f"Retrying previously errored file: {fp.name}")
                new_or_changed.append(fp)
                continue

            current_md5 = self.compute_md5(fp)
            if current_md5 != record.md5:
                logger.debug(f"Modified file: {fp.name} (md5 changed)")
                new_or_changed.append(fp)
            else:
                logger.debug(f"Skipping unchanged file: {fp.name}")

        return new_or_changed

    def build_file_record(
        self,
        filepath: Path,
        status: str = "processed",
        classification: Optional[dict] = None,
        output_path: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> FileRecord:
        """Construct a ``FileRecord`` with the current timestamp and MD5 hash."""
        md5 = self.compute_md5(filepath)
        return FileRecord(
            md5=md5,
            last_processed=datetime.now(timezone.utc).isoformat(),
            classification=classification,
            output_path=output_path,
            status=status,
            error_message=error_message,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _recover_from_backup(self) -> dict[str, FileRecord]:
        """Try to load ``.sync_state.json.backup``.  Return {} on failure."""
        backup = Path(str(self.state_file) + ".backup")
        if not backup.exists():
            logger.warning("No backup found – starting with fresh state.")
            return {}
        try:
            with open(backup, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            logger.warning("Recovered state from backup.")
            files_raw = data.get("files", {})
            return {
                fname: FileRecord(
                    md5=m.get("md5", ""),
                    last_processed=m.get("last_processed", ""),
                    classification=m.get("classification"),
                    output_path=m.get("output_path"),
                    status=m.get("status", "processed"),
                    error_message=m.get("error_message"),
                )
                for fname, m in files_raw.items()
            }
        except Exception as exc:
            logger.error(f"Backup recovery also failed: {exc}")
            return {}
