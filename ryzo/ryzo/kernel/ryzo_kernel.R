# Ryzo R kernel
#
# This script is sourced into an interactive R process started by the Ryzo IDE.
# Communication:
#   IDE -> R : requests over a local TCP socket (one header line + payload lines)
#   R -> IDE : framed JSON messages on stdout:  \002RYZO{json}\003
#   stdin    : left untouched, so readline(), scan() and menu() work for the user.
#
# All helpers live in the "tools:ryzo" environment on the search path,
# so they don't clutter the user's global environment.

local({

  ryzo <- new.env()
  ryzo$buffer <- character()
  ryzo$last_plot_page <- NULL
  ryzo$plot_dir <- file.path(tempdir(), "ryzo_plots")
  ryzo$plot_counter <- 0L
  ryzo$plot_width <- 700L
  ryzo$plot_height <- 500L
  ryzo$plot_res <- 96L
  ryzo$last_cwd <- ""
  ryzo$traceback <- NULL
  dir.create(ryzo$plot_dir, showWarnings = FALSE, recursive = TRUE)

  # ------------------------------------------------------------------ JSON --
  json_str <- function(s) {
    s <- enc2utf8(as.character(s))
    s <- gsub("\\", "\\\\", s, fixed = TRUE)
    s <- gsub("\"", "\\\"", s, fixed = TRUE)
    s <- gsub("\n", "\\n", s, fixed = TRUE)
    s <- gsub("\r", "\\r", s, fixed = TRUE)
    s <- gsub("\t", "\\t", s, fixed = TRUE)
    s <- gsub("[\001-\037]", "", s, useBytes = TRUE)
    paste0("\"", s, "\"")
  }
  to_json <- function(x) {
    if (is.null(x)) return("null")
    if (is.list(x)) {
      parts <- vapply(x, to_json, "")
      nms <- names(x)
      if (!is.null(nms)) {
        return(paste0("{", paste0(json_str(nms), ":", parts, collapse = ","), "}"))
      }
      return(paste0("[", paste0(parts, collapse = ","), "]"))
    }
    as_array <- inherits(x, "AsIs") || length(x) != 1L
    if (is.logical(x)) {
      v <- ifelse(is.na(x), "null", ifelse(x, "true", "false"))
    } else if (is.numeric(x)) {
      v <- ifelse(is.na(x) | !is.finite(x), "null", format(x, digits = 15, trim = TRUE))
    } else {
      v <- ifelse(is.na(x), "null", json_str(x))
    }
    if (as_array) paste0("[", paste0(v, collapse = ","), "]") else v
  }

  emit <- function(type, ...) {
    msg <- list(type = type, ...)
    cat("\002RYZO", to_json(msg), "\003", sep = "", file = stdout())
    flush(stdout())
    invisible()
  }
  ryzo$emit <- emit
  stream <- function(text, name = "stderr") emit("stream", name = name, text = text)

  # -------------------------------------------------------------- plotting --
  # Plots go to an invisible pdf(NULL) device with the display list enabled.
  # After every evaluation (and before a new page starts) the current page is
  # recorded, stored under an id, and replayed into a PNG for the Plots tool.
  # The IDE can ask for any stored plot to be re-rendered at another size
  # (RENDERPLOT) or exported (SAVEPLOT), so plots always fit the panel.
  ryzo$plots <- list()        # id -> recordedplot
  ryzo$plot_files <- list()   # id -> last png rendered for it
  ryzo$plot_seq <- 0L
  ryzo$plot_dpr <- 1
  ryzo$plot_style <- TRUE
  ryzo$max_plots <- 100L

  # A cleaner look for base graphics: horizontal axis labels, an L-shaped box,
  # softer axis colours and filled points. Set in the device, so it is part of
  # every recorded plot. Toggle with the Plots tool's style button.
  apply_style <- function() {
    if (!isTRUE(ryzo$plot_style)) return(invisible())
    graphics::par(las = 1, bty = "l", tcl = -0.3, mgp = c(2.5, 0.55, 0),
                  mar = c(4.1, 4.3, 2.8, 1.2), pch = 16, family = "sans",
                  col.axis = "#505050", col.lab = "#262626", col.main = "#1a1a1a",
                  col.sub = "#505050", fg = "#8c8c8c", cex.axis = 0.88,
                  cex.lab = 0.98, cex.main = 1.12, font.main = 2, lwd = 1.2)
    invisible()
  }

  # Plots are never laid out smaller than this (in 96-dpi pixels): R cannot fit
  # its margins on a tiny device ("figure margins too large"). If the panel is
  # smaller, the plot is drawn at this minimum and scaled down for display.
  min_size <- function(w, h, min_w = 480, min_h = 360) {
    # keep a sensible shape in very flat or very tall panels (it gets letterboxed)
    aspect <- w / h
    if (aspect > 2.5) w <- h * 2.5
    if (aspect < 0.4) h <- w / 0.4
    s <- max(1, min_w / w, min_h / h)
    c(w * s, h * s)
  }

  ryzo_device <- function(...) {
    sz <- min_size(ryzo$plot_width, ryzo$plot_height)
    grDevices::pdf(NULL, width = sz[1] / 96, height = sz[2] / 96, bg = "white")
    grDevices::dev.control("enable")
    apply_style()
    # what's on the display list now is set-up, not a plot
    ryzo$dl_baseline[[as.character(grDevices::dev.cur())]] <-
      length(tryCatch(grDevices::recordPlot()[[1]], error = function(e) NULL))
  }
  ryzo$dl_baseline <- list()
  ryzo$device <- ryzo_device

  # Each new page gets a new id; re-snapshots of the same page (e.g. after
  # abline() or points()) update that plot in the IDE.
  ryzo$page_id <- 0L
  ryzo$emitted_page <- -1L
  snapshot_plot <- function() {
    if (grDevices::dev.cur() == 1L) return(invisible())
    if (!identical(names(grDevices::dev.cur()), "pdf")) return(invisible())
    p <- tryCatch(grDevices::recordPlot(), error = function(e) NULL)
    if (is.null(p) || is.null(p[[1]]) || length(p[[1]]) == 0L) return(invisible())
    base <- ryzo$dl_baseline[[as.character(grDevices::dev.cur())]]
    if (!is.null(base) && length(p[[1]]) <= base) return(invisible())
    if (!is.null(ryzo$last_plot_page) && identical(p[[1]], ryzo$last_plot_page[[1]]))
      return(invisible())
    ryzo$last_plot_page <- p
    if (!identical(ryzo$emitted_page, ryzo$page_id)) {
      ryzo$plot_seq <- ryzo$plot_seq + 1L
      ryzo$emitted_page <- ryzo$page_id
    }
    id <- as.character(ryzo$plot_seq)
    ryzo$plots[[id]] <- p
    # keep memory bounded
    if (length(ryzo$plots) > ryzo$max_plots) {
      old <- names(ryzo$plots)[seq_len(length(ryzo$plots) - ryzo$max_plots)]
      for (o in old) forget_plot(o)
    }
    show_plot(id)
  }
  # A new page is about to start: capture the finished one first.
  on_new_page <- function(...) {
    if (grDevices::dev.cur() == 1L) {  # no device yet (don't open one via par())
      ryzo$page_id <- ryzo$page_id + 1L
      return(invisible())
    }
    new_page <- tryCatch(isTRUE(graphics::par("page")), error = function(e) TRUE)
    if (new_page) {
      snapshot_plot()
      ryzo$page_id <- ryzo$page_id + 1L
    }
  }
  setHook("before.plot.new", on_new_page)
  setHook("before.grid.newpage", function(...) {
    snapshot_plot()
    ryzo$page_id <- ryzo$page_id + 1L
  })
  forget_plot <- function(id) {
    if (!is.null(ryzo$plot_files[[id]])) unlink(ryzo$plot_files[[id]])
    ryzo$plots[[id]] <- NULL
    ryzo$plot_files[[id]] <- NULL
  }
  # Render plot `id` to a fresh PNG and tell the IDE.
  show_plot <- function(id, width = ryzo$plot_width, height = ryzo$plot_height,
                        dpr = ryzo$plot_dpr, rerender = FALSE) {
    p <- ryzo$plots[[id]]
    if (is.null(p)) return(invisible(FALSE))
    ryzo$plot_counter <- ryzo$plot_counter + 1L
    file <- file.path(ryzo$plot_dir, sprintf("plot_%s_%05d.png", id, ryzo$plot_counter))
    sz <- min_size(width, height)
    ok <- render_plot(p, sz[1], sz[2], file, dpi = 96 * dpr)
    if (ok && file.exists(file)) {
      if (!is.null(ryzo$plot_files[[id]])) unlink(ryzo$plot_files[[id]])
      ryzo$plot_files[[id]] <- file
      emit("plot", id = as.integer(id), path = normalizePath(file, winslash = "/"),
           width = width, height = height, dpr = dpr, rerender = rerender)
    }
    invisible(ok)
  }
  # width/height are in 96-dpi pixels (screen size); dpi sets the resolution
  # of raster output, so text scales the same way at any resolution.
  render_plot <- function(p, width, height, file, dpi = 96) {
    cur <- grDevices::dev.cur()
    win <- width / 96
    hin <- height / 96
    ext <- tolower(tools::file_ext(file))
    cairo <- capabilities("cairo")
    ok <- tryCatch({
      if (ext == "pdf") {
        if (cairo) grDevices::cairo_pdf(file, width = win, height = hin)
        else grDevices::pdf(file, width = win, height = hin)
      } else if (ext == "svg") {
        grDevices::svg(file, width = win, height = hin, bg = "white")
      } else if (ext %in% c("jpg", "jpeg")) {
        grDevices::jpeg(file, width = round(win * dpi), height = round(hin * dpi), res = dpi,
                        quality = 95, bg = "white", type = if (cairo) "cairo" else getOption("bitmapType"))
      } else if (ext %in% c("tif", "tiff")) {
        grDevices::tiff(file, width = round(win * dpi), height = round(hin * dpi), res = dpi,
                        compression = "lzw", bg = "white", type = if (cairo) "cairo" else getOption("bitmapType"))
      } else {
        grDevices::png(file, width = round(win * dpi), height = round(hin * dpi), res = dpi,
                       bg = "white", type = if (cairo) "cairo" else getOption("bitmapType"))
      }
      suppressWarnings(grDevices::replayPlot(p))
      TRUE
    }, error = function(e) FALSE, finally = {
      if (grDevices::dev.cur() != cur) grDevices::dev.off()
      if (cur > 1L) grDevices::dev.set(cur)
    })
    invisible(ok)
  }
  ryzo$render_plot <- render_plot
  ryzo$snapshot_plot <- snapshot_plot

  # ------------------------------------------------------------ evaluation --
  format_error <- function(e) {
    call <- conditionCall(e)
    msg <- conditionMessage(e)
    if (!is.null(call) && identical(deparse(call, nlines = 1L), "eval(expr, envir = globalenv())"))
      call <- NULL
    if (!is.null(call)) {
      dcall <- paste(deparse(call, nlines = 1L), collapse = "")
      sep <- if (nchar(dcall) + nchar(msg) > 58L) " : \n  " else " : "
      paste0("Error in ", dcall, sep, msg, "\n")
    } else {
      paste0("Error: ", msg, "\n")
    }
  }
  format_warnings <- function(warns) {
    one <- function(w) {
      call <- conditionCall(w)
      if (!is.null(call) && identical(deparse(call, nlines = 1L), "eval(expr, envir = globalenv())"))
      call <- NULL
    if (is.null(call)) conditionMessage(w)
      else paste0("In ", paste(deparse(call, nlines = 1L), collapse = ""), " : ",
                  conditionMessage(w))
    }
    if (length(warns) == 1L) {
      paste0("Warning message:\n", one(warns[[1L]]), "\n")
    } else {
      shown <- warns[seq_len(min(length(warns), 50L))]
      txt <- paste0(seq_along(shown), ": ", vapply(shown, one, ""), collapse = "\n")
      more <- if (length(warns) > 50L)
        sprintf("\nThere were %d warnings (use warnings() to see them)", length(warns)) else ""
      paste0("Warning messages:\n", txt, more, "\n")
    }
  }

  # Evaluate one top-level expression the way the R console does.
  run_expr <- function(expr) {
    warns <- list()
    status <- "ok"
    tryCatch(
      withCallingHandlers({
        v <- withVisible(eval(expr, envir = globalenv()))
        ryzo$last_value <- v$value
        if (v$visible) print(v$value)
      },
      error = function(e) {
        ryzo$traceback <- vapply(sys.calls(), function(cl)
          paste(deparse(cl, nlines = 1L), collapse = ""), "")
      },
      warning = function(w) {
        if (getOption("warn", 0) >= 0) warns[[length(warns) + 1L]] <<- w
        invokeRestart("muffleWarning")
      },
      message = function(m) {
        stream(conditionMessage(m))
        invokeRestart("muffleMessage")
      }),
      error = function(e) {
        stream(format_error(e))
        status <<- "error"
      },
      interrupt = function(e) {
        stream("\n[interrupted]\n")
        status <<- "interrupt"
      })
    if (length(warns)) {
      ryzo$last_warning <- setNames(lapply(warns, function(w) {
                                      cl <- conditionCall(w)
                                      if (identical(deparse(cl, nlines = 1L),
                                                    "eval(expr, envir = globalenv())")) NULL else cl
                                    }),
                                    vapply(warns, conditionMessage, ""))
      stream(format_warnings(warns), name = "warning")
    }
    status
  }

  is_incomplete <- function(err) {
    grepl("unexpected end of input|INCOMPLETE_STRING", conditionMessage(err))
  }

  # mode: "line"  = typed in the shell (may be continued with "+ " prompts)
  #       "block" = sent from the editor, echoed expression by expression
  #       "file"  = run a whole file, no echo
  eval_code <- function(lines, mode, srcname, lineoffset) {
    if (mode == "line") {
      ryzo$buffer <- c(ryzo$buffer, lines)
      lines <- ryzo$buffer
    }
    code <- paste(lines, collapse = "\n")
    if (lineoffset > 0L && mode != "line") {
      # keep line numbers in parse errors aligned with the editor
      code <- paste0(strrep("\n", lineoffset), code)
    }
    srcfile <- srcfilecopy(if (nzchar(srcname)) srcname else "<text>",
                           strsplit(code, "\n", fixed = TRUE)[[1]])
    exprs <- tryCatch(parse(text = code, keep.source = TRUE, srcfile = srcfile),
                      error = function(e) e)
    if (inherits(exprs, "error")) {
      if (mode == "line" && is_incomplete(exprs)) return("+ ")
      ryzo$buffer <- character()
      msg <- sub("^<text>:", "", conditionMessage(exprs))
      stream(paste0("Error: ", msg, "\n"))
      return("> ")
    }
    ryzo$buffer <- character()
    refs <- attr(exprs, "srcref")
    for (i in seq_along(exprs)) {
      if (mode == "block" && !is.null(refs)) {
        src <- as.character(refs[[i]])
        echo <- paste0(c("> ", rep("+ ", length(src) - 1L)), src, collapse = "\n")
        emit("echo", text = paste0(echo, "\n"))
      }
      status <- run_expr(exprs[[i]])
      if (status == "interrupt" || (status == "error" && mode != "line")) break
    }
    snapshot_plot()
    "> "
  }

  # ------------------------------------------------------------ introspection --
  complete <- function(line) {
    ok <- tryCatch({
      utils:::.assignLinebuffer(line)
      utils:::.assignEnd(nchar(line))
      token <- utils:::.guessTokenFromLine()
      utils:::.completeToken()
      comps <- utils:::.retrieveCompletions()
      list(token = token, items = I(as.character(comps)))
    }, error = function(e) list(token = "", items = I(character())))
    ok
  }

  resolve <- function(name) {
    if (!grepl("^[A-Za-z.][A-Za-z0-9._]*(:::?[A-Za-z.][A-Za-z0-9._]*)?$", name)) return(NULL)
    tryCatch(eval(parse(text = name), globalenv()), error = function(e) NULL)
  }

  calltip <- function(name) {
    f <- resolve(name)
    if (!is.function(f)) return("")
    a <- tryCatch(args(f), error = function(e) NULL)
    if (is.null(a)) return(paste0(name, "(...)"))
    d <- deparse(a, width.cutoff = 500L)
    d <- d[-length(d)]  # drop the trailing NULL body
    sig <- sub("^function ", name, paste(trimws(d), collapse = " "))
    sig
  }

  obj_size <- function(x) {
    d <- dim(x)
    if (!is.null(d)) paste(d, collapse = " x ") else as.character(length(x))
  }
  obj_summary <- function(x) {
    out <- tryCatch({
      if (is.data.frame(x)) {
        sprintf("%d obs. of %d variables", nrow(x), ncol(x))
      } else if (is.function(x)) {
        d <- deparse(args(x), width.cutoff = 500L)
        paste(trimws(d[-length(d)]), collapse = " ")
      } else if (is.environment(x)) {
        format(x)
      } else if (is.factor(x)) {
        sprintf("Factor w/ %d levels: %s", nlevels(x),
                paste(head(levels(x), 5), collapse = ", "))
      } else if (is.atomic(x) && !is.null(x)) {
        paste(format(head(as.vector(x), 20)), collapse = " ")
      } else if (is.list(x)) {
        sprintf("List of %d", length(x))
      } else {
        paste(class(x), collapse = ", ")
      }
    }, error = function(e) "?")
    out <- paste(out, collapse = " ")
    if (nchar(out) > 120L) out <- paste0(substr(out, 1L, 117L), "...")
    out
  }
  can_expand <- function(x) {
    (is.list(x) && length(x) > 0L) || is.environment(x)
  }

  workspace <- function(path) {
    target <- if (!nzchar(path)) globalenv() else
      tryCatch(eval(parse(text = path), globalenv()), error = function(e) NULL)
    entries <- list()
    add <- function(name, expr, obj) {
      entries[[length(entries) + 1L]] <<- list(
        name = name, expr = expr,
        class = paste(class(obj), collapse = "/"),
        type = typeof(obj),
        size = obj_size(obj),
        value = obj_summary(obj),
        expandable = can_expand(obj))
    }
    if (is.environment(target)) {
      for (n in sort(ls(target, all.names = FALSE))) {
        obj <- tryCatch(get(n, envir = target), error = function(e) NULL)
        expr <- if (!nzchar(path)) n else paste0(path, "$", n)
        if (!nzchar(path) && !grepl("^[A-Za-z.][A-Za-z0-9._]*$", n)) expr <- paste0("`", n, "`")
        add(n, expr, obj)
      }
    } else if (is.list(target)) {
      nms <- names(target)
      for (i in seq_len(min(length(target), 500L))) {
        n <- if (!is.null(nms) && nzchar(nms[i])) nms[i] else paste0("[[", i, "]]")
        expr <- if (!is.null(nms) && nzchar(nms[i]))
          paste0(path, "[[", json_str(nms[i]), "]]") else paste0(path, "[[", i, "]]")
        add(n, expr, target[[i]])
      }
    }
    list(path = path, entries = entries)
  }

  help_page <- function(topic, package = "") {
    h <- tryCatch({
      if (nzchar(package)) utils::help((topic), package = (package), help_type = "html")
      else utils::help((topic), help_type = "html")
    }, error = function(e) character())
    files <- as.character(h)
    if (!length(files)) {
      return(list(topic = topic, html = "", error = paste0("No documentation for '", topic, "'")))
    }
    help_file(files[1L], topic)
  }
  help_file <- function(file, topic) {
    html <- tryCatch({
      rd <- utils:::.getHelpFile(file)
      pkg <- basename(dirname(dirname(file)))
      out <- tempfile(fileext = ".html")
      tools::Rd2HTML(rd, out, package = pkg, dynamic = TRUE, stylesheet = "")
      paste(readLines(out, encoding = "UTF-8", warn = FALSE), collapse = "\n")
    }, error = function(e) "")
    list(topic = topic, html = html, error = "")
  }

  # --------------------------------------------------------- data preview --
  # Used by the Import Dataset dialog: evaluate the import code (with a row
  # limit) and send column names, types and the first rows as text.
  preview_data <- function(lines, max_rows = 50L, max_cols = 60L) {
    warns <- character()
    x <- tryCatch(
      withCallingHandlers(
        eval(parse(text = lines), new.env(parent = globalenv())),
        warning = function(w) {
          warns <<- c(warns, conditionMessage(w))
          invokeRestart("muffleWarning")
        },
        message = function(m) invokeRestart("muffleMessage")),
      error = function(e) e)
    if (inherits(x, "error"))
      return(list(error = paste(c(conditionMessage(x), unique(warns)), collapse = "\n")))
    if (is.environment(x)) {  # load() of an .RData file
      objs <- ls(x)
      if (!length(objs)) return(list(error = "The file contains no objects"))
      frames <- objs[vapply(objs, function(o) is.data.frame(get(o, x)), NA)]
      pick <- if (length(frames)) frames[1L] else objs[1L]
      note <- sprintf("Objects in file: %s (showing %s)", paste(objs, collapse = ", "), pick)
      x <- get(pick, x)
      warns <- c(note, warns)
    }
    df <- tryCatch(as.data.frame(x, stringsAsFactors = FALSE), error = function(e) NULL)
    if (is.null(df)) {
      txt <- paste(utils::capture.output(utils::str(x)), collapse = "\n")
      return(list(error = "", text = txt, warnings = I(warns)))
    }
    nr <- nrow(df)
    nc <- ncol(df)
    shown <- df[seq_len(min(nr, max_rows)), seq_len(min(nc, max_cols)), drop = FALSE]
    types <- vapply(df[seq_len(min(nc, max_cols))], function(col) {
      cl <- class(col)[1L]
      switch(cl, numeric = "double", integer = "integer", character = "character",
             factor = "factor", logical = "logical", Date = "date", POSIXct = "date-time",
             haven_labelled = "labelled", cl)
    }, "")
    rows <- lapply(seq_len(nrow(shown)), function(i)
      I(vapply(shown[i, , drop = FALSE], function(v) {
        v <- v[[1L]]
        if (length(v) != 1L) return(paste(format(v), collapse = ", "))
        if (is.na(v)) "NA" else format(v)
      }, "")))
    list(error = "", columns = I(names(shown)), types = I(unname(types)), rows = rows,
         nrow = nr, ncol = nc, warnings = I(warns))
  }

  # -------------------------------------------------- overrides for the IDE --
  tools_env <- attach(NULL, name = "tools:ryzo")

  # Help requested via ?topic or help(topic) shows up in the Help tool.
  print_help <- function(x, ...) {
    files <- as.character(x)
    topic <- attr(x, "topic")
    if (!length(files)) {
      stream(paste0("No documentation for '", topic, "' in specified packages and libraries\n"))
    } else {
      res <- help_file(files[1L], topic)
      emit("help", topic = res$topic, html = res$html, error = res$error)
      cat("[help for '", topic, "' shown in the Help tool]\n", sep = "")
    }
    invisible(x)
  }
  registerS3method("print", "help_files_with_topic", print_help,
                   envir = asNamespace("utils"))

  # View(df) opens the data viewer.
  assign("View", function(x, title) {
    if (missing(title)) title <- paste(deparse(substitute(x))[1L], collapse = "")
    df <- tryCatch(as.data.frame(x), error = function(e) NULL)
    if (is.null(df)) stop("cannot coerce object to a data frame for viewing")
    n <- nrow(df)
    if (n > 10000L) df <- df[seq_len(10000L), , drop = FALSE]
    f <- tempfile(fileext = ".tsv")
    utils::write.table(df, f, sep = "\t", quote = FALSE, row.names = TRUE,
                       col.names = NA, na = "NA", fileEncoding = "UTF-8")
    emit("view", path = normalizePath(f, winslash = "/"), title = title, nrow = n)
    invisible(x)
  }, envir = tools_env)

  # Clear the shell.
  assign("clear", function() emit("clear"), envir = tools_env)

  # Last error traceback (R's own traceback() is empty because Ryzo catches errors).
  assign("traceback", function(x = NULL, ...) {
    tb <- ryzo$traceback
    if (is.null(tb)) { cat("No traceback available\n"); return(invisible(NULL)) }
    # strip Ryzo's own frames and the condition-handling frames
    start <- which(tb == "eval(expr, envir = globalenv())")
    if (length(start)) tb <- tb[-seq_len(start[length(start)])]
    stop_at <- which(startsWith(tb, ".handleSimpleError("))
    if (length(stop_at)) tb <- tb[seq_len(stop_at[1L] - 1L)]
    if (!length(tb)) { cat("No traceback available\n"); return(invisible(NULL)) }
    tb <- rev(tb)
    cat(paste0(seq_along(tb), ": ", tb), sep = "\n")
    invisible(tb)
  }, envir = tools_env)

  assign("warnings", function(...) {
    lw <- ryzo$last_warning
    if (is.null(lw)) return(invisible(NULL))
    structure(lw, dots = list(...), class = "warnings")
  }, envir = tools_env)

  makeActiveBinding(".Last.value", function() ryzo$last_value, tools_env)
  assign(".ryzo", ryzo, envir = tools_env)

  options(
    device = ryzo_device,
    help_type = "html",
    browser = function(url, ...) emit("open_url", url = url),
    pager = function(files, header, title, delete.file) {
      txt <- paste(unlist(lapply(files, readLines, warn = FALSE)), collapse = "\n")
      emit("pager", title = if (length(title)) title[1L] else "", text = txt)
      if (isTRUE(delete.file)) unlink(files)
    },
    width = 100L,
    menu.graphics = FALSE,
    askYesNo = function(msg, ...) {
      ans <- readline(paste0(msg, " (yes/no/cancel) "))
      switch(tolower(substr(ans, 1, 1)), y = TRUE, n = FALSE, NA)
    }
  )

  repos <- getOption("repos")
  if (is.null(repos) || !length(repos)) {
    options(repos = c(CRAN = "https://cloud.r-project.org"))
  } else if (any(repos == "@CRAN@")) {
    repos[repos == "@CRAN@"] <- "https://cloud.r-project.org"
    options(repos = repos)
  }

  # ----------------------------------------------------------------- main loop --
  port <- as.integer(Sys.getenv("RYZO_PORT"))
  token <- Sys.getenv("RYZO_TOKEN")
  Sys.unsetenv(c("RYZO_PORT", "RYZO_TOKEN"))
  sock <- socketConnection("127.0.0.1", port = port, blocking = TRUE,
                           open = "r+b", encoding = "UTF-8", timeout = 3600 * 24 * 365)
  writeLines(token, sock)
  flush(sock)

  read_n <- function(n) {
    if (n <= 0L) return(character())
    lines <- character()
    while (length(lines) < n) {
      got <- readLines(sock, n = n - length(lines), encoding = "UTF-8")
      if (!length(got)) quit(save = "no")
      lines <- c(lines, got)
    }
    lines
  }

  notify_state <- function(prompt) {
    wd <- getwd()
    if (!identical(wd, ryzo$last_cwd)) {
      ryzo$last_cwd <- wd
      emit("cwd", path = normalizePath(wd, winslash = "/"))
    }
    emit("ready", prompt = prompt)
  }

  emit("hello", version = R.version.string, pid = Sys.getpid(),
       home = R.home(), cwd = normalizePath(getwd(), winslash = "/"))
  ryzo$last_cwd <- getwd()
  emit("ready", prompt = "> ")

  ryzo$loop <- function() {
    repeat {
      header <- tryCatch(readLines(sock, n = 1L, encoding = "UTF-8"),
                         interrupt = function(e) "INTERRUPT_IDLE")
      if (!length(header)) quit(save = "no")
      if (identical(header, "INTERRUPT_IDLE")) {
        ryzo$buffer <- character()
        notify_state("> ")
        next
      }
      parts <- strsplit(header, "\t", fixed = TRUE)[[1L]]
      cmd <- parts[1L]
      arg <- function(i, default = "") if (length(parts) >= i) parts[i] else default
      tryCatch({
        if (cmd == "EVAL") {
          # EVAL <mode> <nlines> <srcname> <lineoffset>
          lines <- read_n(as.integer(arg(3, "0")))
          emit("busy")
          prompt <- eval_code(lines, arg(2, "line"), arg(4), as.integer(arg(5, "0")))
          notify_state(prompt)
        } else if (cmd == "COMPLETE") {
          line <- read_n(1L)
          res <- complete(line)
          emit("complete", id = arg(2), token = res$token, items = res$items)
        } else if (cmd == "CALLTIP") {
          emit("calltip", id = arg(2), name = arg(3), tip = calltip(arg(3)))
        } else if (cmd == "WORKSPACE") {
          res <- workspace(arg(2))
          emit("workspace", path = res$path, entries = res$entries)
        } else if (cmd == "HELP") {
          res <- help_page(arg(2), arg(3))
          emit("help", topic = res$topic, html = res$html, error = res$error)
        } else if (cmd == "PLOTSIZE") {
          # PLOTSIZE <width> <height> <dpr>: default size for new plots
          ryzo$plot_width <- max(50L, as.integer(arg(2, "700")))
          ryzo$plot_height <- max(50L, as.integer(arg(3, "500")))
          ryzo$plot_dpr <- max(1, as.numeric(arg(4, "1")))
        } else if (cmd == "RENDERPLOT") {
          # RENDERPLOT <id> <width> <height> <dpr>
          ok <- show_plot(arg(2), max(50L, as.integer(arg(3))), max(50L, as.integer(arg(4))),
                          max(1, as.numeric(arg(5, "1"))), rerender = TRUE)
          if (!ok) emit("plot_missing", id = as.integer(arg(2)))
        } else if (cmd == "SAVEPLOT") {
          # SAVEPLOT <id> <file> <width px> <height px> <dpi>
          p <- ryzo$plots[[arg(2)]]
          ok <- !is.null(p) && render_plot(p, as.numeric(arg(4)), as.numeric(arg(5)), arg(3),
                                           dpi = as.numeric(arg(6, "96")))
          emit("saved", path = arg(3), ok = isTRUE(ok))
        } else if (cmd == "REMOVEPLOT") {
          if (arg(2) == "all") for (id in names(ryzo$plots)) forget_plot(id)
          else forget_plot(arg(2))
        } else if (cmd == "PLOTSTYLE") {
          ryzo$plot_style <- arg(2) == "1"
          # the style is part of the device: start a fresh one for the next plot
          if (grDevices::dev.cur() > 1L && identical(names(grDevices::dev.cur()), "pdf")) {
            snapshot_plot()
            grDevices::dev.off()
          }
        } else if (cmd == "SETWD") {
          setwd(arg(2))
          notify_state("> ")
        } else if (cmd == "QUERY") {
          # QUERY <id> <nlines>: evaluate code (in a scratch env) and return its value
          lines <- read_n(as.integer(arg(3, "0")))
          res <- tryCatch(list(value = eval(parse(text = lines), new.env(parent = globalenv())),
                               error = ""),
                          error = function(e) list(value = NULL, error = conditionMessage(e)))
          emit("query", id = arg(2), value = res$value, error = res$error)
        } else if (cmd == "PREVIEW") {
          # PREVIEW <id> <nlines>: evaluate code returning data; send the first rows
          lines <- read_n(as.integer(arg(3, "0")))
          emit("preview", id = arg(2), data = preview_data(lines))
        } else if (cmd == "SILENT") {
          # run code without echo or output (used by tool actions)
          lines <- read_n(as.integer(arg(2, "0")))
          try(eval(parse(text = lines), globalenv()), silent = TRUE)
          emit("done", id = arg(3))
        }
      }, error = function(e) {
        stream(paste0("[ryzo kernel] ", conditionMessage(e), "\n"))
        notify_state("> ")
      }, interrupt = function(e) {
        stream("\n[interrupted]\n")
        ryzo$buffer <- character()
        notify_state("> ")
      })
    }
  }
})
local(get(".ryzo", envir = as.environment("tools:ryzo"))$loop())
