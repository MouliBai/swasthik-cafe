# SASTHIK CAFE Token POS Prototype

Desktop POS prototype built with Python, PyQt6, and SQLite.

## Run

```powershell
pip install -r requirements.txt
python pos_app.py
```

On startup, type or browse for a database file name. If the file already exists,
the app opens it. If it does not exist, the app creates the SQLite schema and
adds starter cafe items automatically.

## Included

- SASTHIK CAFE header with token POS layout
- F10 item search
- Menu item list and cart
- Quantity editing and item removal
- Hold and recall order
- Sale completion with token number
- Token print preview
- Company settings stored in SQLite

