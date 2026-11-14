"""Colour themes for the editor, shell and the application palette."""

from PySide6 import QtGui

THEMES = {
    "Ryzo light": {
        "dark": False,
        "background": "#ffffff",
        "foreground": "#1e1e1e",
        "gutter_bg": "#f3f3f3",
        "gutter_fg": "#9a9a9a",
        "current_line": "#f2f7ff",
        "selection": "#cfe2ff",
        "cell_line": "#6c8ebf",
        "indent_guide": "#e6e6e6",
        "long_line": "#e8e8e8",
        "brace_match": "#c5f0c5",
        "brace_bad": "#ffc8c8",
        "find_match": "#fff176",
        "keyword": "#0033b3",
        "constant": "#8a2be2",
        "function": "#00627a",
        "string": "#067d17",
        "number": "#1750eb",
        "comment": "#8c8c8c",
        "roxygen": "#4f8f6f",
        "cell": "#2a4f8a",
        "operator": "#871094",
        "assign": "#c0392b",
        "backtick": "#7a5a00",
        "shell_out": "#1e1e1e",
        "shell_err": "#c62828",
        "shell_warn": "#b26a00",
        "shell_echo": "#3b5ba5",
        "shell_prompt": "#0033b3",
        "shell_info": "#808080",
    },
    "Ryzo dark": {
        "dark": True,
        "background": "#1f2227",
        "foreground": "#d7dae0",
        "gutter_bg": "#252930",
        "gutter_fg": "#5f6672",
        "current_line": "#2a2f37",
        "selection": "#3e4f6b",
        "cell_line": "#6f8fc9",
        "indent_guide": "#2f343c",
        "long_line": "#2c3038",
        "brace_match": "#3d5c3d",
        "brace_bad": "#6b3030",
        "find_match": "#6b5d1e",
        "keyword": "#c678dd",
        "constant": "#d19a66",
        "function": "#61afef",
        "string": "#98c379",
        "number": "#d19a66",
        "comment": "#7f848e",
        "roxygen": "#6fa58a",
        "cell": "#8fb0ff",
        "operator": "#56b6c2",
        "assign": "#e06c75",
        "backtick": "#e5c07b",
        "shell_out": "#d7dae0",
        "shell_err": "#ef6b73",
        "shell_warn": "#e5c07b",
        "shell_echo": "#8fb0ff",
        "shell_prompt": "#61afef",
        "shell_info": "#7f848e",
    },
    "Solarized light": {
        "dark": False,
        "background": "#fdf6e3",
        "foreground": "#586e75",
        "gutter_bg": "#eee8d5",
        "gutter_fg": "#93a1a1",
        "current_line": "#f5efdc",
        "selection": "#e3dcc5",
        "cell_line": "#268bd2",
        "indent_guide": "#eee8d5",
        "long_line": "#eee8d5",
        "brace_match": "#d7e7c0",
        "brace_bad": "#f5c6c0",
        "find_match": "#f4e08a",
        "keyword": "#859900",
        "constant": "#d33682",
        "function": "#268bd2",
        "string": "#2aa198",
        "number": "#d33682",
        "comment": "#93a1a1",
        "roxygen": "#6c9a8f",
        "cell": "#268bd2",
        "operator": "#6c71c4",
        "assign": "#cb4b16",
        "backtick": "#b58900",
        "shell_out": "#586e75",
        "shell_err": "#dc322f",
        "shell_warn": "#b58900",
        "shell_echo": "#268bd2",
        "shell_prompt": "#859900",
        "shell_info": "#93a1a1",
    },
}


def get_theme(name):
    return THEMES.get(name, THEMES["Ryzo light"])


def apply_app_palette(app, theme):
    """Use a dark Fusion palette for dark themes, the default one otherwise."""
    app.setStyle("Fusion")
    if not theme["dark"]:
        app.setPalette(app.style().standardPalette())
        return
    p = QtGui.QPalette()
    C = QtGui.QColor
    base, alt, text = C("#1f2227"), C("#2b2f36"), C("#d7dae0")
    p.setColor(QtGui.QPalette.Window, alt)
    p.setColor(QtGui.QPalette.WindowText, text)
    p.setColor(QtGui.QPalette.Base, base)
    p.setColor(QtGui.QPalette.AlternateBase, alt)
    p.setColor(QtGui.QPalette.ToolTipBase, C("#3a3f47"))
    p.setColor(QtGui.QPalette.ToolTipText, text)
    p.setColor(QtGui.QPalette.Text, text)
    p.setColor(QtGui.QPalette.Button, alt)
    p.setColor(QtGui.QPalette.ButtonText, text)
    p.setColor(QtGui.QPalette.BrightText, C("#ff6b6b"))
    p.setColor(QtGui.QPalette.Highlight, C("#3e5f9a"))
    p.setColor(QtGui.QPalette.HighlightedText, C("#ffffff"))
    p.setColor(QtGui.QPalette.Link, C("#61afef"))
    p.setColor(QtGui.QPalette.PlaceholderText, C("#7f848e"))
    for role in (QtGui.QPalette.Text, QtGui.QPalette.ButtonText, QtGui.QPalette.WindowText):
        p.setColor(QtGui.QPalette.Disabled, role, C("#6b717c"))
    app.setPalette(p)
