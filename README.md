# SWASTHIK CAFE Token Billing Prototype

Desktop cafe billing prototype built with Python, PyQt6, and SQLite.

## Run

```powershell
pip install -r requirements.txt
python pos_app.py
```

On startup, type or browse for a database file name. If the file already exists,
the app opens it. If it does not exist, the app creates the SQLite schema and
adds starter cafe items automatically.

If a SQLite database already exists in this folder, the app opens it directly.
It only asks for a database name when no `.sqlite3`, `.db`, `.sqlite`, or `.db3`
file is found.

## Included

- Screenshot-style cafe billing counter layout
- SWASTHIK CAFE header with product search
- Separate `image` and `icon` asset folders
- Separate `image_links.py` and `icon_links.py` path files
- Left category sidebar
- Cafe product cards with generated thumbnails
- Add New Item popup with category, price, and image picker
- Order type, discount, and note controls
- Right cart panel with payment method
- F10 item search
- Quantity editing and item removal
- Hold and recall order
- Place order with token number
- Token print support
- 3-inch PDF bill generation with ReportLab
- Company settings mapped to bill name, phone, address, footer, and logo image
- Company settings stored in SQLite
