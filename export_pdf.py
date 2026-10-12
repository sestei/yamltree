#!/usr/bin/env python3
"""Render the yamltree card tree to a printable PDF.

Standalone script, not wired into the Flask app. Lays the tree out
itself (not via Graphviz) and draws strictly horizontal/vertical
connectors in the classic org-chart style: a single trunk line leaves
the parent, meets a bus line, and the bus fans out into one drop per
child. Each card is styled like the web UI's cards (TRL border/fill
colors, important star + highlight) but on a white background.

Usage:
    python3 export_pdf.py [path/to/main.yaml] [-o output.pdf]
    python3 export_pdf.py --direction TB   # root on top, growing down
    python3 export_pdf.py --direction LR   # root on the left, growing right (default)

Requires the `reportlab` pip package (no system/binary dependency).
"""

import argparse
import colorsys
import os
import re

from reportlab.lib.colors import HexColor
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from ruamel.yaml import YAML

from app import TRL_RE, parse_status_tokens

BOX_WIDTH = 190
PAD = 8
TITLE_FONT = "Helvetica-Bold"
BODY_FONT = "Helvetica"
TITLE_SIZE = 11
BODY_SIZE = 8
TITLE_LEADING = 14
BODY_LEADING = 11
SIBLING_GAP = 22
DEPTH_GAP = 56
TRUNK_LENGTH = 20
MARGIN = 40
EDGE_COLOR = "#777777"
BORDER_DEFAULT = "#999999"
IMPORTANT_FILL = "#fff7cc"
IMPORTANT_STAR_COLOR = "#b8860b"
BADGE_FONT = "Helvetica-Bold"
BADGE_SIZE = 7
BADGE_HEIGHT = 13
BADGE_PAD_X = 6


def _hex(r, g, b):
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def trl_hue(trl):
    return (trl - 1) / 8.0 * 120.0 / 360.0


def trl_border_color(trl):
    """TRL border color tuned for a white page: bold and saturated."""
    return _hex(*colorsys.hls_to_rgb(trl_hue(trl), 0.28, 0.95))


def trl_fill_color(trl):
    """Light tint of the same hue, used as the card's background."""
    return _hex(*colorsys.hls_to_rgb(trl_hue(trl), 0.93, 0.75))


def markdown_to_plain(text):
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def card_status(card):
    trl = None
    important = False
    for token in parse_status_tokens(card.get("status")):
        match = TRL_RE.match(token)
        if match:
            trl = int(match.group(1))
        elif token == "important":
            important = True
    return trl, important


def wrap_to_width(text, font, size, max_width):
    words = text.split()
    lines = []
    cur = ""
    for word in words:
        trial = (cur + " " + word).strip()
        if stringWidth(trial, font, size) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def format_contact_plain(contact):
    parts = [contact.get("name", "")]
    extra = [v for v in (contact.get("email"), contact.get("institution")) if v]
    if extra:
        parts.append("(" + ", ".join(extra) + ")")
    return " ".join(parts)


class Box:
    def __init__(self, card, depth):
        self.card = card
        self.depth = depth
        self.children = []
        # `primary` = position along the axis siblings are spread on
        # (center-aligned); `secondary` = position along the depth axis
        # (start-aligned). Which screen axis each maps to depends on
        # `direction` and is resolved only when drawing.
        self.primary = 0.0
        self.secondary = 0.0
        self.height = 0.0
        self.trl = None
        self.effective_trl = None
        self.trl_inherited = False
        self.important = False
        self.title_lines = []
        self.contact_lines = []
        self.desc_lines = []

    def compute_content(self):
        self.trl, self.important = card_status(self.card)
        title = self.card.get("title") or "Untitled"
        star = " ★" if self.important else ""
        avail = BOX_WIDTH - 2 * PAD

        self.title_lines = wrap_to_width(title + star, TITLE_FONT, TITLE_SIZE, avail)

        for contact in self.card.get("contacts") or []:
            self.contact_lines.extend(
                wrap_to_width(format_contact_plain(contact), BODY_FONT, BODY_SIZE, avail)
            )

        description = self.card.get("description")
        if description:
            for para in markdown_to_plain(description).split("\n\n"):
                para = " ".join(para.split())
                if para:
                    self.desc_lines.extend(wrap_to_width(para, BODY_FONT, BODY_SIZE, avail))

    def compute_height(self):
        height = PAD * 2 + len(self.title_lines) * TITLE_LEADING
        if self.effective_trl:
            height += 2 + BADGE_HEIGHT + 4
        if self.contact_lines:
            height += 6 + len(self.contact_lines) * BODY_LEADING
        if self.desc_lines:
            height += 6 + len(self.desc_lines) * BODY_LEADING
        self.height = height


def build_tree(card, depth=0):
    box = Box(card, depth)
    box.compute_content()
    for child in card.get("subcards") or []:
        box.children.append(build_tree(child, depth + 1))
    return box


def resolve_trl_inheritance(box):
    """A card without its own TRL inherits the lowest (least mature)
    effective TRL among its children, recursively. Inherited values are
    flagged so the badge can be marked as derived rather than explicit."""
    for child in box.children:
        resolve_trl_inheritance(child)

    if box.trl is not None:
        box.effective_trl = box.trl
        box.trl_inherited = False
    else:
        child_trls = [c.effective_trl for c in box.children if c.effective_trl is not None]
        if child_trls:
            box.effective_trl = min(child_trls)
            box.trl_inherited = True

    box.compute_height()


def assign_primary(box, counter, direction):
    """Position siblings along the spread axis: fixed box width when
    stacking left-to-right (TB), actual box height when stacking
    top-to-bottom (LR)."""
    size = BOX_WIDTH if direction == "TB" else box.height
    if not box.children:
        box.primary = counter[0] + size / 2
        counter[0] += size + SIBLING_GAP
    else:
        for child in box.children:
            assign_primary(child, counter, direction)
        box.primary = (box.children[0].primary + box.children[-1].primary) / 2


def assign_secondary(box, direction):
    """Position depth levels along the other axis: TB uses per-row max
    card height (rows of varying-height cards, top-aligned); LR uses a
    fixed column width (every card is BOX_WIDTH wide)."""
    if direction == "TB":
        row_heights = {}

        def collect(b):
            row_heights[b.depth] = max(row_heights.get(b.depth, 0), b.height)
            for c in b.children:
                collect(c)

        collect(box)
        row_top = {}
        offset = 0.0
        for depth in sorted(row_heights):
            row_top[depth] = offset
            offset += row_heights[depth] + DEPTH_GAP
        total = offset - DEPTH_GAP

        def assign(b):
            b.secondary = row_top[b.depth]
            for c in b.children:
                assign(c)

        assign(box)
        return total
    else:
        max_depth = [0]

        def find_max(b):
            max_depth[0] = max(max_depth[0], b.depth)
            for c in b.children:
                find_max(c)

        find_max(box)

        def assign(b):
            b.secondary = b.depth * (BOX_WIDTH + DEPTH_GAP)
            for c in b.children:
                assign(c)

        assign(box)
        return max_depth[0] * (BOX_WIDTH + DEPTH_GAP) + BOX_WIDTH


def box_rect(box, direction, page_width, page_height):
    """Return (x_left, y_bottom) for this box's rectangle."""
    if direction == "TB":
        x_left = MARGIN + box.primary - BOX_WIDTH / 2
        y_top = page_height - MARGIN - box.secondary
        y_bottom = y_top - box.height
    else:
        x_left = MARGIN + box.secondary
        y_center = page_height - MARGIN - box.primary
        y_bottom = y_center - box.height / 2
    return x_left, y_bottom


def draw_box(c, box, direction, page_width, page_height):
    x_left, y_bottom = box_rect(box, direction, page_width, page_height)
    y_top = y_bottom + box.height

    border = trl_border_color(box.trl) if box.trl else BORDER_DEFAULT
    fill = trl_fill_color(box.trl) if box.trl else "#ffffff"

    c.setFillColor(HexColor(fill))
    c.rect(x_left, y_bottom, BOX_WIDTH, box.height, fill=1, stroke=0)

    if box.important:
        header_h = PAD + len(box.title_lines) * TITLE_LEADING
        c.setFillColor(HexColor(IMPORTANT_FILL))
        c.rect(x_left, y_top - header_h, BOX_WIDTH, header_h, fill=1, stroke=0)

    c.setStrokeColor(HexColor(border))
    c.setLineWidth(1.6)
    c.rect(x_left, y_bottom, BOX_WIDTH, box.height, fill=0, stroke=1)

    text_y = y_top - PAD
    c.setFont(TITLE_FONT, TITLE_SIZE)
    c.setFillColor(HexColor(IMPORTANT_STAR_COLOR if box.important else "#111111"))
    for line in box.title_lines:
        c.drawString(x_left + PAD, text_y - TITLE_SIZE * 0.85, line)
        text_y -= TITLE_LEADING
    if box.important:
        c.setFillColor(HexColor("#111111"))

    if box.effective_trl:
        text_y -= 2
        badge_color = trl_border_color(box.effective_trl)
        badge_text = "TRL{}".format(box.effective_trl)
        if box.trl_inherited:
            badge_text += " ✦"
        badge_w = stringWidth(badge_text, BADGE_FONT, BADGE_SIZE) + 2 * BADGE_PAD_X
        badge_bottom = text_y - BADGE_HEIGHT
        if box.trl_inherited:
            # Hollow pill for an inherited (derived, not explicitly set) TRL.
            c.setFillColor(HexColor("#ffffff"))
            c.setStrokeColor(HexColor(badge_color))
            c.setLineWidth(1)
            c.roundRect(x_left + PAD, badge_bottom, badge_w, BADGE_HEIGHT, 3, fill=1, stroke=1)
            c.setFillColor(HexColor(badge_color))
        else:
            c.setFillColor(HexColor(badge_color))
            c.roundRect(x_left + PAD, badge_bottom, badge_w, BADGE_HEIGHT, 3, fill=1, stroke=0)
            c.setFillColor(HexColor("#ffffff"))
        c.setFont(BADGE_FONT, BADGE_SIZE)
        c.drawCentredString(
            x_left + PAD + badge_w / 2, badge_bottom + BADGE_HEIGHT / 2 - BADGE_SIZE * 0.35, badge_text
        )
        text_y = badge_bottom - 4

    if box.contact_lines:
        text_y -= 6
        c.setFont(BODY_FONT, BODY_SIZE)
        c.setFillColor(HexColor("#555555"))
        for line in box.contact_lines:
            c.drawString(x_left + PAD, text_y, line)
            text_y -= BODY_LEADING

    if box.desc_lines:
        text_y -= 6
        c.setFont(BODY_FONT, BODY_SIZE)
        c.setFillColor(HexColor("#333333"))
        for line in box.desc_lines:
            c.drawString(x_left + PAD, text_y, line)
            text_y -= BODY_LEADING

    for child in box.children:
        draw_box(c, child, direction, page_width, page_height)


def draw_connectors(c, box, direction, page_width, page_height):
    if not box.children:
        return

    c.setStrokeColor(HexColor(EDGE_COLOR))
    c.setLineWidth(1.2)

    if direction == "TB":
        x_left, y_bottom = box_rect(box, direction, page_width, page_height)
        parent_x = x_left + BOX_WIDTH / 2
        bus_y = y_bottom - TRUNK_LENGTH
        first_x = MARGIN + box.children[0].primary
        last_x = MARGIN + box.children[-1].primary

        c.line(parent_x, y_bottom, parent_x, bus_y)
        if last_x != first_x:
            c.line(first_x, bus_y, last_x, bus_y)
        for child in box.children:
            child_x = MARGIN + child.primary
            _, child_y_bottom = box_rect(child, direction, page_width, page_height)
            child_top = child_y_bottom + child.height
            c.line(child_x, bus_y, child_x, child_top)
    else:
        x_left, y_bottom = box_rect(box, direction, page_width, page_height)
        parent_right = x_left + BOX_WIDTH
        parent_y = y_bottom + box.height / 2
        bus_x = parent_right + TRUNK_LENGTH
        first_y = page_height - MARGIN - box.children[0].primary
        last_y = page_height - MARGIN - box.children[-1].primary

        c.line(parent_right, parent_y, bus_x, parent_y)
        if last_y != first_y:
            c.line(bus_x, first_y, bus_x, last_y)
        for child in box.children:
            child_y = page_height - MARGIN - child.primary
            child_left, _ = box_rect(child, direction, page_width, page_height)
            c.line(bus_x, child_y, child_left, child_y)

    for child in box.children:
        draw_connectors(c, child, direction, page_width, page_height)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "yaml_file",
        nargs="?",
        default=os.path.join(os.path.dirname(__file__), "main.yaml"),
        help="path to the yamltree YAML file (default: main.yaml)",
    )
    parser.add_argument("-o", "--output", help="output PDF path (default: <yaml name>.pdf)")
    parser.add_argument(
        "--direction",
        choices=["TB", "LR"],
        default="LR",
        help="LR: root on the left, growing right (default). TB: root on top, growing down.",
    )
    args = parser.parse_args()

    yaml = YAML(typ="safe")
    with open(args.yaml_file) as f:
        root_card = yaml.load(f)

    root = build_tree(root_card)
    resolve_trl_inheritance(root)

    counter = [0.0]
    assign_primary(root, counter, args.direction)
    primary_extent = max(counter[0] - SIBLING_GAP, BOX_WIDTH if args.direction == "TB" else root.height)

    secondary_extent = assign_secondary(root, args.direction)

    if args.direction == "TB":
        page_width = primary_extent + 2 * MARGIN
        page_height = secondary_extent + 2 * MARGIN
    else:
        page_width = secondary_extent + 2 * MARGIN
        page_height = primary_extent + 2 * MARGIN

    output = args.output or os.path.splitext(args.yaml_file)[0] + ".pdf"
    c = canvas.Canvas(output, pagesize=(page_width, page_height))
    c.setFillColor(HexColor("#ffffff"))
    c.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    draw_connectors(c, root, args.direction, page_width, page_height)
    draw_box(c, root, args.direction, page_width, page_height)

    c.save()
    print("Wrote {}".format(output))


if __name__ == "__main__":
    main()
