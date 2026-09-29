#!/usr/bin/env python3
"""Minimal MCP server (stdio, no deps) that drives a running Vim via --remote-expr.

Start Vim with:  vim --servername VIM
Register with your MCP client as a stdio server: python3 /path/to/vim_mcp.py
Pick server:     VIM_SERVER=NAME, else $VIM_SERVERNAME (set by Vim's :terminal),
                  else first entry of `vim --serverlist`
"""
import json, os, subprocess, sys, time


def server():
    name = os.environ.get("VIM_SERVER") or os.environ.get("VIM_SERVERNAME")
    if name:
        return name
    out = subprocess.run(["vim", "--serverlist"], capture_output=True, text=True).stdout.split()
    if not out:
        raise RuntimeError("no Vim server running; start one with: vim --servername VIM")
    return out[0]


def s(value):
    """Python value -> Vim expression (JSON-decoded inside Vim, so any text is safe)."""
    return "json_decode('" + json.dumps(value).replace("'", "''") + "')"


def vim(expr):
    r = subprocess.run(["vim", "--servername", server(), "--remote-expr", expr],
                       capture_output=True, text=True, timeout=10)
    if r.returncode or r.stderr.strip():
        raise RuntimeError(r.stderr.strip() or f"vim exited {r.returncode}")
    return r.stdout.rstrip("\n")


# The editing window: the current one, or the previous one if we're called from
# a :terminal (e.g. an MCP client running inside Vim), so edits never land in the terminal.
WIN = "(&buftype ==# 'terminal' ? win_getid(winnr('#')) : win_getid())"


def buf(buffer):
    return f"winbufnr({WIN})" if buffer == "%" else f"bufnr({s(str(buffer))})"


def in_win(cmd):
    """Run an Ex command in the editing window and return its output."""
    return vim(f"win_execute({WIN}, {s(cmd)})")


def numbered(first, lines):
    return "\n".join(f"{first + i}\t{l}" for i, l in enumerate(lines))


# --- tools ------------------------------------------------------------------

def list_buffers():
    return vim("json_encode(map(getbufinfo({'buflisted':1}),"
               "{_,b->{'nr':b.bufnr,'name':b.name,'changed':b.changed,'current':b.bufnr==winbufnr(" + WIN + ")}}))")


def read_buffer(buffer="%"):
    b = buf(buffer)
    lines = json.loads(vim(f"json_encode(getbufline({b},1,'$'))"))
    return numbered(1, lines)


def get_selection():
    r = json.loads(in_win("echon json_encode({'file':expand('%:p'),'start':line(\"'<\"),"
                          "'lines':getline(\"'<\",\"'>\")})").strip())
    return f"{r['file']}\n" + numbered(r["start"], r["lines"])


# Typing effect: Vim types inserted text out on a timer so you can watch it.
# VIM_MCP_TYPE_MS = ms per tick (default 10); 0 = insert instantly.
TYPE_MS = int(os.environ.get("VIM_MCP_TYPE_MS", "10"))
TYPER = r"""
func! McpTypeStart(buf, win, lnum, lines, step, ms) abort
  let g:mcp_t = {'buf': a:buf, 'win': a:win, 'lnum': a:lnum, 'lines': a:lines, 'i': 0, 'col': -1, 'step': a:step}
  let g:mcp_typing = 1
  call timer_start(a:ms, 'McpTypeTick', {'repeat': -1})
  return 1
endfunc
func! McpTypeTick(timer) abort
  let t = g:mcp_t
  try
    if t.i >= len(t.lines)
      call timer_stop(a:timer)
      let g:mcp_typing = 0
      return
    endif
    let l = t.lnum + t.i
    let line = t.lines[t.i]
    if t.col < 0
      call appendbufline(t.buf, l - 1, '')
      let t.col = strchars(matchstr(line, '^\s*'))
    endif
    let t.col += t.step
    let typed = strcharpart(line, 0, t.col)
    call setbufline(t.buf, l, typed)
    if winbufnr(t.win) == t.buf
      call win_execute(t.win, 'call cursor(' . l . ',' . (strlen(typed) + 1) . ')')
    endif
    if t.col >= strchars(line)
      let t.i += 1
      let t.col = -1
    endif
    redraw
  catch
    call timer_stop(a:timer)
    let g:mcp_typing = 0
  endtry
endfunc
"""


def show_step(step, start, end):
    """Announce the step in a popup, scroll to it, and flash the lines about to be replaced."""
    pat = f"\\%>{start - 1}l\\%<{max(end, start - 1) + 1}l"
    cmds = [f"call cursor({max(start, 1)}, 1)", "normal! zz",
            f"let w:mcp_m = matchadd('DiffDelete', '{pat}')"]
    vim(f"[popup_notification({s(step)}, {{'time': 5000, 'highlight': 'PmenuSel', 'padding': [0,1,0,1]}}),"
        f"win_execute({WIN}, {s(cmds)}), execute('redraw')]")
    time.sleep(0.8 if end >= start else 0.3)
    vim(f"[win_execute({WIN}, {s('silent! call matchdelete(w:mcp_m)')}), execute('redraw')]")


def replace_lines(start, end, text, buffer="%", step=""):
    b = buf(buffer)
    lines = text.split("\n") if text else []
    if step and TYPE_MS > 0:
        show_step(step, start, end)
    parts = []
    if end >= start:
        parts.append(f"deletebufline({b},{start},{end})")
    if lines and TYPE_MS > 0:
        vim(f"exists('*McpTypeTick') ? 0 : execute({s(TYPER.strip().split(chr(10)))})")
        step = max(1, -(-sum(len(l) for l in lines) // 250))  # finish in ~250 ticks
        parts.append(f"McpTypeStart({b},{WIN},{start},{s(lines)},{step},{TYPE_MS})")
    elif lines:
        parts.append(f"appendbufline({b},{start - 1},{s(lines)})")
    parts.append("execute('redraw')")
    vim("[" + ",".join(parts) + "]")
    if lines and TYPE_MS > 0:
        deadline = time.time() + 60
        while vim("get(g:, 'mcp_typing', 0)") == "1" and time.time() < deadline:
            time.sleep(0.05)
    return f"replaced lines {start}-{end} with {len(lines)} line(s)"


def ex(command):
    return in_win(command).strip() or "ok"


BUF = {"type": "string", "description": "buffer number or name; default current ('%')"}
TOOLS = {
    "list_buffers": (list_buffers, "List open Vim buffers.", {}, []),
    "read_buffer": (read_buffer, "Read a buffer's lines, prefixed with line numbers.",
                    {"buffer": BUF}, []),
    "get_selection": (get_selection, "Get the last visual selection in the current buffer.", {}, []),
    "replace_lines": (replace_lines,
                      "Replace lines start..end (1-based, inclusive) with text. "
                      "Use end = start-1 to insert before start without deleting. Empty text deletes.",
                      {"start": {"type": "integer"}, "end": {"type": "integer"},
                       "text": {"type": "string"}, "buffer": BUF,
                       "step": {"type": "string",
                                "description": "short label shown to the user in Vim, e.g. 'Step 2/4: handle empty list'"}},
                      ["start", "end", "text"]),
    "ex": (ex, "Run an Ex command in Vim (e.g. 'edit foo.py', 'w', '42', 'normal! gg=G') and return its output.",
           {"command": {"type": "string"}}, ["command"]),
}


INSTRUCTIONS = ("The user is watching their Vim live. For files open in Vim (see list_buffers), "
                "edit with replace_lines instead of writing the file, so changes appear as you type. "
                "Work in small logical steps: one replace_lines per step "
                "(e.g. signature, then body, then edge cases, then the call site), each with a short "
                "`step` label like 'Step 2/4: handle empty list'. Re-read the buffer before each "
                "step since line numbers shift. Save with ex 'w' when done.")


# --- MCP / JSON-RPC over stdio ------------------------------------------------

def handle(msg):
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "vim-mcp", "version": "0.1"},
                "instructions": INSTRUCTIONS}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": n, "description": d,
                           "inputSchema": {"type": "object", "properties": p, "required": r}}
                          for n, (_, d, p, r) in TOOLS.items()]}
    if method == "tools/call":
        fn = TOOLS[params["name"]][0]
        try:
            return {"content": [{"type": "text", "text": fn(**(params.get("arguments") or {}))}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}
    raise KeyError(method)


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" not in msg:  # notification
            continue
        try:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg)}
        except KeyError as e:
            reply = {"jsonrpc": "2.0", "id": msg["id"],
                     "error": {"code": -32601, "message": f"unknown method {e}"}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
