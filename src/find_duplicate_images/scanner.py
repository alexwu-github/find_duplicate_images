import hashlib
import logging
import os
from collections import defaultdict
from pathlib import Path

from find_duplicate_images.config import supported_extension

logger = logging.getLogger(__name__)


class DuplicateScanner:
    file_extension = supported_extension

    def __init__(self):
        logger.debug("Supported extensions: %s", self.file_extension)
        self.duplicates = []
        self.total_files = 0
        self.scanned = 0
        self.cancel_scan = False

    def scan_drive(self, root_paths, progress_callback=None, duplicate_callback=None):
        """
        Find groups of byte-identical files under root_paths.

        progress_callback(phase, current, total, filepath) fires during both
        the file-discovery/sizing pass ("sizing") and the slower hashing pass
        ("hashing"), so callers can show progress through the whole scan
        rather than have it go blank during the slow part.

        duplicate_callback(key, files), if given, fires every time a duplicate
        group is confirmed or gains another member — `files` is the group's
        full member list so far. `key` identifies the group stably across
        calls, so callers can list results live instead of waiting for the
        whole scan to finish.

        Cancelling stops each phase early but never throws work away: whatever
        duplicate groups were already confirmed are still returned.
        """
        self.duplicates = []
        self.cancel_scan = False

        image_files = self._collect_image_files(root_paths)
        self.total_files = len(image_files)

        size_groups = self._group_by_size(image_files, progress_callback)
        hash_groups = self._group_by_hash(
            size_groups, progress_callback, duplicate_callback
        )

        self.duplicates = [files for files in hash_groups.values() if len(files) > 1]
        return self.duplicates

    def _collect_image_files(self, root_paths):
        """Walk root_paths and return every file with a supported extension."""
        image_files = []
        for root in root_paths:
            if not os.path.exists(root):
                continue
            for dirpath, _, filenames in os.walk(root):
                if self.cancel_scan:
                    return image_files
                for filename in filenames:
                    ext = Path(filename).suffix.lower()
                    if ext in self.file_extension:
                        image_files.append(os.path.join(dirpath, filename))
        return image_files

    def _group_by_size(self, image_files, progress_callback=None):
        """Bucket files by byte size — only same-size files can be duplicates."""
        size_groups = defaultdict(list)
        for idx, filepath in enumerate(image_files):
            if self.cancel_scan:
                return size_groups
            try:
                self.scanned = idx + 1
                if progress_callback:
                    progress_callback("sizing", idx + 1, self.total_files, filepath)

                size = os.path.getsize(filepath)
                if size > 0:
                    size_groups[size].append(filepath)
            except OSError:
                continue
        return size_groups

    def _group_by_hash(
        self, size_groups, progress_callback=None, duplicate_callback=None
    ):
        """Hash the contents of same-size files to confirm real duplicates."""
        # Only groups with 2+ same-size files are worth hashing at all — a
        # unique size can never turn out to be a duplicate.
        candidates = {
            size: files for size, files in size_groups.items() if len(files) >= 2
        }
        total_to_hash = sum(len(files) for files in candidates.values())

        hash_groups = defaultdict(list)
        hashed = 0
        for size, files in candidates.items():
            for filepath in files:
                if self.cancel_scan:
                    return hash_groups
                hashed += 1
                if progress_callback:
                    progress_callback("hashing", hashed, total_to_hash, filepath)
                try:
                    file_hash = self.get_file_hash(filepath)
                except OSError:
                    continue

                # key on size too, so a hash collision across different sizes
                # can't merge unrelated files into one group
                key = (size, file_hash)
                hash_groups[key].append(filepath)
                if duplicate_callback and len(hash_groups[key]) >= 2:
                    duplicate_callback(key, list(hash_groups[key]))
        return hash_groups

    def get_file_hash(self, filepath, algorithm="md5"):
        """
        Compute hash of file contents. Uses MD5 by default (fast).

        Args:
            filepath: Path to the file to hash
            algorithm: Hash algorithm to use ('md5', 'sha1', 'sha256', etc.)

        Returns:
            str: Hexadecimal hash string
        """
        try:
            # usedforsecurity=False keeps md5 available on FIPS-mode systems
            hasher = hashlib.new(algorithm, usedforsecurity=False)
            with open(filepath, "rb") as f:
                # Read in chunks to avoid memory blow-up
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except OSError as e:
            logger.error("Error hashing %s: %s", filepath, e)
            raise

    def stop_scan(self):
        """Stop the current scan operation."""
        self.cancel_scan = True
