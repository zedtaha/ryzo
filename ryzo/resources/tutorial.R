## Welcome to Ryzo
# Ryzo is an interactive editor for R, modelled after Pyzo. The editor is on
# the left, an R shell is at the top right and the tools are below it.
#
# This file is split into *cells*. A cell starts at a line beginning with "##".
# "# %%" and RStudio-style section comments ("# Section ----") work as cell
# separators too. Put your cursor in a cell and press Ctrl+Enter to run it.


## Running code
# Ctrl+Enter         run the current cell
# Ctrl+Shift+Enter   run the cell and move to the next one
# Alt+Enter / F9     run the selection, or the current line
# Shift+F9           run the selection/line and move to the next line
# Ctrl+E / F5        run the whole file in the current shell
# Ctrl+Shift+E       restart R, change to the file's folder and run it
#                    ("run as script")

x <- rnorm(100)
summary(x)


## Plots
# Plots are captured and shown in the Plots tool. Use the arrows there to
# go back through earlier plots, or save them as PNG, PDF or SVG.

hist(x, col = "steelblue", main = "A histogram")
plot(cars, pch = 19, col = "tomato")
abline(lm(dist ~ speed, data = cars), lwd = 2)


## The workspace and the data viewer
# The Workspace tool lists the objects in the global environment.
# Double-click a list or data frame to look inside it; right-click for
# more options. View() opens a data frame in a sortable table.

fit <- lm(mpg ~ wt + hp, data = mtcars)
View(mtcars)


## Help
# Put your cursor on a function name and the Interactive help tool shows its
# documentation. You can also use ?topic in the shell, or press Shift+F1.

?mean


## Completion and calltips
# Start typing a name (3 characters) to get completions from R itself.
# Typing "(" after a function name shows its arguments.
# Try it: type   seq(   or   mtcars$   on the line below.



## The shell
# - Up/Down browse the history (type a prefix first to filter it).
# - Tab completes.
# - Ctrl+I (or Ctrl+C with nothing selected) interrupts a long computation.
# - Ctrl+K restarts R, Ctrl+L clears the screen.
# - Shift+Enter adds a new line without running the input.
# Try interrupting this one:

for (i in 1:30) { cat(i, ""); Sys.sleep(0.2) }


## Functions and the source structure
# The Source structure tool lists the cells and functions in this file.
# Click an entry to jump to it.

square <- function(x) {
  x^2
}

cube <- function(x) x^3

sapply(1:5, square)


## That's it!
# Ryzo keeps your open files between sessions. Use File > New (Ctrl+N) to
# start your own script, and Shell > Edit shell configurations to choose
# which R installation to use. Have fun!
