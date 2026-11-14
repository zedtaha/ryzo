# PyInstaller spec for a single-file Windows build:  pyinstaller packaging/ryzo.spec
import os

root = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(root, "ryzolauncher.py")],
    pathex=[root],
    datas=[
        (os.path.join(root, "ryzo", "kernel", "ryzo_kernel.R"), "ryzo/kernel"),
        (os.path.join(root, "ryzo", "resources"), "ryzo/resources"),
    ],
    hiddenimports=["ryzo.core.main"],
    excludes=[
        "tkinter", "unittest", "pydoc_data", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtDesigner", "PySide6.QtHelp",
        "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtSvgWidgets", "PySide6.QtUiTools",
        "PySide6.QtXml",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="Ryzo",
    icon=os.path.join(root, "packaging", "ryzo.ico"),
    console=False,
    upx=False,
    version=None,
)
