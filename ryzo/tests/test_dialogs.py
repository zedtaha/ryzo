"""Code generation of the Import Dataset and Install Packages dialogs."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeMain:
    cfg = {}

    def current_shell(self):
        return None


@pytest.fixture(scope="module")
def app():
    from PySide6 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture()
def main(app):
    from PySide6 import QtWidgets

    class Main(QtWidgets.QWidget, FakeMain):
        pass
    return Main()


def test_text_import_code(main, tmp_path):
    from ryzo.core.importdialog import ImportDatasetDialog
    f = tmp_path / "my data-2024.csv"
    f.write_text("a;b\n1,5;x\n2,5;y\n")
    dlg = ImportDatasetDialog(main, path=str(f))
    assert dlg.current_format() == "text_base"
    assert dlg.name.text() == "my_data_2024"
    assert dlg.reader_call().startswith("read.csv2(")  # ';' and decimal comma sniffed
    dlg.open_viewer.setChecked(False)
    assert dlg.import_code().startswith("my_data_2024 <- read.csv2(")
    assert "View(" not in dlg.code.toPlainText()
    assert "nrows = 50" in dlg.reader_call(preview=True)
    dlg.fmt.setCurrentIndex(dlg.fmt.findData("text_readr"))
    call = dlg.reader_call()
    assert call.startswith("readr::read_delim(") and 'delim = ";"' in call
    assert 'decimal_mark = ","' in call and "na =" not in call


def test_other_formats(main, tmp_path):
    from ryzo.core.importdialog import ImportDatasetDialog
    for name, start in (("x.xlsx", "readxl::read_excel("), ("x.sav", "haven::read_sav("),
                        ("x.dta", "haven::read_dta("), ("x.json", "jsonlite::fromJSON("),
                        ("x.rds", "readRDS(")):
        dlg = ImportDatasetDialog(main, path=str(tmp_path / name))
        assert dlg.reader_call().startswith(start), name
    dlg = ImportDatasetDialog(main, path=str(tmp_path / "all.RData"))
    assert dlg.import_code().startswith("load(")


def test_install_code(main):
    from ryzo.core.packagedialog import InstallPackagesDialog
    dlg = InstallPackagesDialog(main, packages="dplyr, ggplot2")
    assert dlg.install_code() == 'install.packages(c("dplyr", "ggplot2"))'
    dlg.deps.setChecked(False)
    assert dlg.install_code().endswith("dependencies = FALSE)")
    dlg.source.setCurrentIndex(1)
    dlg.packages.setText("/tmp/pkg_1.0.tar.gz")
    assert dlg.install_code() == 'install.packages("/tmp/pkg_1.0.tar.gz", repos = NULL, type = "source")'
