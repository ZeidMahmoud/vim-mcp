# vim-mcp

A tiny [MCP](https://modelcontextprotocol.io) server that lets any MCP client read and edit the buffers of your **running Vim**.

One Python file, standard library only, no Vim plugin needed. It talks to Vim through Vim's built-in client-server feature (`vim --remote-expr`).

![demo](docs/demo.gif)

*An MCP client running in a Vim split, editing the buffer step by step. Full video: [docs/demo.mp4](docs/demo.mp4)*

```
MCP client  --stdio-->  vim_mcp.py  --vim --remote-expr-->  your Vim
```

## Watch the edits

Edits aren't dumped in all at once — you watch them happen:

- **Typing** — inserted text is typed out character by character, cursor following along
- **Steps** — each edit can carry a label, shown in a popup like `Step 2/4: handle empty list`
- **Highlight** — lines about to be replaced flash red first, then the view scrolls to them

Speed: `VIM_MCP_TYPE_MS` (ms per tick, default `10`); `0` disables all animation.

## Requirements

- Vim built with `+clientserver` (check: `vim --version | grep -E 'clientserver|socketserver'`)
  - Vim 9.2+ with `+socketserver`: works anywhere, including TTY/SSH — no X needed
  - older Vim: needs an X11 session (`$DISPLAY` set)
- Python 3.8+

## Install

```sh
git clone https://github.com/ZeidMahmoud/vim-mcp.git ~/vim-mcp
```

Register it with your MCP client as a stdio server. Most clients accept this config:

```json
{
  "mcpServers": {
    "vim": {
      "command": "python3",
      "args": ["/home/you/vim-mcp/vim_mcp.py"]
    }
  }
}
```

## Vim setup

Save as `~/.vim/plugin/mcp.vim` (or `~/.config/vim/plugin/mcp.vim`), or paste into your vimrc:

```vim
" register this Vim as a server so vim-mcp can find it
" (on VimEnter, so an explicit --servername still wins)
augroup mcp_server
  autocmd!
  autocmd VimEnter * if has('clientserver') && empty(v:servername)
        \ | call remote_startserver('VIM' . getpid()) | endif
augroup END

" <Space>m opens your MCP client in a vertical split
let g:mcp_client = get(g:, 'mcp_client', 'your-mcp-client')
nnoremap <Space>m :execute 'vertical terminal ++close' g:mcp_client<CR>

" reload files changed on disk, so edits made outside Vim show up live
set autoread
augroup mcp_autoread
  autocmd!
  autocmd FocusGained,BufEnter,CursorHold * silent! checktime
augroup END
if !exists('s:mcp_timer')
  let s:mcp_timer = timer_start(1000, {-> execute('silent! checktime')}, {'repeat': -1})
endif
```

Set `g:mcp_client` to the command that starts your client. The `autoread` part matters: some clients write files on disk instead of going through Vim; with it, those changes show up within a second — no need to close and reopen the file.

## Usage

### Client inside Vim

```sh
vim src/app.py
```

Press `Space m`. The client opens in a split. Vim exports `$VIM_SERVERNAME` to its terminals, so this client always drives *this* Vim, even with several Vims open. Move between panes with `Ctrl-w h` / `Ctrl-w l`; in the terminal pane press `Ctrl-w N` to scroll, `i` to type again.

### Client in another terminal

```sh
vim --servername VIM src/app.py     # terminal 1
# terminal 2: start your MCP client
```

### Example session

```
you:     what does the current vim buffer do?
client:  [read_buffer] It's a Flask app with two routes...

you:     I selected parse_args in vim, add type hints and a docstring
client:  [get_selection] [replace_lines 12-20] Done — lines 12-24 updated.

you:     open tests/test_app.py in vim and add a test for parse_args, then save
client:  [ex "edit tests/test_app.py"] [read_buffer] [replace_lines] [ex "w"]
```

Selections: select with `v`/`V`, press `Esc`, *then* ask (Vim only records the selection once you leave visual mode).

Edits appear live in Vim. They are **not saved** until you `:w` (or the client runs `w`), and you can undo them with `u`.

## Tools

| Tool | Description |
|---|---|
| `list_buffers` | Open buffers, with which is current / modified |
| `read_buffer` | A buffer's lines, prefixed with line numbers (`buffer`: number or name, default current) |
| `get_selection` | The last visual selection in the current buffer |
| `replace_lines` | Replace lines `start`..`end` (1-based, inclusive) with `text`, typed out live. `end = start-1` inserts; empty `text` deletes; optional `step` label is shown in a popup |
| `ex` | Run any Ex command (`w`, `edit foo.c`, `42`, `normal! gg=G`, …) and return its output |

## Which Vim?

Order: `$VIM_SERVER`, then `$VIM_SERVERNAME` (set automatically inside Vim's `:terminal`), then the first entry of `vim --serverlist`. To pin one, add it to the server config:

```json
"env": { "VIM_SERVER": "VIM" }
```

## Security

The `ex` tool can run any Ex command, including `:!shell commands`. Only connect clients you'd trust with a shell.

## License

MIT
