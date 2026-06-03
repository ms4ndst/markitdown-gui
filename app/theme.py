"""Visma brand palette and stylesheet."""

VISMA_PURPLE = "#7F56FA"
VISMA_PURPLE_HOVER = "#6A3FE8"
VISMA_PURPLE_PRESSED = "#5A30D0"
VISMA_WHITE = "#FEFEFE"
VISMA_BLACK = "#131313"
VISMA_OLIVE = "#4A4608"
VISMA_BURGUNDY = "#4C0C32"
VISMA_CREME = "#F9F5F1"
VISMA_COOL_GREY = "#B9C4C9"
VISMA_COOL_GREY_LIGHT = "#E7EBEC"
VISMA_AMPLIFY_END = "#FF6B35"
VISMA_AMPLIFY_MID = "#C84FD8"

VISMA_GREEN = "#1E8E3E"
VISMA_RED = "#C5221F"


STYLESHEET = f"""
* {{
    font-family: "Visma Text", "Instrument Sans", "Segoe UI", sans-serif;
    color: {VISMA_BLACK};
}}

QMainWindow, QDialog {{
    background-color: {VISMA_WHITE};
}}

/* --- Hero band with Amplify gradient --- */
QFrame#HeroFrame {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 {VISMA_PURPLE},
        stop:0.5 {VISMA_AMPLIFY_MID},
        stop:1 {VISMA_AMPLIFY_END}
    );
    border: none;
    border-radius: 0px;
}}

QLabel#HeroTitle {{
    color: {VISMA_WHITE};
    font-size: 26px;
    font-weight: 700;
    background: transparent;
}}

QLabel#HeroSubtitle {{
    color: {VISMA_WHITE};
    font-size: 13px;
    font-weight: 400;
    background: transparent;
}}

/* --- Section headers --- */
QLabel#SectionLabel {{
    color: {VISMA_BLACK};
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
}}

QLabel#HintLabel {{
    color: #555;
    font-size: 11px;
}}

/* --- Inputs --- */
QLineEdit {{
    background-color: {VISMA_WHITE};
    border: 1px solid {VISMA_COOL_GREY};
    border-radius: 6px;
    padding: 8px 10px;
    selection-background-color: {VISMA_PURPLE};
    selection-color: {VISMA_WHITE};
}}
QLineEdit:focus {{
    border: 1px solid {VISMA_PURPLE};
}}

/* --- Buttons --- */
QPushButton {{
    background-color: {VISMA_COOL_GREY_LIGHT};
    color: {VISMA_BLACK};
    border: 1px solid {VISMA_COOL_GREY};
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: #DDE3E6;
}}
QPushButton:pressed {{
    background-color: {VISMA_COOL_GREY};
}}
QPushButton:disabled {{
    color: #999;
    background-color: #F2F4F5;
}}

QPushButton#PrimaryButton {{
    background-color: {VISMA_PURPLE};
    color: {VISMA_WHITE};
    border: none;
    padding: 12px 24px;
    font-size: 14px;
    font-weight: 700;
}}
QPushButton#PrimaryButton:hover {{
    background-color: {VISMA_PURPLE_HOVER};
}}
QPushButton#PrimaryButton:pressed {{
    background-color: {VISMA_PURPLE_PRESSED};
}}
QPushButton#PrimaryButton:disabled {{
    background-color: #C9B8F5;
    color: {VISMA_WHITE};
}}

QPushButton#DangerButton {{
    background-color: {VISMA_WHITE};
    color: {VISMA_BURGUNDY};
    border: 1px solid {VISMA_COOL_GREY};
}}
QPushButton#DangerButton:hover {{
    background-color: #FCEFF5;
    border-color: {VISMA_BURGUNDY};
}}

/* --- File list --- */
QListWidget {{
    background-color: {VISMA_CREME};
    border: 1px solid {VISMA_COOL_GREY_LIGHT};
    border-radius: 8px;
    padding: 6px;
    outline: 0;
}}
QListWidget::item {{
    padding: 6px 8px;
    border-radius: 4px;
}}
QListWidget::item:selected {{
    background-color: {VISMA_PURPLE};
    color: {VISMA_WHITE};
}}
QListWidget::item:hover {{
    background-color: {VISMA_COOL_GREY_LIGHT};
}}
QListWidget::item:selected:hover {{
    background-color: {VISMA_PURPLE_HOVER};
}}

/* --- Log view --- */
QPlainTextEdit {{
    background-color: {VISMA_BLACK};
    color: {VISMA_WHITE};
    border: 1px solid {VISMA_COOL_GREY};
    border-radius: 8px;
    padding: 8px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 11px;
    selection-background-color: {VISMA_PURPLE};
}}

/* --- Progress bar --- */
QProgressBar {{
    background-color: {VISMA_COOL_GREY_LIGHT};
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: {VISMA_BLACK};
    font-size: 10px;
    font-weight: 500;
}}
QProgressBar::chunk {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {VISMA_PURPLE},
        stop:1 {VISMA_AMPLIFY_END}
    );
    border-radius: 6px;
}}

/* --- Checkbox --- */
QCheckBox {{
    spacing: 8px;
    color: {VISMA_BLACK};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {VISMA_COOL_GREY};
    border-radius: 3px;
    background-color: {VISMA_WHITE};
}}
QCheckBox::indicator:hover {{
    border-color: {VISMA_PURPLE};
}}
QCheckBox::indicator:checked {{
    background-color: {VISMA_PURPLE};
    border-color: {VISMA_PURPLE};
    image: none;
}}

/* --- Status bar --- */
QStatusBar {{
    background-color: {VISMA_CREME};
    color: {VISMA_BLACK};
    border-top: 1px solid {VISMA_COOL_GREY_LIGHT};
    font-size: 11px;
}}

/* --- Scroll bars --- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {VISMA_COOL_GREY};
    min-height: 24px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {VISMA_PURPLE};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


def visma_logo_svg(color: str = VISMA_WHITE) -> str:
    """Stylised wordmark used in lieu of the official asset.

    The official Visma logo is a brand asset that must be downloaded from
    design.visma.com. This is a clean, contrast-correct wordmark placeholder
    that follows the brand rules (solid colour, no gradient, no outline).
    """
    return f"""<?xml version='1.0' encoding='UTF-8'?>
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 64'>
  <text x='0' y='48' font-family='Visma Text, Instrument Sans, Segoe UI, sans-serif'
        font-weight='700' font-size='44' fill='{color}' letter-spacing='-1'>visma</text>
</svg>"""
