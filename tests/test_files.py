import time

import pytest

from weeek_mcp.files import store
from weeek_mcp.files.detect import detect_mime, is_viewable

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8


@pytest.fixture(autouse=True)
def isolated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path / "weeek-mcp")


@pytest.mark.parametrize(
    "data,expected",
    [(PNG, "image/png"), (JPEG, "image/jpeg"), (b"GIF89a...", "image/gif"), (WEBP, "image/webp")],
)
def test_magic_bytes_win(data, expected):
    # The name lies; the bytes decide.
    assert detect_mime(data, filename="whatever.txt") == expected


def test_octet_stream_falls_back_to_the_extension():
    """Weeek's object storage commonly serves application/octet-stream."""
    assert detect_mime(b"\x00\x01\x02", "shot.png", declared="application/octet-stream") == "image/png"


def test_svg_is_identified_so_it_can_be_skipped():
    assert detect_mime(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "d.svg") == "image/svg+xml"
    assert not is_viewable("image/svg+xml")


def test_only_formats_a_vision_model_accepts_are_viewable():
    assert is_viewable("image/png")
    assert is_viewable("image/webp")
    assert not is_viewable("application/pdf")
    assert not is_viewable(None)


def test_unidentifiable_bytes_return_none():
    assert detect_mime(b"\x01\x02\x03", "mystery") is None


@pytest.mark.parametrize(
    "supplied,expected",
    [
        ("../../../etc/passwd", "passwd"),
        ("/absolute/secret.png", "secret.png"),
        ("..\\..\\windows.png", "windows.png"),
        ("..", "attachment"),
        ("", "attachment"),
        ("normal name (1).png", "normal_name_1.png"),
    ],
)
def test_supplied_filenames_cannot_escape_the_directory(supplied, expected):
    assert store.safe_name(supplied) == expected


@pytest.mark.parametrize(
    "supplied,mime,expected",
    [
        # Sanitising a Cyrillic stem leaves nothing behind; without the mime the
        # file would land as "png", no extension, and be read as text.
        ("ошибка.png", "image/png", "attachment.png"),
        ("баг на логине.png", "image/png", "attachment.png"),
        ("скрин 2.png", "image/png", "2.png"),
        # A comment image node often has no name at all, only a uuid in its URL.
        ("9f3c-uuid", "image/png", "9f3c-uuid.png"),
        # An extension that already denotes the same type is preserved as written.
        ("photo.jpeg", "image/jpeg", "photo.jpeg"),
        # A name that lies about its type is corrected from the sniffed bytes.
        ("screenshot.txt", "image/png", "screenshot.png"),
        # Nothing recognisable: leave the name alone rather than invent a suffix.
        ("report.xyz", None, "report.xyz"),
    ],
)
def test_extension_comes_from_the_detected_type(supplied, mime, expected):
    assert store.safe_name(supplied, mime) == expected


def test_a_very_long_name_keeps_its_extension():
    name = store.safe_name("a" * 400 + ".png", "image/png")

    assert name.endswith(".png")
    assert len(name) <= 110


def test_saving_never_writes_outside_the_task_directory():
    directory = store.task_dir(154)

    path = store.save(directory, "../../escape.png", PNG)

    assert path.parent == directory
    assert path.read_bytes() == PNG


def test_colliding_names_get_suffixes():
    directory = store.task_dir(154)

    first = store.save(directory, "shot.png", PNG)
    second = store.save(directory, "shot.png", JPEG)

    assert first != second
    assert second.name == "shot-2.png"


def test_task_dir_starts_empty_on_a_repeat_request():
    directory = store.task_dir(154)
    store.save(directory, "stale.png", PNG)

    assert list(store.task_dir(154).iterdir()) == []


def test_sweep_removes_only_old_directories():
    fresh = store.task_dir(1)
    old = store.task_dir(2)
    import os

    stale = time.time() - store.MAX_AGE_SECONDS - 60
    os.utime(old, (stale, stale))

    store.sweep()

    assert fresh.exists()
    assert not old.exists()


def test_sweep_is_a_no_op_without_a_root():
    store.sweep()  # must not raise when nothing has been downloaded yet
