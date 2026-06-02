#!/usr/bin/env python3
"""Полная перезагрузка базы данных"""

import os
import sys

# Удаляем все БД
for root, dirs, files in os.walk('.'):
    for file in files:
        if file.endswith('.db') or file.endswith('.db-shm') or file.endswith('.db-wal'):
            os.remove(os.path.join(root, file))
            print(f"Удалён: {file}")

# Удаляем instance
if os.path.exists('instance'):
    import shutil
    shutil.rmtree('instance')
    print("Удалена папка instance")

# Импортируем приложение и создаём таблицы
from app import app, db

with app.app_context():
    db.create_all()
    print("✅ База данных создана с новой структурой")
    print("✅ Колонка image_path добавлена")
    