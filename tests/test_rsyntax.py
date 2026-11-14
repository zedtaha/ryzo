from ryzo.core.rsyntax import (S_DQ, S_NORMAL, cell_title, is_cell_line, parse_structure,
                               tokenize)


def kinds(line, state=S_NORMAL):
    tokens, _ = tokenize(line, state)
    return [(line[s:s + n], k) for s, n, k in tokens]


def test_basic_tokens():
    toks = kinds('x <- mean(c(1, 2.5e3, NA), na.rm = TRUE) # done')
    assert ("<-", "assign") in toks
    assert ("mean", "function") in toks
    assert ("2.5e3", "number") in toks
    assert ("NA", "constant") in toks
    assert ("TRUE", "constant") in toks
    assert ("# done", "comment") in toks


def test_keywords_and_strings():
    toks = kinds("if (y == 'a\\'b') function(x) x else \"q\"")
    assert ("if", "keyword") in toks
    assert ("'a\\'b'", "string") in toks
    assert ("function", "keyword") in toks
    assert ('"q"', "string") in toks


def test_multiline_string_state():
    _, state = tokenize('s <- "first line')
    assert state == S_DQ
    tokens, state = tokenize('second line" + 1', state)
    assert tokens[0][2] == "string"
    assert state == S_NORMAL


def test_raw_string():
    toks = kinds('r"(C:\\path "quoted")" ; 1')
    assert toks[0] == ('r"(C:\\path "quoted")"', "string")


def test_pipe_and_roxygen():
    assert ("|>", "operator") in kinds("x |> head()")
    assert ("%>%", "operator") in kinds("x %>% head()")
    assert kinds("#' @param x")[0][1] == "roxygen"


def test_cells():
    assert is_cell_line("## Load data")
    assert is_cell_line("# %% section")
    assert is_cell_line("# Section ----")
    assert not is_cell_line("### not a cell")
    assert not is_cell_line("#' roxygen ----")
    assert not is_cell_line("x <- 1 ## trailing")
    assert cell_title("## Load data") == "Load data"
    assert cell_title("# Model fitting ----") == "Model fitting"


def test_structure():
    src = "\n".join([
        "library(stats)",
        "## Setup",
        "f <- function(x) {",
        "  helper = function(y) y",
        "  x",
        "}",
        "## Classes",
        'setClass("Person", representation(name = "character"))',
        "Acc <- R6::R6Class('Acc')",
        'msg <- "f2 <- function() not real',
        'still in string"',
    ])
    items = parse_structure(src)
    assert [i.name for i in items] == ["stats", "Setup", "Classes"]
    setup = items[1]
    assert setup.children[0].name == "f"
    assert setup.children[0].children[0].name == "helper"
    classes = items[2]
    names = [c.name for c in classes.children]
    assert "Person  [setClass]" in names and "Acc" in names
    assert all("f2" not in c.name for c in classes.children)
