from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash, session
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
# ========== НАСТРОЙКА ЛОГИРОВАНИЯ В ФАЙЛ ==========
import logging

# Определяем путь к лог-файлу
if getattr(sys, 'frozen', False):
    log_dir = os.path.dirname(sys.executable)
else:
    log_dir = os.path.dirname(__file__)
log_file = os.path.join(log_dir, 'carpet_manager.log')

# Настройка логгера
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()  # дублируем в консоль (если запущено с консолью)
    ]
)
logger = logging.getLogger(__name__)
logger.info("="*60)
logger.info("Программа Ковровый учёт запущена")
logger.info(f"Режим: {'EXE' if getattr(sys, 'frozen', False) else 'скрипт'}")
logger.info(f"Путь к исполняемому файлу: {sys.executable}")
logger.info(f"Лог-файл: {log_file}")
# ========== ОПРЕДЕЛЕНИЕ ПУТЕЙ ДЛЯ ШАБЛОНОВ ==========
if getattr(sys, 'frozen', False):
    # Режим EXE
    if hasattr(sys, '_MEIPASS'):
        # Для --onefile: временная папка распаковки
        base_path = sys._MEIPASS
        logger.info(f"Режим: --onefile, base_path = {base_path}")
    else:
        # Для --onedir: папка, где лежит EXE
        base_path = os.path.dirname(sys.executable)
        logger.info(f"Режим: --onedir, base_path = {base_path}")
else:
    # Режим скрипта
    base_path = os.path.dirname(__file__)
    logger.info(f"Режим: скрипт, base_path = {base_path}")

template_folder = os.path.join(base_path, 'templates')
logger.info(f"Папка шаблонов: {template_folder}")
logger.info(f"Папка шаблонов существует: {os.path.exists(template_folder)}")

app = Flask(__name__, template_folder=template_folder)
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
    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print(f"Unhandled exception: {error_msg}")
    try:
        log_path = os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd(), 'error.log')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(f"Time: {datetime.now()}\n")
            f.write(error_msg)
    except:
        pass

sys.excepthook = exception_handler

# ========== ОПРЕДЕЛЕНИЕ ПУТЕЙ ==========
if getattr(sys, 'frozen', False):
    base_path = os.path.dirname(sys.executable)
else:
    base_path = os.path.dirname(__file__)

def find_data_folder():
    possible_folders = []
    if sys.platform == 'win32':
        appdata_folder = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'CarpetManager')
        possible_folders.append(appdata_folder)
    user_folder = os.path.join(os.path.expanduser('~'), '.carpetmanager')
    possible_folders.append(user_folder)
    docs_folder = os.path.join(os.path.expanduser('~'), 'Documents', 'CarpetManager')
    possible_folders.append(docs_folder)
    temp_folder = os.path.join(os.environ.get('TEMP', os.path.expanduser('~')), 'CarpetManager')
    possible_folders.append(temp_folder)
    local_folder = os.path.join(base_path, 'Data')
    possible_folders.append(local_folder)

    for folder in possible_folders:
        try:
            os.makedirs(folder, exist_ok=True)
            test_file = os.path.join(folder, '.write_test')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            print(f"[FOLDER] Используется папка: {folder}")
            return folder
        except Exception as e:
            print(f"[FOLDER] Папка {folder} недоступна: {e}")
            continue
    return os.environ.get('TEMP', 'C:\\Temp')

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

def find_free_port():
    preferred_ports = [5000, 5001, 5002, 8080, 8081, 3000, 8000, 8888]
    for port in preferred_ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                s.listen(1)
                return port
        except OSError:
            continue
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            return s.getsockname()[1]
    except:
        return 8080

# ========== МОДЕЛИ ==========
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

class MarketplaceAccount(db.Model):
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
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('marketplace_account.id'))
    sync_time = db.Column(db.String(20))
    orders_found = db.Column(db.Integer)
    orders_new = db.Column(db.Integer)
    error_message = db.Column(db.Text)
    status = db.Column(db.String(20))
class WBAnalyticsCache(db.Model):
    """Кэш аналитики Wildberries"""
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('marketplace_account.id'))
    nm_id = db.Column(db.Integer)  # Артикул WB
    data = db.Column(db.Text)  # JSON с данными аналитики
    period_start = db.Column(db.String(20))
    period_end = db.Column(db.String(20))
    cached_at = db.Column(db.String(20))
    
class WBProductAnalytics(db.Model):
    """Аналитика по товарам Wildberries"""
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('marketplace_account.id'))
    nm_id = db.Column(db.Integer)
    product_name = db.Column(db.String(200))
    brand_name = db.Column(db.String(100))
    
    # Текущий период
    views = db.Column(db.Integer, default=0)  # Просмотры
    cart_adds = db.Column(db.Integer, default=0)  # Добавления в корзину
    orders = db.Column(db.Integer, default=0)  # Заказы
    sales = db.Column(db.Integer, default=0)  # Продажи (выкупы)
    cancellations = db.Column(db.Integer, default=0)  # Отмены
    returns = db.Column(db.Integer, default=0)  # Возвраты
    
    # Прошлый период (для сравнения)
    past_views = db.Column(db.Integer, default=0)
    past_cart_adds = db.Column(db.Integer, default=0)
    past_orders = db.Column(db.Integer, default=0)
    past_sales = db.Column(db.Integer, default=0)
    
    # Показатели конверсии
    conversion_to_cart = db.Column(db.Float, default=0)  # Просмотр → Корзина
    conversion_to_order = db.Column(db.Float, default=0)  # Просмотр → Заказ
    conversion_to_sale = db.Column(db.Float, default=0)  # Просмотр → Продажа
    
    period_start = db.Column(db.String(20))
    period_end = db.Column(db.String(20))
    updated_at = db.Column(db.String(20))
    
    carpet_id = db.Column(db.String(50), db.ForeignKey('carpet.carpet_id'), nullable=True)    

# ========== МИГРАЦИЯ БД ==========
DB_VERSION = 2

def get_db_version():
    try:
        result = db.session.execute("SELECT version FROM db_version LIMIT 1").fetchone()
        return result[0] if result else 0
    except:
        return 0

def set_db_version(version):
    try:
        db.session.execute("CREATE TABLE IF NOT EXISTS db_version (version INTEGER)")
        db.session.execute("DELETE FROM db_version")
        db.session.execute("INSERT INTO db_version (version) VALUES (:version)", {'version': version})
        db.session.commit()
    except:
        pass

def safe_add_column(table, column, type_sql):
    try:
        cursor = db.session.execute(f"PRAGMA table_info({table})").fetchall()
        existing = [col[1] for col in cursor] if cursor else []
        if column not in existing:
            db.session.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_sql}")
            db.session.commit()
            print(f"[MIGRATION] Добавлена колонка {column} в {table}")
    except Exception as e:
        print(f"[MIGRATION] Ошибка добавления {column}: {e}")

def init_database():
    os.makedirs(DATA_FOLDER, exist_ok=True)
    db.create_all()
    current = get_db_version()
    if current == 0:
        set_db_version(DB_VERSION)
    elif current < DB_VERSION:
        if current == 1:
            safe_add_column('marketplace_order', 'account_id', 'INTEGER')
            safe_add_column('marketplace_order', 'wb_supply_id', 'VARCHAR(50)')
            safe_add_column('marketplace_order', 'ozon_posting_number', 'VARCHAR(50)')
            safe_add_column('marketplace_account', 'account_name', 'VARCHAR(100)')
            safe_add_column('marketplace_account', 'account_login', 'VARCHAR(100)')
            safe_add_column('marketplace_account', 'client_id', 'VARCHAR(100)')
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
        else:
            set_db_version(DB_VERSION)

# ========== ФУНКЦИИ ПРОГНОЗА НА ОСНОВЕ ЗАКАЗОВ МАРКЕТПЛЕЙСОВ ==========
def forecast_sales(days=30):
    """Прогноз на основе отправленных заказов (status='shipped')"""
    try:
        orders = MarketplaceOrder.query.filter_by(status='shipped').all()
        if len(orders) < 7:
            return {
                "error": None,
                "no_data": True,
                "message": "Недостаточно данных для прогноза (нужно минимум 7 отправленных заказов)",
                "data": [], "total": 0, "daily_avg": 0,
                "historical_data": [], "historical_dates": []
            }

        daily_counts = defaultdict(int)
        for order in orders:
            date_str = order.shipped_at if order.shipped_at else order.ordered_at
            if date_str:
                date = date_str[:10]
                daily_counts[date] += 1

        if not daily_counts:
            return {
                "error": None,
                "no_data": True,
                "message": "Нет данных о датах отправки заказов",
                "data": [], "total": 0, "daily_avg": 0
            }

        dates = sorted(daily_counts.keys())
        counts = [daily_counts[d] for d in dates]

        if len(counts) >= 7:
            avg = sum(counts[-7:]) / 7
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
            "method": "Скользящее среднее (7 дней) на основе заказов маркетплейсов",
            "data": forecast_with_season,
            "dates": forecast_dates,
            "total": sum(forecast_with_season),
            "daily_avg": round(sum(forecast_with_season) / days, 1),
            "historical_data": counts[-30:],
            "historical_dates": dates[-30:]
        }
    except Exception as e:
        print(f"[FORECAST] Ошибка: {e}")
        traceback.print_exc()
        return {"error": str(e), "no_data": True, "data": [], "total": 0, "daily_avg": 0}

def calculate_trend():
    """Тренд на основе отправленных заказов"""
    try:
        orders = MarketplaceOrder.query.filter_by(status='shipped').all()
        if len(orders) < 14:
            return {"trend": "unknown", "percent": 0, "last_week": 0, "prev_week": 0}

        now = datetime.now()
        last_week = 0
        prev_week = 0

        for order in orders:
            date_str = order.shipped_at if order.shipped_at else order.ordered_at
            if date_str:
                try:
                    order_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
                    days_diff = (now - order_date).days
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

# ========== API МАРКЕТПЛЕЙСОВ ==========
class MarketplaceAPI:
    @staticmethod
    def get_wb_orders(api_key, date_from=None):
        if not date_from:
            date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        try:
            r = requests.get("https://suppliers-api.wildberries.ru/api/v3/orders",
                             headers={"Authorization": api_key},
                             params={"dateFrom": date_from}, timeout=30)
            return r.json().get('orders', []) if r.status_code == 200 else []
        except:
            return []
    @staticmethod
    def get_ozon_orders(api_key, client_id, date_from=None):
        if not date_from:
            date_from = (datetime.now() - timedelta(days=7)).isoformat()
        try:
            r = requests.post("https://api-seller.ozon.ru/v3/posting/fbs/list",
                              headers={"Api-Key": api_key, "Client-Id": client_id, "Content-Type": "application/json"},
                              json={"dir": "desc", "filter": {"since": date_from, "status": "awaiting_packaging"}, "limit": 100},
                              timeout=30)
            return r.json().get('result', {}).get('postings', []) if r.status_code == 200 else []
        except:
            return []

def generate_qr_code(carpet_id, _):
    qr = qrcode.QRCode(version=1, box_size=10, border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(carpet_id)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    path = os.path.join(QR_FOLDER, f"carpet_{carpet_id}.png")
    img.save(path)
    return path

def generate_next_id():
    last = Carpet.query.order_by(Carpet.id.desc()).first()
    if last:
        try:
            n = int(last.carpet_id.split('-')[1]) + 1
        except:
            n = Carpet.query.count() + 1
    else:
        n = 1
    return f"CARPET-{n:04d}"

def sync_account_orders(account_id):
    """Синхронизация заказов для конкретного аккаунта (Wildberries DBS + история)"""
    acc = db.session.get(MarketplaceAccount, account_id)
    if not acc or not acc.is_active:
        logger.warning(f"Аккаунт {account_id} не активен или не найден")
        return 0
    
    new = 0
    all_orders = []
    
    try:
        if acc.marketplace == 'wb':
            headers = {"Authorization": acc.api_key}
            request_success = False
            
            # ========== 1. Получаем НОВЫЕ сборочные задания ==========
            url_new = "https://marketplace-api.wildberries.ru/api/v3/dbs/orders/new"
            logger.info(f"Запрос к WB (новые заказы): {url_new}")
            
            try:
                response_new = requests.get(url_new, headers=headers, timeout=30)
                logger.info(f"Статус ответа (новые): {response_new.status_code}")
                
                if response_new.status_code == 200:
                    data_new = response_new.json()
                    new_orders = data_new.get('orders', [])
                    logger.info(f"Получено новых заказов: {len(new_orders)}")
                    all_orders.extend(new_orders)
                    request_success = True
                else:
                    logger.error(f"Ошибка получения новых заказов: {response_new.status_code} - {response_new.text[:200]}")
            except Exception as e:
                logger.error(f"Исключение при получении новых заказов: {e}")
            
            # ========== 2. Получаем ЗАВЕРШЁННЫЕ заказы (историю) ==========
            url_completed = "https://marketplace-api.wildberries.ru/api/v3/dbs/orders"
            params = {
                "limit": 100,
                "next": 0,
                "dateFrom": int((datetime.now() - timedelta(days=30)).timestamp()),
                "dateTo": int(datetime.now().timestamp())
            }
            logger.info(f"Запрос к WB (история): {url_completed}")
            
            try:
                response_completed = requests.get(url_completed, headers=headers, params=params, timeout=30)
                logger.info(f"Статус ответа (история): {response_completed.status_code}")
                
                if response_completed.status_code == 200:
                    data_completed = response_completed.json()
                    completed_orders = data_completed.get('orders', [])
                    logger.info(f"Получено завершённых заказов: {len(completed_orders)}")
                    all_orders.extend(completed_orders)
                    request_success = True
                else:
                    logger.error(f"Ошибка получения истории: {response_completed.status_code} - {response_completed.text[:200]}")
            except Exception as e:
                logger.error(f"Исключение при получении истории: {e}")
            
            # Проверяем, был ли хоть один успешный запрос
            if not request_success:
                flash(f'❌ {acc.account_name}: не удалось подключиться к Wildberries API. Проверьте API-ключ и интернет.', 'error')
                return 0
            
            # ========== 3. Обрабатываем все полученные заказы ==========
            logger.info(f"Всего заказов для обработки: {len(all_orders)}")
            
            for o in all_orders:
                existing = MarketplaceOrder.query.filter_by(
                    marketplace='wb', 
                    order_id=str(o.get('id'))
                ).first()
                
                if not existing:
                    address = o.get('address', {})
                    mo = MarketplaceOrder(
                        account_id=acc.id,
                        marketplace='wb',
                        order_id=str(o.get('id')),
                        customer_name='',
                        customer_phone='',
                        delivery_address=address.get('fullAddress', ''),
                        status='new',
                        ordered_at=o.get('createdAt', ''),
                        price=o.get('price', 0),
                        products_info=json.dumps(o.get('skus', [])),
                        wb_supply_id=str(o.get('warehouseId', ''))
                    )
                    db.session.add(mo)
                    new += 1
            
            db.session.commit()
            
            # ========== 4. Flash-сообщения (только при реальных изменениях или ошибках) ==========
            if new > 0:
                flash(f'✅ {acc.account_name}: получено {new} новых заказов', 'success')
            # Если заказов нет, НЕ показываем ничего (это нормальная ситуация)
                    
        elif acc.marketplace == 'ozon':
            # ========== Ozon API ==========
            url = "https://api-seller.ozon.ru/v3/posting/fbs/list"
            headers = {
                "Api-Key": acc.api_key,
                "Client-Id": acc.client_id,
                "Content-Type": "application/json"
            }
            payload = {
                "dir": "desc",
                "filter": {
                    "since": (datetime.now() - timedelta(days=30)).isoformat(),
                    "status": "awaiting_packaging"
                },
                "limit": 100
            }
            
            logger.info(f"Запрос к Ozon API")
            
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=30)
                logger.info(f"Статус ответа Ozon: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    orders = data.get('result', {}).get('postings', [])
                    logger.info(f"Получено заказов: {len(orders)}")
                    
                    for o in orders:
                        if not MarketplaceOrder.query.filter_by(marketplace='ozon', order_id=o.get('posting_number')).first():
                            cust = o.get('customer', {})
                            deliv = o.get('delivery', {})
                            prods = o.get('products', [])
                            mo = MarketplaceOrder(
                                account_id=acc.id,
                                marketplace='ozon',
                                order_id=o.get('posting_number'),
                                customer_name=cust.get('name', ''),
                                customer_phone=cust.get('phone', ''),
                                delivery_address=deliv.get('address', {}).get('address_txt', ''),
                                status='new',
                                ordered_at=o.get('created_at', ''),
                                price=sum(p.get('price', 0) * p.get('quantity', 1) for p in prods),
                                products_info=json.dumps(prods),
                                ozon_posting_number=o.get('posting_number')
                            )
                            db.session.add(mo)
                            new += 1
                    
                    db.session.commit()
                    
                    if new > 0:
                        flash(f'✅ {acc.account_name}: получено {new} новых заказов', 'success')
                    # Если заказов нет, НЕ показываем ничего
                else:
                    error_msg = f"Ozon API ошибка {response.status_code}"
                    logger.error(f"{error_msg}: {response.text[:200]}")
                    flash(f'❌ Ошибка синхронизации {acc.account_name}: {error_msg}', 'error')
                    return 0
                    
            except requests.exceptions.ConnectionError:
                flash(f'❌ {acc.account_name}: ошибка соединения с Ozon API. Проверьте интернет.', 'error')
                return 0
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Исключение при запросе к Ozon: {error_msg}")
                flash(f'❌ Ошибка синхронизации {acc.account_name}: {error_msg[:200]}', 'error')
                return 0
        
        # Обновляем время последней синхронизации
        acc.last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.session.commit()
        
        # Логируем синхронизацию
        sync_log = MarketplaceSyncLog(
            account_id=acc.id,
            sync_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            orders_found=len(all_orders) if acc.marketplace == 'wb' else len(orders) if 'orders' in locals() else 0,
            orders_new=new,
            status='success'
        )
        db.session.add(sync_log)
        db.session.commit()
        
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Ошибка синхронизации аккаунта {acc.account_name}: {error_msg}")
        
        sync_log = MarketplaceSyncLog(
            account_id=acc.id,
            sync_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error_message=error_msg,
            status='error'
        )
        db.session.add(sync_log)
        db.session.commit()
        
        flash(f'❌ Ошибка синхронизации {acc.account_name}: {error_msg[:200]}', 'error')
    
    return new
@app.route('/sync_orders')
def sync_orders():
    """Перенаправление со старого маршрута на новый"""
    return redirect(url_for('sync_all_orders'))
def get_wb_analytics(api_key, account_id, period_days=30):
    """
    Получение аналитики по товарам Wildberries
    period_days: за сколько дней получить аналитику (макс 365)
    """
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)
        
        # Форматируем даты для API
        date_from = start_date.strftime("%Y-%m-%d")
        date_to = end_date.strftime("%Y-%m-%d")
        
        # Получаем аналитику по всем товарам
        url = "https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products"
        
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json"
        }
        
        # Параметры запроса
        payload = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "limit": 1000,
            "offset": 0
        }
        
        logger.info(f"Запрос аналитики WB: {date_from} - {date_to}")
        
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        
        if response.status_code == 200:
            data = response.json()
            products = data.get('data', {}).get('products', [])
            logger.info(f"Получено {len(products)} товаров в аналитике")
            return products
        else:
            logger.error(f"Ошибка WB Analytics: {response.status_code} - {response.text[:200]}")
            return []
            
    except Exception as e:
        logger.exception(f"Ошибка получения аналитики WB: {e}")
        return []

def sync_wb_analytics(account_id):
    """Синхронизация аналитики Wildberries"""
    acc = db.session.get(MarketplaceAccount, account_id)
    if not acc or not acc.is_active or acc.marketplace != 'wb':
        return 0
    
    try:
        products = get_wb_analytics(acc.api_key, account_id, 30)
        
        if not products:
            return 0
        
        updated = 0
        new = 0
        
        for prod in products:
            nm_id = prod.get('nmId')
            if not nm_id:
                continue
            
            # Ищем существующую запись
            analytic = WBProductAnalytics.query.filter_by(
                account_id=account_id,
                nm_id=nm_id
            ).first()
            
            if not analytic:
                analytic = WBProductAnalytics(
                    account_id=account_id,
                    nm_id=nm_id,
                    product_name=prod.get('productName', ''),
                    brand_name=prod.get('brandName', '')
                )
                new += 1
            
            # Данные текущего периода
            selected = prod.get('selectedPeriod', {})
            past = prod.get('pastPeriod', {})
            
            analytic.views = selected.get('views', 0)
            analytic.cart_adds = selected.get('carts', 0)
            analytic.orders = selected.get('orders', 0)
            analytic.sales = selected.get('sales', 0)
            analytic.cancellations = selected.get('cancellations', 0)
            analytic.returns = selected.get('returns', 0)
            
            analytic.past_views = past.get('views', 0)
            analytic.past_cart_adds = past.get('carts', 0)
            analytic.past_orders = past.get('orders', 0)
            analytic.past_sales = past.get('sales', 0)
            
            # Рассчитываем конверсию
            if analytic.views > 0:
                analytic.conversion_to_cart = round((analytic.cart_adds / analytic.views) * 100, 2)
                analytic.conversion_to_order = round((analytic.orders / analytic.views) * 100, 2)
                analytic.conversion_to_sale = round((analytic.sales / analytic.views) * 100, 2)
            
            analytic.period_start = selected.get('dateFrom', '')
            analytic.period_end = selected.get('dateTo', '')
            analytic.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Пытаемся связать с ковром по артикулу
            carpet = Carpet.query.filter_by(carpet_id=f"CARPET-{nm_id:04d}").first()
            if carpet:
                analytic.carpet_id = carpet.carpet_id
            
            db.session.add(analytic)
            updated += 1
        
        db.session.commit()
        
        # Кэшируем время последней синхронизации
        cache = WBAnalyticsCache.query.filter_by(account_id=account_id).first()
        if not cache:
            cache = WBAnalyticsCache(account_id=account_id)
        
        cache.cached_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cache.period_start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        cache.period_end = datetime.now().strftime("%Y-%m-%d")
        db.session.add(cache)
        db.session.commit()
        
        flash(f'📊 WB Аналитика: {new} новых, {updated} обновлено', 'success')
        return updated
        
    except Exception as e:
        logger.exception(f"Ошибка синхронизации аналитики: {e}")
        flash(f'❌ Ошибка синхронизации аналитики WB: {str(e)[:200]}', 'error')
        return 0
# ========== ИНИЦИАЛИЗАЦИЯ ==========
with app.app_context():
    init_database()
    if CarpetType.query.count() == 0:
        for t in [CarpetType(name="Персидский", base_price=15000),
                  CarpetType(name="Турецкий", base_price=12000),
                  CarpetType(name="Современный", base_price=8000),
                  CarpetType(name="Винтажный", base_price=20000)]:
            db.session.add(t)
        db.session.commit()
    if Craftsman.query.count() == 0:
        for c in [Craftsman(name="Анна Иванова", phone="+7-999-123-45-67"),
                  Craftsman(name="Мария Петрова", phone="+7-999-234-56-78"),
                  Craftsman(name="Елена Сидорова", phone="+7-999-345-67-89"),
                  Craftsman(name="Ольга Смирнова", phone="+7-999-456-78-90")]:
            db.session.add(c)
        db.session.commit()
    if Carpet.query.count() == 0:
        for qr, tid, cid, price, status, sat in [
            ("CARPET-0001",1,1,15000,"scanned","2025-06-01 14:30:00"),
            ("CARPET-0002",2,2,12000,"created",None),
            ("CARPET-0003",3,1,8000,"created",None),
            ("CARPET-0004",1,3,49000,"created",None),
            ("CARPET-0005",2,2,12000,"created",None),
            ("CARPET-0006",3,1,8000,"created",None),
        ]:
            c = Carpet(carpet_id=qr, carpet_type_id=tid, craftsman_id=cid, price=price, status=status, scanned_at=sat)
            db.session.add(c)
        db.session.commit()
        for c in Carpet.query.all():
            ct = db.session.get(CarpetType, c.carpet_type_id)
            cr = db.session.get(Craftsman, c.craftsman_id)
            if ct and cr:
                c.qr_code_path = generate_qr_code(c.carpet_id, {})
        db.session.commit()

# ========== МАРШРУТЫ ==========
@app.route('/')
def index():
    return render_template('index.html',
        carpets=Carpet.query.all(),
        craftsmen=Craftsman.query.all(),
        carpet_types=CarpetType.query.all(),
        new_orders_count=MarketplaceOrder.query.filter_by(status='new').count(),
        processing_orders_count=MarketplaceOrder.query.filter_by(status='processing').count(),
        ready_orders_count=MarketplaceOrder.query.filter_by(status='ready').count(),
        accounts_count=MarketplaceAccount.query.filter_by(is_active=True).count()
    )
@app.route('/wb_analytics')
def wb_analytics():
    """Страница аналитики Wildberries"""
    accounts = MarketplaceAccount.query.filter_by(marketplace='wb', is_active=True).all()
    
    # Получаем аналитику
    analytics = WBProductAnalytics.query.all()
    
    # Агрегированная статистика
    total_stats = {
        'total_views': sum(a.views for a in analytics),
        'total_cart_adds': sum(a.cart_adds for a in analytics),
        'total_orders': sum(a.orders for a in analytics),
        'total_sales': sum(a.sales for a in analytics),
        'avg_conversion_to_cart': 0,
        'avg_conversion_to_order': 0,
        'avg_conversion_to_sale': 0
    }
    
    if total_stats['total_views'] > 0:
        total_stats['avg_conversion_to_cart'] = round((total_stats['total_cart_adds'] / total_stats['total_views']) * 100, 2)
        total_stats['avg_conversion_to_order'] = round((total_stats['total_orders'] / total_stats['total_views']) * 100, 2)
        total_stats['avg_conversion_to_sale'] = round((total_stats['total_sales'] / total_stats['total_views']) * 100, 2)
    
    # Топ товаров
    top_by_views = sorted(analytics, key=lambda x: x.views, reverse=True)[:10]
    top_by_sales = sorted(analytics, key=lambda x: x.sales, reverse=True)[:10]
    top_by_conversion = sorted([a for a in analytics if a.views > 50], key=lambda x: x.conversion_to_sale, reverse=True)[:10]
    
    return render_template('wb_analytics.html',
                          accounts=accounts,
                          analytics=analytics,
                          total_stats=total_stats,
                          top_by_views=top_by_views,
                          top_by_sales=top_by_sales,
                          top_by_conversion=top_by_conversion)

@app.route('/sync_wb_analytics/<int:account_id>')
def sync_wb_analytics_route(account_id):
    """Синхронизация аналитики WB"""
    sync_wb_analytics(account_id)
    return redirect(url_for('wb_analytics'))

@app.route('/sync_all_wb_analytics')
def sync_all_wb_analytics():
    """Синхронизация аналитики всех аккаунтов WB"""
    accounts = MarketplaceAccount.query.filter_by(marketplace='wb', is_active=True).all()
    for acc in accounts:
        sync_wb_analytics(acc.id)
    return redirect(url_for('wb_analytics'))

@app.route('/wb_product_detail/<int:nm_id>')
def wb_product_detail(nm_id):
    """Детальная страница товара"""
    analytic = WBProductAnalytics.query.filter_by(nm_id=nm_id).first_or_404()
    
    # Динамика за последние дни (можно добавить)
    return render_template('wb_product_detail.html', product=analytic)
@app.route('/forecast')
def forecast_page():
    try:
        forecast = forecast_sales(30)
        trend = calculate_trend()
        marketplace_stats = {
            'total_orders': MarketplaceOrder.query.count(),
            'shipped_orders': MarketplaceOrder.query.filter_by(status='shipped').count(),
            'processing_orders': MarketplaceOrder.query.filter_by(status='processing').count(),
            'ready_orders': MarketplaceOrder.query.filter_by(status='ready').count(),
            'new_orders': MarketplaceOrder.query.filter_by(status='new').count(),
            'total_revenue': db.session.query(db.func.sum(MarketplaceOrder.price)).filter(MarketplaceOrder.status == 'shipped').scalar() or 0,
            'wb_orders': MarketplaceOrder.query.filter_by(marketplace='wb', status='shipped').count(),
            'ozon_orders': MarketplaceOrder.query.filter_by(marketplace='ozon', status='shipped').count(),
            'wb_revenue': db.session.query(db.func.sum(MarketplaceOrder.price)).filter(MarketplaceOrder.marketplace == 'wb', MarketplaceOrder.status == 'shipped').scalar() or 0,
            'ozon_revenue': db.session.query(db.func.sum(MarketplaceOrder.price)).filter(MarketplaceOrder.marketplace == 'ozon', MarketplaceOrder.status == 'shipped').scalar() or 0,
        }
        return render_template('forecast.html', forecast=forecast, trend=trend, marketplace_stats=marketplace_stats)
    except Exception as e:
        print(f"[FORECAST_PAGE] Ошибка: {e}")
        traceback.print_exc()
        return render_template('forecast.html', forecast={"error": str(e), "no_data": True}, trend={"trend": "unknown", "percent": 0}, marketplace_stats={})

@app.route('/add_carpet', methods=['POST'])
def add_carpet():
    cid = generate_next_id()
    carpet = Carpet(
        carpet_id=cid,
        carpet_type_id=request.form['carpet_type_id'],
        craftsman_id=request.form['craftsman_id'],
        price=float(request.form['price']),
        size=request.form.get('size',''),
        material=request.form.get('material',''),
        color=request.form.get('color',''),
        status='created',
        notes=request.form.get('notes','')
    )
    db.session.add(carpet)
    db.session.commit()
    ct = db.session.get(CarpetType, carpet.carpet_type_id)
    cr = db.session.get(Craftsman, carpet.craftsman_id)
    if ct and cr:
        carpet.qr_code_path = generate_qr_code(cid, {})
        db.session.commit()
    flash(f'Ковёр {cid} добавлен', 'success')
    return redirect(url_for('index'))

@app.route('/add_carpet_group', methods=['POST'])
def add_carpet_group():
    type_id = request.form['carpet_type_id']
    count = int(request.form['count'])
    craftsman_id = request.form['craftsman_id']
    size = request.form.get('size','')
    material = request.form.get('material','')
    color = request.form.get('color','')
    ct = db.session.get(CarpetType, type_id)
    cr = db.session.get(Craftsman, craftsman_id)
    if not ct or not cr:
        flash('Ошибка: тип или швея не найдены', 'error')
        return redirect(url_for('index'))
    created = []
    for i in range(count):
        cid = generate_next_id()
        carpet = Carpet(
            carpet_id=cid, carpet_type_id=type_id, craftsman_id=craftsman_id,
            price=ct.base_price, size=size, material=material, color=color,
            status='created', notes=f'Групповое {i+1}/{count}'
        )
        db.session.add(carpet)
        db.session.flush()
        carpet.qr_code_path = generate_qr_code(cid, {})
        created.append(cid)
        if (i+1) % 100 == 0:
            print(f"Прогресс: {i+1}/{count}")
    db.session.commit()
    flash(f'Создано {len(created)} ковров типа "{ct.name}"', 'success')
    return redirect(url_for('index'))

@app.route('/edit_carpet/<int:id>', methods=['GET','POST'])
def edit_carpet(id):
    carpet = Carpet.query.get_or_404(id)
    if request.method == 'POST':
        carpet.carpet_type_id = request.form['carpet_type_id']
        carpet.craftsman_id = request.form['craftsman_id']
        carpet.price = float(request.form['price'])
        carpet.size = request.form.get('size','')
        carpet.material = request.form.get('material','')
        carpet.color = request.form.get('color','')
        carpet.notes = request.form.get('notes','')
        db.session.commit()
        ct = db.session.get(CarpetType, carpet.carpet_type_id)
        cr = db.session.get(Craftsman, carpet.craftsman_id)
        if ct and cr:
            carpet.qr_code_path = generate_qr_code(carpet.carpet_id, {})
            db.session.commit()
        flash(f'Ковёр {carpet.carpet_id} обновлён', 'success')
        return redirect(url_for('index'))
    return render_template('edit_carpet.html', carpet=carpet,
                          craftsmen=Craftsman.query.all(),
                          carpet_types=CarpetType.query.all())

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
    db.session.add(Craftsman(name=request.form['name'], phone=request.form.get('phone','')))
    db.session.commit()
    flash('Швея добавлена', 'success')
    return redirect(url_for('index'))

@app.route('/edit_craftsman/<int:id>', methods=['GET','POST'])
def edit_craftsman(id):
    c = Craftsman.query.get_or_404(id)
    if request.method == 'POST':
        c.name = request.form['name']
        c.phone = request.form['phone']
        db.session.commit()
        flash('Данные швеи обновлены', 'success')
        return redirect(url_for('index'))
    return render_template('edit_craftsman.html', craftsman=c)

@app.route('/delete_craftsman/<int:id>')
def delete_craftsman(id):
    c = Craftsman.query.get_or_404(id)
    cnt = len(c.carpets)
    for carpet in c.carpets:
        if carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
            os.remove(carpet.qr_code_path)
    db.session.delete(c)
    db.session.commit()
    flash(f'Швея "{c.name}" удалена с {cnt} коврами', 'success')
    return redirect(url_for('index'))

@app.route('/craftsman/<int:id>')
def craftsman_detail(id):
    c = Craftsman.query.get_or_404(id)
    q = Carpet.query.filter_by(craftsman_id=id)
    from_date = request.args.get('scan_date_from','')
    to_date = request.args.get('scan_date_to','')
    if from_date:
        q = q.filter(Carpet.scanned_at >= from_date)
    if to_date:
        q = q.filter(Carpet.scanned_at <= to_date)
    carpets = q.all()
    type_stats = {}
    month_stats = {}
    for carpet in carpets:
        tn = carpet.carpet_type_ref.name if carpet.carpet_type_ref else 'Неизвестно'
        type_stats[tn] = type_stats.get(tn,0)+1
        if carpet.scanned_at:
            m = carpet.scanned_at[:7]
            month_stats[m] = month_stats.get(m,0)+1
    return render_template('craftsman_detail.html', craftsman=c, carpets=carpets,
                          total_count=len(carpets),
                          scanned_count=len([x for x in carpets if x.status=='scanned']),
                          total_price=sum(x.price for x in carpets),
                          type_stats=type_stats, month_stats=month_stats,
                          scan_date_from=from_date, scan_date_to=to_date)

@app.route('/types')
def types_list():
    return render_template('types.html', types=CarpetType.query.all())

@app.route('/add_type', methods=['POST'])
def add_type():
    name = request.form['name']
    price = float(request.form['base_price'])
    desc = request.form.get('description','')
    if CarpetType.query.filter_by(name=name).first():
        flash('Тип уже существует', 'error')
    else:
        db.session.add(CarpetType(name=name, base_price=price, description=desc))
        db.session.commit()
        flash(f'Тип "{name}" добавлен', 'success')
    return redirect(url_for('types_list'))

@app.route('/edit_type/<int:id>', methods=['GET','POST'])
def edit_type(id):
    t = CarpetType.query.get_or_404(id)
    if request.method == 'POST':
        t.name = request.form['name']
        t.base_price = float(request.form['base_price'])
        t.description = request.form.get('description','')
        db.session.commit()
        flash(f'Тип "{t.name}" обновлён', 'success')
        return redirect(url_for('types_list'))
    return render_template('edit_type.html', type=t)

@app.route('/delete_type/<int:id>')
def delete_type(id):
    t = CarpetType.query.get_or_404(id)
    if len(t.carpets) > 0:
        flash('Нельзя удалить тип с коврами', 'error')
    else:
        db.session.delete(t)
        db.session.commit()
        flash('Тип удалён', 'info')
    return redirect(url_for('types_list'))

@app.route('/scan_qr', methods=['POST'])
def scan_qr():
    data = request.json.get('qr_code')
    scanner = request.json.get('scanner','admin')
    carpet = Carpet.query.filter_by(carpet_id=data).first()
    log = ScanLog(carpet_id=data, scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), scanned_by=scanner)
    if not carpet:
        log.result = 'not_found'
        db.session.add(log)
        db.session.commit()
        return jsonify({'success': False, 'message': '❌ Ковёр не найден'})
    if carpet.status == 'scanned':
        log.result = 'already_scanned'
        db.session.add(log)
        db.session.commit()
        return jsonify({'success': False, 'already_scanned': True, 'carpet_id': carpet.carpet_id,
                       'scanned_at': carpet.scanned_at, 'message': f'⚠️ Уже отсканирован {carpet.scanned_at}'})
    carpet.status = 'scanned'
    carpet.scanned_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    carpet.scanned_by = scanner
    log.result = 'success'
    db.session.add(log)
    db.session.commit()
    ct = db.session.get(CarpetType, carpet.carpet_type_id)
    cr = db.session.get(Craftsman, carpet.craftsman_id)
    return jsonify({'success': True, 'first_time': True, 'carpet_id': carpet.carpet_id,
                   'carpet_type': ct.name if ct else '-', 'craftsman': cr.name if cr else '-',
                   'price': carpet.price, 'size': carpet.size or '-', 'material': carpet.material or '-',
                   'color': carpet.color or '-', 'scanned_at': carpet.scanned_at})

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
        w, h = A4
        sticker_w = 30*mm
        sticker_h = 20*mm
        xc = (w - sticker_w)/2
        yc = (h - sticker_h)/2
        c.rect(xc, yc, sticker_w, sticker_h)
        qr_sz = 12*mm
        qr_x = xc + 1.5*mm
        qr_y = yc + 2*mm
        if carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
            c.drawImage(ImageReader(carpet.qr_code_path), qr_x, qr_y, qr_sz, qr_sz)
        tx = qr_x + qr_sz + 1*mm
        ty = yc + sticker_h - 2.5*mm
        ct = db.session.get(CarpetType, carpet.carpet_type_id)
        cr = db.session.get(Craftsman, carpet.craftsman_id)
        type_name = ct.name if ct else '-'
        craftsman_name = cr.name if cr else '-'
        if FONT_REGISTERED:
            c.setFont("RussianFont", 5)
        else:
            c.setFont("Helvetica", 5)
        c.drawString(tx, ty, carpet.carpet_id)
        c.drawString(tx, ty-2.5*mm, type_name)
        c.drawString(tx, ty-5*mm, craftsman_name)
        c.drawString(tx, ty-7.5*mm, f"{carpet.price} p")
        c.save()
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f'{carpet.carpet_id}_sticker.pdf')
    except Exception as e:
        return f"Ошибка: {e}", 500

@app.route('/mass_print_qr')
def mass_print_qr():
    t = request.args.get('carpet_type_id','')
    c = request.args.get('craftsman_id','')
    s = request.args.get('status','')
    q = Carpet.query
    if t:
        q = q.filter(Carpet.carpet_type_id == t)
    if c:
        q = q.filter(Carpet.craftsman_id == c)
    if s:
        q = q.filter(Carpet.status == s)
    carpets = q.all()
    return render_template('mass_print.html', carpets=carpets,
                          carpet_types=CarpetType.query.all(),
                          craftsmen=Craftsman.query.all(),
                          selected_type=t, selected_craftsman=c, selected_status=s)

@app.route('/generate_qr_zip')
def generate_qr_zip():
    t = request.args.get('carpet_type_id','')
    c = request.args.get('craftsman_id','')
    s = request.args.get('status','')
    q = Carpet.query
    if t: q = q.filter(Carpet.carpet_type_id == t)
    if c: q = q.filter(Carpet.craftsman_id == c)
    if s: q = q.filter(Carpet.status == s)
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for carpet in q.all():
            if carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
                zf.write(carpet.qr_code_path, f"{carpet.carpet_id}.png")
    zip_buf.seek(0)
    return send_file(zip_buf, mimetype='application/zip', as_attachment=True, download_name='qr_codes.zip')

@app.route('/generate_qr_pdf')
def generate_qr_pdf():
    t = request.args.get('carpet_type_id','')
    c = request.args.get('craftsman_id','')
    s = request.args.get('status','')
    q = Carpet.query
    if t: q = q.filter(Carpet.carpet_type_id == t)
    if c: q = q.filter(Carpet.craftsman_id == c)
    if s: q = q.filter(Carpet.status == s)
    carpets = q.all()
    if not carpets:
        flash('Нет ковров для печати', 'error')
        return redirect(url_for('mass_print_qr'))
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        from PIL import Image
        buffer = io.BytesIO()
        w, h = A4
        for i, carpet in enumerate(carpets):
            if not carpet.qr_code_path or not os.path.exists(carpet.qr_code_path):
                continue
            pil = Image.open(carpet.qr_code_path).resize((int(w), int(h)), Image.Resampling.LANCZOS)
            tmp = io.BytesIO()
            pil.save(tmp, format='PNG')
            tmp.seek(0)
            c = canvas.Canvas(buffer, pagesize=A4)
            c.drawImage(ImageReader(tmp), 0, 0, w, h)
            c.setFillColorRGB(1,1,1)
            c.rect(0,0,w,55, fill=1, stroke=0)
            c.setFillColorRGB(0,0,0)
            c.setFont("Helvetica-Bold", 14)
            ct = db.session.get(CarpetType, carpet.carpet_type_id)
            cr = db.session.get(Craftsman, carpet.craftsman_id)
            c.drawCentredString(w/2, 38, carpet.carpet_id)
            c.setFont("Helvetica", 10)
            c.drawCentredString(w/2, 24, f"{ct.name if ct else '-'} | {cr.name if cr else '-'} | {carpet.price} ₽")
            c.setFont("Helvetica", 8)
            c.drawCentredString(w/2, 10, f"{i+1}/{len(carpets)}")
            c.save()
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f'qr_print_{len(carpets)}_pages.pdf')
    except Exception as e:
        return f"Ошибка: {e}", 500

# ========== ОСНОВНАЯ ФУНКЦИЯ ГЕНЕРАЦИИ PDF С QR НА ВЕСЬ ЛИСТ (УМЕНЬШЕН ДО 85%) ==========
@app.route('/generate_single_pages_pdf')
def generate_single_pages_pdf():
    """Генерирует PDF, где каждый QR-код на весь лист А4 (увеличенные шрифты)"""
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
        
        # Уменьшаем до 85% от листа
        scale_factor = 0.85
        new_width = width * scale_factor
        new_height = height * scale_factor
        x_offset = (width - new_width) / 2
        y_offset = (height - new_height) / 2
        
        # Увеличенная высота белой полосы для текста (было 80, стало 105 - +31%)
        text_height = 105
        
        c = canvas.Canvas(buffer, pagesize=A4)
        
        for i, carpet in enumerate(carpets):
            if not carpet.qr_code_path or not os.path.exists(carpet.qr_code_path):
                continue
            
            # Загружаем QR-код
            pil_img = Image.open(carpet.qr_code_path)
            img_width, img_height = pil_img.size
            
            # Масштабируем QR внутри уменьшенной области
            scale_x = new_width / img_width
            scale_y = new_height / img_height
            scale = max(scale_x, scale_y)
            
            qr_new_width = img_width * scale
            qr_new_height = img_height * scale
            qr_x_offset = x_offset + (new_width - qr_new_width) / 2
            qr_y_offset = y_offset + (new_height - qr_new_height) / 2
            
            # Увеличиваем разрешение и вставляем QR
            temp_buffer = io.BytesIO()
            pil_img_resized = pil_img.resize((int(qr_new_width), int(qr_new_height)), Image.Resampling.LANCZOS)
            pil_img_resized.save(temp_buffer, format='PNG', dpi=(300, 300))
            temp_buffer.seek(0)
            
            img = ImageReader(temp_buffer)
            c.drawImage(img, qr_x_offset, qr_y_offset, qr_new_width, qr_new_height, preserveAspectRatio=True)
            
            # Белая полоса внизу для текста
            c.setFillColorRGB(1, 1, 1)
            c.rect(0, 0, width, text_height, fill=1, stroke=0)
            
            # Получаем данные о ковре
            carpet_type = db.session.get(CarpetType, carpet.carpet_type_id)
            type_name = carpet_type.name if carpet_type else '-'
            craftsman = db.session.get(Craftsman, carpet.craftsman_id)
            craftsman_name = craftsman.name if craftsman else '-'
            
            c.setFillColorRGB(0, 0, 0)
            
            # ID ковра (было 20, стало 26 - +30%)
            c.setFont("Helvetica-Bold", 26)
            c.drawCentredString(width / 2, text_height - 22, carpet.carpet_id)
            
            # Тип и швея (было 14, стало 18.5 - +32%)
            if FONT_REGISTERED:
                c.setFont("RussianFont", 18.5)
            else:
                c.setFont("Helvetica", 18.5)
            c.drawCentredString(width / 2, text_height - 48, f"{type_name} | {craftsman_name}")
            
            # Цена (было 16, стало 22 - +37%)
            c.setFont("Helvetica-Bold", 22)
            price_str = f"{carpet.price:,} ₽".replace(',', ' ')
            c.drawCentredString(width / 2, text_height - 78, price_str)
            
            # Размер и материал (новая строка)
            size_material = ""
            if carpet.size:
                size_material += f"Размер: {carpet.size}"
            if carpet.material:
                if size_material:
                    size_material += f" | Материал: {carpet.material}"
                else:
                    size_material += f"Материал: {carpet.material}"
            if size_material:
                c.setFont("Helvetica", 13)
                c.drawCentredString(width / 2, text_height - 100, size_material)
            
            # Номер страницы
            c.setFont("Helvetica", 7)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawRightString(width - 20, 8, f"Страница {i+1} из {len(carpets)}")
            
            c.showPage()
        
        c.save()
        buffer.seek(0)
        
        return send_file(
            buffer, 
            mimetype='application/pdf', 
            as_attachment=True, 
            download_name=f'qr_full_page_{len(carpets)}_pages.pdf'
        )
    except Exception as e:
        print(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return f"Ошибка: {str(e)}", 500
# ========== МАРШРУТЫ МАРКЕТПЛЕЙСОВ ==========
@app.route('/marketplace_accounts')
def marketplace_accounts():
    accounts = MarketplaceAccount.query.all()
    for a in accounts:
        a.stats = {
            'new': MarketplaceOrder.query.filter_by(account_id=a.id, status='new').count(),
            'processing': MarketplaceOrder.query.filter_by(account_id=a.id, status='processing').count(),
            'ready': MarketplaceOrder.query.filter_by(account_id=a.id, status='ready').count(),
            'shipped': MarketplaceOrder.query.filter_by(account_id=a.id, status='shipped').count(),
            'total': MarketplaceOrder.query.filter_by(account_id=a.id).count()
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
    mp = request.form['marketplace']
    name = request.form['account_name']
    login = request.form.get('account_login','')
    key = request.form['api_key']
    cid = request.form.get('client_id','')
    active = 'is_active' in request.form
    if MarketplaceAccount.query.filter_by(marketplace=mp, account_name=name).first():
        flash('Аккаунт с таким названием уже существует', 'error')
    else:
        db.session.add(MarketplaceAccount(marketplace=mp, account_name=name, account_login=login, api_key=key, client_id=cid, is_active=active))
        db.session.commit()
        flash(f'Аккаунт "{name}" добавлен', 'success')
    return redirect(url_for('marketplace_accounts'))

@app.route('/edit_marketplace_account/<int:id>', methods=['GET','POST'])
def edit_marketplace_account(id):
    acc = MarketplaceAccount.query.get_or_404(id)
    if request.method == 'POST':
        acc.account_name = request.form['account_name']
        acc.account_login = request.form.get('account_login','')
        acc.api_key = request.form['api_key']
        acc.client_id = request.form.get('client_id','')
        acc.is_active = 'is_active' in request.form
        db.session.commit()
        flash(f'Аккаунт "{acc.account_name}" обновлён', 'success')
        return redirect(url_for('marketplace_accounts'))
    return render_template('edit_marketplace_account.html', account=acc)

@app.route('/delete_marketplace_account/<int:id>')
def delete_marketplace_account(id):
    acc = MarketplaceAccount.query.get_or_404(id)
    cnt = MarketplaceOrder.query.filter_by(account_id=id).count()
    if cnt > 0:
        flash(f'Нельзя удалить аккаунт с {cnt} заказами', 'error')
    else:
        db.session.delete(acc)
        db.session.commit()
        flash(f'Аккаунт "{acc.account_name}" удалён', 'info')
    return redirect(url_for('marketplace_accounts'))

@app.route('/sync_account/<int:account_id>')
def sync_account(account_id):
    new = sync_account_orders(account_id)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'new_orders': new})
    
    return redirect(url_for('marketplace_accounts'))

@app.route('/sync_all_orders')
def sync_all_orders():
    accounts = MarketplaceAccount.query.filter_by(is_active=True).all()
    total = 0
    logs = []
    for a in accounts:
        n = sync_account_orders(a.id)
        total += n
        logs.append({'account_name': a.account_name, 'marketplace': a.marketplace, 'new_orders': n})
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'new_orders': total, 'logs': logs})
    
    # flash-сообщения уже установлены в sync_account_orders
    return redirect(url_for('marketplace_accounts'))

@app.route('/marketplace_orders')
def marketplace_orders():
    acc = request.args.get('account_id','')
    st = request.args.get('status','')
    mp = request.args.get('marketplace','')
    q = MarketplaceOrder.query
    if acc:
        q = q.filter(MarketplaceOrder.account_id == acc)
    if st:
        q = q.filter(MarketplaceOrder.status == st)
    if mp:
        q = q.filter(MarketplaceOrder.marketplace == mp)
    orders = q.order_by(MarketplaceOrder.ordered_at.desc()).all()
    accounts = MarketplaceAccount.query.all()
    carpets = Carpet.query.filter_by(status='created').all()
    if acc:
        stats = {
            'new': MarketplaceOrder.query.filter_by(account_id=acc, status='new').count(),
            'processing': MarketplaceOrder.query.filter_by(account_id=acc, status='processing').count(),
            'ready': MarketplaceOrder.query.filter_by(account_id=acc, status='ready').count(),
            'shipped': MarketplaceOrder.query.filter_by(account_id=acc, status='shipped').count()
        }
    else:
        stats = {
            'new': MarketplaceOrder.query.filter_by(status='new').count(),
            'processing': MarketplaceOrder.query.filter_by(status='processing').count(),
            'ready': MarketplaceOrder.query.filter_by(status='ready').count(),
            'shipped': MarketplaceOrder.query.filter_by(status='shipped').count()
        }
    return render_template('marketplace_orders.html', orders=orders, accounts=accounts, carpets=carpets,
                          stats=stats, selected_account=acc, selected_status=st, selected_marketplace=mp)

@app.route('/link_order_to_carpet', methods=['POST'])
def link_order_to_carpet():
    oid = request.form['order_id']
    cid = request.form['carpet_id']
    order = MarketplaceOrder.query.get(oid)
    carpet = Carpet.query.filter_by(carpet_id=cid).first()
    if order and carpet:
        order.carpet_id = carpet.carpet_id
        order.status = 'processing'
        db.session.commit()
        flash(f'Ковёр {cid} привязан к заказу {order.order_id}', 'success')
    return redirect(url_for('marketplace_orders'))

@app.route('/update_order_status', methods=['POST'])
def update_order_status():
    oid = request.form['order_id']
    status = request.form['status']
    order = MarketplaceOrder.query.get(oid)
    if order:
        order.status = status
        if status == 'shipped':
            order.shipped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if order.carpet_id:
                carp = Carpet.query.filter_by(carpet_id=order.carpet_id).first()
                if carp and carp.status == 'scanned':
                    carp.status = 'sold'
                    db.session.commit()
        db.session.commit()
        flash(f'Статус заказа {order.order_id} обновлён на "{status}"', 'success')
    return redirect(url_for('marketplace_orders'))

@app.route('/marketplace_stats_api')
def marketplace_stats_api():
    accounts = MarketplaceAccount.query.filter_by(is_active=True).all()
    total = {'new':0,'processing':0,'ready':0,'shipped':0,'total_orders':0,'total_revenue':0}
    result = {'total': total, 'accounts': []}
    for a in accounts:
        stats = {
            'id': a.id, 'name': a.account_name, 'marketplace': a.marketplace, 'login': a.account_login,
            'new': MarketplaceOrder.query.filter_by(account_id=a.id, status='new').count(),
            'processing': MarketplaceOrder.query.filter_by(account_id=a.id, status='processing').count(),
            'ready': MarketplaceOrder.query.filter_by(account_id=a.id, status='ready').count(),
            'shipped': MarketplaceOrder.query.filter_by(account_id=a.id, status='shipped').count(),
            'total': MarketplaceOrder.query.filter_by(account_id=a.id).count(),
            'revenue': db.session.query(db.func.sum(MarketplaceOrder.price)).filter(MarketplaceOrder.account_id == a.id).scalar() or 0,
            'last_sync': a.last_sync
        }
        result['accounts'].append(stats)
        for k in ['new','processing','ready','shipped','total_orders','total_revenue']:
            if k == 'total_orders':
                total[k] += stats['total']
            elif k == 'total_revenue':
                total[k] += stats['revenue']
            else:
                total[k] += stats[k]
    return jsonify(result)

@app.route('/search')
def search():
    q = request.args.get('q','')
    status = request.args.get('status','')
    cid = request.args.get('craftsman_id','')
    tid = request.args.get('carpet_type_id','')
    date_from = request.args.get('scan_date_from','')
    date_to = request.args.get('scan_date_to','')
    query = Carpet.query
    if q:
        query = query.filter(Carpet.carpet_id.contains(q) | Carpet.craftsman_ref.has(name=q))
    if status:
        query = query.filter(Carpet.status == status)
    if cid:
        query = query.filter(Carpet.craftsman_id == cid)
    if tid:
        query = query.filter(Carpet.carpet_type_id == tid)
    if date_from:
        query = query.filter(Carpet.scanned_at >= date_from)
    if date_to:
        query = query.filter(Carpet.scanned_at <= date_to)
    carpets = query.all()
    craftsmen_stats = []
    for c in Craftsman.query.all():
        cnt = Carpet.query.filter_by(craftsman_id=c.id).count()
        scn = Carpet.query.filter_by(craftsman_id=c.id, status='scanned').count()
        craftsmen_stats.append({'id': c.id, 'name': c.name, 'count': cnt, 'scanned': scn})
    return render_template('search.html', carpets=carpets, query=q, status=status,
                          craftsmen_stats=craftsmen_stats, craftsmen=Craftsman.query.all(),
                          carpet_types=CarpetType.query.all(), selected_craftsman=cid,
                          selected_type=tid, scan_date_from=date_from, scan_date_to=date_to)

@app.route('/stats')
def stats():
    date_from = request.args.get('scan_date_from','')
    date_to = request.args.get('scan_date_to','')
    status = request.args.get('status','')
    cid = request.args.get('craftsman_id','')
    tid = request.args.get('carpet_type_id','')
    query = Carpet.query
    if date_from: query = query.filter(Carpet.scanned_at >= date_from)
    if date_to: query = query.filter(Carpet.scanned_at <= date_to)
    if status: query = query.filter(Carpet.status == status)
    if cid: query = query.filter(Carpet.craftsman_id == cid)
    if tid: query = query.filter(Carpet.carpet_type_id == tid)
    carpets = query.all()
    total = len(carpets)
    scanned = len([c for c in carpets if c.status == 'scanned'])
    sold = len([c for c in carpets if c.status == 'sold'])
    created = len([c for c in carpets if c.status == 'created'])
    scans_stats = []
    for i in range(7):
        d = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        cnt = ScanLog.query.filter(ScanLog.scanned_at.like(f'{d}%'), ScanLog.result == 'success').count()
        scans_stats.append({'date': d, 'count': cnt})
    craftsmen_stats = []
    for c in Craftsman.query.all():
        cc = [x for x in carpets if x.craftsman_id == c.id]
        if cc:
            craftsmen_stats.append({'name': c.name, 'count': len(cc), 'scanned': len([x for x in cc if x.status=='scanned'])})
    return render_template('stats.html', carpets=carpets, total_carpets=total,
                          scanned_count=scanned, sold_count=sold, created_count=created,
                          scans_stats=scans_stats, craftsmen_stats=craftsmen_stats,
                          craftsmen=Craftsman.query.all(), carpet_types=CarpetType.query.all(),
                          selected_craftsman=cid, selected_type=tid, selected_status=status,
                          scan_date_from=date_from, scan_date_to=date_to)

@app.route('/check_db')
def check_db():
    try:
        db.session.execute('SELECT 1')
        return jsonify({
            'status': 'ok',
            'database_path': DB_PATH,
            'data_folder': DATA_FOLDER,
            'carpets_count': Carpet.query.count(),
            'scans_count': ScanLog.query.count(),
            'orders_count': MarketplaceOrder.query.count(),
            'accounts_count': MarketplaceAccount.query.count(),
            'file_exists': os.path.exists(DB_PATH),
            'file_size': os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e), 'database_path': DB_PATH}), 500

def open_browser(port):
    time.sleep(2)
    webbrowser.open(f'http://127.0.0.1:{port}')

if __name__ == '__main__':
    port = find_free_port()
    print("="*60)
    print("КОВРОВЫЙ УЧЁТ - Система управления")
    print("="*60)
    print(f"Папка с данными: {DATA_FOLDER}")
    print(f"База данных: {DB_PATH}")
    print(f"QR-коды: {QR_FOLDER}")
    print("="*60)
    print(f"Сервер запущен на порту: {port}")
    print(f"Открой в браузере: http://localhost:{port}")
    print("="*60)
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    app.run(host='0.0.0.0', port=port, debug=False)