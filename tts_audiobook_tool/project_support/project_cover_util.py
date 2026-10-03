"""
Cover image of a project's book.

On EPUB import, the EPUB's cover image is saved in the project directory as
"project_cover.jpg" (or ".png"). When an M4B file gets created, the cover is
embedded in it.
"""

from __future__ import annotations

import importlib
import io
import os
from dataclasses import dataclass
from typing import Any

from tts_audiobook_tool.constants import PROJECT_COVER_FILE_STEM, PROJECT_TEXT_EPUB_FILE_NAME
from tts_audiobook_tool.l import L
from tts_audiobook_tool.util import make_error_string

# Image formats that M4B (MP4) cover art supports, by file suffix
COVER_SUFFIXES = (".jpg", ".png")


@dataclass(frozen=True)
class CoverImage:
    data: bytes
    media_type: str


class ProjectCoverUtil:

    @staticmethod
    def extract_epub_cover(epub_path: str) -> CoverImage | None:
        """
        Returns the cover image of an EPUB file, or None if it has none.

        Looks for, in order: the EPUB 3 "cover-image" item, the item referenced
        by the EPUB 2 <meta name="cover"> element, and an image item whose id or
        file name contains "cover".
        """
        try:
            ebooklib = importlib.import_module("ebooklib")
            epub = importlib.import_module("ebooklib.epub")
            book = epub.read_epub(epub_path, options={"ignore_ncx": True})
        except Exception as e:
            L.w(f"Couldn't read EPUB for cover: {make_error_string(e)}")
            return None

        item = ProjectCoverUtil._find_cover_item(book, ebooklib)
        if item is None:
            return None
        try:
            data = item.get_content()
        except Exception as e:
            L.w(f"Couldn't read EPUB cover image: {make_error_string(e)}")
            return None
        if not data:
            return None
        return CoverImage(data=data, media_type=getattr(item, "media_type", "") or "")

    @staticmethod
    def _find_cover_item(book: Any, ebooklib: Any) -> Any | None:
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_COVER:
                return item

        for _, attributes in book.get_metadata("OPF", "cover"):
            item_id = (attributes or {}).get("content")
            item = book.get_item_with_id(item_id) if item_id else None
            if item is not None and str(getattr(item, "media_type", "")).startswith("image/"):
                return item

        for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
            names = f"{item.get_id()} {item.get_name()}".lower()
            if "cover" in names:
                return item

        return None

    @staticmethod
    def get_cover_path(project_dir: str) -> str:
        """ Returns the path of the project's cover image file, or empty string if there is none """
        for suffix in COVER_SUFFIXES:
            path = os.path.join(project_dir, PROJECT_COVER_FILE_STEM + suffix)
            if os.path.exists(path):
                return path
        return ""

    @staticmethod
    def delete_cover(project_dir: str) -> None:
        for suffix in COVER_SUFFIXES:
            path = os.path.join(project_dir, PROJECT_COVER_FILE_STEM + suffix)
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                L.w(f"Couldn't delete cover image {path}: {make_error_string(e)}")

    @staticmethod
    def save_cover(project_dir: str, cover: CoverImage) -> tuple[str, str]:
        """
        Saves the cover image in the project directory, replacing any existing one.
        JPEG and PNG images are saved as-is; other formats are converted to JPEG.
        Returns (saved path, error string).
        """
        if cover.media_type == "image/jpeg":
            suffix, data = ".jpg", cover.data
        elif cover.media_type == "image/png":
            suffix, data = ".png", cover.data
        else:
            suffix = ".jpg"
            try:
                data = ProjectCoverUtil._convert_to_jpeg(cover.data)
            except Exception as e:
                return "", f"Couldn't convert cover image ({cover.media_type}) to JPEG: {make_error_string(e)}"

        ProjectCoverUtil.delete_cover(project_dir)
        path = os.path.join(project_dir, PROJECT_COVER_FILE_STEM + suffix)
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError as e:
            return "", f"Couldn't save cover image: {make_error_string(e)}"
        return path, ""

    @staticmethod
    def _convert_to_jpeg(data: bytes) -> bytes:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            output = io.BytesIO()
            image.convert("RGB").save(output, format="JPEG", quality=92)
            return output.getvalue()

    @staticmethod
    def update_from_epub(project_dir: str, epub_path: str) -> tuple[str, str]:
        """
        Replaces the project's cover image with the cover of the EPUB file,
        or removes it if the EPUB has no cover.
        Returns (saved path or empty string, error string).
        """
        cover = ProjectCoverUtil.extract_epub_cover(epub_path)
        if cover is None:
            ProjectCoverUtil.delete_cover(project_dir)
            return "", ""
        return ProjectCoverUtil.save_cover(project_dir, cover)

    @staticmethod
    def get_or_extract_cover_path(project_dir: str, text_source_kind: str) -> str:
        """
        Returns the path of the project's cover image file. For an EPUB-based
        project imported before covers were saved, extracts the cover from the
        project's EPUB copy first. Returns empty string if there is no cover.
        """
        path = ProjectCoverUtil.get_cover_path(project_dir)
        if path or text_source_kind != "epub":
            return path
        epub_path = os.path.join(project_dir, PROJECT_TEXT_EPUB_FILE_NAME)
        if not os.path.exists(epub_path):
            return ""
        path, err = ProjectCoverUtil.update_from_epub(project_dir, epub_path)
        if err:
            L.w(err)
        return path
