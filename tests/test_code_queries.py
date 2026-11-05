from pathlib import Path
from pybrowser.code_queries import callable_name_from_label, implementers, senders
from pybrowser.project import open_world


def test_callable_name_and_signature_format(tmp_path):
    assert callable_name_from_label("run  (self, value) [staticmethod]") == "run"
    source = "def empty():\n    pass\n\ndef values(a,b,c):\n    return a\n"
    path = tmp_path / "app.py"
    path.write_text(source)
    from pybrowser.parser import build_index
    labels = [m.label for m in build_index(path, source)[0].members if not m.synthetic]
    assert "empty  ()" in labels
    assert "values  (a, b, c)" in labels


def test_implementers_and_senders(tmp_path):
    (tmp_path / "a.py").write_text("class A:\n    def run(self):\n        pass\n")
    (tmp_path / "b.py").write_text("class B:\n    def run(self):\n        pass\n\ndef caller(obj):\n    obj.run()\n")
    world = open_world(tmp_path)
    assert len(implementers(world, "run")) == 2
    found = senders(world, "run")
    assert len(found) == 1
    assert found[0].label.startswith("caller")
