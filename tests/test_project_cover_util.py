import io
import os
import shutil
import subprocess

import pytest
from ebooklib import epub
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image

from tts_audiobook_tool.constants import PROJECT_TEXT_EPUB_FILE_NAME
from tts_audiobook_tool.project_support.project_cover_util import CoverImage, ProjectCoverUtil
from tts_audiobook_tool.sound.audio_meta_util import AudioMetaUtil


def make_image_bytes(image_format: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(output, format=image_format)
    return output.getvalue()


def write_epub(path: str, cover_mode: str) -> bytes:
    """ Writes a minimal EPUB and returns the bytes of its cover image (if any) """
    book = epub.EpubBook()
    book.set_identifier("test-book")
    book.set_title("Test Book")
    book.set_language("en")
    chapter = epub.EpubHtml(title="Chapter 1", file_name="chapter1.xhtml", lang="en")
    chapter.content = "<html><body><p>Hello.</p></body></html>"
    book.add_item(chapter)

    cover_bytes = make_image_bytes("JPEG")
    if cover_mode == "epub3":
        book.set_cover("images/front.jpg", cover_bytes, create_page=False)
    elif cover_mode == "epub2_meta":
        image = epub.EpubImage(uid="img1", file_name="images/front.jpg", media_type="image/jpeg", content=cover_bytes)
        book.add_item(image)
        book.add_metadata(None, "meta", "", {"name": "cover", "content": "img1"})
    elif cover_mode == "none":
        cover_bytes = b""

    book.toc = [chapter]
    book.spine = [chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(path, book)
    return cover_bytes


@pytest.mark.parametrize("cover_mode", ["epub3", "epub2_meta"])
def test_extract_epub_cover(tmp_path, cover_mode: str) -> None:
    epub_path = str(tmp_path / "book.epub")
    cover_bytes = write_epub(epub_path, cover_mode)

    cover = ProjectCoverUtil.extract_epub_cover(epub_path)

    assert cover is not None
    assert cover.data == cover_bytes
    assert cover.media_type == "image/jpeg"


def test_extract_epub_cover_returns_none_without_cover(tmp_path) -> None:
    epub_path = str(tmp_path / "book.epub")
    write_epub(epub_path, "none")

    assert ProjectCoverUtil.extract_epub_cover(epub_path) is None


def test_save_cover_replaces_existing_cover_and_converts_other_formats(tmp_path) -> None:
    project_dir = str(tmp_path)
    png_path, err = ProjectCoverUtil.save_cover(project_dir, CoverImage(make_image_bytes("PNG"), "image/png"))
    assert err == ""
    assert png_path.endswith("project_cover.png")

    jpg_path, err = ProjectCoverUtil.save_cover(project_dir, CoverImage(make_image_bytes("GIF"), "image/gif"))

    assert err == ""
    assert jpg_path.endswith("project_cover.jpg")
    assert not os.path.exists(png_path)
    with Image.open(jpg_path) as image:
        assert image.format == "JPEG"
    assert ProjectCoverUtil.get_cover_path(project_dir) == jpg_path


def test_get_or_extract_cover_path_extracts_from_project_epub(tmp_path) -> None:
    project_dir = str(tmp_path)
    cover_bytes = write_epub(os.path.join(project_dir, PROJECT_TEXT_EPUB_FILE_NAME), "epub3")

    assert ProjectCoverUtil.get_or_extract_cover_path(project_dir, "plain_text") == ""
    path = ProjectCoverUtil.get_or_extract_cover_path(project_dir, "epub")

    assert path.endswith("project_cover.jpg")
    with open(path, "rb") as f:
        assert f.read() == cover_bytes


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not available")
def test_set_mp4_cover_embeds_cover_art(tmp_path) -> None:
    m4b_path = str(tmp_path / "book.m4b")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", "1", "-c:a", "aac", "-f", "mp4", m4b_path],
        check=True,
    )
    image_path = str(tmp_path / "project_cover.png")
    image_bytes = make_image_bytes("PNG")
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    err = AudioMetaUtil.set_mp4_cover(m4b_path, image_path)

    assert err == ""
    covers = MP4(m4b_path).tags["covr"]
    assert bytes(covers[0]) == image_bytes
    assert covers[0].imageformat == MP4Cover.FORMAT_PNG
