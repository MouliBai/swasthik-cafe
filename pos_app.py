import json
import os
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QDoubleValidator, QFont, QIcon, QKeySequence, QPainter, QPixmap
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from icon_links import icon_path
from image_links import IMAGE_DIR, brand_logo_path, brand_wordmark_path, product_image_path


APP_TITLE = "SWASTHIK CAFE"
DEFAULT_FOOTER = "Please collect your order at counter"
RUPEE = "\u20b9"
DEFAULT_PRODUCT_COLUMNS = 5
MIN_PRODUCT_CARD_WIDTH = 176
PRODUCT_CARD_WIDTH = 176
PRODUCT_CARD_HEIGHT = 238


@dataclass
class CompanySettings:
    cafe_name: str = "SWASTHIK CAFE"
    logo: str = ""
    address: str = "Add later"
    phone: str = "Optional"
    footer_text: str = DEFAULT_FOOTER


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.initialize()

    def initialize(self):
        self.conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS company_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS menu_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL DEFAULT 'Cafe',
                price REAL NOT NULL,
                image_path TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS menu_item_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                UNIQUE(item_id, name),
                FOREIGN KEY (item_id) REFERENCES menu_items(id)
            );

            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_no INTEGER NOT NULL,
                sold_at TEXT NOT NULL,
                total REAL NOT NULL,
                payment_mode TEXT NOT NULL DEFAULT 'Cash'
            );

            CREATE TABLE IF NOT EXISTS sale_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL,
                item_id INTEGER,
                name TEXT NOT NULL,
                qty INTEGER NOT NULL,
                price REAL NOT NULL,
                line_total REAL NOT NULL,
                FOREIGN KEY (sale_id) REFERENCES sales(id)
            );

            CREATE TABLE IF NOT EXISTS held_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                cart_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self._ensure_column("menu_items", "image_path", "TEXT NOT NULL DEFAULT ''")
        self._seed_settings()
        self._seed_items()
        self._seed_variants()
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str):
        columns = [row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")]
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _seed_settings(self):
        for key, value in CompanySettings().__dict__.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO company_settings(key, value) VALUES (?, ?)",
                (key, value),
            )

    def _seed_items(self):
        count = self.conn.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0]
        if count:
            return
        items = [
            ("Whipped Coffee", "Shop Coffee", 45),
            ("Filter Coffee", "Shop Coffee", 22),
            ("Cold Coffee", "Cold Brew Special Drinks", 45),
            ("Butterscotch Coffee", "Cold Brew Special Drinks", 35),
            ("Authentic Espresso", "Expresso Coffee", 40),
            ("Cappuccino Coffee", "Expresso Coffee", 55),
            ("Iced Coffee", "Cold Brew Special Drinks", 55),
            ("Coffee Coffee", "Seasonal Drinks", 60),
            ("Tea", "Shop Coffee", 12),
            ("Samosa", "Snacks", 15),
            ("Veg Puff", "Snacks", 22),
            ("Sandwich", "Sandwiches", 50),
            ("London Latte", "London's Coffee", 70),
            ("Mocha", "Seasonal Drinks", 65),
        ]
        self.conn.executemany(
            "INSERT INTO menu_items(name, category, price) VALUES (?, ?, ?)", items
        )

    def _seed_variants(self):
        tea = self.conn.execute("SELECT id FROM menu_items WHERE name = 'Tea'").fetchone()
        if not tea:
            return
        count = self.conn.execute(
            "SELECT COUNT(*) FROM menu_item_variants WHERE item_id = ?", (tea["id"],)
        ).fetchone()[0]
        if count:
            return
        self.conn.executemany(
            "INSERT OR IGNORE INTO menu_item_variants(item_id, name, price) VALUES (?, ?, ?)",
            [
                (tea["id"], "Small Tea", 12),
                (tea["id"], "Large Tea", 20),
            ],
        )

    def settings(self) -> CompanySettings:
        rows = self.conn.execute("SELECT key, value FROM company_settings").fetchall()
        data = CompanySettings().__dict__
        data.update({row["key"]: row["value"] for row in rows})
        return CompanySettings(**data)

    def save_settings(self, settings: CompanySettings):
        for key, value in settings.__dict__.items():
            self.conn.execute(
                """
                INSERT INTO company_settings(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
        self.conn.commit()

    def categories(self):
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM menu_items WHERE active = 1 ORDER BY category"
        ).fetchall()
        return ["All Items"] + [row["category"] for row in rows]

    def item_variants(self, item_id: int):
        return self.conn.execute(
            """
            SELECT id, name, price
            FROM menu_item_variants
            WHERE item_id = ? AND active = 1
            ORDER BY id
            """,
            (item_id,),
        ).fetchall()

    def menu_items(self, search_text: str = "", category: str = "All Items"):
        search = f"%{search_text.strip()}%"
        return self.conn.execute(
            """
            SELECT id, name, category, price, image_path
            FROM menu_items
            WHERE active = 1
              AND (? = '%%' OR name LIKE ? OR category LIKE ?)
              AND (? = 'All Items' OR category = ?)
            ORDER BY category, name
            """,
            (search, search, search, category, category),
        ).fetchall()

    def add_menu_item(self, name: str, category: str, price: float, image_path: str = ""):
        self.conn.execute(
            """
            INSERT INTO menu_items(name, category, price, image_path, active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (name, category, price, image_path),
        )
        self.conn.commit()

    def next_token_no(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(token_no), 1002) + 1 FROM sales").fetchone()
        return int(row[0])

    def save_sale(self, token_no: int, cart: list[dict], total: float, payment_mode: str) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO sales(token_no, sold_at, total, payment_mode) VALUES (?, ?, ?, ?)",
            (token_no, now, total, payment_mode),
        )
        sale_id = cur.lastrowid
        self.conn.executemany(
            """
            INSERT INTO sale_items(sale_id, item_id, name, qty, price, line_total)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    sale_id,
                    item["id"],
                    item["name"],
                    item["qty"],
                    item["price"],
                    item["qty"] * item["price"],
                )
                for item in cart
            ],
        )
        self.conn.commit()
        return sale_id

    def today_summary(self):
        today = datetime.now().date().isoformat()
        return self.conn.execute(
            """
            SELECT
                COUNT(*) AS order_count,
                COALESCE(SUM(total), 0) AS revenue,
                COALESCE(AVG(total), 0) AS average_bill
            FROM sales
            WHERE date(sold_at) = ?
            """,
            (today,),
        ).fetchone()

    def all_bills(self):
        return self.conn.execute(
            """
            SELECT id, token_no, sold_at, total, payment_mode
            FROM sales
            ORDER BY sold_at DESC, id DESC
            """
        ).fetchall()

    def sale_items(self, sale_id: int):
        return self.conn.execute(
            """
            SELECT name, qty, price, line_total
            FROM sale_items
            WHERE sale_id = ?
            ORDER BY id
            """,
            (sale_id,),
        ).fetchall()

    def hold_order(self, label: str, cart: list[dict]):
        self.conn.execute(
            "INSERT INTO held_orders(label, cart_json, created_at) VALUES (?, ?, ?)",
            (label, json.dumps(cart), datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def held_orders(self):
        return self.conn.execute(
            "SELECT id, label, cart_json, created_at FROM held_orders ORDER BY id DESC"
        ).fetchall()

    def recall_order(self, hold_id: int):
        row = self.conn.execute("SELECT cart_json FROM held_orders WHERE id = ?", (hold_id,)).fetchone()
        if not row:
            return []
        self.conn.execute("DELETE FROM held_orders WHERE id = ?", (hold_id,))
        self.conn.commit()
        return json.loads(row["cart_json"])


class SearchLineEdit(QLineEdit):
    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()

    def mousePressEvent(self, event):
        was_focused = self.hasFocus()
        super().mousePressEvent(event)
        if not was_focused:
            self.selectAll()


class StartupDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Open Billing Database")
        self.setMinimumWidth(560)
        self.db_path: Path | None = None

        title = QLabel("SWASTHIK CAFE")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("Choose an existing SQLite DB or type a new DB filename to create it.")

        self.path_edit = QLineEdit(str(Path.cwd() / "sasthik_cafe.sqlite3"))
        self.path_edit.setPlaceholderText("Example: C:\\Cafe\\sasthik_cafe.sqlite3")

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse)

        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse_btn)

        open_btn = QPushButton("Start Billing")
        open_btn.setObjectName("PrimaryButton")
        open_btn.clicked.connect(self.accept_path)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(path_row)
        layout.addWidget(open_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def browse(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Choose SQLite Database",
            self.path_edit.text(),
            "SQLite Database (*.sqlite3 *.db);;All Files (*)",
        )
        if filename:
            self.path_edit.setText(filename)

    def accept_path(self):
        raw_path = self.path_edit.text().strip()
        if not raw_path:
            QMessageBox.warning(self, "Database Required", "Please type a database filename.")
            return
        db_path = Path(raw_path).expanduser()
        if db_path.suffix == "":
            db_path = db_path.with_suffix(".sqlite3")
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Cannot Create Folder", str(exc))
            return
        self.db_path = db_path
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Company Settings")
        self.setMinimumWidth(520)
        settings = db.settings()

        self.cafe_name = QLineEdit(settings.cafe_name)
        self.logo = QLineEdit(settings.logo)
        self.logo.setPlaceholderText("Choose logo image...")
        self.address = QLineEdit(settings.address)
        self.phone = QLineEdit(settings.phone)
        self.footer_text = QLineEdit(settings.footer_text)

        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo, 1)
        logo_btn = QPushButton("Browse")
        logo_btn.clicked.connect(self.choose_logo)
        logo_row.addWidget(logo_btn)

        form = QFormLayout()
        form.addRow("Cafe Name", self.cafe_name)
        form.addRow("Logo Image", logo_row)
        form.addRow("Address", self.address)
        form.addRow("Phone", self.phone)
        form.addRow("Footer Text", self.footer_text)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self.save)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(save_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def save(self):
        self.db.save_settings(
            CompanySettings(
                cafe_name=self.cafe_name.text().strip() or "SWASTHIK CAFE",
                logo=self.logo.text().strip(),
                address=self.address.text().strip() or "Add later",
                phone=self.phone.text().strip() or "Optional",
                footer_text=self.footer_text.text().strip() or DEFAULT_FOOTER,
            )
        )
        self.accept()

    def choose_logo(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Logo Image",
            str(Path.cwd() / "image"),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if filename:
            self.logo.setText(filename)


class RecallDialog(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.selected_hold_id: int | None = None
        self.setWindowTitle("Recall Held Order")
        self.setMinimumSize(500, 320)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "Label", "Created"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.choose)

        recall_btn = QPushButton("Recall")
        recall_btn.setObjectName("PrimaryButton")
        recall_btn.clicked.connect(self.choose)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(recall_btn, alignment=Qt.AlignmentFlag.AlignRight)
        self.load()

    def load(self):
        rows = self.db.held_orders()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col, value in enumerate((row["id"], row["label"], row["created_at"])):
                self.table.setItem(row_index, col, QTableWidgetItem(str(value)))

    def choose(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return
        self.selected_hold_id = int(self.table.item(selected[0].row(), 0).text())
        self.accept()


class AddItemDialog(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Add New Item")
        self.setMinimumWidth(520)
        self.image_path = ""

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Item Name")
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.addItems([c for c in db.categories() if c != "All Items"])
        self.price_spin = QSpinBox()
        self.price_spin.setRange(1, 99999)
        self.price_spin.setPrefix(RUPEE)
        self.price_spin.setValue(20)
        self.image_label = QLabel("No image selected")
        self.image_label.setObjectName("ImageChoiceLabel")

        image_btn = QPushButton("Choose Image")
        image_btn.clicked.connect(self.choose_image)

        form = QFormLayout()
        form.addRow("Item Name", self.name_edit)
        form.addRow("Category", self.category_combo)
        form.addRow("Selling Price", self.price_spin)
        form.addRow("Image", image_btn)
        form.addRow("", self.image_label)

        save_btn = QPushButton("Save Item")
        save_btn.setObjectName("OrangeButton")
        save_btn.clicked.connect(self.save_item)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(save_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def choose_image(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Product Image",
            str(Path.cwd() / "image"),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if filename:
            self.image_path = filename
            self.image_label.setText(Path(filename).name)

    def save_item(self):
        name = self.name_edit.text().strip()
        category = self.category_combo.currentText().strip()
        if not name:
            QMessageBox.warning(self, "Item Required", "Item name is required.")
            return
        if not category:
            QMessageBox.warning(self, "Category Required", "Category is required.")
            return
        try:
            stored_image = self.store_image(name)
            self.db.add_menu_item(name, category, float(self.price_spin.value()), stored_image)
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Duplicate Item", "Item already exists.")
            return
        self.accept()

    def store_image(self, item_name: str) -> str:
        if not self.image_path:
            return ""
        source = Path(self.image_path)
        if not source.exists():
            return ""
        IMAGE_DIR.mkdir(exist_ok=True)
        safe_name = re.sub(r"[^a-z0-9]+", "_", item_name.lower()).strip("_")
        destination = IMAGE_DIR / f"{safe_name}{source.suffix.lower()}"
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        return str(destination)


class ProductCard(QFrame):
    clicked = pyqtSignal(int, str, float)

    def __init__(self, row, accent: QColor):
        super().__init__()
        self.item_id = int(row["id"])
        self.name = row["name"]
        self.price = float(row["price"])
        self.setObjectName("ProductCard")
        self.setFixedSize(QSize(PRODUCT_CARD_WIDTH, PRODUCT_CARD_HEIGHT))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setOffset(5, 5)
        shadow.setColor(QColor(0, 0, 0, 75))
        self.setGraphicsEffect(shadow)

        image_wrap = QFrame()
        image_wrap.setObjectName("ProductImageWrap")
        image_wrap.setFixedHeight(138)
        image_layout = QVBoxLayout(image_wrap)
        image_layout.setContentsMargins(10, 10, 10, 0)
        image_layout.setSpacing(0)

        image = QLabel()
        pixmap = QPixmap(product_image_path(self.name, row["image_path"]))
        if pixmap.isNull():
            pixmap = make_product_pixmap(self.name, accent)
        image.setPixmap(pixmap)
        image.setScaledContents(True)
        image.setFixedHeight(128)
        image.setObjectName("ProductImage")
        image_layout.addWidget(image)

        name = QLabel(self.name)
        name.setObjectName("ProductName")
        name.setWordWrap(True)
        name.setFixedHeight(38)

        secondary = QLabel(f"{row['category']}  {RUPEE}{self.price:.2f}")
        secondary.setObjectName("ProductSecondary")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 14)
        layout.setSpacing(0)
        layout.addWidget(image_wrap)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 0)
        content_layout.setSpacing(6)
        content_layout.addWidget(name)
        content_layout.addWidget(secondary)
        layout.addWidget(content)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item_id, self.name, self.price)
        super().mousePressEvent(event)


class OrderSwitch(QCheckBox):
    def __init__(self):
        super().__init__()
        self.setObjectName("OrderSwitch")
        self.setFixedSize(56, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._knob_progress = 0.0
        self.animation = QPropertyAnimation(self, b"knobProgress", self)
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self.animate_knob)

    def knob_progress(self) -> float:
        return self._knob_progress

    def set_knob_progress(self, value: float):
        self._knob_progress = value
        self.update()

    knobProgress = pyqtProperty(float, knob_progress, set_knob_progress)

    def animate_knob(self, checked: bool):
        self.animation.stop()
        self.animation.setStartValue(self._knob_progress)
        self.animation.setEndValue(1.0 if checked else 0.0)
        self.animation.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0, 0, self.width(), self.height())
        track_color = QColor("#4296f4") if self.isChecked() else QColor("#cccccc")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 16, 16)

        knob_size = 24
        offset = 4
        x = offset + (self.width() - knob_size - (offset * 2)) * self._knob_progress
        knob = QRectF(x, offset, knob_size, knob_size)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(knob)
        painter.end()


class OrderTypeToggle(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("OrderTypeToggle")
        self.setFixedSize(220, 34)
        self.value = "Take Away"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.takeaway_label = QLabel("Take Away")
        self.takeaway_label.setObjectName("ToggleLabel")

        self.switch = OrderSwitch()
        self.switch.toggled.connect(self.set_checked)

        self.dinein_label = QLabel("Dine In")
        self.dinein_label.setObjectName("ToggleLabel")

        layout.addWidget(self.takeaway_label)
        layout.addWidget(self.switch)
        layout.addWidget(self.dinein_label)
        layout.addStretch(1)

    def set_value(self, value: str):
        self.value = value
        self.switch.setChecked(value == "Dine In")

    def set_checked(self, checked: bool):
        self.value = "Dine In" if checked else "Take Away"


class CartItemRow(QFrame):
    def __init__(self, item: dict, index: int, parent_window):
        super().__init__()
        self.setObjectName("CartItemRow")
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.index = index
        self.parent_window = parent_window

        title = QLabel(item["name"])
        title.setObjectName("CartItemTitle")
        price = QLabel(f"{RUPEE}{item['price']:.2f}")
        price.setObjectName("CartItemPrice")
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        text_col.addWidget(title)
        text_col.addWidget(price)

        minus_btn = QToolButton()
        minus_btn.setText("-")
        minus_btn.setObjectName("RoundQty")
        minus_btn.clicked.connect(lambda: parent_window.bump_qty(index, -1))

        qty = QLabel(str(item["qty"]))
        qty.setObjectName("QtyNumber")

        plus_btn = QToolButton()
        plus_btn.setText("+")
        plus_btn.setObjectName("RoundQty")
        plus_btn.clicked.connect(lambda: parent_window.bump_qty(index, 1))

        remove_btn = QToolButton()
        remove_btn.setText("x")
        remove_btn.setObjectName("RemoveButton")
        remove_btn.clicked.connect(lambda: parent_window.remove_cart_item(index))

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        controls.addWidget(minus_btn)
        controls.addWidget(qty)
        controls.addWidget(plus_btn)
        controls.addWidget(remove_btn)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(10)
        layout.addLayout(text_col, 1)
        layout.addLayout(controls)


class AnalysisDialog(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("AnalysisDialog")
        self.setAutoFillBackground(True)
        self.setWindowTitle("Analysis")
        self.setMinimumSize(920, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        title = QLabel("Order Analysis")
        title.setObjectName("AnalysisTitle")
        layout.addWidget(title)
        layout.addLayout(self.build_kpis())

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self.build_bill_list(), 1)
        body.addWidget(self.build_bill_detail(), 1)
        layout.addLayout(body, 1)

        self.load_bills()

    def build_kpis(self):
        summary = self.db.today_summary()
        bills = self.db.all_bills()
        total_revenue = sum(float(row["total"]) for row in bills)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self.kpi_card("Today's Revenue", f"{RUPEE}{float(summary['revenue']):.2f}"))
        row.addWidget(self.kpi_card("Today's Orders", str(summary["order_count"])))
        row.addWidget(self.kpi_card("Average Bill", f"{RUPEE}{float(summary['average_bill']):.2f}"))
        row.addWidget(self.kpi_card("All-Time Revenue", f"{RUPEE}{total_revenue:.2f}"))
        return row

    def kpi_card(self, label: str, value: str):
        card = QFrame()
        card.setObjectName("KpiCard")
        card.setMinimumHeight(86)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        label_widget = QLabel(label)
        label_widget.setObjectName("KpiLabel")
        value_widget = QLabel(value)
        value_widget.setObjectName("KpiValue")
        layout.addWidget(label_widget)
        layout.addWidget(value_widget)
        return card

    def build_bill_list(self):
        panel = QFrame()
        panel.setObjectName("AnalysisPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        label = QLabel("Bills")
        label.setObjectName("AnalysisPanelTitle")
        self.bill_table = QTableWidget(0, 4)
        self.bill_table.setHorizontalHeaderLabels(["Order", "Date", "Time", "Paid"])
        self.bill_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.bill_table.verticalHeader().setVisible(False)
        self.bill_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.bill_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.bill_table.itemSelectionChanged.connect(self.load_selected_bill)

        layout.addWidget(label)
        layout.addWidget(self.bill_table, 1)
        return panel

    def build_bill_detail(self):
        panel = QFrame()
        panel.setObjectName("AnalysisPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.detail_title = QLabel("Bill Items")
        self.detail_title.setObjectName("AnalysisPanelTitle")
        self.detail_items = QTableWidget(0, 4)
        self.detail_items.setHorizontalHeaderLabels(["Item", "Qty", "Price", "Total"])
        self.detail_items.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.detail_items.verticalHeader().setVisible(False)
        self.detail_items.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.detail_items.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.detail_total = QLabel(f"Total: {RUPEE}0.00")
        self.detail_total.setObjectName("AnalysisTotal")

        layout.addWidget(self.detail_title)
        layout.addWidget(self.detail_items, 1)
        layout.addWidget(self.detail_total, alignment=Qt.AlignmentFlag.AlignRight)
        return panel

    def load_bills(self):
        self.bills = self.db.all_bills()
        self.bill_table.setRowCount(len(self.bills))
        for row_index, bill in enumerate(self.bills):
            sold_at = datetime.fromisoformat(bill["sold_at"])
            values = (
                f"#{bill['token_no']}",
                sold_at.strftime("%d-%m-%Y"),
                sold_at.strftime("%I:%M %p"),
                f"{RUPEE}{float(bill['total']):.2f}",
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, bill["id"])
                self.bill_table.setItem(row_index, col, item)
        if self.bills:
            self.bill_table.selectRow(0)

    def load_selected_bill(self):
        selected = self.bill_table.selectionModel().selectedRows()
        if not selected:
            return
        row = selected[0].row()
        sale_id = int(self.bill_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
        bill = self.bills[row]
        self.detail_title.setText(f"Order #{bill['token_no']} Items")
        items = self.db.sale_items(sale_id)
        self.detail_items.setRowCount(len(items))
        for row_index, item_row in enumerate(items):
            values = (
                item_row["name"],
                item_row["qty"],
                f"{RUPEE}{float(item_row['price']):.2f}",
                f"{RUPEE}{float(item_row['line_total']):.2f}",
            )
            for col, value in enumerate(values):
                self.detail_items.setItem(row_index, col, QTableWidgetItem(str(value)))
        self.detail_total.setText(f"Paid: {RUPEE}{float(bill['total']):.2f} ({bill['payment_mode']})")


def make_product_pixmap(name: str, accent: QColor) -> QPixmap:
    pixmap = QPixmap(180, 112)
    pixmap.fill(QColor("#f5f5f7"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.fillRect(0, 0, 180, 112, QColor("#f5f5f7"))
    painter.setBrush(QColor("#8e8e93"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(35, 16, 110, 78)
    painter.setBrush(QColor("#ffffff"))
    painter.drawEllipse(48, 25, 84, 58)
    painter.setBrush(accent)
    painter.drawEllipse(68, 35, 42, 28)
    painter.setBrush(QColor(255, 255, 255, 185))
    painter.drawEllipse(76, 41, 18, 10)
    painter.setPen(QColor("#1d1d1f"))
    painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    painter.drawText(8, 100, name[:24])
    painter.end()
    return pixmap


class MainWindow(QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.settings = db.settings()
        self.cart: list[dict] = []
        self.last_receipt = ""
        self.last_bill_pdf: Path | None = None
        self.selected_category = "All Items"
        self.payment_mode = "Cash"
        self.product_columns = DEFAULT_PRODUCT_COLUMNS

        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(1100, 650)
        self.resize(1366, 768)
        self.setup_actions()
        self.setup_ui()
        self.refresh_header()
        self.refresh_categories()
        self.refresh_items()
        self.refresh_cart()

    def setup_actions(self):
        settings_action = QAction("Company Settings", self)
        settings_action.triggered.connect(self.open_settings)
        self.menuBar().addAction(settings_action)

        focus_search = QAction("Search Item", self)
        focus_search.setShortcut(QKeySequence("F9"))
        focus_search.triggered.connect(lambda checked=False: self.search_edit.setFocus())
        self.addAction(focus_search)

        save_order = QAction("Save Order", self)
        save_order.setShortcut(QKeySequence("F10"))
        save_order.triggered.connect(lambda checked=False: self.complete_sale(print_after=False))
        self.addAction(save_order)

        save_print_order = QAction("Save and Print Order", self)
        save_print_order.setShortcut(QKeySequence("F11"))
        save_print_order.triggered.connect(lambda checked=False: self.complete_sale(print_after=True))
        self.addAction(save_print_order)

    def setup_ui(self):
        root = QWidget()
        root.setObjectName("AppRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(48, 18, 48, 24)
        root_layout.setSpacing(12)

        root_layout.addWidget(self.build_topbar())

        body = QHBoxLayout()
        body.setSpacing(8)
        body.addWidget(self.build_sidebar())
        body.addWidget(self.build_products_panel(), 1)
        body.addWidget(self.build_cart_panel())
        root_layout.addLayout(body, 1)

        self.receipt_preview = QTextEdit()
        self.receipt_preview.hide()

        self.setCentralWidget(root)

    def build_topbar(self):
        bar = QFrame()
        bar.setObjectName("TopBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        brand = QWidget()
        brand.setObjectName("BrandWrap")
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(8)

        self.logo_label = QLabel()
        self.logo_label.setObjectName("BrandLogo")
        self.logo_label.setFixedSize(42, 42)
        self.logo_label.setScaledContents(True)

        self.brand_label = QLabel()
        self.brand_label.setObjectName("BrandLabel")
        self.brand_label.setFixedSize(192, 42)
        self.brand_label.setScaledContents(True)

        brand_layout.addWidget(self.logo_label)
        brand_layout.addWidget(self.brand_label)

        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("Search Products...  [F9]")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.refresh_items)

        add_btn = QPushButton("+ Add New Item")
        add_btn.setObjectName("OrangeButton")
        add_btn.clicked.connect(self.open_add_item)

        hold_btn = QToolButton()
        hold_btn.setIcon(QIcon(icon_path("refresh")))
        hold_btn.setObjectName("IconButton")
        hold_btn.setToolTip("Hold order")
        hold_btn.clicked.connect(self.hold_cart)

        recall_btn = QToolButton()
        recall_btn.setIcon(QIcon(icon_path("receipt")))
        recall_btn.setObjectName("IconButton")
        recall_btn.setToolTip("Recall order")
        recall_btn.clicked.connect(self.recall_cart)

        bell_btn = QToolButton()
        bell_btn.setIcon(QIcon(icon_path("bell")))
        bell_btn.setObjectName("IconButton")
        bell_btn.setToolTip("Notifications")

        analysis_btn = QPushButton("Analysis")
        analysis_btn.setObjectName("PrintButton")
        analysis_btn.setIcon(QIcon(icon_path("receipt")))
        analysis_btn.clicked.connect(self.open_analysis)

        back_btn = QPushButton("Back")
        back_btn.setObjectName("PrintButton")
        back_btn.setIcon(QIcon(icon_path("back")))
        back_btn.clicked.connect(self.go_back)

        layout.addWidget(brand)
        layout.addWidget(self.search_edit, 1)
        layout.addWidget(add_btn)
        layout.addWidget(hold_btn)
        layout.addWidget(recall_btn)
        layout.addWidget(bell_btn)
        layout.addWidget(analysis_btn)
        layout.addWidget(back_btn)
        return bar

    def build_sidebar(self):
        panel = QFrame()
        panel.setObjectName("Sidebar")
        panel.setFixedWidth(288)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.category_layout = layout
        layout.addStretch(1)
        return panel

    def build_products_panel(self):
        panel = QFrame()
        panel.setObjectName("ProductsPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        controls = QFrame()
        controls.setObjectName("OrderControls")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(14, 12, 14, 12)
        controls_layout.setSpacing(12)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Your Comment Here...")
        controls_layout.addWidget(self.control_group("Note", self.note_edit), 1)
        self.order_type_toggle = OrderTypeToggle()
        controls_layout.addWidget(self.control_group("Order Type", self.order_type_toggle))

        self.products_scroll = QScrollArea()
        self.products_scroll.setObjectName("ProductsScroll")
        self.products_scroll.setWidgetResizable(True)
        self.products_container = QWidget()
        self.products_container.setObjectName("ProductsContainer")
        self.products_grid = QGridLayout(self.products_container)
        self.products_grid.setContentsMargins(10, 10, 18, 18)
        self.products_grid.setHorizontalSpacing(18)
        self.products_grid.setVerticalSpacing(18)
        self.products_grid.setColumnStretch(DEFAULT_PRODUCT_COLUMNS, 1)
        self.products_scroll.setWidget(self.products_container)

        layout.addWidget(controls)
        layout.addWidget(self.products_scroll, 1)
        return panel

    def control_group(self, title: str, widget: QWidget):
        group = QWidget()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel(title)
        label.setObjectName("ControlLabel")
        layout.addWidget(label)
        layout.addWidget(widget)
        return group

    def build_cart_panel(self):
        panel = QFrame()
        panel.setObjectName("CartPanel")
        panel.setFixedWidth(288)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("Cart Items")
        title.setObjectName("CartTitle")
        self.token_label = QLabel()
        self.token_label.setObjectName("OrderNumber")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.token_label)

        self.date_label = QLabel()
        self.date_label.setObjectName("CartDate")
        self.cart_items_container = QWidget()
        self.cart_items_container.setObjectName("CartItemsContainer")
        self.cart_items_layout = QVBoxLayout()
        self.cart_items_layout.setContentsMargins(0, 0, 0, 0)
        self.cart_items_layout.setSpacing(0)
        self.cart_items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cart_items_container.setLayout(self.cart_items_layout)

        self.cart_items_scroll = QScrollArea()
        self.cart_items_scroll.setObjectName("CartItemsScroll")
        self.cart_items_scroll.setWidgetResizable(True)
        self.cart_items_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cart_items_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cart_items_scroll.setWidget(self.cart_items_container)

        self.subtotal_label = QLabel()
        self.discount_input = QLineEdit("0.00")
        self.discount_input.setObjectName("DiscountInput")
        self.discount_input.setValidator(QDoubleValidator(0.0, 999999.0, 2, self))
        self.discount_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.discount_input.textChanged.connect(self.refresh_cart)
        self.total_label = QLabel()
        self.total_label.setObjectName("CartTotalValue")

        payment_title = QLabel("Payment Method")
        payment_title.setObjectName("PaymentTitle")
        payment_row = QHBoxLayout()
        self.payment_group = QButtonGroup(self)
        for index, payment in enumerate(("Cash", "UPI")):
            button = QRadioButton(payment)
            button.setObjectName("PaymentButton")
            button.setIcon(QIcon(icon_path(("cash", "wallet")[index])))
            button.setIconSize(QSize(22, 18))
            button.setChecked(index == 0)
            button.toggled.connect(lambda checked, text=payment: self.set_payment(text, checked))
            self.payment_group.addButton(button)
            payment_row.addWidget(button)

        place_order = QPushButton("Place Order")
        place_order.setObjectName("PlaceOrderButton")
        place_order.clicked.connect(lambda: self.complete_sale(print_after=True))

        layout.addLayout(title_row)
        layout.addWidget(self.date_label, alignment=Qt.AlignmentFlag.AlignRight)
        clear_btn = QPushButton("Clear Cart")
        clear_btn.setObjectName("CartClearButton")
        clear_btn.clicked.connect(self.clear_cart)
        layout.addWidget(clear_btn, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.summary_line())
        layout.addWidget(self.cart_items_scroll, 1)
        layout.addWidget(self.summary_row("Subtotal", self.subtotal_label))
        layout.addWidget(self.summary_row("Discount", self.discount_input))
        layout.addWidget(self.summary_line())
        layout.addWidget(self.summary_row("Total", self.total_label))
        layout.addWidget(payment_title)
        layout.addLayout(payment_row)
        layout.addWidget(place_order)
        return panel

    def summary_row(self, label_text: str, value_label: QLabel):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setObjectName("SummaryLabel")
        value_label.setObjectName(value_label.objectName() or "SummaryValue")
        layout.addWidget(label)
        layout.addStretch(1)
        layout.addWidget(value_label)
        return row

    def summary_line(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("SummaryLine")
        return line

    def refresh_header(self):
        self.settings = self.db.settings()
        logo = QPixmap(brand_logo_path())
        if not logo.isNull():
            self.logo_label.setPixmap(logo)
        else:
            self.logo_label.setText("S")

        wordmark = QPixmap(brand_wordmark_path())
        if not wordmark.isNull():
            self.brand_label.setPixmap(wordmark)
            self.brand_label.setText("")
        else:
            self.brand_label.setText("swasthik cafe")
        self.token_label.setText(f"Order No. #{self.db.next_token_no()}")
        self.date_label.setText(datetime.now().strftime("%A, %d %b, %Y"))

    def refresh_categories(self):
        while self.category_layout.count() > 1:
            item = self.category_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for category in self.db.categories():
            button = QPushButton(category)
            button.setObjectName("CategoryButton")
            button.setCheckable(True)
            button.setChecked(category == self.selected_category)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _, value=category: self.select_category(value))
            self.category_layout.insertWidget(self.category_layout.count() - 1, button)

    def select_category(self, category: str):
        self.selected_category = category
        self.refresh_categories()
        self.refresh_items()

    def refresh_items(self):
        while self.products_grid.count():
            item = self.products_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        rows = self.db.menu_items(
            self.search_edit.text() if hasattr(self, "search_edit") else "",
            self.selected_category,
        )
        accents = [
            QColor("#007aff"),
            QColor("#5ac8fa"),
            QColor("#34c759"),
            QColor("#af52de"),
            QColor("#ff9500"),
            QColor("#8e8e93"),
        ]
        self.product_columns = self.product_column_count()
        for col in range(self.product_columns):
            self.products_grid.setColumnStretch(col, 1)
        self.products_grid.setColumnStretch(self.product_columns, 0)

        for index, row in enumerate(rows):
            card = ProductCard(row, accents[index % len(accents)])
            card.clicked.connect(self.add_to_cart)
            self.products_grid.addWidget(card, index // self.product_columns, index % self.product_columns)
        self.products_grid.setRowStretch((len(rows) + self.product_columns - 1) // self.product_columns, 1)

    def product_column_count(self) -> int:
        if not hasattr(self, "products_scroll"):
            return DEFAULT_PRODUCT_COLUMNS
        available_width = self.products_scroll.viewport().width()
        if available_width <= 0:
            return DEFAULT_PRODUCT_COLUMNS
        spacing = self.products_grid.horizontalSpacing()
        columns = max(1, int((available_width + spacing) // (PRODUCT_CARD_WIDTH + spacing)))
        default_width = DEFAULT_PRODUCT_COLUMNS * PRODUCT_CARD_WIDTH + (DEFAULT_PRODUCT_COLUMNS - 1) * spacing
        if available_width >= default_width:
            return max(DEFAULT_PRODUCT_COLUMNS, columns)
        return columns

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "products_scroll"):
            new_columns = self.product_column_count()
            if new_columns != self.product_columns:
                self.refresh_items()

    def add_to_cart(self, item_id: int, name: str, price: float):
        cart_key = f"{item_id}:{name}"
        for item in self.cart:
            if item.get("key") == cart_key:
                item["qty"] += 1
                self.refresh_cart()
                return
        self.cart.append({"key": cart_key, "id": item_id, "name": name, "price": price, "qty": 1})
        self.refresh_cart()

    def refresh_cart(self):
        while self.cart_items_layout.count():
            item = self.cart_items_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for index, item in enumerate(self.cart):
            self.cart_items_layout.addWidget(CartItemRow(item, index, self))

        if not self.cart:
            empty = QLabel("No items added")
            empty.setObjectName("EmptyCart")
            self.cart_items_layout.addWidget(empty)

        subtotal = sum(item["qty"] * item["price"] for item in self.cart)
        discount = self.discount_amount(subtotal)
        total = max(0, subtotal - discount)
        self.subtotal_label.setText(f"{RUPEE}{subtotal:.2f}")
        self.total_label.setText(f"{RUPEE}{total:.2f}")
        if self.last_receipt and not self.cart:
            self.receipt_preview.setPlainText(self.last_receipt)
        else:
            self.receipt_preview.setPlainText(self.preview_receipt(self.db.next_token_no(), preview=not self.cart))

    def discount_amount(self, subtotal: float) -> float:
        if not hasattr(self, "discount_input"):
            return 0.0
        text = self.discount_input.text().strip()
        if not text:
            return 0.0
        try:
            return min(float(text), subtotal)
        except ValueError:
            return 0.0

    def bump_qty(self, index: int, delta: int):
        if not 0 <= index < len(self.cart):
            return
        self.cart[index]["qty"] += delta
        if self.cart[index]["qty"] <= 0:
            self.cart.pop(index)
        self.refresh_cart()

    def remove_cart_item(self, index: int):
        if 0 <= index < len(self.cart):
            self.cart.pop(index)
            self.refresh_cart()

    def clear_cart(self):
        if self.cart:
            reply = QMessageBox.question(
                self,
                "Clear Cart",
                "Remove all cart items?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.cart.clear()
        self.last_receipt = ""
        self.refresh_cart()

    def hold_cart(self):
        if not self.cart:
            QMessageBox.information(self, "Hold Order", "Cart is empty.")
            return
        label = f"Hold #{datetime.now().strftime('%H%M%S')}"
        self.db.hold_order(label, self.cart)
        self.clear_cart()
        QMessageBox.information(self, "Order Held", f"Saved as {label}.")

    def recall_cart(self):
        dialog = RecallDialog(self.db, self)
        if dialog.exec() and dialog.selected_hold_id:
            self.cart = self.db.recall_order(dialog.selected_hold_id)
            self.refresh_cart()

    def set_payment(self, payment: str, checked: bool):
        if checked:
            self.payment_mode = payment

    def complete_sale(self, print_after: bool = True):
        if not self.cart:
            QMessageBox.information(self, "Place Order", "Add at least one item.")
            return
        token_no = self.db.next_token_no()
        bill_cart = [dict(item) for item in self.cart]
        subtotal = sum(item["qty"] * item["price"] for item in bill_cart)
        total = max(0, subtotal - self.discount_amount(subtotal))
        discount = max(0, subtotal - total)
        self.db.save_sale(token_no, bill_cart, total, self.payment_mode)
        self.last_receipt = self.preview_receipt(token_no, preview=False)
        self.receipt_preview.setPlainText(self.last_receipt)
        self.last_bill_pdf = self.generate_bill_pdf(
            token_no=token_no,
            cart=bill_cart,
            subtotal=subtotal,
            discount=discount,
            total=total,
            payment_mode=self.payment_mode,
        )
        if print_after:
            self.print_bill_pdf()
        QMessageBox.information(self, "Order Placed", f"Token {token_no} saved.")
        self.cart.clear()
        self.refresh_header()
        self.refresh_cart()

    def print_token(self):
        if not self.receipt_preview.toPlainText().strip():
            QMessageBox.information(self, "Print Token", "No token preview to print.")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.receipt_preview.print(printer)

    def generate_bill_pdf(
        self,
        token_no: int,
        cart: list[dict],
        subtotal: float,
        discount: float,
        total: float,
        payment_mode: str,
    ) -> Path | None:
        try:
            from reportlab.graphics.barcode import code128
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import inch, mm
            from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except ImportError:
            QMessageBox.warning(
                self,
                "ReportLab Missing",
                "Install reportlab to generate the 3-inch bill PDF: pip install reportlab",
            )
            return None

        settings = self.db.settings()
        receipt_dir = Path(__file__).resolve().parent / "receipts"
        receipt_dir.mkdir(exist_ok=True)
        output_path = receipt_dir / f"token_{token_no}.pdf"

        width = 3 * inch
        left_margin = 4 * mm
        right_margin = 4 * mm
        usable_width = width - left_margin - right_margin

        styles = getSampleStyleSheet()
        center = ParagraphStyle("ReceiptCenter", parent=styles["Normal"], alignment=TA_CENTER, fontSize=8, leading=10)
        left = ParagraphStyle("ReceiptLeft", parent=styles["Normal"], alignment=TA_LEFT, fontSize=8, leading=10)
        right = ParagraphStyle("ReceiptRight", parent=styles["Normal"], alignment=TA_RIGHT, fontSize=8, leading=10)
        title = ParagraphStyle("ReceiptTitle", parent=center, fontSize=11, leading=13)
        table_text = ParagraphStyle("ReceiptTableText", parent=left, fontSize=7, leading=9, wordWrap="CJK")

        sold_at = datetime.now()
        bill_no = f"Token No.: {token_no}"
        date_time = sold_at.strftime("%d-%m-%Y %I:%M %p")

        content = []
        logo_path = Path(settings.logo) if settings.logo else None
        if logo_path and logo_path.exists():
            logo = Image(str(logo_path))
            logo._restrictSize(usable_width, 18 * mm)
            logo.hAlign = "CENTER"
            content.append(logo)
            content.append(Spacer(1, 3))

        content.append(Paragraph(f"<b>{settings.cafe_name}</b>", title))
        if settings.address and settings.address != "Add later":
            content.append(Paragraph(settings.address, center))
        if settings.phone and settings.phone != "Optional":
            content.append(Paragraph(f"Phone: {settings.phone}", center))

        solid_line = HRFlowable(width="100%", thickness=0.8, color=colors.black)
        dotted_line = HRFlowable(width="100%", thickness=0.8, dash=(2, 2), color=colors.black)
        content.append(solid_line)
        content.append(Paragraph("<b>Sales Bill</b>", center))
        content.append(solid_line)

        bill_row = [[Paragraph(bill_no, left), Paragraph(date_time, right)]]
        bill_table = Table(bill_row, colWidths=[usable_width * 0.45, usable_width * 0.55])
        bill_table.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        content.append(bill_table)
        content.append(solid_line)
        content.append(Spacer(1, 3))

        table_data = [["S.No", "Item", "Price", "Qty", "Total"]]
        for index, item in enumerate(cart, start=1):
            line_total = item["qty"] * item["price"]
            table_data.append([
                str(index),
                Paragraph(item["name"], table_text),
                f"{item['price']:.2f}",
                str(item["qty"]),
                f"{line_total:.2f}",
            ])

        col_widths = [
            usable_width * 0.12,
            usable_width * 0.40,
            usable_width * 0.16,
            usable_width * 0.10,
            usable_width * 0.22,
        ]
        items_table = Table(table_data, colWidths=col_widths)
        items_table.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (1, 0), (1, -1), "LEFT"),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ("ALIGN", (3, 0), (3, -1), "CENTER"),
            ("ALIGN", (4, 0), (4, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.white),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]))
        content.append(items_table)
        content.append(Spacer(1, 4))
        content.append(solid_line)
        content.append(Paragraph(f"Subtotal : Rs {subtotal:.2f}", right))
        if discount > 0:
            content.append(Paragraph(f"Discount : - Rs {discount:.2f}", right))
        content.append(dotted_line)
        content.append(Paragraph(f"<b>Grand Total : Rs {total:.2f}</b>", right))
        content.append(Paragraph(f"Payment : {payment_mode}", right))
        content.append(dotted_line)
        content.append(Spacer(1, 5))
        content.append(Paragraph(settings.footer_text, center))
        content.append(Spacer(1, 5))

        barcode = code128.Code128(str(token_no), barHeight=10 * mm, barWidth=0.35)
        barcode.hAlign = "CENTER"
        content.append(barcode)
        content.append(Paragraph(str(token_no), center))

        def calculate_height(flowables, available_width):
            total_height = 0
            for flowable in flowables:
                _, height = flowable.wrap(available_width, 1000)
                total_height += height
            return total_height

        final_height = calculate_height(content, usable_width) + 16 * mm
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=(width, final_height),
            leftMargin=left_margin,
            rightMargin=right_margin,
            topMargin=4 * mm,
            bottomMargin=0,
        )
        doc.build(content)
        return output_path

    def print_bill_pdf(self):
        if not self.last_bill_pdf or not self.last_bill_pdf.exists():
            QMessageBox.information(self, "Print Bill", "No generated bill PDF found.")
            return
        try:
            os.startfile(str(self.last_bill_pdf), "print")
        except OSError:
            os.startfile(str(self.last_bill_pdf))

    def go_back(self):
        if self.cart:
            reply = QMessageBox.question(
                self,
                "Leave Billing",
                "Cart has unsaved items. Do you want to leave?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.close()

    def open_add_item(self):
        dialog = AddItemDialog(self.db, self)
        if dialog.exec():
            self.refresh_categories()
            self.refresh_items()

    def open_analysis(self):
        dialog = AnalysisDialog(self.db, self)
        dialog.exec()

    def preview_receipt(self, token_no: int, preview: bool = False) -> str:
        now = datetime.now()
        cart = self.cart or [
            {"name": "Tea", "qty": 1, "price": 12},
            {"name": "Samosa", "qty": 2, "price": 15},
        ]
        lines = [
            self.settings.cafe_name,
            f"TOKEN NO: {token_no}",
            "",
            f"Date: {now.strftime('%d-%m-%Y')}",
            f"Time: {now.strftime('%I:%M %p')}",
            "",
        ]
        for item in cart:
            total = item["qty"] * item["price"]
            lines.append(f"{item['name']:<14} x{item['qty']:<3} {RUPEE}{total:.0f}")
        subtotal = sum(item["qty"] * item["price"] for item in cart)
        discount = self.discount_amount(subtotal) if self.cart else 0
        total = int(max(0, subtotal - discount))
        lines.extend(
            [
                "",
                "----------------------",
                f"TOTAL:{(RUPEE + str(total)):>17}",
                "",
                self.settings.footer_text,
            ]
        )
        if preview and not self.cart:
            lines.insert(0, "Sample token preview")
            lines.insert(1, "")
        return "\n".join(lines)

    def open_settings(self):
        dialog = SettingsDialog(self.db, self)
        if dialog.exec():
            self.refresh_header()
            self.refresh_cart()


def apply_style(app: QApplication):
    app.setStyleSheet(
        """
        QWidget {
            font-family: Segoe UI, Arial, sans-serif;
            font-size: 10pt;
            color: #1d1d1f;
        }
        QMainWindow, QWidget#AppRoot {
            background: #f5f5f7;
        }
        QDialog {
            background: #f5f5f7;
            color: #1d1d1f;
        }
        QDialog#AnalysisDialog {
            background: #f5f5f7;
        }
        QFrame#TopBar, QFrame#Sidebar, QFrame#ProductsPanel, QFrame#OrderControls, QFrame#CartPanel {
            background: #ffffff;
            border: 1px solid #d2d2d7;
            border-radius: 14px;
        }
        QWidget#BrandWrap {
            min-width: 250px;
            max-width: 250px;
            background: transparent;
        }
        QLabel#BrandLogo {
            background: transparent;
        }
        QLabel#BrandLabel {
            background: transparent;
        }
        QLabel#DialogTitle {
            font-size: 18pt;
            font-weight: 900;
            color: #1d1d1f;
            min-width: 178px;
        }
        QLineEdit, QComboBox {
            min-height: 32px;
            border: 1px solid #d2d2d7;
            border-radius: 9px;
            padding: 4px 10px;
            background: #ffffff;
            color: #1d1d1f;
        }
        QPushButton, QToolButton {
            min-height: 30px;
            border: 1px solid #d2d2d7;
            border-radius: 9px;
            padding: 4px 11px;
            background: #ffffff;
            font-weight: 600;
            color: #1d1d1f;
        }
        QPushButton:hover, QToolButton:hover {
            background: #f5f5f7;
            border-color: #007aff;
        }
        QPushButton#GhostButton {
            color: #007aff;
            border: 0;
            text-decoration: underline;
        }
        QPushButton#CartClearButton {
            color: #007aff;
            border: 0;
            background: transparent;
            text-decoration: underline;
            min-height: 22px;
            padding: 0;
        }
        QPushButton#OrangeButton, QPushButton#PlaceOrderButton, QPushButton#PrimaryButton {
            background: #007aff;
            color: #ffffff;
            border-color: #007aff;
            font-weight: 800;
        }
        QPushButton#PlaceOrderButton {
            min-height: 42px;
            border-radius: 6px;
        }
        QPushButton#PrintButton {
            color: #007aff;
            background: #f5f5f7;
        }
        QToolButton#IconButton {
            color: #007aff;
            background: #f5f5f7;
            border-color: #d2d2d7;
        }
        QPushButton#CategoryButton {
            border: 0;
            border-radius: 10px;
            min-height: 46px;
            text-align: left;
            padding-left: 28px;
            padding-right: 0;
            margin: 6px 8px;
            background: transparent;
            color: #1d1d1f;
        }
        QPushButton#CategoryButton:checked {
            background: #007aff;
            color: white;
            font-weight: 800;
        }
        QLabel#ControlLabel {
            font-size: 8pt;
            font-weight: 800;
            color: #1d1d1f;
        }
        QWidget#OrderTypeToggle {
            background: transparent;
            border: 0;
        }
        QLabel#ToggleLabel {
            color: #1d1d1f;
            font-weight: 800;
            font-size: 8pt;
        }
        QCheckBox#OrderSwitch {
            min-width: 56px;
            max-width: 56px;
            min-height: 32px;
            max-height: 32px;
            spacing: 0;
            background: transparent;
            border: 0;
        }
        QRadioButton#PaymentButton::indicator {
            width: 0;
            height: 0;
        }
        QScrollArea#ProductsScroll {
            border: 0;
            background: #ffffff;
        }
        QWidget#ProductsContainer {
            background: #ffffff;
        }
        QFrame#ProductCard {
            background: #ffffff;
            border: 2px solid #bebebe;
            border-radius: 10px;
            min-width: 176px;
            max-width: 176px;
            min-height: 238px;
            max-height: 238px;
        }
        QFrame#ProductCard:hover {
            border: 2px solid #bebebe;
            background: #ffffff;
        }
        QFrame#ProductImageWrap {
            background: #f5f5f7;
            border: 0;
            border-radius: 8px;
        }
        QLabel#ProductImage {
            border-radius: 8px;
            background: #e5e5ea;
        }
        QLabel#ProductName {
            font-size: 12pt;
            font-weight: 800;
            color: #1d1d1f;
        }
        QLabel#ProductSecondary {
            font-size: 9pt;
            color: #6e6e73;
        }
        QLabel#CartTitle {
            font-size: 14pt;
            font-weight: 900;
            color: #1d1d1f;
        }
        QLabel#OrderNumber {
            font-size: 8pt;
            font-weight: 800;
            color: #007aff;
        }
        QLabel#CartDate {
            font-size: 8pt;
            color: #6e6e73;
        }
        QScrollArea#CartItemsScroll {
            border: 0;
            background: transparent;
        }
        QWidget#CartItemsContainer {
            background: transparent;
        }
        QFrame#CartItemRow {
            border-bottom: 1px solid #e5e5ea;
            background: transparent;
            min-height: 56px;
            max-height: 56px;
        }
        QLabel#CartItemTitle {
            font-size: 9pt;
            font-weight: 800;
            color: #1d1d1f;
        }
        QLabel#CartItemPrice {
            font-size: 8pt;
            font-weight: 800;
            color: #6e6e73;
        }
        QToolButton#RoundQty {
            min-width: 21px;
            max-width: 21px;
            min-height: 21px;
            max-height: 21px;
            border-radius: 10px;
            color: #ffffff;
            background: #007aff;
            border-color: #007aff;
            padding: 0;
        }
        QLabel#QtyNumber {
            min-width: 18px;
            qproperty-alignment: AlignCenter;
            font-weight: 900;
            color: #007aff;
        }
        QToolButton#RemoveButton {
            min-width: 21px;
            max-width: 21px;
            min-height: 21px;
            max-height: 21px;
            border: 0;
            color: #6e6e73;
            background: transparent;
            padding: 0;
        }
        QLabel#SummaryLabel, QLabel#SummaryValue {
            font-size: 9pt;
            font-weight: 700;
        }
        QLineEdit#DiscountInput {
            min-width: 86px;
            max-width: 110px;
            min-height: 26px;
            border: 1px solid #d2d2d7;
            border-radius: 8px;
            padding: 2px 6px;
            background: #ffffff;
            color: #1d1d1f;
            font-weight: 700;
        }
        QLabel#CartTotalValue {
            font-size: 10pt;
            font-weight: 900;
            color: #1d1d1f;
        }
        QLabel#PaymentTitle {
            font-size: 9pt;
            font-weight: 900;
            color: #1d1d1f;
        }
        QRadioButton#PaymentButton {
            min-height: 36px;
            border: 1px solid #d2d2d7;
            border-radius: 9px;
            padding: 4px 8px;
            background: #ffffff;
            font-size: 8pt;
            color: #1d1d1f;
        }
        QRadioButton#PaymentButton:checked {
            color: white;
            background: #007aff;
            border-color: #007aff;
            font-weight: 800;
        }
        QLabel#EmptyCart {
            color: #6e6e73;
            padding: 20px 0;
        }
        QTableWidget {
            background: #ffffff;
            alternate-background-color: #fbfbfd;
            color: #1d1d1f;
            gridline-color: #e5e5ea;
            border: 1px solid #d2d2d7;
            border-radius: 6px;
        }
        QTableWidget::viewport {
            background: #ffffff;
        }
        QTableCornerButton::section {
            background: #f5f5f7;
            border: 0;
        }
        QHeaderView::section {
            background: #f5f5f7;
            color: #1d1d1f;
            border: 0;
            border-bottom: 1px solid #d2d2d7;
            padding: 7px;
            font-weight: 700;
        }
        QHeaderView {
            background: #ffffff;
        }
        QLabel#AnalysisTitle {
            font-size: 18pt;
            font-weight: 900;
            color: #1d1d1f;
        }
        QFrame#KpiCard, QFrame#AnalysisPanel {
            background: #ffffff;
            border: 1px solid #d2d2d7;
            border-radius: 14px;
        }
        QLabel#KpiLabel {
            color: #6e6e73;
            font-size: 9pt;
            font-weight: 700;
        }
        QLabel#KpiValue {
            color: #1d1d1f;
            font-size: 18pt;
            font-weight: 900;
        }
        QLabel#AnalysisPanelTitle {
            color: #1d1d1f;
            font-size: 13pt;
            font-weight: 900;
        }
        QLabel#AnalysisTotal {
            color: #1d1d1f;
            font-size: 11pt;
            font-weight: 900;
        }
        """
    )


def default_database_path() -> Path | None:
    base_dir = Path(__file__).resolve().parent
    preferred = base_dir / "sasthik_cafe.sqlite3"
    if preferred.exists():
        return preferred

    candidates = []
    for pattern in ("*.sqlite3", "*.db", "*.sqlite", "*.db3"):
        candidates.extend(base_dir.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def main():
    app = QApplication(sys.argv)
    apply_style(app)

    db_path = default_database_path()
    if db_path is None:
        startup = StartupDialog()
        if startup.exec() != QDialog.DialogCode.Accepted or startup.db_path is None:
            return 0
        db_path = startup.db_path

    try:
        db = Database(db_path)
    except sqlite3.Error as exc:
        QMessageBox.critical(None, "Database Error", str(exc))
        return 1

    window = MainWindow(db)
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
