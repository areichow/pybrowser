from pybrowser.parser import read_document
from pybrowser.recovery import RecoveryJournal
from pybrowser.saving import changed
from pybrowser.source_write_service import SaveRequest, SourceWriteService


def test_crlf_encoding_cookie_and_final_newline(tmp_path):
    path = tmp_path / "sample.py"
    path.write_bytes(b"# coding: latin-1\r\nNAME = 'caf\xe9'\r\n")
    document = read_document(path)
    assert document.encoding == "iso-8859-1"
    assert document.newline == "\r\n"
    assert document.final_newline
    journal = RecoveryJournal(tmp_path, tmp_path / "history")
    SourceWriteService(journal).save_document(SaveRequest(
        document, document.text.replace("caf\xe9", "th\xe9"), "save_file", "Save sample",
    ))
    assert b"\r\n" in path.read_bytes()


def test_digest_detects_same_size_change(tmp_path):
    path = tmp_path / "x.py"
    path.write_text("A=1\n")
    document = read_document(path)
    path.write_text("A=2\n")
    assert changed(document)
