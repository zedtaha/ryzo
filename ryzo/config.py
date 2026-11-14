"""Persistent configuration, stored as JSON in the user's app-data folder."""

import copy
import json
import os
import sys


def app_data_dir():
    override = os.environ.get("RYZO_CONFIG_DIR")
    if override:
        path = override
    elif sys.platform.startswith("win"):
        path = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ryzo")
    elif sys.platform == "darwin":
        path = os.path.expanduser("~/Library/Application Support/ryzo")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        path = os.path.join(base, "ryzo")
    os.makedirs(path, exist_ok=True)
    return path


def default_r_executable():
    return "R.exe" if sys.platform.startswith("win") else "R"


DEFAULTS = {
    "shellConfigs": [
        {
            "name": "R",
            "exe": default_r_executable(),
            "args": "",
            "startDir": "",
            "env": "",
            "startupCode": "",
        }
    ],
    "theme": "Ryzo light",
    "font": {"family": "", "size": 10},
    "zoom": 0,
    "indentWidth": 2,
    "wrap": False,
    "showWhitespace": False,
    "showLineNumbers": True,
    "showIndentGuides": True,
    "longLineIndicator": 80,
    "highlightCurrentLine": True,
    "autoComplete": True,
    "autoCompleteMinChars": 3,
    "calltips": True,
    "autoClose": True,
    "helpFollowsCursor": True,
    "plotStyle": True,
    "plotThumbnails": True,
    "plotExportDpi": 300,
    "recentFiles": [],
    "openFiles": [],
    "currentFile": "",
    "mainFile": "",
    "lastDir": "",
    "fileBrowser": {"path": "", "filter": "*.R *.r *.Rmd *.qmd *.md *.txt *.csv *.tsv *.json",
                    "starred": []},
    "history": [],
    "windowGeometry": "",
    "windowState": "",
    "firstRun": True,
}


class Config(dict):
    """A dict with attribute access that loads/saves itself."""

    def __init__(self, path=None):
        super().__init__()
        self.path = path or os.path.join(app_data_dir(), "config.json")
        self.update(copy.deepcopy(DEFAULTS))
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(self.get(key), dict):
                self[key].update(value)
            else:
                self[key] = value

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self, f, indent=2)
            os.replace(tmp, self.path)
        except OSError as err:
            print("Could not save config:", err, file=sys.stderr)

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        if name == "path":
            super().__setattr__(name, value)
        else:
            self[name] = value


config = None


def get_config():
    global config
    if config is None:
        config = Config()
    return config
