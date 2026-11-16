# Compass design language ("Lilac")

The app has one design language. Its tokens live in `tailwind.config.js`, its shared components in `app/static/css/tailwind_input.css`, and `tests/unit/test_design_tokens.py` fails the build when code reaches around them. This page explains the tokens and the rules for using them.

After changing either file, rebuild the CSS with `npm run build:css:prod` and commit `app/static/css/tailwind_output.css`.

## Principles

- **Purple is an accent, never a surface.** `primary` marks things you can act on and the current state: buttons, selected chips, the active page, progress, links, focus and checkboxes. Backgrounds, fields and cards stay neutral.
- **Air over boxes.** Sections are separated by white space and type, not borders. Cards appear only where content needs grouping: saved workflows, admin panels and tables.
- **One component per job.** Use the shared classes below. Don't restyle an element one-off with utilities.
- **Tables keep their structure.** The admin tables keep their original markup. Only colours and the font come from the tokens.

## Colours

The palette replaces Tailwind's defaults rather than extending them, so `bg-blue-500`, `text-orange-600` and similar classes do not exist.

| Token | Value | Use |
|---|---|---|
| `primary` | `#5A2BD6` | Primary buttons, selected state, links, focus, progress |
| `primary-dark` | `#4920B5` | Hover on primary, text on `primary-soft` |
| `primary-soft` | `#F1ECFF` | Tonal fills: active nav item, workflow results, purpose tags, Live link |
| `primary-tint` | `#F6F3FF` | The one highlighted zone: the audio file drop zone |
| `primary-track` | `#EDE7FF` | Progress and meter tracks |
| `gray-50…950` | cool neutrals | Surfaces, borders, muted text |
| `surface`, `surface-muted` | `#FFFFFF`, `#F4F4F6` | Page and card background, grey fills (secondary buttons, tiles) |
| `border-default`, `border-strong` | `#ECEBF0`, `#DCDAE2` | Hairlines, outlined chips and panels |
| `text-strong`, `text-muted` | `#16121F`, `#6B6877` | Body text, secondary text |
| `danger`, `success`, `warning` | `#C2352B`, `#15803D`, `#B45309` | Status text and icons |
| `red-*`, `green-*`, `amber-*` | Tailwind ramps | Status backgrounds only (`bg-red-50`, `bg-green-50`, `bg-amber-50`) |
| `workflow-label-*` | pastels | User-chosen workflow label colours (data, not chrome) |

The dropdown chevron is an SVG data URI that can't read tokens. It hard-codes `#5A2BD6`, and a test checks that it matches `primary`.

## Type

Onest for everything. Icons use the Material Icons Outlined font (the same icon names as Material Icons).

| Token | Size | Use |
|---|---|---|
| `text-page` / `text-page-sm` | 32 / 26px | Page titles (`page-title`, `card-title`); 26px below `sm` |
| `text-modal` | 24px | Modal titles (`modal-title`) |
| `text-section` | 20px | Section headings (`section-heading`) |
| `text-group` | 17px | Group and card headings (`section-title`) |
| `text-hero` | 15px | Hero button, workflow panel titles |
| `text-sm` | 13.6px | Body and default controls |
| `text-nav` | 13.5px | Sidebar links |
| `text-control` | 13px | Labels, small buttons, chips |
| `text-badge` | 12.5px | Status badges |
| `text-xs` | 12px | Meta lines, hints, uppercase eyebrows (`eyebrow`) |
| `text-tag` | 11px | Purpose tags, avatar initials |
| `text-stat` / `text-pct` | 40 / 28px | Dashboard numbers, progress percentage |

Letter spacing tokens are `tracking-display`, `tracking-title`, `tracking-heading`, `tracking-snug`, `tracking-stat`, `tracking-live` and `tracking-caps`. Page, card and modal titles end with a purple full stop, added by CSS.

## Sizes

| Token | Value | Use |
|---|---|---|
| `control` | 42px | Default height of buttons **and** fields, so they line up side by side |
| `control-sm` | 34px | Small controls: chips, Stop, Choose File, Rows per page |
| `control-lg` | 50px | The single hero call to action (Transcribe) |
| `icon-btn` | 32px | Round icon buttons |
| `badge` | 26px | Status badges, label colour swatches |
| `btn` | 18px | Horizontal padding of default buttons |
| `modal` | 26px | Modal horizontal padding |
| `rail` | 72px | Collapsed admin sidebar |
| `max-w-page` | 52rem | Single-column app pages |

**Spacing:** 32px between page sections, 20px inside a section, 16px from a heading to its content.

## Radii

| Token | Value | Use |
|---|---|---|
| `rounded-full` | pill | All buttons, chips, badges, icon buttons |
| `rounded-field` | 12px | Inputs, selects, textareas, segmented controls, nav links |
| `rounded-segment` | 9px | The selected segment inside a segmented control |
| `rounded-card` | 16px | Cards, panels, tiles, the drop zone, history rows |
| `rounded-modal` | 22px | Modals and drawers |

Admin tables keep their own 8px `table-card` radius.

## Shadows

| Token | Use |
|---|---|
| `shadow-raised` / `shadow-raised-hover` | White fields and cards: a faint ring plus a soft shadow (the "raised" field style) |
| `shadow-focus` | The focus ring on fields (purple border plus soft purple ring) |
| `shadow-cta` | Under primary buttons |
| `shadow-menu` | Dropdown menus and toasts |
| `shadow-surface-xl` | Modals and drawers |
| `shadow-progress` | The outlined progress panel |

## Components

All of these live in `tailwind_input.css`.

- **Buttons:** `ui-btn` plus one of the following variants:
  - `ui-btn--primary`: solid purple. Use one per area for the main action.
  - `ui-btn--secondary` / `--muted`: grey fill, for Cancel, Close and other secondary actions.
  - `ui-btn--danger`: soft red, for destructive actions.
  - `ui-btn--link`: purple text.
  - `ui-btn--raised`: white, for use on tinted surfaces.

  Sizes: default, `ui-btn--sm` and `ui-btn--hero`. In templates, use the `ui.button()` macro; it always puts the icon before the label. `--success` is an alias of primary.
- **Icon buttons:** `icon-btn`, plus `icon-btn--danger` for destructive actions. For pins, add `pin-btn is-pinned` to get a filled purple pin.
- **Toggle chips:** `chip-toggle`. Add `is-active` (or `aria-pressed="true"`) for the selected state.
- **Fields:** `input-control`, `input-select`, `input-textarea` and `checkbox-control`, with labels as `form-label`, hints as `form-hint` and errors as `form-error`.
- **Segmented choice:** a `rounded-field bg-surface-muted p-1` track. The selected segment is white, `shadow-raised` and purple text (see "Use this model for").
- **Headings:**
  - `page-title` for an admin page `<h1>`.
  - `card-title` for app page sections, via the `form_layout.card()` macro.
  - `modal-title`.
  - `section-heading` for 20px sections, via the `form_layout.section()` macro.
  - `section-title` for 17px groups.
  - `eyebrow` for uppercase labels.

  Use `page-intro` for the sentence under an admin page title.
- **Surfaces:**
  - `raised-card` for a white raised card.
  - `table-card` for admin panels and tables.
  - `workflow-panel` for lilac generated output (add `is-error` for failures).
  - `progress-panel` for the outlined running state.
  - `audio-drop-zone`.
  - `stat-tile` (add `is-featured` for the purple tile).
- **Feedback:** `alert-info`, `alert-success`, `alert-warning`, `alert-danger`, plus the `badge-*` variants.
- **Modals:** use the `ui.modal_shell()` macro with `modal-header`, `modal-title`, `modal-close`, `modal-body` and `modal-footer`.
- **Navigation:** `admin-nav-link` (add `is-active` for the current page), and `pager` with `pager__item` (add `is-current` for the current page).

## Rules

1. **Use a token, or add one.** No one-off colour, font size, letter spacing, radius or shadow values (`text-[14px]`, `bg-[#…]`, `rounded-[7px]`) in templates, JS or component CSS. If something is missing, add a named token to `tailwind.config.js` and list it here. One-off layout values (widths, heights, `calc()`, z-index) are fine.
2. **No off-palette colours.** Only the colours above exist. For status, use `danger`, `success` or `warning` for text, and `red-50`, `green-50` or `amber-50` for backgrounds.
3. **One style per button level.** Primary is purple, secondary is grey, destructive is soft red. Two buttons at the same level never look different. Icons always come before the label.
4. **Buttons and fields share heights** (`control`, `control-sm`). Never size a button with padding alone.
5. **Purple stays an accent.** Don't fill inputs, dropdowns or page backgrounds with purple. The audio file zone (`primary-tint`) is the one deliberate exception, and workflow results (`primary-soft`) mark generated output.
6. **Sentence case.** Labels are sentence case. For legacy upper-case translations, wrap the label in `sentence-case` rather than changing the message ID.
7. **JS-rendered markup uses the same classes** as server-rendered markup: history items, workflow panels, key rows, saved workflows.
8. **Admin tables keep their structure.** Only colours and the font may change.

The mockups this language was built from are in `design-proposals/compass-lilac-screens.html`.
