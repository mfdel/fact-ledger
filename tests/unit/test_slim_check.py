from pathlib import Path

import pytest

import slim_check

pytestmark = pytest.mark.unit

BODY = "".join(f"value_{i} = {i}\n" for i in range(10))


def write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def test_count_lines_ignores_pragmas_and_counts_multiline_strings() -> None:
    source = '"""Doc\nstring."""\nx = 1  # noqa: F401\ny = 2  # real comment\n# another\n'
    assert slim_check.count_lines(source) == (4, 2)


def test_tiny_module_is_reported(tmp_path: Path) -> None:
    findings = slim_check.check_file(write(tmp_path, "tiny.py", "x = 1\n"))
    assert [f.message for f in findings] == ["tiny module (1 code lines); merge it"]


def test_comment_heavy_module_is_reported(tmp_path: Path) -> None:
    source = "# one\n# two\n# three\n" + BODY
    findings = slim_check.check_file(write(tmp_path, "chatty.py", source))
    assert [f.message for f in findings] == ["3 comments for 10 code lines; cut them"]


@pytest.mark.parametrize("name", ["__init__.py", "conftest.py"])
def test_exempt_files_are_skipped(tmp_path: Path, name: str) -> None:
    assert slim_check.check_file(write(tmp_path, name, "")) == []


def test_slim_module_passes(tmp_path: Path) -> None:
    assert slim_check.check_file(write(tmp_path, "slim.py", "# why\n" + BODY)) == []


def test_main_reports_unused_function(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "src").mkdir()
    write(tmp_path / "src", "mod.py", "def unused() -> int:\n    return 1\n" + BODY)
    monkeypatch.chdir(tmp_path)
    assert slim_check.main() == 1
    assert "src/mod.py:1: unused function 'unused'" in capsys.readouterr().out


def test_main_passes_clean_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "src").mkdir()
    write(tmp_path / "src", "mod.py", BODY)
    monkeypatch.chdir(tmp_path)
    assert slim_check.main() == 0
