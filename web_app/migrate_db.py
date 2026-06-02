import sqlite3

conn = sqlite3.connect('carpets.db')
cursor = conn.cursor()

# Проверяем, существует ли колонка image_path
cursor.execute("PRAGMA table_info(carpet)")
columns = [col[1] for col in cursor.fetchall()]

if 'image_path' not in columns:
    cursor.execute("ALTER TABLE carpet ADD COLUMN image_path TEXT")
    print("✅ Добавлена колонка image_path")
else:
    print("⚠️ Колонка image_path уже существует")

conn.commit()
conn.close()
print("✅ Миграция завершена")