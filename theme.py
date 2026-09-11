"""
theme.py
========

Every color, size and font in the app is defined in this one file.

This is the "customizable" knob you asked for. If you want the whole app to
look different, you change values here and nothing else. No color codes are
written anywhere else in the project -- if you ever find one, it belongs here
instead.

Two things live in this file:

1. Plain constants (BG_APP, TEXT, ACCENT ...) used by the code that draws the
   floor canvas, because that is drawn by hand and needs the raw colors.

2. stylesheet(), which returns a big string of QSS. QSS is Qt's version of
   CSS -- same idea, same syntax. Qt applies it to every widget in the app at
   once, which is how buttons, lists and text boxes all get styled without us
   touching them individually.
"""

# ---------------------------------------------------------------------------
# PALETTE
# ---------------------------------------------------------------------------
# Backgrounds, darkest to lightest. Layering a few near-black grays like this
# (rather than using pure black everywhere) is most of what makes a dark UI
# look considered instead of flat.
BG_APP = "#0d0f14"        # the window itself
BG_SIDEBAR = "#12151c"    # left navigation strip
BG_PANEL = "#161a22"      # side panels, headers
BG_CARD = "#1b2029"       # cards, list rows, raised things
BG_INPUT = "#11141a"      # text boxes (sunken, so darker than cards)
BG_HOVER = "#232936"      # what a card looks like under the mouse
BG_ACTIVE = "#2b3243"     # what it looks like while pressed / selected

BORDER = "#262c3a"        # ordinary 1px dividers
BORDER_LIGHT = "#333b4d"  # borders that need to be noticed

TEXT = "#e8ebf2"          # normal text
TEXT_MUTED = "#98a1b5"    # secondary text, captions
TEXT_FAINT = "#5d677d"    # hints, placeholders, disabled

ACCENT = "#4f7cff"        # the single "primary" color of the app
ACCENT_HOVER = "#6b91ff"
ACCENT_SOFT = "#1e2a4d"   # accent at low intensity, for selected backgrounds

DANGER = "#f2555a"        # delete buttons, destructive confirmations
DANGER_HOVER = "#ff6b70"
SUCCESS = "#33d6a0"
WARNING = "#f0a726"

# The floor canvas has its own slightly darker background so it reads as a
# separate "workspace" rather than more panel.
CANVAS_BG = "#0a0c10"
GRID_MINOR = "#141821"    # fine grid lines
GRID_MAJOR = "#1c2230"    # every 5th line, drawn brighter
CANVAS_ORIGIN = "#2a3346"  # the x=0 / y=0 axis lines

# ---------------------------------------------------------------------------
# SWATCHES
# ---------------------------------------------------------------------------
# The colors offered whenever you color-code something: a profile, floor,
# room, container, item or tag. Twelve fits a tidy 6x2 grid in the picker.
# Add or remove entries freely -- the picker just draws whatever is in here.
SWATCHES = [
    "#4f7cff",  # blue
    "#33d6a0",  # mint
    "#f0a726",  # amber
    "#f2555a",  # coral
    "#a78bfa",  # violet
    "#22d3ee",  # cyan
    "#f472b6",  # pink
    "#84cc16",  # lime
    "#fb923c",  # orange
    "#e879f9",  # magenta
    "#facc15",  # yellow
    "#94a3b8",  # slate
]

# ---------------------------------------------------------------------------
# SIZING
# ---------------------------------------------------------------------------
# Spacing values come from one small set of numbers rather than being picked
# per-widget. Consistent spacing is a surprisingly large part of why an
# interface looks designed rather than assembled.
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

RADIUS_SM = 6      # inputs
RADIUS_MD = 8      # buttons
RADIUS_LG = 12     # cards

FONT_FAMILY = '"Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif'
FONT_SIZE = 13     # base text size in pixels
FONT_SIZE_SM = 11  # captions, tag chips
FONT_SIZE_LG = 16  # section headings
FONT_SIZE_XL = 22  # screen titles

# Canvas behavior. GRID_SIZE is the spacing of the fine grid in scene units,
# and also what room corners and containers snap to while you drag them.
GRID_SIZE = 20
GRID_MAJOR_EVERY = 5


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def with_alpha(hex_color, alpha):
    """Turn "#4f7cff" into "rgba(79, 124, 255, 0.25)".

    Qt understands rgba() in stylesheets, and the canvas code uses the same
    idea to draw a room's fill as a faded version of its label color.

    `alpha` is 0.0 (invisible) to 1.0 (solid).
    """
    hex_color = hex_color.lstrip("#")
    red = int(hex_color[0:2], 16)
    green = int(hex_color[2:4], 16)
    blue = int(hex_color[4:6], 16)
    return f"rgba({red}, {green}, {blue}, {alpha})"


def mix(hex_color, other_hex, amount):
    """Blend two colors. `amount` 0.0 gives the first, 1.0 gives the second.

    Used for things like "this color, but 30% darker" without having to
    hand-pick a second color for every swatch.
    """
    first = hex_color.lstrip("#")
    second = other_hex.lstrip("#")
    channels = []
    for start in (0, 2, 4):
        a = int(first[start:start + 2], 16)
        b = int(second[start:start + 2], 16)
        channels.append(round(a + (b - a) * amount))
    return "#{:02x}{:02x}{:02x}".format(*channels)


def readable_text_on(hex_color):
    """Pick black or white text so it stays legible on the given background.

    Uses the standard luminance formula -- human eyes are far more sensitive
    to green than to blue, hence the lopsided weights.
    """
    hex_color = hex_color.lstrip("#")
    red = int(hex_color[0:2], 16)
    green = int(hex_color[2:4], 16)
    blue = int(hex_color[4:6], 16)
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    return "#0d0f14" if luminance > 0.6 else "#ffffff"


# ---------------------------------------------------------------------------
# THE STYLESHEET
# ---------------------------------------------------------------------------

def stylesheet():
    """Return the QSS applied to the whole application.

    Widgets are targeted three ways in here:

      QPushButton              -> every button of that type
      #inspectorTitle          -> one specific widget, by objectName
      QPushButton[kind="danger"] -> any button with a custom property set

    That last one is worth knowing. In the Python code we write
    `button.setProperty("kind", "danger")` and the delete-red styling below
    attaches itself automatically. It keeps color decisions in this file
    instead of scattering them through the screens.
    """
    return f"""
    /* ---- base ------------------------------------------------------- */
    QWidget {{
        background-color: {BG_APP};
        color: {TEXT};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE}px;
    }}

    /* Labels must not paint their own background, or every caption shows up
       as a dark rectangle sitting on top of whatever panel it is in. Qt has
       no "inherit" for this, so it has to be said explicitly. */
    QLabel {{
        background: transparent;
    }}

    QToolTip {{
        background-color: {BG_CARD};
        color: {TEXT};
        border: 1px solid {BORDER_LIGHT};
        border-radius: {RADIUS_SM}px;
        padding: 6px 8px;
    }}

    /* ---- named containers ------------------------------------------- */
    #sidebar {{
        background-color: {BG_SIDEBAR};
        border-right: 1px solid {BORDER};
    }}

    #panel, #inspector {{
        background-color: {BG_PANEL};
        border-left: 1px solid {BORDER};
    }}

    #topBar {{
        background-color: {BG_PANEL};
        border-bottom: 1px solid {BORDER};
    }}

    #card {{
        background-color: {BG_CARD};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_LG}px;
    }}

    /* A plain grouping widget that should show whatever is behind it. The
       selector names the widget itself rather than using a bare
       "background: transparent", which would cascade into its children and
       flatten the text boxes inside it. */
    QWidget#plain {{
        background: transparent;
    }}

    /* ---- text styles ------------------------------------------------- */
    #screenTitle {{
        font-size: {FONT_SIZE_XL}px;
        font-weight: 600;
        color: {TEXT};
    }}

    #sectionTitle {{
        font-size: {FONT_SIZE_LG}px;
        font-weight: 600;
        color: {TEXT};
    }}

    #caption {{
        color: {TEXT_MUTED};
        font-size: {FONT_SIZE_SM}px;
    }}

    #hint {{
        color: {TEXT_FAINT};
        font-size: {FONT_SIZE_SM}px;
    }}

    /* ---- buttons ----------------------------------------------------- */
    QPushButton {{
        background-color: {BG_CARD};
        color: {TEXT};
        border: 1px solid {BORDER_LIGHT};
        border-radius: {RADIUS_MD}px;
        padding: 7px 14px;
        font-size: {FONT_SIZE}px;
    }}
    QPushButton:hover {{
        background-color: {BG_HOVER};
        border-color: {mix(BORDER_LIGHT, TEXT, 0.2)};
    }}
    QPushButton:pressed {{
        background-color: {BG_ACTIVE};
    }}
    QPushButton:disabled {{
        color: {TEXT_FAINT};
        background-color: {BG_PANEL};
        border-color: {BORDER};
    }}

    QPushButton[kind="primary"] {{
        background-color: {ACCENT};
        border-color: {ACCENT};
        color: #ffffff;
        font-weight: 600;
    }}
    QPushButton[kind="primary"]:hover {{
        background-color: {ACCENT_HOVER};
        border-color: {ACCENT_HOVER};
    }}

    QPushButton[kind="danger"] {{
        background-color: transparent;
        border-color: {mix(DANGER, BG_APP, 0.55)};
        color: {DANGER};
    }}
    QPushButton[kind="danger"]:hover {{
        background-color: {with_alpha(DANGER, 0.12)};
        border-color: {DANGER};
        color: {DANGER_HOVER};
    }}

    QPushButton[kind="ghost"] {{
        background-color: transparent;
        border-color: transparent;
        color: {TEXT_MUTED};
    }}
    QPushButton[kind="ghost"]:hover {{
        background-color: {BG_HOVER};
        color: {TEXT};
    }}

    /* Smaller buttons for dense rows. These reduce the PADDING rather than
       forcing a fixed height -- a button with a fixed height smaller than its
       font needs is exactly how text ends up clipped, so nothing in this app
       sets one. Let the text decide how tall it needs to be. */
    QPushButton[size="sm"] {{
        padding: 4px 10px;
        font-size: {FONT_SIZE_SM}px;
    }}
    QPushButton[size="icon"] {{
        padding: 3px 6px;
        font-size: {FONT_SIZE}px;
        min-width: 18px;
    }}

    /* Buttons that open a menu get a little arrow drawn by Qt. Ours already
       says "▾" in its own label, and two arrows side by side looks like a
       mistake, so hide Qt's. */
    QPushButton::menu-indicator {{
        image: none;
        width: 0px;
    }}

    /* Buttons that stay pressed in, used for the canvas tool modes. */
    QPushButton:checked {{
        background-color: {ACCENT_SOFT};
        border-color: {ACCENT};
        color: {TEXT};
    }}

    /* ---- text inputs -------------------------------------------------- */
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox {{
        background-color: {BG_INPUT};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        padding: 7px 10px;
        color: {TEXT};
        selection-background-color: {ACCENT};
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{
        border-color: {ACCENT};
    }}
    QLineEdit::placeholder {{
        color: {TEXT_FAINT};
    }}

    QSpinBox::up-button, QSpinBox::down-button {{
        background-color: {BG_CARD};
        border: none;
        width: 16px;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
        background-color: {BG_HOVER};
    }}

    /* ---- lists -------------------------------------------------------- */
    QListWidget, QTreeWidget {{
        background-color: transparent;
        border: none;
        outline: none;
    }}
    QListWidget::item {{
        background-color: {BG_CARD};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_MD}px;
        padding: 9px 11px;
        margin-bottom: {SPACE_XS}px;
        color: {TEXT};
    }}
    QListWidget::item:hover {{
        background-color: {BG_HOVER};
        border-color: {BORDER_LIGHT};
    }}
    QListWidget::item:selected {{
        background-color: {ACCENT_SOFT};
        border-color: {ACCENT};
        color: {TEXT};
    }}

    /* ---- combo boxes --------------------------------------------------- */
    QComboBox {{
        background-color: {BG_INPUT};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        padding: 7px 10px;
        color: {TEXT};
    }}
    QComboBox:hover {{
        border-color: {BORDER_LIGHT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {BG_CARD};
        border: 1px solid {BORDER_LIGHT};
        border-radius: {RADIUS_SM}px;
        selection-background-color: {ACCENT_SOFT};
        color: {TEXT};
        padding: 4px;
    }}

    /* ---- checkboxes ---------------------------------------------------- */
    QCheckBox {{
        color: {TEXT};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {BORDER_LIGHT};
        background-color: {BG_INPUT};
    }}
    QCheckBox::indicator:checked {{
        background-color: {ACCENT};
        border-color: {ACCENT};
    }}

    /* ---- scrollbars ----------------------------------------------------- */
    /* Thin, no arrow buttons, only visible where content actually scrolls. */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER_LIGHT};
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {TEXT_FAINT};
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {BORDER_LIGHT};
        border-radius: 5px;
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {TEXT_FAINT};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        width: 0px;
        height: 0px;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: none;
    }}

    QScrollArea {{
        border: none;
        background-color: transparent;
    }}

    /* ---- dialogs --------------------------------------------------------- */
    QDialog {{
        background-color: {BG_PANEL};
    }}

    QMessageBox {{
        background-color: {BG_PANEL};
    }}
    QMessageBox QLabel {{
        color: {TEXT};
    }}

    /* ---- the floor canvas ------------------------------------------------ */
    /* The grid itself is painted in code (see floor_view.py); this just
       removes Qt's default frame so the canvas sits flush. */
    QGraphicsView {{
        background-color: {CANVAS_BG};
        border: none;
    }}

    /* ---- splitter handle --------------------------------------------------- */
    QSplitter::handle {{
        background-color: {BORDER};
    }}
    QSplitter::handle:hover {{
        background-color: {ACCENT};
    }}
    """
