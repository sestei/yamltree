# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

yamltree reads a YAML file describing a tree of nested "cards" (title, optional contacts, description) and serves it as a lightweight, navigable, **editable** web UI. The tree is laid out as fixed-width columns expanding left to right (Miller-columns / file-browser style): column 0 is the root, column 1 is always its children, and clicking a card with children opens the next column with elbow connector lines drawn from parent to child; clicking the same card again collapses everything to its right. Descriptions support Markdown. Dark theme by default (no light mode). Every non-root card has an action row (move up/down, edit, insert sibling/child, archive) that mutates `main.yaml` directly through `ruamel.yaml`, preserving the user's formatting/comments. It's a small Flask app with server-computed data and a vanilla-JS frontend that owns all DOM rendering — no frontend framework, no build step.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py            # serves http://127.0.0.1:5100, debug=True (auto-restarts on .py changes)
```

There is no test suite, linter, or build step yet.

To point the app at a different data file: `YAMLTREE_FILE=/path/to/other.yaml python app.py`.

## Architecture

- **`app.py`** — the entire backend. On every `GET /` request it re-reads and re-parses `main.yaml` from disk (no caching) — this is intentional and is what makes hand-edits to the YAML show up without restarting the server. `process_card()` walks the parsed tree recursively (post-order) and, per card: renders `description` to `description_html` via the `markdown` package, parses `status` into `trl` (int or `None`) / `trl_color` (precomputed hex, dark red→dark green via HSL interpolation in `trl_color()`) / `important` (bool), and sets `has_important` to whether *this card or any descendant* is important. It also stamps `card["_path"]` (a list of subcard indices from the root) as it recurses — see "Editing / writes" below.
- **Malformed YAML never 500s.** `YAMLError` (from `ruamel.yaml`) is caught in the `/` route and routed to `render_error()`, which pulls `problem_mark.line`/`.column` off the exception plus the raw offending line from the file, and renders `templates/error.html` with a normal 200. The polling script (below) runs on the error page too, so fixing the file recovers automatically.
- **`GET /api/mtime`** returns the YAML file's mtime as JSON. `static/script.js` polls this every 2s and compares it against the mtime embedded in `<body data-mtime>` at render time; on a mismatch it saves the current selection (see below) and does `location.reload()`. This is the live-reload mechanism — no websockets/SSE.
- **Data handoff, not server-side rendering of the tree**: `templates/index.html` embeds the whole parsed+markdown-converted tree as JSON via Jinja's `tojson` filter (`window.__TREE_DATA__ = {{ root | tojson }}`). `static/script.js` does 100% of the DOM building from that object — there is no `templates/card.html` or recursive Jinja macro. `templates/error.html` has no tree data, and `script.js` no-ops its render step (`if (!treeData) return;`) but still runs the mtime poll on that page.
- **Column layout (`static/script.js`)**: `path` is an array where `path[d - 1]` is the selected card in column `d` (columns are 1-indexed; column 0 is always just the root, which has no selection state of its own — its children column is unconditionally rendered). `render()` walks `path` to decide how many columns to draw and which card in each is highlighted; `selectAt(depth, card)` toggles selection at that depth (clicking the already-selected card truncates `path` back to collapse everything after it, clicking a different card replaces the tail of `path`). Each rebuild calls `drawConnectors()`, which measures rendered `.card` positions with `getBoundingClientRect()` and draws right-angle (elbow) SVG paths from the selected card in column *i* to every card in column *i + 1* — column 0→1 is a special case since the root has no `.selected` class but still always connects to its children.

### Editing / writes

- **YAML I/O is `ruamel.yaml` in round-trip mode** (`yaml_rt = YAML()` in `app.py`), used for both the display path and every mutation — this is what lets hand-added comments/formatting in `main.yaml` survive a save from the UI (see `load_document()`/`save_document()`). Edited field values are re-serialized in ruamel's default style, but multi-line `description` values are wrapped in `FoldedScalarString` before saving so they still come out as a `>` block like the rest of the file, not a quoted one-liner.
- **Addressing a card**: every card in the embedded JSON carries `_path` (stamped by `process_card`), a list of subcard indices from the root (`[]` = root, `[1, 0]` = `root.subcards[1].subcards[0]`). The frontend never computes indices itself — it just reads `card._path`. All mutation endpoints take a `path` in the POST body and resolve it with `resolve_path(doc, path)` in `app.py`, which returns `(parent_subcards_list, index, node)`.
- **Four POST routes** in `app.py`, each `load_document() → mutate the ruamel doc in place → save_document()`: `/api/cards/move` (swap with sibling), `/api/cards/edit` (overwrite title/description/contacts/status; empty `contacts`/`status`/`description` are deleted from the node rather than saved as empty), `/api/cards/insert` (`kind: "sibling"` inserts right after `path` in its parent list; `kind: "child"` only succeeds if the target has no `subcards` yet — once it does, further children go through that child column's own "insert sibling" instead, which is why the "+ Child" button disappears after the first child), `/api/cards/archive` (pops the card's whole subtree out of its parent list and appends it to a top-level `archive` list living on the *document root*, sibling to `title`/`subcards`). The root card (`path == []`) can't be moved, inserted-as-sibling, or archived — there's no parent list for it.
- **`root.archive` is never rendered.** `static/script.js` only ever walks `treeData.subcards`, so archived subtrees are invisible in the UI but sit right there in `main.yaml` as plain YAML for the user to cut back into a `subcards:` list by hand — there is deliberately no "unarchive" button.
- **Selection persists across every reload a mutation causes** (and across the mtime-poll's reload too, via `window.__yamltreeSaveSelection`), using `sessionStorage`: before reloading, the current `path` selection's `_path` values are saved (`yamltree.selection`); on load they're replayed against the fresh tree, stopping early if something no longer resolves (e.g. it was archived). Move/insert/edit responses carry the affected card's own `path`, which is used to build an explicit focus chain instead (so the action always ends up looking at the card you just touched, not just "wherever you were before"). A fresh insert also sets a one-shot `yamltree.editAfter` flag so the new card opens straight into its edit form.
- **The edit form is client-side only until Save** (`buildEditForm()` in `static/script.js`): title input, TRL 1–9 picker + ★ toggle, a contacts editor that always keeps one trailing blank row (typing a name into the last row grows another blank one after it), and a description textarea holding the raw Markdown (`card.description`, not `description_html`). Cancel just clears local state and re-renders — no server round trip; only Save POSTs to `/api/cards/edit`.

## Data format (`main.yaml`)

Each card node: `title` (required), `description` (optional, Markdown), `contacts` (optional list of `{name, email?, institution?}`), `subcards` (optional list of child card nodes, same shape, recursively — tree can go ~6 levels deep), `status` (optional — see below).

`status` accepts a YAML list (`status: [trl5, important]`) or a plain string, which `parse_status_tokens()` in `app.py` splits on commas/whitespace (`status: trl5, important` and `status: important trl5` both work), case-insensitively. Recognized tokens:
- `trl1`..`trl9` — sets the card's outline color on a dark-red-to-dark-green gradient (`trl_color()` in `app.py`). Anything not matching `^trl[1-9]$` exactly (`trl0`, `trl10`, typos) is silently ignored, not an error.
- `important` — gives the card itself a strong `--important`-colored highlight (`.card.important` in `static/style.css`, plus a ★ badge in the header). Every ancestor of an important card gets a subtle `--important`-colored inset border glow only, no background tint or badge (`.card.important-descendant`), driven by the `has_important` flag `process_card()` computes — this applies tree-wide, not just to currently-expanded columns, so a collapsed ancestor still hints that something important is nested below it.

A card can have both a TRL level and `important` at once; the TRL color still applies to the border while the `--important`-colored tint/badge layers on top (see the CSS rules keyed off `.card.important` / `.card.has-trl` / `.card.selected` in `static/style.css` — selection is deliberately a `box-shadow` ring rather than a border-color change, so it never fights with the TRL border color).

The document root additionally has one reserved key not present on any other card: `archive` (a list of card subtrees, same shape as `subcards`) — see "Editing / writes" above.

