import colorsys
import os
import re
import time

import markdown
import yaml
from flask import Flask, jsonify, render_template

app = Flask(__name__)

YAML_FILE = os.environ.get("YAMLTREE_FILE", os.path.join(os.path.dirname(__file__), "main.yaml"))

TRL_RE = re.compile(r"^trl([1-9])$")


def parse_status_tokens(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        tokens = [str(t) for t in raw]
    else:
        tokens = re.split(r"[,\s]+", str(raw).strip())
    return [t.lower() for t in tokens if t]


def trl_color(trl):
    hue = (trl - 1) / 8.0 * 120.0 / 360.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.34, 0.55)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def process_card(card):
    """Convert descriptions to HTML, parse `status` into trl/important flags,
    and return whether this card or any descendant is marked important."""
    if "description" in card:
        card["description_html"] = markdown.markdown(card["description"])

    trl = None
    important = False
    for token in parse_status_tokens(card.get("status")):
        match = TRL_RE.match(token)
        if match:
            trl = int(match.group(1))
        elif token == "important":
            important = True

    card["trl"] = trl
    card["trl_color"] = trl_color(trl) if trl else None
    card["important"] = important

    has_important = important
    for sub in card.get("subcards", []):
        if process_card(sub):
            has_important = True
    card["has_important"] = has_important

    return has_important


@app.route("/")
def index():
    try:
        with open(YAML_FILE, "r") as f:
            raw_text = f.read()
        root = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        return render_error(exc, YAML_FILE)

    process_card(root)
    mtime = os.path.getmtime(YAML_FILE)
    return render_template("index.html", root=root, mtime=mtime)


def render_error(exc, path):
    line = None
    column = None
    snippet = None
    mark = getattr(exc, "problem_mark", None)
    if mark is not None:
        line = mark.line + 1
        column = mark.column + 1
        try:
            with open(path, "r") as f:
                lines = f.readlines()
            if 0 <= mark.line < len(lines):
                snippet = lines[mark.line].rstrip("\n")
        except OSError:
            snippet = None

    mtime = os.path.getmtime(path) if os.path.exists(path) else time.time()
    return render_template(
        "error.html",
        message=str(exc),
        line=line,
        column=column,
        snippet=snippet,
        mtime=mtime,
    )


@app.route("/api/mtime")
def api_mtime():
    try:
        mtime = os.path.getmtime(YAML_FILE)
    except OSError:
        mtime = time.time()
    return jsonify({"mtime": mtime})


if __name__ == "__main__":
    app.run(debug=True, port=5100)
