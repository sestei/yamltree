# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

yamltree reads a YAML file describing a tree of nested "cards" (title, optional contacts, description) and serves it as a lightweight, navigable web UI. The tree is laid out as fixed-width columns expanding left to right (Miller-columns / file-browser style): column 0 is the root, column 1 is always its children, and clicking a card with children opens the next column with elbow connector lines drawn from parent to child; clicking the same card again collapses everything to its right. Descriptions support Markdown. Dark theme by default (no light mode). It's a small Flask app with server-computed data and a vanilla-JS frontend that owns all DOM rendering — no frontend framework, no build step.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py            # serves http://127.0.0.1:5100, debug=True (auto-restarts on .py changes)
```

There is no test suite, linter, or build step yet.

To point the app at a different data file: `YAMLTREE_FILE=/path/to/other.yaml python app.py`.

## Architecture

- **`app.py`** — the entire backend. On every `GET /` request it re-reads and re-parses `main.yaml` from disk (no caching) — this is intentional and is what makes hand-edits to the YAML show up without restarting the server. `process_card()` walks the parsed tree recursively (post-order) and, per card: renders `description` to `description_html` via the `markdown` package, parses `status` into `trl` (int or `None`) / `trl_color` (precomputed hex, dark red→dark green via HSL interpolation in `trl_color()`) / `important` (bool), and sets `has_important` to whether *this card or any descendant* is important — that aggregate is what lets ancestor cards get a highlight even before you've drilled down to the important one. All of this is computed server-side so `static/script.js` never needs tree-wide knowledge, just the per-card fields already sitting on the JSON.
- **Malformed YAML never 500s.** `yaml.YAMLError` is caught in the `/` route and routed to `render_error()`, which pulls `problem_mark.line`/`.column` off the exception plus the raw offending line from the file, and renders `templates/error.html` with a normal 200. The polling script (below) runs on the error page too, so fixing the file recovers automatically.
- **`GET /api/mtime`** returns the YAML file's mtime as JSON. `static/script.js` polls this every 2s and compares it against the mtime embedded in `<body data-mtime>` at render time; on a mismatch it does `location.reload()`. This is the live-reload mechanism — no websockets/SSE.
- **Data handoff, not server-side rendering of the tree**: `templates/index.html` embeds the whole parsed+markdown-converted tree as JSON via Jinja's `tojson` filter (`window.__TREE_DATA__ = {{ root | tojson }}`). `static/script.js` does 100% of the DOM building from that object — there is no `templates/card.html` or recursive Jinja macro. `templates/error.html` has no tree data, and `script.js` no-ops its render step (`if (!treeData) return;`) but still runs the mtime poll on that page.
- **Column layout (`static/script.js`)**: `path` is an array where `path[d - 1]` is the selected card in column `d` (columns are 1-indexed; column 0 is always just the root, which has no selection state of its own — its children column is unconditionally rendered). `render()` walks `path` to decide how many columns to draw and which card in each is highlighted; `selectAt(depth, card)` toggles selection at that depth (clicking the already-selected card truncates `path` back to collapse everything after it, clicking a different card replaces the tail of `path`). Each rebuild calls `drawConnectors()`, which measures rendered `.card` positions with `getBoundingClientRect()` and draws right-angle (elbow) SVG paths from the selected card in column *i* to every card in column *i + 1* — column 0→1 is a special case since the root has no `.selected` class but still always connects to its children.

## Data format (`main.yaml`)

Each card node: `title` (required), `description` (optional, Markdown), `contacts` (optional list of `{name, email?, institution?}`), `subcards` (optional list of child card nodes, same shape, recursively — tree can go ~6 levels deep), `status` (optional — see below).

`status` accepts a YAML list (`status: [trl5, important]`) or a plain string, which `parse_status_tokens()` in `app.py` splits on commas/whitespace (`status: trl5, important` and `status: important trl5` both work), case-insensitively. Recognized tokens:
- `trl1`..`trl9` — sets the card's outline color on a dark-red-to-dark-green gradient (`trl_color()` in `app.py`). Anything not matching `^trl[1-9]$` exactly (`trl0`, `trl10`, typos) is silently ignored, not an error.
- `important` — gives the card itself a strong gold highlight (`.card.important` in `static/style.css`, plus a ★ badge in the header). Every ancestor of an important card gets a subtle gold inset border glow only, no background tint or badge (`.card.important-descendant`), driven by the `has_important` flag `process_card()` computes — this applies tree-wide, not just to currently-expanded columns, so a collapsed ancestor still hints that something important is nested below it.

A card can have both a TRL level and `important` at once; the TRL color still applies to the border while the gold tint/badge layers on top (see the CSS rules keyed off `.card.important` / `.card.has-trl` / `.card.selected` in `static/style.css` — selection is deliberately a `box-shadow` ring rather than a border-color change, so it never fights with the TRL border color).

## Known extension point

There's no editing UI yet — the YAML file is hand-edited externally. If in-browser editing is added later, the plan (see `~/.claude/plans/yamltree-should-read-the-serialized-pony.md`) is to add `POST` endpoints to `app.py` and switch from `PyYAML` to `ruamel.yaml` for round-tripping so comments/formatting in `main.yaml` survive a save.
