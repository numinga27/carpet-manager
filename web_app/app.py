from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import sys
import qrcode
import webbrowser
import threading
import time
import io
import zipfile
import socket
from collections import defaultdict
import requests
import json
import traceback

# ========== ПОДДЕРЖКА РУССКОГО ШРИФТА ДЛЯ PDF ==========
try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    
    font_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        os.path.join(os.path.dirname(__file__), 'LiberationSans-Regular.ttf'),
    ]
    
    FONT_REGISTERED = False
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont('RussianFont', font_path))
                FONT_REGISTERED = True
                print(f"[FONT] Русский шрифт загружен: {font_path}")
                break
            except Exception as e:
                print(f"[FONT] Ошибка: {e}")
    
    if not FONT_REGISTERED:
        print("[FONT] ⚠️ Русский шрифт не найден, используется стандартный")
except ImportError:
    print("[FONT] ReportLab не установлен")
    FONT_REGISTERED = False
# ===============================================

# ========== ОБРАБОТЧИК НЕОТЛОВЛЕННЫХ ИСКЛЮЧЕНИЙ ==========
def exception_handler(exc_type, exc_value, exc_traceback):
    """Обработчик неотловленных исключений для EXE"""
    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print(f"Unhandled exception: {error_msg}")
    
    # Пытаемся записать в файл лога
    try:
        log_path = os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd(), 'error.log')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(f"Time: {datetime.now()}\n")
            f.write(error_msg)
    except:
        pass

# Устанавливаем обработчик
sys.excepthook = exception_handler

# ========== ОПРЕДЕЛЕНИЕ ПУТЕЙ ==========
if getattr(sys, 'frozen', False):
    base_path = os.path.dirname(sys.executable)
else:
    base_path = os.path.dirname(__file__)

# Функция для поиска доступной папки для данных
def find_data_folder():
    """Поиск доступной папки для хранения данных"""
    possible_folders = []
    
    # 1. Папка рядом с программой
    local_folder = os.path.join(base_path, 'CarpetManagerData')
    possible_folders.append(local_folder)
    
    # 2. AppData (Windows)
    if sys.platform == 'win32':
        appdata_folder = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'CarpetManager')
        possible_folders.append(appdata_folder)
    
    # 3. Документы пользователя
    docs_folder = os.path.join(os.path.expanduser('~'), 'Documents', 'CarpetManager')
    possible_folders.append(docs_folder)
    
    # 4. TEMP папка
    temp_folder = os.path.join(os.environ.get('TEMP', os.path.expanduser('~')), 'CarpetManager')
    possible_folders.append(temp_folder)
    
    # 5. Папка с программой (последний шанс)
    program_folder = base_path
    possible_folders.append(program_folder)
    
    for folder in possible_folders:
        try:
            os.makedirs(folder, exist_ok=True)
            # Проверяем возможность записи
            test_file = os.path.join(folder, '.write_test')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            print(f"[FOLDER] Найдена доступная папка: {folder}")
            return folder
        except Exception as e:
            print(f"[FOLDER] Папка {folder} недоступна: {e}")
            continue
    
    # Если ничего не подошло, используем текущую папку
    print(f"[FOLDER] Использую папку по умолчанию: {base_path}")
    return base_path

DATA_FOLDER = find_data_folder()
template_folder = os.path.join(base_path, 'templates')
app = Flask(__name__, template_folder=template_folder)

DB_PATH = os.path.join(DATA_FOLDER, 'carpets.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key-here'

db = SQLAlchemy(app)

QR_FOLDER = os.path.join(DATA_FOLDER, 'qr_codes')
os.makedirs(QR_FOLDER, exist_ok=True)

print(f"[DB] База данных: {DB_PATH}")
print(f"[QR] QR-коды: {QR_FOLDER}")

# ========== ФУНКЦИЯ ПОИСКА ПОРТА ==========
def find_free_port():
    preferred_ports = [5000, 5001, 5002, 8080, 8081, 3000, 8000, 8888]
    for port in preferred_ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                s.listen(1)
                print(f"[OK] Свободный порт: {port}")
                return port
        except OSError:
            continue
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            port = s.getsockname()[1]
            print(f"[OK] Свободный порт (авто): {port}")
            return port
    except:
        print("[ERROR] Не найден свободный порт!")
        return 8080

# ========== МОДЕЛИ ДАННЫХ ==========
class CarpetType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    base_price = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    carpets = db.relationship('Carpet', backref='carpet_type_ref', lazy=True)

class Craftsman(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    carpets = db.relationship('Carpet', backref='craftsman_ref', cascade="all, delete-orphan")

class Carpet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    carpet_id = db.Column(db.String(50), unique=True, nullable=False)
    carpet_type_id = db.Column(db.Integer, db.ForeignKey('carpet_type.id'), nullable=False)
    craftsman_id = db.Column(db.Integer, db.ForeignKey('craftsman.id'), nullable=False)
    price = db.Column(db.Float, nullable=False)
    size = db.Column(db.String(50))
    material = db.Column(db.String(100))
    color = db.Column(db.String(50))
    status = db.Column(db.String(50), default='created')
    scanned_at = db.Column(db.String(20), nullable=True)
    scanned_by = db.Column(db.String(50), default='admin')
    notes = db.Column(db.Text)
    qr_code_path = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ScanLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    carpet_id = db.Column(db.String(50), nullable=False)
    scanned_at = db.Column(db.String(20), nullable=False)
    scanned_by = db.Column(db.String(50), default='admin')
    result = db.Column(db.String(20))

# ========== МОДЕЛИ ДЛЯ МАРКЕТПЛЕЙСОВ ==========
class MarketplaceAccount(db.Model):
    """Аккаунт на маркетплейсе"""
    id = db.Column(db.Integer, primary_key=True)
    marketplace = db.Column(db.String(20))
    account_name = db.Column(db.String(100))
    account_login = db.Column(db.String(100))
    api_key = db.Column(db.String(500))
    client_id = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    last_sync = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    orders = db.relationship('MarketplaceOrder', backref='account_ref', lazy=True)

class MarketplaceOrder(db.Model):
    """Заказ с маркетплейса"""
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('marketplace_account.id'))
    marketplace = db.Column(db.String(20))
    order_id = db.Column(db.String(50), unique=True)
    carpet_id = db.Column(db.String(50), db.ForeignKey('carpet.carpet_id'))
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    delivery_address = db.Column(db.Text)
    status = db.Column(db.String(50), default='new')
    ordered_at = db.Column(db.String(20))
    shipped_at = db.Column(db.String(20))
    price = db.Column(db.Float)
    products_info = db.Column(db.Text)
    wb_supply_id = db.Column(db.String(50))
    ozon_posting_number = db.Column(db.String(50))

class MarketplaceSyncLog(db.Model):
    """Лог синхронизации заказов"""
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('marketplace_account.id'))
    sync_time = db.Column(db.String(20))
    orders_found = db.Column(db.Integer)
    orders_new = db.Column(db.Integer)
    error_message = db.Column(db.Text)
    status = db.Column(db.String(20))

# ========== ФУНКЦИИ АВТОМАТИЧЕСКОЙ МИГРАЦИИ БД ==========
DB_VERSION = 2

def get_db_version():
    """Получение текущей версии БД"""
    try:
        result = db.session.execute("SELECT version FROM db_version LIMIT 1").fetchone()
        return result[0] if result else 0
    except:
        return 0

def set_db_version(version):
    """Установка версии БД"""
    try:
        db.session.execute("CREATE TABLE IF NOT EXISTS db_version (version INTEGER)")
        db.session.execute("DELETE FROM db_version")
        db.session.execute("INSERT INTO db_version (version) VALUES (:version)", {'version': version})
        db.session.commit()
    except:
        pass

def safe_add_column(table, column, type_sql):
    """Безопасное добавление колонки в таблицу"""
    try:
        cursor = db.session.execute(f"PRAGMA table_info({table})").fetchall()
        existing_columns = [col[1] for col in cursor] if cursor else []
        
        if column not in existing_columns:
            db.session.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_sql}")
            db.session.commit()
            print(f"[MIGRATION] ✓ Добавлена колонка {column} в {table}")
            return True
        else:
            print(f"[MIGRATION] Колонка {column} уже существует в {table}")
            return True
    except Exception as e:
        print(f"[MIGRATION] ⚠️ Не удалось добавить {column}: {e}")
        return False

def init_database():
    """Инициализация базы данных с обработкой ошибок"""
    try:
        # Проверяем доступность папки
        if not os.path.exists(DATA_FOLDER):
            os.makedirs(DATA_FOLDER, exist_ok=True)
            print(f"[DB] Создана папка: {DATA_FOLDER}")
        
        # Создаём таблицы
        db.create_all()
        print(f"[DB] Таблицы успешно созданы/проверены")
        
        # Проверяем и обновляем версию БД
        current_version = get_db_version()
        print(f"[DB] Текущая версия БД: {current_version}")
        
        if current_version == 0:
            set_db_version(DB_VERSION)
            print(f"[DB] БД инициализирована (версия {DB_VERSION})")
        elif current_version < DB_VERSION:
            print(f"[DB] Обновление БД с версии {current_version} до {DB_VERSION}...")
            
            if current_version == 1:
                # Добавляем новые колонки
                safe_add_column('marketplace_order', 'account_id', 'INTEGER')
                safe_add_column('marketplace_order', 'wb_supply_id', 'VARCHAR(50)')
                safe_add_column('marketplace_order', 'ozon_posting_number', 'VARCHAR(50)')
                safe_add_column('marketplace_account', 'account_name', 'VARCHAR(100)')
                safe_add_column('marketplace_account', 'account_login', 'VARCHAR(100)')
                safe_add_column('marketplace_account', 'client_id', 'VARCHAR(100)')
                
                # Создаём таблицу логов
                db.session.execute("""
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
                db.session.commit()
                set_db_version(2)
                print(f"[DB] БД обновлена до версии 2")
        
    except Exception as e:
        print(f"[DB] Ошибка инициализации БД: {e}")
        traceback.print_exc()
        # Пробуем пересоздать папку
        try:
            import shutil
            backup_folder = DATA_FOLDER + "_backup"
            if os.path.exists(DATA_FOLDER):
                shutil.copy(DB_PATH, os.path.join(backup_folder, 'carpets.db')) if os.path.exists(DB_PATH) else None
            db.create_all()
            print(f"[DB] БД пересоздана")
        except:
            pass

# ========== ФУНКЦИИ ПРОГНОЗИРОВАНИЯ ==========
def forecast_sales(days=30):
    try:
        try:
            scans = ScanLog.query.filter_by(result='success').all()
        except Exception as db_error:
            print(f"[FORECAST] Ошибка БД: {db_error}")
            return {"error": None, "data": [], "total": 0, "daily_avg": 0, "historical_data": [], "historical_dates": [], "dates": [], "no_data": True}
        
        if len(scans) < 7:
            return {"error": None, "no_data": True, "message": "Недостаточно данных для прогноза (нужно минимум 7 дней)", "data": [], "total": 0, "daily_avg": 0}
        
        daily_counts = defaultdict(int)
        for scan in scans:
            if scan.scanned_at:
                try:
                    date = scan.scanned_at[:10]
                    daily_counts[date] += 1
                except:
                    continue
        
        if not daily_counts:
            return {"error": None, "no_data": True, "message": "Нет данных о сканированиях", "data": [], "total": 0, "daily_avg": 0}
        
        dates = sorted(daily_counts.keys())
        counts = [daily_counts[d] for d in dates]
        
        if len(counts) >= 7:
            last_7 = counts[-7:]
            avg = sum(last_7) / len(last_7)
        else:
            avg = sum(counts) / len(counts)
        
        forecast = [max(0, round(avg * (0.9 + (i * 0.02)))) for i in range(days)]
        
        weekday_weights = {0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.2, 5: 1.5, 6: 1.1}
        today = datetime.now()
        
        forecast_with_season = []
        forecast_dates = []
        for i in range(days):
            forecast_date = today + timedelta(days=i+1)
            weight = weekday_weights.get(forecast_date.weekday(), 1.0)
            value = round(forecast[i] * weight)
            forecast_with_season.append(value)
            forecast_dates.append(forecast_date.strftime("%Y-%m-%d"))
        
        return {
            "error": None,
            "no_data": False,
            "method": "Скользящее среднее (7 дней)",
            "data": forecast_with_season,
            "dates": forecast_dates,
            "total": sum(forecast_with_season),
            "daily_avg": round(sum(forecast_with_season) / days, 1),
            "historical_data": counts[-30:] if len(counts) > 0 else [],
            "historical_dates": dates[-30:] if len(dates) > 0 else []
        }
    except Exception as e:
        print(f"[FORECAST] Ошибка: {e}")
        return {"error": str(e), "no_data": True, "data": [], "total": 0, "daily_avg": 0}

def calculate_trend():
    try:
        try:
            scans = ScanLog.query.filter_by(result='success').all()
        except Exception as db_error:
            print(f"[TREND] Ошибка БД: {db_error}")
            return {"trend": "unknown", "percent": 0, "last_week": 0, "prev_week": 0}
        
        if len(scans) < 14:
            return {"trend": "unknown", "percent": 0, "last_week": 0, "prev_week": 0}
        
        now = datetime.now()
        last_week = 0
        prev_week = 0
        
        for scan in scans:
            if scan.scanned_at:
                try:
                    scan_date = datetime.strptime(scan.scanned_at[:10], "%Y-%m-%d")
                    days_diff = (now - scan_date).days
                    if days_diff <= 7:
                        last_week += 1
                    elif days_diff <= 14:
                        prev_week += 1
                except:
                    continue
        
        if prev_week == 0:
            percent = 100 if last_week > 0 else 0
        else:
            percent = round((last_week - prev_week) / prev_week * 100, 1)
        
        if percent > 10:
            trend = "growing"
        elif percent < -10:
            trend = "declining"
        else:
            trend = "stable"
        
        return {"trend": trend, "percent": percent, "last_week": last_week, "prev_week": prev_week}
    except Exception as e:
        print(f"[TREND] Ошибка: {e}")
        return {"trend": "unknown", "percent": 0, "last_week": 0, "prev_week": 0}

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С МАРКЕТПЛЕЙСАМИ ==========
class MarketplaceAPI:
    @staticmethod
    def get_wb_orders(api_key, date_from=None):
        if not date_from:
            date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        
        url = "https://suppliers-api.wildberries.ru/api/v3/orders"
        headers = {"Authorization": api_key}
        params = {"dateFrom": date_from}
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data.get('orders', [])
            else:
                print(f"[WB] Ошибка: {response.status_code}")
                return []
        except Exception as e:
            print(f"[WB] Ошибка соединения: {e}")
            return []
    
    @staticmethod
    def get_ozon_orders(api_key, client_id, date_from=None):
        if not date_from:
            date_from = (datetime.now() - timedelta(days=7)).isoformat()
        
        url = "https://api-seller.ozon.ru/v3/posting/fbs/list"
        headers = {"Api-Key": api_key, "Client-Id": client_id, "Content-Type": "application/json"}
        payload = {"dir": "desc", "filter": {"since": date_from, "status": "awaiting_packaging"}, "limit": 100}
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data.get('result', {}).get('postings', [])
            else:
                print(f"[Ozon] Ошибка: {response.status_code}")
                return []
        except Exception as e:
            print(f"[Ozon] Ошибка соединения: {e}")
            return []

# ========== ФУНКЦИИ ==========
def generate_qr_code(carpet_id, carpet_data):
    qr = qrcode.QRCode(version=1, box_size=10, border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(carpet_id)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    filename = f"carpet_{carpet_id}.png"
    filepath = os.path.join(QR_FOLDER, filename)
    img.save(filepath)
    return filepath

def generate_next_id():
    last_carpet = Carpet.query.order_by(Carpet.id.desc()).first()
    if last_carpet:
        try:
            last_num = int(last_carpet.carpet_id.split('-')[1])
            next_num = last_num + 1
        except:
            next_num = Carpet.query.count() + 1
    else:
        next_num = 1
    return f"CARPET-{next_num:04d}"

def sync_account_orders(account_id):
    account = MarketplaceAccount.query.get(account_id)
    if not account or not account.is_active:
        return 0
    
    new_orders_count = 0
    orders = []
    
    try:
        if account.marketplace == 'wb':
            orders = MarketplaceAPI.get_wb_orders(account.api_key)
            for order in orders:
                existing = MarketplaceOrder.query.filter_by(marketplace='wb', order_id=str(order.get('id'))).first()
                if not existing:
                    customer = order.get('customer', {})
                    delivery = order.get('delivery', {})
                    new_order = MarketplaceOrder(
                        account_id=account.id, marketplace='wb', order_id=str(order.get('id')),
                        customer_name=customer.get('name', ''), customer_phone=customer.get('phone', ''),
                        delivery_address=delivery.get('address', ''), status='new',
                        ordered_at=order.get('createdAt', ''), price=order.get('price', 0),
                        products_info=json.dumps(order.get('products', [])), wb_supply_id=order.get('supplyId', '')
                    )
                    db.session.add(new_order)
                    new_orders_count += 1
        elif account.marketplace == 'ozon':
            orders = MarketplaceAPI.get_ozon_orders(account.api_key, account.client_id)
            for order in orders:
                existing = MarketplaceOrder.query.filter_by(marketplace='ozon', order_id=str(order.get('posting_number'))).first()
                if not existing:
                    customer = order.get('customer', {})
                    delivery = order.get('delivery', {})
                    products = order.get('products', [])
                    new_order = MarketplaceOrder(
                        account_id=account.id, marketplace='ozon', order_id=order.get('posting_number'),
                        customer_name=customer.get('name', ''), customer_phone=customer.get('phone', ''),
                        delivery_address=delivery.get('address', {}).get('address_txt', ''), status='new',
                        ordered_at=order.get('created_at', ''),
                        price=sum(p.get('price', 0) * p.get('quantity', 1) for p in products),
                        products_info=json.dumps(products), ozon_posting_number=order.get('posting_number')
                    )
                    db.session.add(new_order)
                    new_orders_count += 1
        
        account.last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.session.commit()
        
        sync_log = MarketplaceSyncLog(
            account_id=account.id, sync_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            orders_found=len(orders), orders_new=new_orders_count, status='success'
        )
        db.session.add(sync_log)
        db.session.commit()
    except Exception as e:
        print(f"[SYNC] Ошибка: {e}")
        sync_log = MarketplaceSyncLog(
            account_id=account.id, sync_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error_message=str(e), status='error'
        )
        db.session.add(sync_log)
        db.session.commit()
    
    return new_orders_count

# ========== ИНИЦИАЛИЗАЦИЯ БД ==========
with app.app_context():
    init_database()
    
    # Создание тестовых данных
    if CarpetType.query.count() == 0:
        default_types = [
            CarpetType(name="Персидский", base_price=15000),
            CarpetType(name="Турецкий", base_price=12000),
            CarpetType(name="Современный", base_price=8000),
            CarpetType(name="Винтажный", base_price=20000)
        ]
        for t in default_types:
            db.session.add(t)
        db.session.commit()
    
    if Craftsman.query.count() == 0:
        craftsmen = [
            Craftsman(name="Анна Иванова", phone="+7-999-123-45-67"),
            Craftsman(name="Мария Петрова", phone="+7-999-234-56-78"),
            Craftsman(name="Елена Сидорова", phone="+7-999-345-67-89"),
            Craftsman(name="Ольга Смирнова", phone="+7-999-456-78-90")
        ]
        for c in craftsmen:
            db.session.add(c)
        db.session.commit()
    
    if Carpet.query.count() == 0:
        test_data = [
            ("CARPET-0001", 1, 1, 15000, "scanned", "2025-06-01 14:30:00"),
            ("CARPET-0002", 2, 2, 12000, "created", None),
            ("CARPET-0003", 3, 1, 8000, "created", None),
            ("CARPET-0004", 1, 3, 49000, "created", None),
            ("CARPET-0005", 2, 2, 12000, "created", None),
            ("CARPET-0006", 3, 1, 8000, "created", None),
        ]
        for qr, type_id, cm_id, price, status, scanned_at in test_data:
            carpet = Carpet(carpet_id=qr, carpet_type_id=type_id, craftsman_id=cm_id, 
                          price=price, status=status, scanned_at=scanned_at)
            db.session.add(carpet)
        db.session.commit()
        
        for carpet in Carpet.query.all():
            carpet_type = db.session.get(CarpetType, carpet.carpet_type_id)
            craftsman = db.session.get(Craftsman, carpet.craftsman_id)
            if carpet_type and craftsman:
                carpet_data = {'carpet_type_name': carpet_type.name, 'craftsman_name': craftsman.name, 'price': carpet.price}
                carpet.qr_code_path = generate_qr_code(carpet.carpet_id, carpet_data)
        db.session.commit()

# ========== МАРШРУТЫ ==========
@app.route('/')
def index():
    new_orders_count = MarketplaceOrder.query.filter_by(status='new').count()
    processing_orders_count = MarketplaceOrder.query.filter_by(status='processing').count()
    ready_orders_count = MarketplaceOrder.query.filter_by(status='ready').count()
    accounts_count = MarketplaceAccount.query.filter_by(is_active=True).count()
    
    return render_template('index.html', 
                         carpets=Carpet.query.all(),
                         craftsmen=Craftsman.query.all(),
                         carpet_types=CarpetType.query.all(),
                         new_orders_count=new_orders_count,
                         processing_orders_count=processing_orders_count,
                         ready_orders_count=ready_orders_count,
                         accounts_count=accounts_count)

@app.route('/forecast')
def forecast_page():
    try:
        forecast = forecast_sales(30)
        trend = calculate_trend()
        return render_template('forecast.html', forecast=forecast, trend=trend)
    except Exception as e:
        print(f"[FORECAST_PAGE] Ошибка: {e}")
        return render_template('forecast.html', forecast={"error": str(e), "no_data": True}, trend={"trend": "unknown", "percent": 0})

@app.route('/add_carpet', methods=['POST'])
def add_carpet():
    carpet_id = generate_next_id()
    carpet = Carpet(
        carpet_id=carpet_id,
        carpet_type_id=request.form['carpet_type_id'],
        craftsman_id=request.form['craftsman_id'],
        price=float(request.form['price']),
        size=request.form.get('size', ''),
        material=request.form.get('material', ''),
        color=request.form.get('color', ''),
        status='created',
        notes=request.form.get('notes', '')
    )
    db.session.add(carpet)
    db.session.commit()
    
    carpet_type = db.session.get(CarpetType, carpet.carpet_type_id)
    craftsman = db.session.get(Craftsman, carpet.craftsman_id)
    if carpet_type and craftsman:
        carpet_data = {'carpet_type_name': carpet_type.name, 'craftsman_name': craftsman.name, 'price': carpet.price}
        carpet.qr_code_path = generate_qr_code(carpet_id, carpet_data)
        db.session.commit()
    
    flash(f'Ковёр {carpet_id} успешно добавлен!', 'success')
    return redirect(url_for('index'))

@app.route('/add_carpet_group', methods=['POST'])
def add_carpet_group():
    carpet_type_id = request.form['carpet_type_id']
    count = int(request.form['count'])
    craftsman_id = request.form['craftsman_id']
    size = request.form.get('size', '')
    material = request.form.get('material', '')
    color = request.form.get('color', '')
    
    if count > 2000:
        flash('Максимальное количество - 2000 ковров за раз!', 'error')
        return redirect(url_for('index'))
    
    carpet_type = db.session.get(CarpetType, carpet_type_id)
    craftsman = db.session.get(Craftsman, craftsman_id)
    
    created = []
    for i in range(count):
        carpet_id = generate_next_id()
        carpet = Carpet(
            carpet_id=carpet_id, carpet_type_id=carpet_type_id, craftsman_id=craftsman_id,
            price=carpet_type.base_price if carpet_type else 0, size=size, material=material, color=color,
            status='created', notes=f'Групповое добавление {i+1}/{count}'
        )
        db.session.add(carpet)
        db.session.flush()
        if carpet_type and craftsman:
            carpet_data = {'carpet_type_name': carpet_type.name, 'craftsman_name': craftsman.name, 'price': carpet.price}
            carpet.qr_code_path = generate_qr_code(carpet_id, carpet_data)
        created.append(carpet_id)
        if (i + 1) % 100 == 0:
            print(f"Прогресс: {i+1}/{count} ковров создано")
    
    db.session.commit()
    flash(f'Успешно создано {len(created)} ковров типа "{carpet_type.name if carpet_type else "-"}"', 'success')
    return redirect(url_for('index'))

@app.route('/edit_carpet/<int:id>', methods=['GET', 'POST'])
def edit_carpet(id):
    carpet = Carpet.query.get_or_404(id)
    if request.method == 'POST':
        carpet.carpet_type_id = request.form['carpet_type_id']
        carpet.craftsman_id = request.form['craftsman_id']
        carpet.price = float(request.form['price'])
        carpet.size = request.form.get('size', '')
        carpet.material = request.form.get('material', '')
        carpet.color = request.form.get('color', '')
        carpet.notes = request.form.get('notes', '')
        db.session.commit()
        
        carpet_type = db.session.get(CarpetType, carpet.carpet_type_id)
        craftsman = db.session.get(Craftsman, carpet.craftsman_id)
        if carpet_type and craftsman:
            carpet_data = {'carpet_type_name': carpet_type.name, 'craftsman_name': craftsman.name, 'price': carpet.price}
            carpet.qr_code_path = generate_qr_code(carpet.carpet_id, carpet_data)
            db.session.commit()
        
        flash(f'Ковёр {carpet.carpet_id} успешно обновлён!', 'success')
        return redirect(url_for('index'))
    return render_template('edit_carpet.html', carpet=carpet, craftsmen=Craftsman.query.all(), carpet_types=CarpetType.query.all())

@app.route('/delete_carpet/<int:id>')
def delete_carpet(id):
    carpet = Carpet.query.get_or_404(id)
    if carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
        os.remove(carpet.qr_code_path)
    db.session.delete(carpet)
    db.session.commit()
    flash(f'Ковёр {carpet.carpet_id} удалён', 'info')
    return redirect(url_for('index'))

@app.route('/add_craftsman', methods=['POST'])
def add_craftsman():
    db.session.add(Craftsman(name=request.form['name'], phone=request.form.get('phone', '')))
    db.session.commit()
    flash('Швея успешно добавлена!', 'success')
    return redirect(url_for('index'))

@app.route('/edit_craftsman/<int:id>', methods=['GET', 'POST'])
def edit_craftsman(id):
    craftsman = Craftsman.query.get_or_404(id)
    if request.method == 'POST':
        craftsman.name = request.form['name']
        craftsman.phone = request.form['phone']
        db.session.commit()
        flash('Данные швеи обновлены!', 'success')
        return redirect(url_for('index'))
    return render_template('edit_craftsman.html', craftsman=craftsman)

@app.route('/delete_craftsman/<int:id>')
def delete_craftsman(id):
    craftsman = Craftsman.query.get_or_404(id)
    carpet_count = len(craftsman.carpets)
    for carpet in craftsman.carpets:
        if carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
            os.remove(carpet.qr_code_path)
    db.session.delete(craftsman)
    db.session.commit()
    flash(f'Швея "{craftsman.name}" удалена вместе с {carpet_count} коврами', 'success')
    return redirect(url_for('index'))

@app.route('/craftsman/<int:id>')
def craftsman_detail(id):
    craftsman = Craftsman.query.get_or_404(id)
    scan_date_from = request.args.get('scan_date_from', '')
    scan_date_to = request.args.get('scan_date_to', '')
    query = Carpet.query.filter_by(craftsman_id=id)
    if scan_date_from:
        query = query.filter(Carpet.scanned_at >= scan_date_from)
    if scan_date_to:
        query = query.filter(Carpet.scanned_at <= scan_date_to)
    carpets = query.all()
    
    total_count = len(carpets)
    scanned_count = len([c for c in carpets if c.status == 'scanned'])
    total_price = sum(c.price for c in carpets)
    
    type_stats = {}
    for carpet in carpets:
        type_name = carpet.carpet_type_ref.name if carpet.carpet_type_ref else 'Неизвестно'
        type_stats[type_name] = type_stats.get(type_name, 0) + 1
    
    month_stats = {}
    for carpet in carpets:
        if carpet.scanned_at:
            month = carpet.scanned_at[:7]
            month_stats[month] = month_stats.get(month, 0) + 1
    
    return render_template('craftsman_detail.html', craftsman=craftsman, carpets=carpets,
        total_count=total_count, scanned_count=scanned_count, total_price=total_price,
        type_stats=type_stats, month_stats=month_stats,
        scan_date_from=scan_date_from, scan_date_to=scan_date_to)

@app.route('/types')
def types_list():
    return render_template('types.html', types=CarpetType.query.all())

@app.route('/add_type', methods=['POST'])
def add_type():
    name = request.form['name']
    base_price = float(request.form['base_price'])
    description = request.form.get('description', '')
    existing = CarpetType.query.filter_by(name=name).first()
    if existing:
        flash('Тип с таким названием уже существует!', 'error')
        return redirect(url_for('types_list'))
    new_type = CarpetType(name=name, base_price=base_price, description=description)
    db.session.add(new_type)
    db.session.commit()
    flash(f'Тип "{name}" успешно добавлен!', 'success')
    return redirect(url_for('types_list'))

@app.route('/edit_type/<int:id>', methods=['GET', 'POST'])
def edit_type(id):
    carpet_type = CarpetType.query.get_or_404(id)
    if request.method == 'POST':
        carpet_type.name = request.form['name']
        carpet_type.base_price = float(request.form['base_price'])
        carpet_type.description = request.form.get('description', '')
        db.session.commit()
        flash(f'Тип "{carpet_type.name}" обновлён!', 'success')
        return redirect(url_for('types_list'))
    return render_template('edit_type.html', type=carpet_type)

@app.route('/delete_type/<int:id>')
def delete_type(id):
    carpet_type = CarpetType.query.get_or_404(id)
    if len(carpet_type.carpets) > 0:
        flash('Нельзя удалить тип, у которого есть ковры!', 'error')
        return redirect(url_for('types_list'))
    db.session.delete(carpet_type)
    db.session.commit()
    flash('Тип удалён', 'info')
    return redirect(url_for('types_list'))

@app.route('/scan_qr', methods=['POST'])
def scan_qr():
    qr_data = request.json.get('qr_code')
    scanner_name = request.json.get('scanner', 'admin')
    carpet = Carpet.query.filter_by(carpet_id=qr_data).first()
    
    log = ScanLog(carpet_id=qr_data, scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), scanned_by=scanner_name)
    
    if not carpet:
        log.result = 'not_found'
        db.session.add(log)
        db.session.commit()
        return jsonify({'success': False, 'message': '❌ Ковёр не найден в базе данных!'})
    
    if carpet.status == 'scanned':
        log.result = 'already_scanned'
        db.session.add(log)
        db.session.commit()
        return jsonify({'success': False, 'already_scanned': True, 'carpet_id': carpet.carpet_id,
                       'scanned_at': carpet.scanned_at, 'message': f'⚠️ Этот ковёр уже был отсканирован {carpet.scanned_at}!'})
    
    carpet.status = 'scanned'
    carpet.scanned_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    carpet.scanned_by = scanner_name
    log.result = 'success'
    db.session.add(log)
    db.session.commit()
    
    carpet_type = db.session.get(CarpetType, carpet.carpet_type_id)
    craftsman = db.session.get(Craftsman, carpet.craftsman_id)
    
    return jsonify({'success': True, 'first_time': True, 'carpet_id': carpet.carpet_id,
        'carpet_type': carpet_type.name if carpet_type else '-', 'craftsman': craftsman.name if craftsman else '-', 
        'price': carpet.price, 'size': carpet.size or '-', 'material': carpet.material or '-', 
        'color': carpet.color or '-', 'scanned_at': carpet.scanned_at, 
        'message': f'✅ Ковёр {carpet.carpet_id} успешно отсканирован!'})

@app.route('/mark_sold/<int:id>', methods=['POST'])
def mark_sold(id):
    carpet = Carpet.query.get_or_404(id)
    if carpet.status == 'scanned':
        carpet.status = 'sold'
        db.session.commit()
        return jsonify({'success': True, 'message': 'Ковёр отмечен как проданный'})
    return jsonify({'success': False, 'message': 'Ковёр ещё не отсканирован'})

@app.route('/get_qr/<carpet_id>')
def get_qr(carpet_id):
    carpet = Carpet.query.filter_by(carpet_id=carpet_id).first()
    if carpet and carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
        return send_file(carpet.qr_code_path, mimetype='image/png')
    return "QR не найден", 404

@app.route('/print_qr/<carpet_id>')
def print_qr(carpet_id):
    carpet = Carpet.query.filter_by(carpet_id=carpet_id).first()
    if carpet:
        return render_template('print_qr.html', carpet=carpet, carpet_types=CarpetType.query.all())
    return "Ковёр не найден", 404

@app.route('/print_single_pdf/<carpet_id>')
def print_single_pdf(carpet_id):
    carpet = Carpet.query.filter_by(carpet_id=carpet_id).first()
    if not carpet:
        return "Ковёр не найден", 404
    
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        from reportlab.lib.units import mm
        
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        sticker_width = 30 * mm
        sticker_height = 20 * mm
        
        x_center = (width - sticker_width) / 2
        y_center = (height - sticker_height) / 2
        
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.rect(x_center, y_center, sticker_width, sticker_height)
        
        qr_size = 12 * mm
        qr_x = x_center + 1.5 * mm
        qr_y = y_center + 2 * mm
        
        if carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
            img = ImageReader(carpet.qr_code_path)
            c.drawImage(img, qr_x, qr_y, qr_size, qr_size)
        
        text_x = qr_x + qr_size + 1 * mm
        text_y = y_center + sticker_height - 2.5 * mm
        
        carpet_type = db.session.get(CarpetType, carpet.carpet_type_id)
        type_name = carpet_type.name if carpet_type else '-'
        craftsman = db.session.get(Craftsman, carpet.craftsman_id)
        craftsman_name = craftsman.name if craftsman else '-'
        
        if FONT_REGISTERED:
            c.setFont("RussianFont", 5)
        else:
            c.setFont("Helvetica", 5)
        
        c.drawString(text_x, text_y, f"{carpet.carpet_id}")
        c.drawString(text_x, text_y - 2.5 * mm, f"{type_name}")
        c.drawString(text_x, text_y - 5 * mm, f"{craftsman_name}")
        c.drawString(text_x, text_y - 7.5 * mm, f"{carpet.price} p")
        
        c.save()
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f'{carpet.carpet_id}_sticker.pdf')
    except Exception as e:
        return f"Ошибка: {str(e)}", 500

@app.route('/mass_print_qr')
def mass_print_qr():
    carpet_type_id = request.args.get('carpet_type_id', '')
    craftsman_id = request.args.get('craftsman_id', '')
    status = request.args.get('status', '')
    
    query = Carpet.query
    if carpet_type_id:
        query = query.filter(Carpet.carpet_type_id == carpet_type_id)
    if craftsman_id:
        query = query.filter(Carpet.craftsman_id == craftsman_id)
    if status:
        query = query.filter(Carpet.status == status)
    
    carpets = query.all()
    return render_template('mass_print.html', 
                         carpets=carpets,
                         carpet_types=CarpetType.query.all(),
                         craftsmen=Craftsman.query.all(),
                         selected_type=carpet_type_id,
                         selected_craftsman=craftsman_id,
                         selected_status=status)

@app.route('/generate_qr_zip')
def generate_qr_zip():
    carpet_type_id = request.args.get('carpet_type_id', '')
    craftsman_id = request.args.get('craftsman_id', '')
    status = request.args.get('status', '')
    
    query = Carpet.query
    if carpet_type_id:
        query = query.filter(Carpet.carpet_type_id == carpet_type_id)
    if craftsman_id:
        query = query.filter(Carpet.craftsman_id == craftsman_id)
    if status:
        query = query.filter(Carpet.status == status)
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for carpet in query.all():
            if carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
                zip_file.write(carpet.qr_code_path, f"{carpet.carpet_id}.png")
    
    zip_buffer.seek(0)
    return send_file(zip_buffer, mimetype='application/zip', as_attachment=True, download_name='qr_codes.zip')

@app.route('/generate_qr_pdf')
def generate_qr_pdf():
    carpet_type_id = request.args.get('carpet_type_id', '')
    craftsman_id = request.args.get('craftsman_id', '')
    status = request.args.get('status', '')
    
    query = Carpet.query
    if carpet_type_id:
        query = query.filter(Carpet.carpet_type_id == carpet_type_id)
    if craftsman_id:
        query = query.filter(Carpet.craftsman_id == craftsman_id)
    if status:
        query = query.filter(Carpet.status == status)
    
    carpets = query.all()
    
    if not carpets:
        flash('Нет ковров для печати!', 'error')
        return redirect(url_for('mass_print_qr'))
    
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        from PIL import Image
        
        buffer = io.BytesIO()
        width, height = A4
        
        for i, carpet in enumerate(carpets):
            if not carpet.qr_code_path or not os.path.exists(carpet.qr_code_path):
                continue
            
            pil_img = Image.open(carpet.qr_code_path)
            pil_img_resized = pil_img.resize((int(width), int(height)), Image.Resampling.LANCZOS)
            
            temp_buffer = io.BytesIO()
            pil_img_resized.save(temp_buffer, format='PNG')
            temp_buffer.seek(0)
            
            c = canvas.Canvas(buffer, pagesize=A4)
            img = ImageReader(temp_buffer)
            c.drawImage(img, 0, 0, width, height)
            
            c.setFillColorRGB(1, 1, 1)
            c.rect(0, 0, width, 55, fill=1, stroke=0)
            
            c.setFillColorRGB(0, 0, 0)
            c.setFont("Helvetica-Bold", 14)
            
            carpet_type = db.session.get(CarpetType, carpet.carpet_type_id)
            type_name = carpet_type.name if carpet_type else '-'
            craftsman = db.session.get(Craftsman, carpet.craftsman_id)
            craftsman_name = craftsman.name if craftsman else '-'
            
            c.drawCentredString(width / 2, 38, carpet.carpet_id)
            c.setFont("Helvetica", 10)
            c.drawCentredString(width / 2, 24, f"{type_name} | {craftsman_name} | {carpet.price} ₽")
            c.setFont("Helvetica", 8)
            c.drawCentredString(width / 2, 10, f"{i+1} / {len(carpets)}")
            
            c.save()
        
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f'qr_print_{len(carpets)}_pages.pdf')
    except Exception as e:
        print(f"Ошибка: {e}")
        return f"Ошибка: {str(e)}", 500

@app.route('/generate_single_pages_pdf')
def generate_single_pages_pdf():
    carpet_type_id = request.args.get('carpet_type_id', '')
    craftsman_id = request.args.get('craftsman_id', '')
    status = request.args.get('status', '')
    
    query = Carpet.query
    if carpet_type_id:
        query = query.filter(Carpet.carpet_type_id == carpet_type_id)
    if craftsman_id:
        query = query.filter(Carpet.craftsman_id == craftsman_id)
    if status:
        query = query.filter(Carpet.status == status)
    
    carpets = query.all()
    
    if not carpets:
        flash('Нет ковров для печати!', 'error')
        return redirect(url_for('mass_print_qr'))
    
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        from PIL import Image
        
        buffer = io.BytesIO()
        width, height = A4
        
        scale_factor = 0.9
        new_width = width * scale_factor
        new_height = height * scale_factor
        x_offset = (width - new_width) / 2
        y_offset = (height - new_height) / 2
        text_height = 63
        
        c = canvas.Canvas(buffer, pagesize=A4)
        
        for i, carpet in enumerate(carpets):
            if not carpet.qr_code_path or not os.path.exists(carpet.qr_code_path):
                continue
            
            pil_img = Image.open(carpet.qr_code_path)
            img_width, img_height = pil_img.size
            scale_x = new_width / img_width
            scale_y = new_height / img_height
            scale = max(scale_x, scale_y)
            
            qr_new_width = img_width * scale
            qr_new_height = img_height * scale
            qr_x_offset = x_offset + (new_width - qr_new_width) / 2
            qr_y_offset = y_offset + (new_height - qr_new_height) / 2
            
            temp_buffer = io.BytesIO()
            pil_img_resized = pil_img.resize((int(qr_new_width), int(qr_new_height)), Image.Resampling.LANCZOS)
            pil_img_resized.save(temp_buffer, format='PNG', dpi=(300, 300))
            temp_buffer.seek(0)
            
            img = ImageReader(temp_buffer)
            c.drawImage(img, qr_x_offset, qr_y_offset, qr_new_width, qr_new_height, preserveAspectRatio=True)
            
            c.setFillColorRGB(1, 1, 1)
            c.rect(0, 0, width, text_height, fill=1, stroke=0)
            
            carpet_type = db.session.get(CarpetType, carpet.carpet_type_id)
            type_name = carpet_type.name if carpet_type else '-'
            craftsman = db.session.get(Craftsman, carpet.craftsman_id)
            craftsman_name = craftsman.name if craftsman else '-'
            
            c.setFillColorRGB(0, 0, 0)
            c.setFont("Helvetica-Bold", 16)
            c.drawCentredString(width / 2, text_height - 18, carpet.carpet_id)
            
            if FONT_REGISTERED:
                c.setFont("RussianFont", 11)
            else:
                c.setFont("Helvetica", 11)
            c.drawCentredString(width / 2, text_height - 36, f"{type_name} | {craftsman_name}")
            
            c.setFont("Helvetica-Bold", 12)
            price_str = f"{carpet.price:,} ₽".replace(',', ' ')
            c.drawCentredString(width / 2, text_height - 52, price_str)
            
            c.setFont("Helvetica", 7)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawRightString(width - 20, 9, f"Страница {i+1} из {len(carpets)}")
            
            c.showPage()
        
        c.save()
        buffer.seek(0)
        
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f'qr_full_page_{len(carpets)}_pages.pdf')
    except Exception as e:
        print(f"Ошибка: {e}")
        return f"Ошибка: {str(e)}", 500

# ========== МАРШРУТЫ ДЛЯ МАРКЕТПЛЕЙСОВ ==========
@app.route('/marketplace_accounts')
def marketplace_accounts():
    accounts = MarketplaceAccount.query.order_by(MarketplaceAccount.marketplace, MarketplaceAccount.account_name).all()
    
    for account in accounts:
        account.stats = {
            'new': MarketplaceOrder.query.filter_by(account_id=account.id, status='new').count(),
            'processing': MarketplaceOrder.query.filter_by(account_id=account.id, status='processing').count(),
            'ready': MarketplaceOrder.query.filter_by(account_id=account.id, status='ready').count(),
            'shipped': MarketplaceOrder.query.filter_by(account_id=account.id, status='shipped').count(),
            'total': MarketplaceOrder.query.filter_by(account_id=account.id).count()
        }
    
    total_stats = {
        'new': MarketplaceOrder.query.filter_by(status='new').count(),
        'processing': MarketplaceOrder.query.filter_by(status='processing').count(),
        'ready': MarketplaceOrder.query.filter_by(status='ready').count(),
        'shipped': MarketplaceOrder.query.filter_by(status='shipped').count(),
        'total': MarketplaceOrder.query.count(),
        'total_revenue': db.session.query(db.func.sum(MarketplaceOrder.price)).scalar() or 0
    }
    
    return render_template('marketplace_accounts.html', accounts=accounts, total_stats=total_stats)

@app.route('/add_marketplace_account', methods=['POST'])
def add_marketplace_account():
    marketplace = request.form.get('marketplace')
    account_name = request.form.get('account_name')
    account_login = request.form.get('account_login')
    api_key = request.form.get('api_key')
    client_id = request.form.get('client_id', '')
    is_active = 'is_active' in request.form
    
    existing = MarketplaceAccount.query.filter_by(marketplace=marketplace, account_name=account_name).first()
    
    if existing:
        flash('Аккаунт с таким названием уже существует!', 'error')
    else:
        new_account = MarketplaceAccount(
            marketplace=marketplace, account_name=account_name, account_login=account_login,
            api_key=api_key, client_id=client_id, is_active=is_active
        )
        db.session.add(new_account)
        db.session.commit()
        flash(f'Аккаунт "{account_name}" добавлен!', 'success')
    
    return redirect(url_for('marketplace_accounts'))

@app.route('/edit_marketplace_account/<int:id>', methods=['GET', 'POST'])
def edit_marketplace_account(id):
    account = MarketplaceAccount.query.get_or_404(id)
    
    if request.method == 'POST':
        account.account_name = request.form.get('account_name')
        account.account_login = request.form.get('account_login')
        account.api_key = request.form.get('api_key')
        account.client_id = request.form.get('client_id', '')
        account.is_active = 'is_active' in request.form
        db.session.commit()
        flash(f'Аккаунт "{account.account_name}" обновлён!', 'success')
        return redirect(url_for('marketplace_accounts'))
    
    return render_template('edit_marketplace_account.html', account=account)

@app.route('/delete_marketplace_account/<int:id>')
def delete_marketplace_account(id):
    account = MarketplaceAccount.query.get_or_404(id)
    orders_count = MarketplaceOrder.query.filter_by(account_id=id).count()
    
    if orders_count > 0:
        flash(f'Нельзя удалить аккаунт с {orders_count} заказами! Сначала удалите заказы.', 'error')
    else:
        db.session.delete(account)
        db.session.commit()
        flash(f'Аккаунт "{account.account_name}" удалён', 'info')
    
    return redirect(url_for('marketplace_accounts'))

@app.route('/sync_account/<int:account_id>')
def sync_account(account_id):
    new_orders = sync_account_orders(account_id)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'new_orders': new_orders})
    
    flash(f'Синхронизировано {new_orders} новых заказов', 'success')
    return redirect(url_for('marketplace_accounts'))

@app.route('/sync_all_orders')
def sync_all_orders():
    accounts = MarketplaceAccount.query.filter_by(is_active=True).all()
    total_new_orders = 0
    sync_logs = []
    
    for account in accounts:
        new_orders = sync_account_orders(account.id)
        total_new_orders += new_orders
        sync_logs.append({'account_name': account.account_name, 'marketplace': account.marketplace, 'new_orders': new_orders})
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'new_orders': total_new_orders, 'logs': sync_logs})
    
    flash(f'Синхронизировано {total_new_orders} новых заказов с {len(accounts)} аккаунтов', 'success')
    return redirect(url_for('marketplace_accounts'))

@app.route('/marketplace_orders')
def marketplace_orders():
    account_id = request.args.get('account_id', '')
    status_filter = request.args.get('status', '')
    marketplace_filter = request.args.get('marketplace', '')
    
    query = MarketplaceOrder.query
    if account_id:
        query = query.filter(MarketplaceOrder.account_id == account_id)
    if status_filter:
        query = query.filter(MarketplaceOrder.status == status_filter)
    if marketplace_filter:
        query = query.filter(MarketplaceOrder.marketplace == marketplace_filter)
    
    orders = query.order_by(MarketplaceOrder.ordered_at.desc()).all()
    accounts = MarketplaceAccount.query.all()
    carpets = Carpet.query.filter_by(status='created').all()
    
    if account_id:
        stats = {
            'new': MarketplaceOrder.query.filter_by(account_id=account_id, status='new').count(),
            'processing': MarketplaceOrder.query.filter_by(account_id=account_id, status='processing').count(),
            'ready': MarketplaceOrder.query.filter_by(account_id=account_id, status='ready').count(),
            'shipped': MarketplaceOrder.query.filter_by(account_id=account_id, status='shipped').count()
        }
    else:
        stats = {
            'new': MarketplaceOrder.query.filter_by(status='new').count(),
            'processing': MarketplaceOrder.query.filter_by(status='processing').count(),
            'ready': MarketplaceOrder.query.filter_by(status='ready').count(),
            'shipped': MarketplaceOrder.query.filter_by(status='shipped').count()
        }
    
    return render_template('marketplace_orders.html', orders=orders, accounts=accounts, carpets=carpets,
                         stats=stats, selected_account=account_id, selected_status=status_filter, selected_marketplace=marketplace_filter)

@app.route('/link_order_to_carpet', methods=['POST'])
def link_order_to_carpet():
    order_id = request.form.get('order_id')
    carpet_id = request.form.get('carpet_id')
    
    order = MarketplaceOrder.query.get(order_id)
    carpet = Carpet.query.filter_by(carpet_id=carpet_id).first()
    
    if order and carpet:
        order.carpet_id = carpet.carpet_id
        order.status = 'processing'
        db.session.commit()
        flash(f'Ковёр {carpet_id} привязан к заказу {order.order_id}', 'success')
    
    return redirect(url_for('marketplace_orders'))

@app.route('/update_order_status', methods=['POST'])
def update_order_status():
    order_id = request.form.get('order_id')
    status = request.form.get('status')
    
    order = MarketplaceOrder.query.get(order_id)
    if order:
        order.status = status
        if status == 'shipped':
            order.shipped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if order.carpet_id:
                carpet = Carpet.query.filter_by(carpet_id=order.carpet_id).first()
                if carpet and carpet.status == 'scanned':
                    carpet.status = 'sold'
                    db.session.commit()
        db.session.commit()
        flash(f'Статус заказа {order.order_id} обновлён на "{status}"', 'success')
    
    return redirect(url_for('marketplace_orders'))

@app.route('/marketplace_stats_api')
def marketplace_stats_api():
    accounts = MarketplaceAccount.query.filter_by(is_active=True).all()
    
    result = {'total': {'new': 0, 'processing': 0, 'ready': 0, 'shipped': 0, 'total_orders': 0, 'total_revenue': 0}, 'accounts': []}
    
    for account in accounts:
        account_stats = {
            'id': account.id, 'name': account.account_name, 'marketplace': account.marketplace, 'login': account.account_login,
            'new': MarketplaceOrder.query.filter_by(account_id=account.id, status='new').count(),
            'processing': MarketplaceOrder.query.filter_by(account_id=account.id, status='processing').count(),
            'ready': MarketplaceOrder.query.filter_by(account_id=account.id, status='ready').count(),
            'shipped': MarketplaceOrder.query.filter_by(account_id=account.id, status='shipped').count(),
            'total': MarketplaceOrder.query.filter_by(account_id=account.id).count(),
            'revenue': db.session.query(db.func.sum(MarketplaceOrder.price)).filter(MarketplaceOrder.account_id == account.id).scalar() or 0,
            'last_sync': account.last_sync
        }
        result['accounts'].append(account_stats)
        result['total']['new'] += account_stats['new']
        result['total']['processing'] += account_stats['processing']
        result['total']['ready'] += account_stats['ready']
        result['total']['shipped'] += account_stats['shipped']
        result['total']['total_orders'] += account_stats['total']
        result['total']['total_revenue'] += account_stats['revenue']
    
    return jsonify(result)

@app.route('/search')
def search():
    q = request.args.get('q', '')
    status = request.args.get('status', '')
    craftsman_id = request.args.get('craftsman_id', '')
    carpet_type_id = request.args.get('carpet_type_id', '')
    scan_date_from = request.args.get('scan_date_from', '')
    scan_date_to = request.args.get('scan_date_to', '')
    
    query = Carpet.query
    if q:
        query = query.filter(Carpet.carpet_id.contains(q) | Carpet.craftsman_ref.has(name=q))
    if status:
        query = query.filter(Carpet.status == status)
    if craftsman_id:
        query = query.filter(Carpet.craftsman_id == craftsman_id)
    if carpet_type_id:
        query = query.filter(Carpet.carpet_type_id == carpet_type_id)
    if scan_date_from:
        query = query.filter(Carpet.scanned_at >= scan_date_from)
    if scan_date_to:
        query = query.filter(Carpet.scanned_at <= scan_date_to)
    
    carpets = query.all()
    craftsmen_stats = []
    for c in Craftsman.query.all():
        count = Carpet.query.filter_by(craftsman_id=c.id).count()
        scanned = Carpet.query.filter_by(craftsman_id=c.id, status='scanned').count()
        craftsmen_stats.append({'id': c.id, 'name': c.name, 'count': count, 'scanned': scanned})
    
    return render_template('search.html', carpets=carpets, query=q, status=status,
        craftsmen_stats=craftsmen_stats, craftsmen=Craftsman.query.all(),
        carpet_types=CarpetType.query.all(), selected_craftsman=craftsman_id,
        selected_type=carpet_type_id, scan_date_from=scan_date_from, scan_date_to=scan_date_to)

@app.route('/stats')
def stats():
    scan_date_from = request.args.get('scan_date_from', '')
    scan_date_to = request.args.get('scan_date_to', '')
    status = request.args.get('status', '')
    craftsman_id = request.args.get('craftsman_id', '')
    carpet_type_id = request.args.get('carpet_type_id', '')
    
    query = Carpet.query
    if scan_date_from:
        query = query.filter(Carpet.scanned_at >= scan_date_from)
    if scan_date_to:
        query = query.filter(Carpet.scanned_at <= scan_date_to)
    if status:
        query = query.filter(Carpet.status == status)
    if craftsman_id:
        query = query.filter(Carpet.craftsman_id == craftsman_id)
    if carpet_type_id:
        query = query.filter(Carpet.carpet_type_id == carpet_type_id)
    
    carpets = query.all()
    total_carpets = len(carpets)
    scanned_count = len([c for c in carpets if c.status == 'scanned'])
    sold_count = len([c for c in carpets if c.status == 'sold'])
    created_count = len([c for c in carpets if c.status == 'created'])
    
    scans_stats = []
    for i in range(7):
        date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        count = ScanLog.query.filter(ScanLog.scanned_at.like(f'{date}%'), ScanLog.result == 'success').count()
        scans_stats.append({'date': date, 'count': count})
    
    craftsmen_stats = []
    for c in Craftsman.query.all():
        craft_carpets = [carp for carp in carpets if carp.craftsman_id == c.id]
        if craft_carpets:
            craftsmen_stats.append({'name': c.name, 'count': len(craft_carpets),
                'scanned': len([cr for cr in craft_carpets if cr.status == 'scanned'])})
    
    return render_template('stats.html', carpets=carpets, total_carpets=total_carpets,
        scanned_count=scanned_count, sold_count=sold_count, created_count=created_count,
        scans_stats=scans_stats, craftsmen_stats=craftsmen_stats, craftsmen=Craftsman.query.all(),
        carpet_types=CarpetType.query.all(), selected_craftsman=craftsman_id,
        selected_type=carpet_type_id, selected_status=status,
        scan_date_from=scan_date_from, scan_date_to=scan_date_to)

@app.route('/check_db')
def check_db():
    try:
        db.session.execute('SELECT 1')
        carpet_count = Carpet.query.count()
        scan_count = ScanLog.query.count()
        order_count = MarketplaceOrder.query.count()
        account_count = MarketplaceAccount.query.count()
        
        return jsonify({
            'status': 'ok', 'database_path': DB_PATH, 'data_folder': DATA_FOLDER,
            'carpets_count': carpet_count, 'scans_count': scan_count,
            'orders_count': order_count, 'accounts_count': account_count,
            'file_exists': os.path.exists(DB_PATH),
            'file_size': os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e), 'database_path': DB_PATH}), 500

# ========== ЗАПУСК ==========
def open_browser(port):
    time.sleep(2)
    webbrowser.open(f'http://127.0.0.1:{port}')

if __name__ == '__main__':
    port = find_free_port()
    print("=" * 60)
    print("КОВРОВЫЙ УЧЁТ - Система управления")
    print("=" * 60)
    print(f"Папка с данными: {DATA_FOLDER}")
    print(f"База данных: {DB_PATH}")
    print(f"QR-коды: {QR_FOLDER}")
    print("=" * 60)
    print(f"Сервер запущен на порту: {port}")
    print(f"Открой в браузере: http://localhost:{port}")
    print("=" * 60)
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    app.run(host='0.0.0.0', port=port, debug=False)