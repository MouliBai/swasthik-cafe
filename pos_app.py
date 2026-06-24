import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QFont, QKeySequence
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


APP_TITLE = "SASTHIK CAFE - Token POS"
DEFAULT_FOOTER = "Please collect your order at counter"


@dataclass
class CompanySettings:
    cafe_name: str = "SASTHIK CAFE"
    logo: str = "Add later"
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
                active INTEGER NOT NULL DEFAULT 1
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
        self._seed_settings()
        self._seed_items()
        self.conn.commit()

    def _seed_settings(self):
        defaults = CompanySettings().__dict__
        for key, value in defaults.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO company_settings(key, value) VALUES (?, ?)",
                (key, value),
            )

    def _seed_items(self):
        count = self.conn.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0]
        if count:
            return
        items = [
            ("Tea", "Beverages", 12),
            ("Coffee", "Beverages", 20),
            ("Boost", "Beverages", 25),
            ("Lemon Tea", "Beverages", 18),
            ("Samosa", "Snacks", 15),
            ("Veg Puff", "Snacks", 22),
            ("Egg Puff", "Snacks", 28),
            ("Masala Dosa", "Breakfast", 45),
            ("Idli Plate", "Breakfast", 35),
            ("Poori", "Breakfast", 40),
            ("Veg Sandwich", "Snacks", 50),
            ("Water Bottle", "Beverages", 20),
        ]
        self.conn.executemany(
            "INSERT INTO menu_items(name, category, price) VALUES (?, ?, ?)", items
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

    def menu_items(self, search_text: str = ""):
        search = f"%{search_text.strip()}%"
        return self.conn.execute(
            """
            SELECT id, name, category, price
            FROM menu_items
            WHERE active = 1
              AND (? = '%%' OR name LIKE ? OR category LIKE ?)
            ORDER BY category, name
            """,
            (search, search, search),
        ).fetchall()

    def next_token_no(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(token_no), 104) + 1 FROM sales").fetchone()
        return int(row[0])

    def save_sale(self, token_no: int, cart: list[dict], total: float) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO sales(token_no, sold_at, total) VALUES (?, ?, ?)",
            (token_no, now, total),
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
        row = self.conn.execute(
            "SELECT cart_json FROM held_orders WHERE id = ?", (hold_id,)
        ).fetchone()
        if not row:
            return []
        self.conn.execute("DELETE FROM held_orders WHERE id = ?", (hold_id,))
        self.conn.commit()
        return json.loads(row["cart_json"])


class StartupDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Open POS Database")
        self.setMinimumWidth(560)
        self.db_path: Path | None = None

        title = QLabel("SASTHIK CAFE")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("Choose an existing SQLite DB or type a new DB filename to create it.")

        self.path_edit = QLineEdit(str(Path.cwd() / "sasthik_cafe.sqlite3"))
        self.path_edit.setPlaceholderText("Example: C:\\Cafe\\sasthik_cafe.sqlite3")

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse)

        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse_btn)

        open_btn = QPushButton("Start POS")
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
        self.address = QLineEdit(settings.address)
        self.phone = QLineEdit(settings.phone)
        self.footer_text = QLineEdit(settings.footer_text)

        form = QFormLayout()
        form.addRow("Cafe Name", self.cafe_name)
        form.addRow("Logo", self.logo)
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
                cafe_name=self.cafe_name.text().strip() or "SASTHIK CAFE",
                logo=self.logo.text().strip() or "Add later",
                address=self.address.text().strip() or "Add later",
                phone=self.phone.text().strip() or "Optional",
                footer_text=self.footer_text.text().strip() or DEFAULT_FOOTER,
            )
        )
        self.accept()


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


class MainWindow(QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.settings = db.settings()
        self.cart: list[dict] = []
        self.last_receipt = ""

        self.setWindowTitle(APP_TITLE)
        self.resize(1220, 760)
        self.setup_actions()
        self.setup_ui()
        self.refresh_header()
        self.refresh_items()
        self.refresh_cart()

    def setup_actions(self):
        settings_action = QAction("Company Settings", self)
        settings_action.triggered.connect(self.open_settings)
        self.menuBar().addAction(settings_action)

        focus_search = QAction("Search Item", self)
        focus_search.setShortcut(QKeySequence("F10"))
        focus_search.triggered.connect(lambda: self.search_edit.setFocus())
        self.addAction(focus_search)

    def setup_ui(self):
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(16, 12, 16, 16)
        root_layout.setSpacing(12)

        header = QGroupBox()
        header.setObjectName("HeaderBox")
        header_layout = QGridLayout(header)

        self.brand_label = QLabel()
        self.brand_label.setObjectName("BrandLabel")
        self.mode_label = QLabel("Token POS / Sales Bill")
        self.mode_label.setObjectName("ModeLabel")

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search item [F10]")
        self.search_edit.textChanged.connect(self.refresh_items)

        hold_btn = QToolButton()
        hold_btn.setText("Hold")
        hold_btn.clicked.connect(self.hold_cart)

        recall_btn = QToolButton()
        recall_btn.setText("Recall")
        recall_btn.clicked.connect(self.recall_cart)

        user_label = QLabel("User: Counter")
        user_label.setObjectName("UserLabel")

        header_layout.addWidget(self.brand_label, 0, 0)
        header_layout.addWidget(self.mode_label, 0, 2, alignment=Qt.AlignmentFlag.AlignRight)
        header_layout.addWidget(self.search_edit, 1, 0)
        header_layout.addWidget(hold_btn, 1, 1)
        header_layout.addWidget(recall_btn, 1, 2)
        header_layout.addWidget(user_label, 1, 3)
        header_layout.setColumnStretch(0, 1)

        splitter = QSplitter()

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_title = QLabel("Menu")
        left_title.setObjectName("SectionTitle")
        self.items_table = QTableWidget(0, 4)
        self.items_table.setHorizontalHeaderLabels(["ID", "Item", "Category", "Price"])
        self.items_table.hideColumn(0)
        self.items_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.items_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.items_table.doubleClicked.connect(self.add_selected_item)
        add_btn = QPushButton("Add Selected Item")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self.add_selected_item)
        left_layout.addWidget(left_title)
        left_layout.addWidget(self.items_table)
        left_layout.addWidget(add_btn)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)

        token_row = QHBoxLayout()
        self.token_label = QLabel()
        self.token_label.setObjectName("TokenLabel")
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_cart)
        token_row.addWidget(self.token_label)
        token_row.addStretch(1)
        token_row.addWidget(clear_btn)

        self.cart_table = QTableWidget(0, 5)
        self.cart_table.setHorizontalHeaderLabels(["Item", "Qty", "Price", "Total", ""])
        self.cart_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.cart_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cart_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        total_row = QHBoxLayout()
        total_caption = QLabel("TOTAL")
        total_caption.setObjectName("TotalCaption")
        self.total_label = QLabel("₹0")
        self.total_label.setObjectName("TotalAmount")
        total_row.addWidget(total_caption)
        total_row.addStretch(1)
        total_row.addWidget(self.total_label)

        bill_btn = QPushButton("Complete Sale + Token")
        bill_btn.setObjectName("CheckoutButton")
        bill_btn.clicked.connect(self.complete_sale)

        print_btn = QPushButton("Print Token")
        print_btn.clicked.connect(self.print_token)

        self.receipt_preview = QTextEdit()
        self.receipt_preview.setReadOnly(True)
        self.receipt_preview.setObjectName("ReceiptPreview")
        self.receipt_preview.setFont(QFont("Consolas", 10))

        right_layout.addLayout(token_row)
        right_layout.addWidget(self.cart_table, 2)
        right_layout.addLayout(total_row)
        right_layout.addWidget(bill_btn)
        right_layout.addWidget(print_btn)
        right_layout.addWidget(QLabel("Token Print Preview"))
        right_layout.addWidget(self.receipt_preview, 1)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([680, 520])

        root_layout.addWidget(header)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

    def refresh_header(self):
        self.settings = self.db.settings()
        self.brand_label.setText(self.settings.cafe_name)
        self.token_label.setText(f"Token No: {self.db.next_token_no()}")

    def refresh_items(self):
        rows = self.db.menu_items(self.search_edit.text() if hasattr(self, "search_edit") else "")
        self.items_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (row["id"], row["name"], row["category"], f"₹{row['price']:.0f}")
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.items_table.setItem(row_index, col, item)

    def add_selected_item(self):
        selected = self.items_table.selectionModel().selectedRows()
        if not selected:
            return
        row_index = selected[0].row()
        item_id = int(self.items_table.item(row_index, 0).text())
        name = self.items_table.item(row_index, 1).text()
        price = float(self.items_table.item(row_index, 3).text().replace("₹", ""))
        self.add_to_cart(item_id, name, price)

    def add_to_cart(self, item_id: int, name: str, price: float):
        for item in self.cart:
            if item["id"] == item_id:
                item["qty"] += 1
                self.refresh_cart()
                return
        self.cart.append({"id": item_id, "name": name, "price": price, "qty": 1})
        self.refresh_cart()

    def refresh_cart(self):
        self.cart_table.setRowCount(len(self.cart))
        for row, item in enumerate(self.cart):
            line_total = item["qty"] * item["price"]
            self.cart_table.setItem(row, 0, QTableWidgetItem(item["name"]))

            qty_spin = QSpinBox()
            qty_spin.setRange(1, 999)
            qty_spin.setValue(item["qty"])
            qty_spin.valueChanged.connect(lambda value, index=row: self.change_qty(index, value))
            self.cart_table.setCellWidget(row, 1, qty_spin)

            self.cart_table.setItem(row, 2, QTableWidgetItem(f"₹{item['price']:.0f}"))
            self.cart_table.setItem(row, 3, QTableWidgetItem(f"₹{line_total:.0f}"))

            remove_btn = QPushButton("Remove")
            remove_btn.clicked.connect(lambda _, index=row: self.remove_cart_item(index))
            self.cart_table.setCellWidget(row, 4, remove_btn)

        total = sum(item["qty"] * item["price"] for item in self.cart)
        self.total_label.setText(f"₹{total:.0f}")
        if not self.last_receipt:
            self.receipt_preview.setPlainText(self.preview_receipt(self.db.next_token_no(), preview=True))

    def change_qty(self, index: int, value: int):
        if 0 <= index < len(self.cart):
            self.cart[index]["qty"] = value
            self.refresh_cart()

    def remove_cart_item(self, index: int):
        if 0 <= index < len(self.cart):
            self.cart.pop(index)
            self.last_receipt = ""
            self.refresh_cart()

    def clear_cart(self):
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
            self.last_receipt = ""
            self.refresh_cart()

    def complete_sale(self):
        if not self.cart:
            QMessageBox.information(self, "Complete Sale", "Add at least one item.")
            return
        token_no = self.db.next_token_no()
        total = sum(item["qty"] * item["price"] for item in self.cart)
        self.db.save_sale(token_no, self.cart, total)
        self.last_receipt = self.preview_receipt(token_no, preview=False)
        self.receipt_preview.setPlainText(self.last_receipt)
        QMessageBox.information(self, "Sale Complete", f"Token {token_no} saved.")
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
            lines.append(f"{item['name']:<12} x{item['qty']:<3} ₹{total:.0f}")
        lines.extend(
            [
                "",
                "----------------------",
                f"TOTAL:{'₹' + str(int(sum(item['qty'] * item['price'] for item in cart))):>17}",
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
            self.last_receipt = ""
            self.refresh_cart()


def apply_style(app: QApplication):
    app.setStyleSheet(
        """
        QWidget {
            font-family: Segoe UI, Arial, sans-serif;
            font-size: 11pt;
            color: #1d252c;
        }
        QMainWindow {
            background: #f4f6f2;
        }
        QGroupBox#HeaderBox {
            background: #ffffff;
            border: 1px solid #d9dfd2;
            border-radius: 8px;
            padding: 14px;
        }
        QLabel#BrandLabel, QLabel#DialogTitle {
            font-size: 24pt;
            font-weight: 800;
            color: #233024;
        }
        QLabel#ModeLabel, QLabel#UserLabel {
            color: #52605a;
            font-weight: 600;
        }
        QLabel#SectionTitle, QLabel#TokenLabel {
            font-size: 15pt;
            font-weight: 700;
        }
        QLabel#TotalCaption {
            font-size: 18pt;
            font-weight: 800;
        }
        QLabel#TotalAmount {
            font-size: 28pt;
            font-weight: 900;
            color: #086c4d;
        }
        QLineEdit {
            min-height: 34px;
            border: 1px solid #c9d2c3;
            border-radius: 6px;
            padding: 4px 10px;
            background: #ffffff;
        }
        QPushButton, QToolButton {
            min-height: 34px;
            border: 1px solid #b8c4b2;
            border-radius: 6px;
            padding: 5px 14px;
            background: #ffffff;
            font-weight: 600;
        }
        QPushButton:hover, QToolButton:hover {
            background: #edf4e9;
        }
        QPushButton#PrimaryButton {
            background: #176b4d;
            color: white;
            border-color: #176b4d;
        }
        QPushButton#CheckoutButton {
            background: #cc4f24;
            color: #ffffff;
            border-color: #cc4f24;
            min-height: 44px;
            font-size: 14pt;
            font-weight: 800;
        }
        QTableWidget {
            background: #ffffff;
            gridline-color: #e2e7dd;
            border: 1px solid #d9dfd2;
            border-radius: 6px;
        }
        QHeaderView::section {
            background: #edf1e8;
            border: 0;
            border-bottom: 1px solid #d3dacd;
            padding: 7px;
            font-weight: 700;
        }
        QTextEdit#ReceiptPreview {
            background: #fffef8;
            border: 1px solid #d6cfb8;
            border-radius: 6px;
            padding: 10px;
        }
        """
    )


def main():
    app = QApplication(sys.argv)
    apply_style(app)

    startup = StartupDialog()
    if startup.exec() != QDialog.DialogCode.Accepted or startup.db_path is None:
        return 0

    try:
        db = Database(startup.db_path)
    except sqlite3.Error as exc:
        QMessageBox.critical(None, "Database Error", str(exc))
        return 1

    window = MainWindow(db)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
