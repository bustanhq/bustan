"""Form bodies, parsed without a form library."""

from __future__ import annotations

from typing import cast

import pytest

from bustan.adapters.asgi.forms import FormData, UploadFile, parse_form_body

_BOUNDARY = "----bustan-boundary"


def _multipart(*parts: str) -> bytes:
    body = "".join(f"--{_BOUNDARY}\r\n{part}\r\n" for part in parts)
    return f"{body}--{_BOUNDARY}--\r\n".encode()


def _multipart_type() -> str:
    return f"multipart/form-data; boundary={_BOUNDARY}"


def test_an_urlencoded_body_parses_into_its_fields() -> None:
    form = parse_form_body(b"name=Ada&admin=true", "application/x-www-form-urlencoded")

    assert form["name"] == "Ada"
    assert form.get("admin") == "true"


def test_an_urlencoded_body_keeps_every_value_of_a_repeated_field() -> None:
    form = parse_form_body(b"tag=a&tag=b", "application/x-www-form-urlencoded")

    assert form.getlist("tag") == ["a", "b"]
    assert form.get("tag") == "b"


def test_a_body_with_no_form_content_type_parses_as_empty() -> None:
    form = parse_form_body(b'{"name": "Ada"}', "application/json")

    assert len(form) == 0
    assert form.get("name") is None


def test_a_body_with_no_content_type_at_all_parses_as_empty() -> None:
    assert len(parse_form_body(b"name=Ada", None)) == 0


def test_a_multipart_body_parses_fields_and_uploads_together() -> None:
    body = _multipart(
        'Content-Disposition: form-data; name="name"\r\n\r\nAda',
        'Content-Disposition: form-data; name="document"; filename="note.txt"\r\n'
        "Content-Type: text/plain\r\n\r\nhello upload",
    )

    form = parse_form_body(body, _multipart_type())

    assert form["name"] == "Ada"
    upload = form["document"]
    assert isinstance(upload, UploadFile)
    assert upload.filename == "note.txt"
    assert upload.content_type == "text/plain"
    assert upload.size == len(b"hello upload")


def test_a_multipart_body_keeps_every_upload_sent_under_one_name() -> None:
    body = _multipart(
        'Content-Disposition: form-data; name="files"; filename="a.txt"\r\n\r\nA',
        'Content-Disposition: form-data; name="files"; filename="b.txt"\r\n\r\nB',
    )

    uploads = parse_form_body(body, _multipart_type()).getlist("files")

    assert all(isinstance(upload, UploadFile) for upload in uploads)
    assert [cast("UploadFile", upload).filename for upload in uploads] == ["a.txt", "b.txt"]


def test_a_multipart_part_with_no_field_name_is_ignored() -> None:
    body = _multipart("Content-Type: text/plain\r\n\r\norphan")

    assert len(parse_form_body(body, _multipart_type())) == 0


def test_a_multipart_body_without_a_boundary_is_refused() -> None:
    with pytest.raises(ValueError, match="must declare a boundary"):
        parse_form_body(b"", "multipart/form-data")


def test_a_multipart_part_with_no_header_block_is_refused() -> None:
    with pytest.raises(ValueError, match="Malformed multipart"):
        parse_form_body(_multipart("no headers here"), _multipart_type())


def test_the_charset_a_form_declared_is_the_one_it_is_decoded_with() -> None:
    form = parse_form_body(
        "name=Ada%E9".encode("latin-1"),
        "application/x-www-form-urlencoded; charset=latin-1",
    )

    assert form["name"] == "Adaé"


@pytest.mark.anyio
async def test_an_upload_is_read_seeked_and_closed_like_a_file() -> None:
    upload = UploadFile("note.txt", "text/plain", b"hello upload")

    assert await upload.read(5) == b"hello"
    await upload.seek(0)
    assert await upload.read() == b"hello upload"
    assert upload.file.tell() == len(b"hello upload")
    await upload.close()
    assert repr(upload) == "UploadFile(filename='note.txt', size=12)"


def test_a_form_reports_what_it_holds() -> None:
    form = FormData([("tag", "a"), ("tag", "b"), ("name", "Ada")])

    assert list(form) == ["tag", "name"]
    assert "tag" in form
    assert len(form) == 2
    assert form.multi_items() == (("tag", "a"), ("tag", "b"), ("name", "Ada"))
    assert repr(form) == "FormData([('tag', 'a'), ('tag', 'b'), ('name', 'Ada')])"
