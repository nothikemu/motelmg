"""Design tokens and the application style sheet (light and dark themes)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from motelmg.core.paths import resource_path

FONT_FAMILY = "Inter"

LIGHT = {
    "bg": "#f4f6fa", "surface": "#ffffff", "surface_alt": "#f8fafc", "surface_hover": "#f1f5f9",
    "border": "#e3e8ef", "border_strong": "#cbd5e1", "text": "#0f172a", "text_muted": "#5b6779",
    "text_faint": "#94a3b8", "primary": "#2563eb", "primary_hover": "#1d4ed8", "primary_pressed": "#1e40af",
    "primary_soft": "#e8f0fe", "on_primary": "#ffffff", "danger": "#dc2626", "danger_hover": "#b91c1c",
    "danger_soft": "#fdecec", "success": "#16a34a", "success_soft": "#e7f6ec", "warning": "#d97706",
    "warning_soft": "#fdf3e1", "sidebar_bg": "#0f172a", "sidebar_text": "#a5b4c8", "sidebar_text_active": "#ffffff",
    "sidebar_active": "#1e293b", "sidebar_hover": "#172133", "sidebar_section": "#5b6b82", "input_bg": "#ffffff",
    "selection": "#dbe7fd", "selection_text": "#0f172a", "shadow": "#0f172a", "grid": "#eef2f6",
    "tooltip_bg": "#0f172a", "tooltip_text": "#f8fafc", "chart_1": "#2563eb", "chart_2": "#14b8a6",
    "chart_3": "#f59e0b", "chart_4": "#8b5cf6",
}

DARK = {
    "bg": "#0b1220", "surface": "#111a2b", "surface_alt": "#0f1726", "surface_hover": "#17233a",
    "border": "#1f2c44", "border_strong": "#2c3d5c", "text": "#e5ebf5", "text_muted": "#97a6bd",
    "text_faint": "#5f6f88", "primary": "#4c8dff", "primary_hover": "#6aa1ff", "primary_pressed": "#3a78e8",
    "primary_soft": "#16284a", "on_primary": "#ffffff", "danger": "#f05252", "danger_hover": "#f87171",
    "danger_soft": "#3a1a20", "success": "#34d399", "success_soft": "#0f2e27", "warning": "#fbbf24",
    "warning_soft": "#352a12", "sidebar_bg": "#070d18", "sidebar_text": "#8c9bb3", "sidebar_text_active": "#ffffff",
    "sidebar_active": "#162036", "sidebar_hover": "#111a2b", "sidebar_section": "#4c5b75", "input_bg": "#0d1524",
    "selection": "#1d3461", "selection_text": "#e5ebf5", "shadow": "#000000", "grid": "#1a2539",
    "tooltip_bg": "#e5ebf5", "tooltip_text": "#0b1220", "chart_1": "#4c8dff", "chart_2": "#2dd4bf",
    "chart_3": "#fbbf24", "chart_4": "#a78bfa",
}

# Semantic tones used by badges, tiles and charts: (foreground, background)
TONES_LIGHT = {
    "green": ("#15803d", "#dcfce7"), "blue": ("#1d4ed8", "#dbeafe"), "purple": ("#7c3aed", "#ede9fe"),
    "amber": ("#b45309", "#fef3c7"), "red": ("#b91c1c", "#fee2e2"), "orange": ("#c2410c", "#ffedd5"),
    "teal": ("#0f766e", "#ccfbf1"), "cyan": ("#0e7490", "#cffafe"), "indigo": ("#4338ca", "#e0e7ff"),
    "slate": ("#334155", "#e2e8f0"), "gray": ("#4b5563", "#f1f5f9"),
}
TONES_DARK = {
    "green": ("#4ade80", "#12301f"), "blue": ("#7fb0ff", "#152a4d"), "purple": ("#c4b5fd", "#2a1f4d"),
    "amber": ("#fcd34d", "#3a2d0f"), "red": ("#fca5a5", "#3f1a1d"), "orange": ("#fdba74", "#3d2312"),
    "teal": ("#5eead4", "#0f312e"), "cyan": ("#67e8f9", "#0e2f38"), "indigo": ("#a5b4fc", "#22264d"),
    "slate": ("#cbd5e1", "#243044"), "gray": ("#b6c2d3", "#1c2638"),
}
# Strong accent colour per tone (tile stripes, chart bars)
ACCENTS = {
    "green": "#16a34a", "blue": "#2563eb", "purple": "#7c3aed", "amber": "#d97706", "red": "#dc2626",
    "orange": "#ea580c", "teal": "#0d9488", "cyan": "#0891b2", "indigo": "#4f46e5", "slate": "#475569",
    "gray": "#94a3b8",
}


@dataclass
class Theme:
    name: str
    c: dict[str, str]
    tones: dict[str, tuple[str, str]]

    @property
    def dark(self) -> bool:
        return self.name == "dark"

    def tone(self, name: str) -> tuple[str, str]:
        return self.tones.get(name, self.tones["gray"])

    def accent(self, name: str) -> str:
        return ACCENTS.get(name, ACCENTS["gray"])

    def color(self, key: str) -> QColor:
        return QColor(self.c[key])


class ThemeManager(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.current = Theme("light", LIGHT, TONES_LIGHT)

    def apply(self, name: str) -> None:
        app = QApplication.instance()
        if name == "system":
            hints = app.styleHints() if app else None
            scheme = hints.colorScheme() if hints is not None and hasattr(hints, "colorScheme") else None
            name = "dark" if scheme is not None and scheme.name == "Dark" else "light"
        self.current = Theme(name, DARK if name == "dark" else LIGHT, TONES_DARK if name == "dark" else TONES_LIGHT)
        if app is not None:
            app.setPalette(build_palette(self.current))
            app.setStyleSheet(build_stylesheet(self.current))
        self.changed.emit()


theme_manager = ThemeManager()


def theme() -> Theme:
    return theme_manager.current


def load_fonts() -> str:
    family = FONT_FAMILY
    loaded = False
    for weight in ("Regular", "Medium", "SemiBold", "Bold"):
        path = resource_path("fonts", f"Inter-{weight}.ttf")
        if path.exists() and QFontDatabase.addApplicationFont(str(path)) >= 0:
            loaded = True
    if not loaded:
        family = QApplication.font().family()
    font = QFont(family, 10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    QApplication.setFont(font)
    return family


def build_palette(t: Theme) -> QPalette:
    c = t.c
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: c["bg"], QPalette.ColorRole.WindowText: c["text"],
        QPalette.ColorRole.Base: c["input_bg"], QPalette.ColorRole.AlternateBase: c["surface_alt"],
        QPalette.ColorRole.Text: c["text"], QPalette.ColorRole.Button: c["surface"],
        QPalette.ColorRole.ButtonText: c["text"], QPalette.ColorRole.Highlight: c["primary"],
        QPalette.ColorRole.HighlightedText: c["on_primary"], QPalette.ColorRole.ToolTipBase: c["tooltip_bg"],
        QPalette.ColorRole.ToolTipText: c["tooltip_text"], QPalette.ColorRole.PlaceholderText: c["text_faint"],
        QPalette.ColorRole.Link: c["primary"], QPalette.ColorRole.Mid: c["border"],
        QPalette.ColorRole.Midlight: c["border"], QPalette.ColorRole.Dark: c["border_strong"],
        QPalette.ColorRole.Light: c["surface"], QPalette.ColorRole.Shadow: c["shadow"],
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["text_faint"]))
    return p


def build_stylesheet(t: Theme) -> str:
    c = t.c
    f = FONT_FAMILY
    check = resource_path("icons", "check.svg").as_posix()
    return f"""
* {{ font-family: "{f}", "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 13px; color: {c['text']}; }}
QMainWindow, QDialog, QWidget#Page, QStackedWidget#Pages, QWidget#PageBody, QScrollArea#PageScroll > QWidget > QWidget
    {{ background: {c['bg']}; }}
QWidget#Transparent {{ background: transparent; }}
QToolTip {{ background: {c['tooltip_bg']}; color: {c['tooltip_text']}; border: none; padding: 6px 8px;
           border-radius: 6px; font-size: 12px; }}

/* ---------- sidebar ---------- */
QFrame#Sidebar {{ background: {c['sidebar_bg']}; border: none; }}
QFrame#Sidebar QLabel {{ color: {c['sidebar_text']}; background: transparent; }}
QLabel#BrandName {{ color: #ffffff; font-size: 15px; font-weight: 700; }}
QLabel#BrandSub {{ color: {c['sidebar_section']}; font-size: 11px; }}
QLabel#NavSection {{ color: {c['sidebar_section']}; font-size: 10.5px; font-weight: 700;
                     padding: 14px 14px 4px 14px; }}
QPushButton[nav="true"] {{ background: transparent; color: {c['sidebar_text']}; border: none; text-align: left;
                          padding: 9px 12px; margin: 1px 10px; border-radius: 8px; font-size: 13.5px;
                          font-weight: 500; }}
QPushButton[nav="true"]:hover {{ background: {c['sidebar_hover']}; color: {c['sidebar_text_active']}; }}
QPushButton[nav="true"]:checked {{ background: {c['sidebar_active']}; color: {c['sidebar_text_active']};
                                  font-weight: 600; }}
QFrame#UserChip {{ background: {c['sidebar_active']}; border-radius: 10px; }}
QFrame#UserChip QLabel#UserName {{ color: #ffffff; font-weight: 600; }}
QToolButton#UserMenu {{ background: transparent; border: none; padding: 4px; border-radius: 6px; }}
QToolButton#UserMenu:hover {{ background: {c['sidebar_hover']}; }}
QToolButton#UserMenu::menu-indicator {{ image: none; width: 0px; }}

/* ---------- top bar ---------- */
QFrame#TopBar {{ background: {c['surface']}; border: none; border-bottom: 1px solid {c['border']}; }}
QLabel#PageTitle {{ font-size: 19px; font-weight: 700; }}
QLabel#PageSubtitle {{ color: {c['text_muted']}; font-size: 12px; }}
QPushButton#SearchLauncher {{ background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 9px;
                              color: {c['text_faint']}; text-align: left; padding: 7px 12px; min-width: 260px; }}
QPushButton#SearchLauncher:hover {{ border-color: {c['border_strong']}; }}
QToolButton#IconButton {{ background: transparent; border: 1px solid transparent; border-radius: 9px; padding: 6px; }}
QToolButton#IconButton:hover {{ background: {c['surface_hover']}; border-color: {c['border']}; }}
QLabel#Badge {{ background: {c['danger']}; color: #ffffff; border-radius: 8px; font-size: 10px; font-weight: 700;
                padding: 0 4px; }}

/* ---------- cards ---------- */
QFrame[card="true"] {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame[card="true"] QLabel {{ background: transparent; }}
QFrame[card="true"][flat="true"] {{ border-radius: 10px; }}
QFrame[soft="true"] {{ background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QFrame[soft="true"] QLabel {{ background: transparent; }}
QLabel[role="cardtitle"] {{ font-size: 14px; font-weight: 600; }}
QLabel[role="h1"] {{ font-size: 24px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 17px; font-weight: 700; }}
QLabel[role="h3"] {{ font-size: 14px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {c['text_muted']}; }}
QLabel[role="faint"] {{ color: {c['text_faint']}; font-size: 12px; }}
QLabel[role="label"] {{ color: {c['text_muted']}; font-size: 12px; font-weight: 500; }}
QLabel[role="kpi"] {{ font-size: 26px; font-weight: 700; }}
QLabel[role="kpi_small"] {{ font-size: 20px; font-weight: 700; }}
QLabel[role="overline"] {{ color: {c['text_muted']}; font-size: 11px; font-weight: 600; }}
QLabel[role="error"] {{ color: {c['danger']}; font-size: 11.5px; }}
QLabel[role="value"] {{ font-weight: 500; }}
QLabel[role="money_big"] {{ font-size: 22px; font-weight: 700; }}
QFrame#Divider {{ background: {c['border']}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#VDivider {{ background: {c['border']}; max-width: 1px; min-width: 1px; border: none; }}

QFrame#Banner {{ border-radius: 9px; }}
QFrame#Banner[tone="error"] {{ background: {c['danger_soft']}; border: 1px solid {c['danger']}; }}
QFrame#Banner[tone="warning"] {{ background: {c['warning_soft']}; border: 1px solid {c['warning']}; }}
QFrame#Banner[tone="info"] {{ background: {c['primary_soft']}; border: 1px solid {c['primary']}; }}
QFrame#Banner[tone="success"] {{ background: {c['success_soft']}; border: 1px solid {c['success']}; }}
QFrame#Banner QLabel {{ background: transparent; }}

/* ---------- buttons ---------- */
QPushButton {{ background: {c['surface']}; border: 1px solid {c['border_strong']}; border-radius: 8px;
              padding: 7px 14px; font-weight: 500; min-height: 18px; }}
QPushButton:hover {{ background: {c['surface_hover']}; }}
QPushButton:pressed {{ background: {c['border']}; }}
QPushButton:disabled {{ color: {c['text_faint']}; background: {c['surface_alt']}; border-color: {c['border']}; }}
QPushButton:focus {{ border-color: {c['primary']}; }}
QPushButton[variant="primary"] {{ background: {c['primary']}; border: 1px solid {c['primary']}; color: {c['on_primary']};
                                 font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {c['primary_hover']}; border-color: {c['primary_hover']}; }}
QPushButton[variant="primary"]:pressed {{ background: {c['primary_pressed']}; }}
QPushButton[variant="primary"]:disabled {{ background: {c['border_strong']}; border-color: {c['border_strong']};
                                          color: {c['surface']}; }}
QPushButton[variant="danger"] {{ background: {c['danger']}; border: 1px solid {c['danger']}; color: #ffffff;
                                font-weight: 600; }}
QPushButton[variant="danger"]:hover {{ background: {c['danger_hover']}; }}
QPushButton[variant="danger-outline"] {{ color: {c['danger']}; border-color: {c['danger']}; background: transparent; }}
QPushButton[variant="danger-outline"]:hover {{ background: {c['danger_soft']}; }}
QPushButton[variant="danger-outline"]:disabled {{ color: {c['text_faint']}; border-color: {c['border']};
                                                 background: transparent; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {c['text_muted']}; }}
QPushButton[variant="ghost"]:hover {{ background: {c['surface_hover']}; color: {c['text']}; }}
QPushButton[variant="link"] {{ background: transparent; border: none; color: {c['primary']}; padding: 2px 4px;
                              font-weight: 600; text-align: left; }}
QPushButton[variant="link"]:hover {{ color: {c['primary_hover']}; }}
QPushButton[variant="soft"] {{ background: {c['primary_soft']}; border: 1px solid transparent; color: {c['primary']};
                              font-weight: 600; }}
QPushButton[variant="soft"]:hover {{ border-color: {c['primary']}; }}
QPushButton[size="small"] {{ padding: 4px 10px; font-size: 12px; }}
QPushButton[chip="true"] {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 15px;
                           padding: 5px 13px; color: {c['text_muted']}; font-weight: 500; }}
QPushButton[chip="true"]:hover {{ border-color: {c['border_strong']}; color: {c['text']}; }}
QPushButton[chip="true"]:checked {{ background: {c['primary_soft']}; border-color: {c['primary']};
                                   color: {c['primary']}; font-weight: 600; }}
QPushButton[quick="true"] {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px;
                            padding: 10px 14px; text-align: left; font-weight: 600; }}
QPushButton[quick="true"]:hover {{ border-color: {c['primary']}; background: {c['primary_soft']}; }}
QToolButton {{ border-radius: 7px; padding: 4px; }}
QToolButton:hover {{ background: {c['surface_hover']}; }}

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {c['input_bg']}; border: 1px solid {c['border_strong']}; border-radius: 8px; padding: 6px 9px;
    selection-background-color: {c['primary']}; selection-color: {c['on_primary']}; }}
QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox {{ min-height: 20px; }}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {c['primary']}; }}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled, QPlainTextEdit:disabled
    {{ background: {c['surface_alt']}; color: {c['text_faint']}; }}
QLineEdit:read-only {{ background: {c['surface_alt']}; }}
*[invalid="true"] {{ border: 1px solid {c['danger']}; background: {c['danger_soft']}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px;
                              selection-background-color: {c['selection']}; selection-color: {c['selection_text']};
                              outline: none; padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QDateEdit::up-button, QDateEdit::down-button, QTimeEdit::up-button, QTimeEdit::down-button
    {{ width: 16px; border: none; background: transparent; }}
QLineEdit#SearchField {{ padding-left: 30px; border-radius: 9px; background: {c['surface']}; }}
QLineEdit#BigSearch {{ font-size: 16px; padding: 12px 14px; border-radius: 10px; }}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1.5px solid {c['border_strong']}; border-radius: 4px;
                       background: {c['input_bg']}; }}
QCheckBox::indicator:hover {{ border-color: {c['primary']}; }}
QCheckBox::indicator:checked {{ background: {c['primary']}; border-color: {c['primary']}; image: url("{check}"); }}
QCheckBox::indicator:disabled {{ background: {c['surface_alt']}; border-color: {c['border']}; }}
QCheckBox::indicator:checked:disabled {{ background: {c['border_strong']}; border-color: {c['border_strong']}; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border: 1.5px solid {c['border_strong']}; border-radius: 9px;
                          background: {c['input_bg']}; }}
QRadioButton::indicator:hover {{ border-color: {c['primary']}; }}
QRadioButton::indicator:checked {{ border: 5px solid {c['primary']}; background: #ffffff; width: 8px; height: 8px; }}
QCalendarWidget QWidget {{ alternate-background-color: {c['surface_alt']}; }}
QCalendarWidget QToolButton {{ color: {c['text']}; font-weight: 600; padding: 4px 8px; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {c['surface']}; }}
QCalendarWidget QAbstractItemView:enabled {{ selection-background-color: {c['primary']};
                                            selection-color: {c['on_primary']}; }}

/* ---------- tables ---------- */
QTableView, QTreeView, QListView, QTableWidget, QListWidget {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px;
    gridline-color: transparent; selection-background-color: {c['selection']};
    selection-color: {c['selection_text']}; alternate-background-color: {c['surface_alt']}; outline: none; }}
QTableView::item, QTableWidget::item {{ padding: 0 8px; border-bottom: 1px solid {c['grid']}; }}
QTableView::item:hover {{ background: {c['surface_hover']}; }}
QTableView::item:selected {{ background: {c['selection']}; color: {c['selection_text']}; }}
QListView::item, QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QListView::item:selected, QListWidget::item:selected {{ background: {c['selection']}; color: {c['selection_text']}; }}
QListView::item:hover, QListWidget::item:hover {{ background: {c['surface_hover']}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {c['surface_alt']}; color: {c['text_muted']}; border: none;
                       border-bottom: 1px solid {c['border']}; padding: 9px 8px; font-size: 11.5px;
                       font-weight: 600; }}
QHeaderView::section:first {{ border-top-left-radius: 10px; }}
QHeaderView::section:last {{ border-top-right-radius: 10px; }}
QTableCornerButton::section {{ background: {c['surface_alt']}; border: none; }}

/* ---------- tabs ---------- */
QTabWidget::pane {{ border: none; background: transparent; top: -1px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; border: none; border-bottom: 2px solid transparent; padding: 9px 14px;
               margin-right: 6px; color: {c['text_muted']}; font-weight: 500; }}
QTabBar::tab:hover {{ color: {c['text']}; }}
QTabBar::tab:selected {{ color: {c['primary']}; border-bottom: 2px solid {c['primary']}; font-weight: 600; }}
QWidget#TabLine {{ border-bottom: 1px solid {c['border']}; }}

/* ---------- menus, scrollbars, misc ---------- */
QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c['surface_hover']}; color: {c['text']}; }}
QMenu::item:disabled {{ color: {c['text_faint']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border_strong']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['text_faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border_strong']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: {c['border']}; }}
QProgressBar {{ background: {c['grid']}; border: none; border-radius: 4px; height: 8px; text-align: center;
               color: transparent; }}
QProgressBar::chunk {{ background: {c['primary']}; border-radius: 4px; }}
QGroupBox {{ border: 1px solid {c['border']}; border-radius: 10px; margin-top: 14px; padding: 12px;
            background: {c['surface']}; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {c['text_muted']}; }}

/* ---------- dialogs ---------- */
QFrame#DialogHeader {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}
QFrame#DialogFooter {{ background: {c['surface_alt']}; border-top: 1px solid {c['border']}; }}
QLabel#DialogTitle {{ font-size: 17px; font-weight: 700; }}
QLabel#DialogSubtitle {{ color: {c['text_muted']}; }}
QWidget#DialogBody {{ background: {c['surface']}; }}
QWidget#DialogBody QScrollArea > QWidget > QWidget {{ background: {c['surface']}; }}
QFrame#StepList {{ background: {c['surface_alt']}; border-right: 1px solid {c['border']}; }}
QLabel[step="current"] {{ color: {c['primary']}; font-weight: 700; }}
QLabel[step="done"] {{ color: {c['success']}; font-weight: 500; }}
QLabel[step="todo"] {{ color: {c['text_faint']}; }}
QFrame#LoginBrand {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1e3a8a, stop:0.55 #2563eb,
                     stop:1 #0ea5e9); }}
QFrame#LoginBrand QLabel {{ color: #ffffff; background: transparent; }}
QFrame#Toast {{ background: {c['tooltip_bg']}; border-radius: 10px; }}
QFrame#Toast QLabel {{ color: {c['tooltip_text']}; background: transparent; }}
QFrame#Overlay {{ background: rgba(15, 23, 42, 40); }}
QFrame#Popup {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#Tile {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 11px; }}
QFrame#Tile:hover {{ border-color: {c['border_strong']}; }}
QFrame#Tile[selected="true"] {{ border: 2px solid {c['primary']}; }}
QFrame#Drawer {{ background: {c['surface']}; border-left: 1px solid {c['border']}; }}
"""
