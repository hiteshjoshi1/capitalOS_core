# Rule 2 of pretooluse-guard.sh (#255, D-70): does a Bash command run `git push` with a force?
# Reads the command on stdin; exits 0 when some git push in it is forced, 1 when none is.
# (An awk error exits 2: the hook then falls back to its old whole-command check.)
#
# It splits the command into simple commands ("segments") the way the shell does, closely
# enough for this one question:
#  - Segments end at a newline, ; & | ( ) (so also && || |&). Quotes and backslashes are
#    honoured: a quoted argument (an issue body, a commit message) is one word of its own
#    command, never a command.
#  - A heredoc body is its command stdin, not commands, and is skipped; when that command is
#    a shell (bash <<EOF) the body is read as commands. In an unquoted heredoc, $(...) and
#    backquotes are read as commands (the shell runs them). A heredoc whose delimiter never
#    comes is read as commands (the safe side).
#  - $(...), backquotes and <(...) are read as commands, also inside double quotes.
#  - The string of bash/sh/zsh -c, the arguments of eval, the remote command of ssh, and text
#    piped or redirected into a shell that reads its stdin are read again as commands.
# Then, for each segment: skip VAR=value and prefixes (env, sudo, timeout, xargs, if, ...);
# for git, skip its global options (-C dir, -c k=v, --git-dir ...); for push, a forced push is
# -f (also in a cluster: -fu, -uf), --force, --force-with-lease[=...], --force-if-includes,
# their abbreviations (--for, --forc), --mirror, or a refspec starting with + (origin +main).
# Not seen: a force hidden in a variable (git push $FLAGS), a git alias, a function or script
# defined elsewhere, or remote config (remote.<name>.mirror, + in a configured refspec).
#
# Portable awk (macOS awk, mawk, gawk). split(s, a, "") gives one element per character, so
# reading is linear; runs of plain text are copied with one substr each.

BEGIN {
  RS = "\001"
  SEP = "\037"     # between the words of a segment
  DAT = "\035"     # prefix: the word is here-string text (stdin data)
  HDW = "\034"     # prefix: the word stands for heredoc body HDBODY[n]
  SQ = "\047"
  SPACES = " \t\r\v\f"
  STOP = SPACES "\n;&|()<>" SQ "\"\\$`#"
  DQSTOP = "\"\\$`"
}
{ input = (NR > 1 ? input "\001" : "") $0 }
END {
  QN = 1; Q[1] = input
  for (q = 1; q <= QN && q <= 64; q++) {
    scan(Q[q])
    for (s = 1; s <= SEGN; s++) if (segment(SEG[s])) exit 0
    if (PIPE_SHELL) queue(piped_text())
  }
  exit 1
}

function queue(x) { Q[++QN] = x }

function scan(str) {
  STR = str; N = split(str, C, ""); I = 1
  SEGN = 0; HDN = 0; PN = 0; PIPE_SHELL = 0; LV = 0
  walk("")
}

# ---- Reading -------------------------------------------------------------------------------
# Per nesting level LV ($(...) inside a word): the word being read WD, whether there is one HW,
# whether it is here-string data DN or a redirection target to drop RN, and its words WS.
function lv_init() { WD[LV] = ""; HW[LV] = 0; DN[LV] = 0; RN[LV] = 0; WN[LV] = 0 }
function add_word(w) { WN[LV]++; WS[LV, WN[LV]] = w }
function flush_word() {
  if (HW[LV]) {
    if (DN[LV]) { WD[LV] = DAT WD[LV]; DN[LV] = 0 }
    if (RN[LV]) RN[LV] = 0
    else add_word(WD[LV])
  }
  WD[LV] = ""; HW[LV] = 0
}
function flush_seg(   j, out) {
  flush_word(); DN[LV] = 0; RN[LV] = 0
  if (WN[LV] > 0) {
    out = WS[LV, 1]
    for (j = 2; j <= WN[LV]; j++) out = out SEP WS[LV, j]
    SEG[++SEGN] = out
  }
  WN[LV] = 0
}
# The first index from I whose character is in stops (N + 1 if none).
function upto(stops,   j) {
  for (j = I; j <= N; j++) if (index(stops, C[j])) break
  return j
}
function take(j) { WD[LV] = WD[LV] substr(STR, I, j - I); HW[LV] = 1; I = j }

# Commands up to the end (term ""), a ")" or a closing backquote.
function walk(term,   c, j) {
  LV++; lv_init()
  while (I <= N) {
    j = upto(STOP)
    if (j > I) { take(j); continue }
    c = C[I]
    if (c == "\n") { flush_seg(); I++; if (PN) read_heredocs() }
    else if (index(SPACES, c)) { flush_word(); I++ }
    else if (c == ";" || c == "&" || c == "|" || c == "(") { flush_seg(); I++ }
    else if (c == ")") { flush_seg(); I++; if (term == ")") { LV--; return } }
    else if (c == "`") {
      I++
      if (term == "`") { flush_seg(); LV--; return }
      HW[LV] = 1; walk("`")
    }
    else if (c == SQ) { I++; j = upto(SQ); take(j); I = j + 1 }
    else if (c == "\"") { I++; read_dquote(1) }
    else if (c == "\\") {
      if (C[I + 1] != "\n") { WD[LV] = WD[LV] C[I + 1]; HW[LV] = 1 }
      I += 2
    }
    else if (c == "$") {
      if (C[I + 1] == "(") { I += 2; HW[LV] = 1; walk(")") }
      else if (C[I + 1] == SQ) { I += 2; read_ansi() }
      else { WD[LV] = WD[LV] c; HW[LV] = 1; I++ }
    }
    else if (c == "#") {
      if (HW[LV]) { WD[LV] = WD[LV] c; I++ }
      else I = upto("\n")      # a comment
    }
    else if (c == "<" || c == ">") redirect(c)
    else { WD[LV] = WD[LV] c; HW[LV] = 1; I++ }
  }
  flush_seg(); LV--
}

# Double-quoted text after its opening quote (closing = 1), or an unquoted heredoc body
# (closing = 0, to N). Only $(...) and backquotes are commands here.
function read_dquote(closing,   c, j) {
  HW[LV] = 1
  while (I <= N) {
    j = upto(DQSTOP)
    if (j > I) { take(j); continue }
    c = C[I]
    if (c == "\"") { I++; if (closing) return; WD[LV] = WD[LV] c }
    else if (c == "\\") {
      if (C[I + 1] != "" && index("$`\"\\", C[I + 1])) { WD[LV] = WD[LV] C[I + 1]; I += 2 }
      else if (C[I + 1] == "\n") I += 2
      else { WD[LV] = WD[LV] c; I++ }
    }
    else if (c == "$") {
      if (C[I + 1] == "(") { I += 2; walk(")") }
      else { WD[LV] = WD[LV] c; I++ }
    }
    else if (c == "`") { I++; walk("`") }
    else { WD[LV] = WD[LV] c; I++ }
  }
}

# $'...' after its opening quote; escapes are kept as written (enough for this purpose).
function read_ansi(   c) {
  HW[LV] = 1
  while (I <= N) {
    c = C[I]
    if (c == "\\") { WD[LV] = WD[LV] c C[I + 1]; I += 2; continue }
    I++
    if (c == SQ) return
    WD[LV] = WD[LV] c
  }
}

# < and > forms, at I.
function redirect(c,   nx) {
  nx = C[I + 1]
  if (nx == "(") { flush_word(); I += 2; HW[LV] = 1; walk(")"); return }   # <(...) >(...)
  if (c == "<" && nx == "<") {
    flush_word()
    if (C[I + 2] == "<") { DN[LV] = 1; I += 3; return }                    # here-string
    I += 2; heredoc_start(); return
  }
  # A file descriptor number before it (2>&1) is not a word, nor is the target after it.
  if (HW[LV] && WD[LV] ~ /^[0-9]+$/) { WD[LV] = ""; HW[LV] = 0 }
  flush_word(); RN[LV] = 1; I++
  if (C[I] == ">" || C[I] == "&" || C[I] == "|") I++
}

# After <<: the delimiter. The body is read at the next newline (read_heredocs).
function heredoc_start(   strip, quoted, delim, c, j) {
  strip = 0; quoted = 0; delim = ""
  if (C[I] == "-") { strip = 1; I++ }
  while (I <= N && (C[I] == " " || C[I] == "\t")) I++
  while (I <= N) {
    c = C[I]
    if (index(SPACES "\n;&|()<>", c)) break
    if (c == SQ || c == "\"") { quoted = 1; I++; j = upto(c); delim = delim substr(STR, I, j - I); I = j + 1 }
    else if (c == "\\") { quoted = 1; delim = delim C[I + 1]; I += 2 }
    else { delim = delim c; I++ }
  }
  HDN++; HDBODY[HDN] = ""
  PN++; PIDX[PN] = HDN; PSTRIP[PN] = strip; PEXP[PN] = !quoted; PDELIM[PN] = delim
  add_word(HDW HDN)
}

# At the start of the line after a heredoc's command: each pending body, up to its delimiter.
function read_heredocs(   k, np, start, lstart, j, line, found) {
  np = PN; PN = 0
  for (k = 1; k <= np; k++) {
    start = I; found = 0
    while (I <= N) {
      lstart = I; j = upto("\n")
      line = substr(STR, I, j - I); I = j + 1
      if (PSTRIP[k]) sub(/^\t+/, "", line)
      if (line == PDELIM[k]) { found = 1; break }
    }
    if (!found) { I = start; break }       # no delimiter: the rest is read as commands
    HDBODY[PIDX[k]] = substr(STR, start, lstart - start)
    if (PEXP[k]) read_expanding(start, lstart)
  }
}
function read_expanding(a, b,   sN, sI) {
  sN = N; sI = I; N = b - 1; I = a
  LV++; lv_init(); read_dquote(0); LV--
  N = sN; I = sI
}

# ---- Judging -------------------------------------------------------------------------------
function base_name(x) { sub(/.*\//, "", x); return x }
function join_from(w, nw, k,   out) {
  out = ""
  for (; k <= nw; k++) out = out (out == "" ? "" : " ") w[k]
  return out
}

# One segment (words joined by SEP). 1 when it force-pushes.
function segment(str,   raw, nr, j, x, w, nw, k, base, stdin, has_c) {
  nr = split(str, raw, SEP)
  nw = 0; stdin = ""
  for (j = 1; j <= nr; j++) {
    x = raw[j]
    if (substr(x, 1, 1) == HDW) stdin = stdin HDBODY[substr(x, 2) + 0]
    else if (substr(x, 1, 1) == DAT) stdin = stdin substr(x, 2) "\n"
    else w[++nw] = x
  }
  k = 1
  while (k <= nw) {
    x = w[k]
    if (x ~ /^[A-Za-z_][A-Za-z0-9_]*=/) { k++; continue }           # VAR=value
    base = base_name(x)
    if (base ~ /^(sudo|env|command|builtin|exec|nohup|time|nice|xargs|stdbuf|caffeinate|timeout|gtimeout|!|[{]|then|do|else|if|elif|while|until)$/) {
      k = skip_prefix_opts(base, w, nw, k + 1); continue
    }
    break
  }
  if (k > nw) return 0
  base = base_name(w[k])
  if (tolower(base) == "git") return git_push_forced(w, nw, k + 1)
  if (base == "eval") { queue(join_from(w, nw, k + 1)); return 0 }
  if (base ~ /^(bash|sh|zsh|dash|ksh|fish)$/) {
    has_c = 0
    for (j = k + 1; j <= nw; j++) {
      x = w[j]
      if (x == "--") { j++; break }
      if (x ~ /^[-+][oO]$/ || x == "--rcfile" || x == "--init-file") { j++; continue }
      if (x ~ /^--/) continue
      if (x ~ /^-[^-]*c/) { has_c = 1; continue }
      if (x ~ /^[-+]/) continue
      break
    }
    if (has_c) { if (j <= nw) queue(w[j]) }
    else if (j > nw) {                        # no script operand: it runs its stdin
      if (stdin != "") queue(stdin); else PIPE_SHELL = 1
    }
    return 0
  }
  if (base == "ssh") {
    for (j = k + 1; j <= nw; j++) {
      x = w[j]
      if (x ~ /^-[bcDEeFIiJLlmOopQRSWwB]$/) { j++; continue }
      if (x ~ /^-/) continue
      break
    }
    j++                                       # the host
    if (j <= nw) queue(join_from(w, nw, j)); else if (stdin != "") queue(stdin)
  }
  return 0
}

# The options of a prefix command; those that take a value skip it too.
function skip_prefix_opts(cmd, w, nw, k,   takes) {
  takes = " "
  if (cmd == "sudo") takes = " -u -g -h -p -U -C -D -r -t -T "
  else if (cmd == "env") takes = " -u -C -S "
  else if (cmd == "xargs") takes = " -I -L -P -n -s -E -d -a -J -R "
  else if (cmd == "timeout" || cmd == "gtimeout") takes = " -s -k "
  else if (cmd == "nice") takes = " -n "
  else if (cmd == "stdbuf") takes = " -i -o -e "
  else if (cmd == "caffeinate") takes = " -t -w "
  while (k <= nw) {
    if (w[k] ~ /^-/) { if (index(takes, " " w[k] " ")) k += 2; else k++ }
    else if (w[k] ~ /^[0-9]/) k++               # a duration (timeout), a value (nice -n)
    else break
  }
  return k
}

# git [global options] push [options] [<repository> [<refspec>...]], from w[k].
function git_push_forced(w, nw, k,   x, cl, j, ch, ended) {
  while (k <= nw) {
    x = w[k]
    if (x ~ /^(-C|-c|--git-dir|--work-tree|--namespace|--config-env|--super-prefix|--list-cmds)$/) k += 2
    else if (x ~ /^-/) k++
    else break
  }
  if (k > nw || w[k] != "push") return 0
  ended = 0
  for (k++; k <= nw; k++) {
    x = w[k]
    if (ended) { if (x ~ /^[+]/) return 1; continue }
    if (x == "--") ended = 1
    else if (x ~ /^--(for|forc|force|force[=-].*|m|mi.*)$/) return 1
    else if (x ~ /^--(repo|push-option|receive-pack|exec|recurse-submodules)$/) k++
    else if (x ~ /^--/) continue
    else if (x ~ /^-./) {                       # short options: -f, -fu, -uf, -vf
      cl = substr(x, 2)
      for (j = 1; j <= length(cl); j++) {
        ch = substr(cl, j, 1)
        if (ch == "f") return 1
        if (ch == "o") { if (j == length(cl)) k++; break }   # -o <push option>
      }
    }
    else if (x ~ /^[+]/) return 1               # +refspec: force this ref
  }
  return 0
}

# Text that may be piped into a shell reading stdin (echo "..." | bash): each segment's
# words one per line, its arguments as one line, and its heredoc and here-string text.
function piped_text(   k, raw, nr, j, x, out, line) {
  out = ""
  for (k = 1; k <= SEGN; k++) {
    nr = split(SEG[k], raw, SEP)
    line = ""
    for (j = 1; j <= nr; j++) {
      x = raw[j]
      if (substr(x, 1, 1) == HDW) out = out HDBODY[substr(x, 2) + 0] "\n"
      else if (substr(x, 1, 1) == DAT) out = out substr(x, 2) "\n"
      else { out = out x "\n"; if (j > 1) line = line (line == "" ? "" : " ") x }
    }
    out = out line "\n"
  }
  return out
}
