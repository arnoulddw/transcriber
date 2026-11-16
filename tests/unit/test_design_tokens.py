"""Guards the Lilac design language against drift (see DESIGN.md).

The design tokens live in tailwind.config.js and the shared components in
app/static/css/tailwind_input.css. These checks fail when templates, JS or the
component CSS reach around the tokens: off-palette colours, one-off colour,
type, radius or shadow values, or raw colour literals.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "tailwind.config.js"
COMPONENT_CSS = ROOT / "app/static/css/tailwind_input.css"
DESIGN_DOC = ROOT / "DESIGN.md"

# Tailwind default palettes that are NOT part of the design language.
BANNED_PALETTES = (
    "slate", "zinc", "neutral", "stone", "orange", "yellow", "lime", "emerald",
    "teal", "cyan", "sky", "blue", "indigo", "violet", "purple", "fuchsia",
    "pink", "rose",
)
COLOUR_UTILITIES = (
    "bg", "text", "border", "border-[trblxy]", "ring", "ring-offset", "divide",
    "from", "via", "to", "placeholder", "outline", "fill", "stroke",
    "decoration", "accent", "caret", "shadow",
)
OFF_PALETTE = re.compile(
    r"(?<![\w-])(?:[\w\[\]=:-]+:)?(?:%s)-(?:%s)-\d{2,3}\b"
    % ("|".join(COLOUR_UTILITIES), "|".join(BANNED_PALETTES))
)
# One-off values for design properties (colour, type size, tracking, radius, shadow).
# Layout one-offs (widths, heights, z-index, calc() heights) are allowed.
ONE_OFF_DESIGN_VALUE = re.compile(
    r"(?<![\w-])(?:[\w\[\]=:-]+:)?"
    r"(?:text|bg|border|border-[trblxy]|ring|shadow|tracking|leading|font|"
    r"rounded|rounded-[trbl]{1,2}|fill|stroke|outline|divide)-\[[^\]]+\]"
)


def _ui_sources():
    files = sorted((ROOT / "app/templates").rglob("*.html"))
    files += sorted((ROOT / "app/static/js").rglob("*.js"))
    # Email templates need inline styles for mail clients; they are not app UI.
    return [f for f in files if "templates/email" not in f.as_posix()]


def _violations(pattern, files):
    found = []
    for path in files:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in pattern.finditer(line):
                found.append(f"{path.relative_to(ROOT)}:{lineno}: {match.group(0)}")
    return found


def test_colour_palette_is_replaced_not_extended():
    config = CONFIG.read_text(encoding="utf-8")
    theme = config[config.index("theme: {"):]
    # The palette sits directly under theme (replacing Tailwind's defaults) ...
    assert theme.index("colors: {") < theme.index("extend: {")
    # ... and only the status ramps are pulled in from Tailwind's palette.
    pulled_in = set(re.findall(r"tailwindColors\.(\w+)", config))
    assert pulled_in == {"red", "green", "amber"}, pulled_in
    assert "primary: {" in config and "DEFAULT: '#5A2BD6'" in config


def test_templates_and_js_use_only_design_palette_colours():
    violations = _violations(OFF_PALETTE, _ui_sources() + [COMPONENT_CSS])
    assert not violations, "Off-palette colour classes (use tokens from tailwind.config.js):\n" + "\n".join(violations)


def test_templates_and_js_use_tokens_not_one_off_design_values():
    violations = _violations(ONE_OFF_DESIGN_VALUE, _ui_sources())
    assert not violations, "One-off design values (add or use a token instead):\n" + "\n".join(violations)


def test_component_css_uses_tokens_not_one_off_design_values():
    violations = _violations(ONE_OFF_DESIGN_VALUE, [COMPONENT_CSS])
    assert not violations, "One-off design values in tailwind_input.css:\n" + "\n".join(violations)


def test_component_css_has_no_raw_colour_literals():
    found = []
    for lineno, line in enumerate(COMPONENT_CSS.read_text(encoding="utf-8").splitlines(), 1):
        if 'url("data:' in line:
            continue  # SVG data URIs cannot read tokens; checked below
        for match in re.finditer(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", line):
            found.append(f"tailwind_input.css:{lineno}: {match.group(0)}")
    assert not found, "Raw colour literals (use theme('colors...')):\n" + "\n".join(found)


def test_dropdown_chevron_matches_primary_token():
    css = COMPONENT_CSS.read_text(encoding="utf-8")
    data_uri_colours = set(re.findall(r"stroke='%23([0-9A-Fa-f]{6})'", css))
    assert data_uri_colours == {"5A2BD6"}, data_uri_colours


def test_design_doc_lists_every_component_token_group():
    doc = DESIGN_DOC.read_text(encoding="utf-8")
    for heading in ("Colours", "Type", "Sizes", "Radii", "Shadows", "Components", "Rules"):
        assert f"## {heading}" in doc, heading
