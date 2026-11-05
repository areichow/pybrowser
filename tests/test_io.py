from pathlib import Path
from pybrowser.parser import read_document
from pybrowser.saving import atomic_write,changed

def test_crlf_encoding_cookie_and_final_newline(tmp_path):
    path=tmp_path/"sample.py";path.write_bytes(b"# coding: latin-1\r\nNAME = 'caf\xe9'\r\n")
    doc=read_document(path);assert doc.encoding=="iso-8859-1";assert doc.newline=="\r\n";assert doc.final_newline
    atomic_write(doc,doc.text.replace("caf\xe9","th\xe9"));assert b"\r\n" in path.read_bytes()
def test_digest_detects_same_size_change(tmp_path):
    path=tmp_path/"x.py";path.write_text("A=1\n");doc=read_document(path);path.write_text("A=2\n");assert changed(doc)
