import colorsys
import os
import re
import time

import markdown
from flask import Flask, jsonify, render_template, request
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from ruamel.yaml.scalarstring import FoldedScalarString

app = Flask(__name__)

YAML_FILE = os.environ.get("YAMLTREE_FILE", os.path.join(os.path.dirname(__file__), "main.yaml"))

TRL_RE = re.compile(r"^trl([1-9])$")

yaml_rt = YAML()
yaml_rt.preserve_quotes = True


def parse_status_tokens(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        tokens = [str(t) for t in raw]
    else:
        tokens = re.split(r"[,\s]+", str(raw).strip())
    return [t.lower() for t in tokens if t]


def encode_status(trl, important):
    tokens = []
    if trl:
        tokens.append("trl{}".format(int(trl)))
    if important:
        tokens.append("important")
    return " ".join(tokens) if tokens else None


def trl_color(trl):
    hue = (trl - 1) / 8.0 * 120.0 / 360.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.34, 0.55)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def to_plain(node):
    """Recursively convert ruamel's CommentedMap/CommentedSeq into plain dict/list."""
    if isinstance(node, dict):
        return {k: to_plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [to_plain(v) for v in node]
    return node


def process_card(card, path=None):
    """Convert descriptions to HTML, parse `status` into trl/important flags,
    stamp each card with its `_path` (index list from the root), and return
    whether this card or any descendant is marked important."""
    path = path if path is not None else []
    card["_path"] = list(path)

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
    for i, sub in enumerate(card.get("subcards", [])):
        if process_card(sub, path + [i]):
            has_important = True
    card["has_important"] = has_important

    return has_important


def load_document():
    with open(YAML_FILE, "r") as f:
        return yaml_rt.load(f)


def save_document(doc):
    with open(YAML_FILE, "w") as f:
        yaml_rt.dump(doc, f)


def resolve_path(doc, path):
    """Return (parent_subcards_list_or_None, index_or_None, node) for `path`
    (a list of subcard indices from the root). path == [] refers to the root
    card itself, in which case there is no parent list."""
    node = doc
    parent_list = None
    index = None
    for i in path:
        parent_list = node["subcards"]
        index = i
        node = parent_list[i]
    return parent_list, index, node


@app.route("/")
def index():
    try:
        with open(YAML_FILE, "r") as f:
            root = yaml_rt.load(f)
    except YAMLError as exc:
        return render_error(exc, YAML_FILE)

    process_card(root)
    mtime = os.path.getmtime(YAML_FILE)
    return render_template("index.html", root=to_plain(root), mtime=mtime)


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


@app.route("/api/cards/move", methods=["POST"])
def api_move_card():
    body = request.get_json(silent=True) or {}
    path = body.get("path") or []
    direction = body.get("direction")

    if not path:
        return jsonify(error="cannot move the root card"), 400

    doc = load_document()
    try:
        parent_list, index, _ = resolve_path(doc, path)
    except (KeyError, IndexError, TypeError):
        return jsonify(error="card not found"), 404

    new_index = index - 1 if direction == "up" else index + 1
    if not (0 <= new_index < len(parent_list)):
        return jsonify(error="already at that end"), 400

    parent_list.insert(new_index, parent_list.pop(index))
    save_document(doc)
    return jsonify(ok=True, path=path[:-1] + [new_index])


@app.route("/api/cards/edit", methods=["POST"])
def api_edit_card():
    body = request.get_json(silent=True) or {}
    path = body.get("path") or []

    doc = load_document()
    try:
        _, _, node = resolve_path(doc, path)
    except (KeyError, IndexError, TypeError):
        return jsonify(error="card not found"), 404

    node["title"] = (body.get("title") or "").strip() or "Untitled"

    description = body.get("description") or ""
    if description.strip():
        node["description"] = FoldedScalarString(description) if "\n" in description else description
    elif "description" in node:
        del node["description"]

    contacts = []
    for raw_contact in body.get("contacts") or []:
        name = (raw_contact.get("name") or "").strip()
        if not name:
            continue
        contact = {"name": name}
        email = (raw_contact.get("email") or "").strip()
        institution = (raw_contact.get("institution") or "").strip()
        if email:
            contact["email"] = email
        if institution:
            contact["institution"] = institution
        contacts.append(contact)
    if contacts:
        node["contacts"] = contacts
    elif "contacts" in node:
        del node["contacts"]

    status = encode_status(body.get("trl"), bool(body.get("important")))
    if status:
        node["status"] = status
    elif "status" in node:
        del node["status"]

    save_document(doc)
    return jsonify(ok=True, path=path)


@app.route("/api/cards/insert", methods=["POST"])
def api_insert_card():
    body = request.get_json(silent=True) or {}
    path = body.get("path") or []
    kind = body.get("kind")

    doc = load_document()
    try:
        parent_list, index, node = resolve_path(doc, path)
    except (KeyError, IndexError, TypeError):
        return jsonify(error="card not found"), 404

    new_card = {"title": "New Card", "description": "Add a description."}

    if kind == "child":
        if node.get("subcards"):
            return jsonify(error="card already has children"), 400
        node["subcards"] = [new_card]
        new_path = path + [0]
    elif kind == "sibling":
        if parent_list is None:
            return jsonify(error="the root card has no siblings"), 400
        parent_list.insert(index + 1, new_card)
        new_path = path[:-1] + [index + 1]
    else:
        return jsonify(error="invalid kind"), 400

    save_document(doc)
    return jsonify(ok=True, path=new_path)


@app.route("/api/cards/archive", methods=["POST"])
def api_archive_card():
    body = request.get_json(silent=True) or {}
    path = body.get("path") or []

    if not path:
        return jsonify(error="cannot archive the root card"), 400

    doc = load_document()
    try:
        parent_list, index, _ = resolve_path(doc, path)
    except (KeyError, IndexError, TypeError):
        return jsonify(error="card not found"), 404

    card = parent_list.pop(index)
    archive = doc.get("archive")
    if archive is None:
        archive = []
        doc["archive"] = archive
    archive.append(card)

    save_document(doc)
    return jsonify(ok=True)


@app.route("/api/cards/delete", methods=["POST"])
def api_delete_card():
    """Permanently remove a card (no archive). Used to discard a freshly
    inserted card that was cancelled before ever being saved."""
    body = request.get_json(silent=True) or {}
    path = body.get("path") or []

    if not path:
        return jsonify(error="cannot delete the root card"), 400

    doc = load_document()
    try:
        parent_list, index, _ = resolve_path(doc, path)
    except (KeyError, IndexError, TypeError):
        return jsonify(error="card not found"), 404

    parent_list.pop(index)
    save_document(doc)
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(debug=True, port=5100)
