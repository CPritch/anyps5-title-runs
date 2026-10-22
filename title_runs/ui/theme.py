"""The app's look: Fusion with a calm palette that follows the desktop's light or dark setting, and text sized for the
screen it is on. Qt's point sizes assume 96 dots per inch, so on a large high-resolution screen at no scaling they come
out tiny; the base size is scaled by the screen's real density, then by the tester's text-size setting."""

from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtCore import Qt

SIZES = {"normal": 1.0, "large": 1.2, "larger": 1.45}
ACCENT = "#2f6fd6"
COLOURS = {"muted": "#5f6470"}  # the palette apply() chose, for colours inside rich text


def density(screen):
    """How much larger than Qt's 96 dpi assumption a point looks small on this screen: 1 on an ordinary screen."""
    if screen is None:
        return 1.0
    physical, logical = screen.physicalDotsPerInch(), screen.logicalDotsPerInch()
    if not physical or not logical or physical < 1:
        return 1.0
    return max(1.0, min(2.0, physical / logical / 1.15))  # a little below the full ratio: text is read closer than it is measured


def dark(app):
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return app.palette().color(QPalette.Window).lightness() < 128


def apply(app, size="normal"):
    """Style, palette, base font and the app's stylesheet. Returns the base font's pixel size, for widgets that size
    themselves from it."""
    app.setStyle("Fusion")
    night = dark(app)
    palette = QPalette()
    colours = COLOURS.copy()
    colours.update({"window": "#1f2126", "base": "#272a30", "text": "#e8e9ec", "mid": "#3a3e46", "muted": "#a3a7b0"} if night else
               {"window": "#f4f5f7", "base": "#ffffff", "text": "#1c1e22", "mid": "#d8dbe0", "muted": "#5f6470"})
    COLOURS.update(colours)
    for role, key in ((QPalette.Window, "window"), (QPalette.Base, "base"), (QPalette.AlternateBase, "window"), (QPalette.Text, "text"),
                      (QPalette.WindowText, "text"), (QPalette.Button, "base"), (QPalette.ButtonText, "text"), (QPalette.Mid, "mid"),
                      (QPalette.ToolTipBase, "base"), (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "muted")):
        palette.setColor(role, QColor(colours[key]))
    palette.setColor(QPalette.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.Link, QColor(ACCENT if not night else "#7aa7ff"))
    app.setPalette(palette)
    screen = QGuiApplication.primaryScreen()
    points = 11 * density(screen) * SIZES.get(size, 1.0)
    font = QFont(app.font())
    font.setPointSizeF(points)
    app.setFont(font)
    pixels = round(points * (screen.logicalDotsPerInch() if screen else 96) / 72)
    c = colours
    app.setStyleSheet(f"""
        QWidget#sidebar {{ background: {c['base']}; border-right: 1px solid {c['mid']}; }}
        QPushButton[nav="true"] {{ text-align: left; padding: {pixels // 2}px {pixels}px; border: none; border-radius: 8px; }}
        QPushButton[nav="true"]:checked {{ background: {ACCENT}; color: white; }}
        QPushButton[nav="true"]:hover:!checked {{ background: {c['mid']}; }}
        QFrame[card="true"] {{ background: {c['base']}; border: 1px solid {c['mid']}; border-radius: 12px; }}
        QLabel[role="title"] {{ font-size: {round(pixels * 1.6)}px; font-weight: 600; }}
        QLabel[role="heading"] {{ font-size: {round(pixels * 1.2)}px; font-weight: 600; }}
        QLabel[role="muted"] {{ color: {c['muted']}; }}
        QPushButton {{ padding: {pixels // 3}px {pixels}px; border-radius: 8px; border: 1px solid {c['mid']}; background: {c['base']}; }}
        QPushButton:hover {{ border-color: {ACCENT}; }}
        QPushButton:disabled {{ color: {c['muted']}; }}
        QPushButton[primary="true"] {{ background: {ACCENT}; color: white; border: none; font-weight: 600;
                                      padding: {pixels // 2}px {round(pixels * 1.5)}px; }}
        QPushButton[primary="true"]:disabled {{ background: {c['mid']}; color: {c['muted']}; }}
        QPushButton[segment="left"], QPushButton[segment="middle"], QPushButton[segment="right"] {{ border-radius: 0;
                                      padding: {pixels // 2}px {round(pixels * 1.2)}px; }}
        QPushButton[segment="left"] {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}
        QPushButton[segment="right"] {{ border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}
        QPushButton[segment="left"]:checked, QPushButton[segment="middle"]:checked, QPushButton[segment="right"]:checked {{
                                      background: {ACCENT}; color: white; border-color: {ACCENT}; font-weight: 600; }}
        QPushButton[danger="true"] {{ background: #c8423b; color: white; border: none; font-weight: 600;
                                     padding: {pixels // 2}px {round(pixels * 1.5)}px; }}
        QLineEdit, QSpinBox, QComboBox {{ padding: {pixels // 4}px {pixels // 2}px; border: 1px solid {c['mid']}; border-radius: 6px;
                                         background: {c['base']}; }}
        QGroupBox {{ font-weight: 600; border: 1px solid {c['mid']}; border-radius: 10px; margin-top: {pixels}px; padding: {pixels}px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: {pixels}px; padding: 0 {pixels // 3}px; }}
        QTreeWidget, QTableWidget, QListWidget, QPlainTextEdit {{ border: 1px solid {c['mid']}; border-radius: 8px; background: {c['base']}; }}
    """)
    return pixels


def mark(widget, **properties):
    """Set the stylesheet properties (role, card, primary, danger, nav, segment) on a widget and return it."""
    for key, value in properties.items():
        widget.setProperty(key, value)
    return widget
