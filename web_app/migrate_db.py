# migrate_db.py
import sqlite3
import os

DB_PATH = '/Users/andrejkrylov/Desktop/fist/carpet-manager/web_app/CarpetManagerData/carpets.db'

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Проверяем и добавляем колонку account_id
try:
    cursor.execute("ALTER TABLE marketplace_order ADD COLUMN account_id INTEGER")
    print("✓ Добавлена колонка account_id")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("✓ Колонка account_id уже существует")
    else:
        print(f"Ошибка: {e}")

# Проверяем и добавляем колонку wb_supply_id
try:
    cursor.execute("ALTER TABLE marketplace_order ADD COLUMN wb_supply_id VARCHAR(50)")
    print("✓ Добавлена колонка wb_supply_id")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("✓ Колонка wb_supply_id уже существует")
    else:
        print(f"Ошибка: {e}")

# Проверяем и добавляем колонку ozon_posting_number
try:
    cursor.execute("ALTER TABLE marketplace_order ADD COLUMN ozon_posting_number VARCHAR(50)")
    print("✓ Добавлена колонка ozon_posting_number")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("✓ Колонка ozon_posting_number уже существует")
    else:
        print(f"Ошибка: {e}")

# Проверяем и добавляем колонку for marketplace_account
try:
    cursor.execute("ALTER TABLE marketplace_account ADD COLUMN account_name VARCHAR(100)")
    print("✓ Добавлена колонка account_name")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("✓ Колонка account_name уже существует")
    else:
        print(f"Ошибка: {e}")

try:
    cursor.execute("ALTER TABLE marketplace_account ADD COLUMN account_login VARCHAR(100)")
    print("✓ Добавлена колонка account_login")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("✓ Колонка account_login уже существует")
    else:
        print(f"Ошибка: {e}")

try:
    cursor.execute("ALTER TABLE marketplace_account ADD COLUMN client_id VARCHAR(100)")
    print("✓ Добавлена колонка client_id")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("✓ Колонка client_id уже существует")
    else:
        print(f"Ошибка: {e}")

# Создаём недостающие таблицы
cursor.execute("""
CREATE TABLE IF NOT EXISTS marketplace_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER,
    sync_time VARCHAR(20),
    orders_found INTEGER,
    orders_new INTEGER,
    error_message TEXT,
    status VARCHAR(20)
)
""")
print("✓ Таблица marketplace_sync_log создана/проверена")

conn.commit()
conn.close()
print("\n✅ Миграция завершена!")