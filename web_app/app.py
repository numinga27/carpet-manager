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
import logging
from functools import lru_cache
from sqlalchemy import text

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
if getattr(sys, 'frozen', False):
    log_dir = os.path.dirname(sys.executable)
else:
    log_dir = os.path.dirname(__file__)
log_file = os.path.join(log_dir, 'carpet_manager.log')

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info("="*60)
logger.info("Программа Ковровый учёт запущена")
logger.info(f"Режим: {'EXE' if getattr(sys, 'frozen', False) else 'скрипт'}")
logger.info(f"Путь к исполняемому файлу: {sys.executable}")
logger.info(f"Лог-файл: {log_file}")

# ========== ОПРЕДЕЛЕНИЕ ПУТЕЙ ДЛЯ ШАБЛОНОВ ==========
def find_template_folder():
    possible_paths = []
    
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        possible_paths.append(os.path.join(exe_dir, 'templates'))
        
        if hasattr(sys, '_MEIPASS'):
            possible_paths.append(os.path.join(sys._MEIPASS, 'templates'))
    else:
        possible_paths.append(os.path.join(os.path.dirname(__file__), 'templates'))
        possible_paths.append(os.path.join(os.getcwd(), 'templates'))
    
    for path in possible_paths:
        logger.info(f"Проверяем путь: {path} - существует: {os.path.exists(path)}")
        if os.path.exists(path) and os.path.isdir(path):
            logger.info(f"✅ Папка шаблонов найдена: {path}")
            return path
    
    fallback = os.path.join(os.path.dirname(sys.executable), 'templates')
    logger.warning(f"⚠️ Папка шаблонов не найдена! Используем fallback: {fallback}")
    os.makedirs(fallback, exist_ok=True)
    return fallback

template_folder = find_template_folder()
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

# ========== ОПРЕДЕЛЕНИЕ ПАПОК ДЛЯ ДАННЫХ ==========
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
    local_folder = os.path.join(os.path.dirname(sys.executable), 'Data')
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
DB_PATH = os.path.join(DATA_FOLDER, 'carpets.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {'check_same_thread': False}
}
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 86400

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
    qr_thumb_path = db.Column(db.String(200), nullable=True)
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
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('marketplace_account.id'))
    nm_id = db.Column(db.Integer)
    data = db.Column(db.Text)
    period_start = db.Column(db.String(20))
    period_end = db.Column(db.String(20))
    cached_at = db.Column(db.String(20))
    
class WBProductAnalytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('marketplace_account.id'))
    nm_id = db.Column(db.Integer)
    product_name = db.Column(db.String(200))
    brand_name = db.Column(db.String(100))
    views = db.Column(db.Integer, default=0)
    cart_adds = db.Column(db.Integer, default=0)
    orders = db.Column(db.Integer, default=0)
    sales = db.Column(db.Integer, default=0)
    cancellations = db.Column(db.Integer, default=0)
    returns = db.Column(db.Integer, default=0)
    past_views = db.Column(db.Integer, default=0)
    past_cart_adds = db.Column(db.Integer, default=0)
    past_orders = db.Column(db.Integer, default=0)
    past_sales = db.Column(db.Integer, default=0)
    conversion_to_cart = db.Column(db.Float, default=0)
    conversion_to_order = db.Column(db.Float, default=0)
    conversion_to_sale = db.Column(db.Float, default=0)
    period_start = db.Column(db.String(20))
    period_end = db.Column(db.String(20))
    updated_at = db.Column(db.String(20))
    carpet_id = db.Column(db.String(50), db.ForeignKey('carpet.carpet_id'), nullable=True)

class CleanupSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    auto_cleanup = db.Column(db.Boolean, default=True)
    cleanup_days = db.Column(db.Integer, default=60)
    last_cleanup = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ========== КЕШИРОВАНИЕ ==========
@lru_cache(maxsize=2)
def get_cached_craftsmen():
    return Craftsman.query.all()

@lru_cache(maxsize=2)
def get_cached_carpet_types():
    return CarpetType.query.all()

def invalidate_cache():
    get_cached_craftsmen.cache_clear()
    get_cached_carpet_types.cache_clear()
    logger.info("[CACHE] Кеш очищен")

# ========== МИГРАЦИЯ БД ==========
DB_VERSION = 4

def get_db_version():
    try:
        result = db.session.execute(text("SELECT version FROM db_version LIMIT 1")).fetchone()
        return result[0] if result else 0
    except:
        return 0

def set_db_version(version):
    try:
        db.session.execute(text("CREATE TABLE IF NOT EXISTS db_version (version INTEGER)"))
        db.session.execute(text("DELETE FROM db_version"))
        db.session.execute(text("INSERT INTO db_version (version) VALUES (:version)"), {'version': version})
        db.session.commit()
    except:
        pass

def ensure_column_exists(table, column, column_type):
    """Проверяет существование колонки и добавляет если её нет"""
    try:
        cursor = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
        columns = [row[1] for row in cursor]
        
        if column not in columns:
            logger.info(f"[MIGRATION] Добавляем колонку {column} в таблицу {table}")
            db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"))
            db.session.commit()
            logger.info(f"[MIGRATION] Колонка {column} успешно добавлена")
            return True
        else:
            logger.info(f"[MIGRATION] Колонка {column} уже существует")
            return True
    except Exception as e:
        logger.error(f"[MIGRATION] Ошибка при проверке/добавлении колонки {column}: {e}")
        return False

def add_indexes():
    try:
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_carpet_status ON carpet(status)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_carpet_scanned_at ON carpet(scanned_at)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_carpet_carpet_id ON carpet(carpet_id)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_carpet_craftsman_id ON carpet(craftsman_id)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_carpet_carpet_type_id ON carpet(carpet_type_id)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_order_status ON marketplace_order(status)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_order_account_id ON marketplace_order(account_id)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_order_marketplace ON marketplace_order(marketplace)'))
        db.session.commit()
        print("[DB] Индексы созданы")
    except Exception as e:
        print(f"[DB] Ошибка создания индексов: {e}")

def init_database():
    os.makedirs(DATA_FOLDER, exist_ok=True)
    db.create_all()
    add_indexes()
    
    # Проверяем и добавляем колонку qr_thumb_path если её нет
    ensure_column_exists('carpet', 'qr_thumb_path', 'VARCHAR(200)')
    
    current = get_db_version()
    print(f"[DB] Текущая версия БД: {current}")
    
    if current == 0:
        set_db_version(DB_VERSION)
    elif current < DB_VERSION:
        set_db_version(DB_VERSION)

# ========== ФУНКЦИИ ==========
def generate_qr_code(carpet_id, _):
    try:
        qr = qrcode.QRCode(
            version=1, 
            box_size=6,
            border=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M
        )
        qr.add_data(carpet_id)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        os.makedirs(QR_FOLDER, exist_ok=True)
        
        img = img.resize((120, 120))
        path = os.path.join(QR_FOLDER, f"carpet_{carpet_id}.png")
        img.save(path, optimize=True, quality=75)
        
        thumb = img.resize((45, 45))
        thumb_path = os.path.join(QR_FOLDER, f"thumb_{carpet_id}.png")
        thumb.save(thumb_path, optimize=True, quality=70)
        
        logger.info(f"[QR] Сгенерирован QR для {carpet_id}")
        return path, thumb_path
    except Exception as e:
        logger.error(f"[QR] Ошибка генерации QR для {carpet_id}: {e}")
        return None, None

def generate_next_id():
    try:
        from sqlalchemy import func
        max_result = db.session.query(func.max(Carpet.id)).scalar()
        
        if max_result:
            last_carpet = Carpet.query.filter_by(id=max_result).first()
            if last_carpet and last_carpet.carpet_id and '-' in last_carpet.carpet_id:
                try:
                    max_num = int(last_carpet.carpet_id.split('-')[1])
                except:
                    max_num = Carpet.query.count()
            else:
                max_num = Carpet.query.count()
        else:
            max_num = 0
        
        new_num = max_num + 1
        new_id = f"CARPET-{new_num:04d}"
        
        existing = Carpet.query.filter_by(carpet_id=new_id).first()
        if existing:
            while True:
                new_num += 1
                new_id = f"CARPET-{new_num:04d}"
                if not Carpet.query.filter_by(carpet_id=new_id).first():
                    break
        
        logger.info(f"[ID] Сгенерирован новый ID: {new_id}")
        return new_id
        
    except Exception as e:
        logger.error(f"[ID] Ошибка генерации ID: {e}")
        count = Carpet.query.count()
        new_id = f"CARPET-{count + 1:04d}"
        return new_id

def cleanup_old_carpets(days=60):
    try:
        cutoff_date = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d %H:%M:%S")
        
        old_carpets = Carpet.query.filter(
            Carpet.status == 'scanned',
            Carpet.scanned_at.isnot(None),
            Carpet.scanned_at < cutoff_str
        ).all()
        
        count = len(old_carpets)
        
        if count > 0:
            logger.info(f"[CLEANUP] Найдено {count} старых отсканированных ковров для удаления")
            
            for carpet in old_carpets:
                for path in [carpet.qr_code_path, carpet.qr_thumb_path]:
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception as e:
                            logger.error(f"[CLEANUP] Ошибка удаления файла: {e}")
                db.session.delete(carpet)
            
            db.session.commit()
            logger.info(f"[CLEANUP] Удалено {count} старых ковров")
            return count
        else:
            logger.info("[CLEANUP] Старых ковров для удаления не найдено")
            return 0
            
    except Exception as e:
        logger.exception(f"[CLEANUP] Ошибка при очистке: {e}")
        db.session.rollback()
        return 0

def auto_cleanup():
    try:
        settings = CleanupSettings.query.first()
        if not settings:
            settings = CleanupSettings(auto_cleanup=True, cleanup_days=60)
            db.session.add(settings)
            db.session.commit()
        
        if settings.auto_cleanup:
            deleted = cleanup_old_carpets(settings.cleanup_days)
            settings.last_cleanup = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.session.commit()
            return deleted
        return 0
    except Exception as e:
        logger.error(f"[AUTO_CLEANUP] Ошибка: {e}")
        return 0

def forecast_sales(days=30):
    try:
        orders = MarketplaceOrder.query.filter_by(status='shipped').all()
        if len(orders) < 7:
            return {
                "error": None, "no_data": True,
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
                "error": None, "no_data": True,
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
            "error": None, "no_data": False,
            "method": "Скользящее среднее (7 дней) на основе заказов маркетплейсов",
            "data": forecast_with_season, "dates": forecast_dates,
            "total": sum(forecast_with_season),
            "daily_avg": round(sum(forecast_with_season) / days, 1),
            "historical_data": counts[-30:], "historical_dates": dates[-30:]
        }
    except Exception as e:
        print(f"[FORECAST] Ошибка: {e}")
        traceback.print_exc()
        return {"error": str(e), "no_data": True, "data": [], "total": 0, "daily_avg": 0}

def calculate_trend():
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

# ========== ФУНКЦИИ ДЛЯ WB АНАЛИТИКИ ==========

def get_wb_analytics(api_key, account_id, period_days=30):
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)
        
        date_from = start_date.strftime("%Y-%m-%d")
        date_to = end_date.strftime("%Y-%m-%d")
        
        url = "https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products"
        
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json"
        }
        
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
            if 'data' in data and 'products' in data['data']:
                products = data['data']['products']
            else:
                products = data.get('data', {}).get('products', [])
            
            logger.info(f"Получено {len(products)} товаров")
            return products if products else []
        else:
            logger.error(f"Ошибка API: {response.status_code}")
            if response.status_code == 401:
                flash('⚠️ Токен Wildberries не имеет прав на аналитику. Нужен токен с доступом к Статистике.', 'warning')
            elif response.status_code == 403:
                flash('⚠️ Доступ запрещен. Проверьте права токена.', 'warning')
            elif response.status_code == 429:
                flash('⚠️ Слишком много запросов. Подождите немного.', 'warning')
            return []
            
    except requests.exceptions.Timeout:
        logger.error("Таймаут при запросе к WB Analytics API")
        flash('⏰ Таймаут соединения с Wildberries API. Проверьте интернет.', 'warning')
        return []
    except requests.exceptions.ConnectionError:
        logger.error("Ошибка соединения с WB Analytics API")
        flash('❌ Ошибка соединения с Wildberries API. Проверьте интернет.', 'warning')
        return []
    except Exception as e:
        logger.exception(f"Ошибка получения аналитики: {e}")
        flash(f'❌ Ошибка получения аналитики: {str(e)[:100]}', 'error')
        return []

def sync_wb_analytics(account_id):
    acc = db.session.get(MarketplaceAccount, account_id)
    if not acc or not acc.is_active or acc.marketplace != 'wb':
        return 0
    
    try:
        products = get_wb_analytics(acc.api_key, account_id, 30)
        
        if not products:
            flash(f'📊 WB Аналитика: нет данных за последние 30 дней', 'info')
            return 0
        
        updated = 0
        new = 0
        
        for prod in products:
            nm_id = prod.get('nmId')
            if not nm_id:
                continue
            
            analytic = WBProductAnalytics.query.filter_by(
                account_id=account_id, 
                nm_id=nm_id
            ).first()
            
            if not analytic:
                analytic = WBProductAnalytics(
                    account_id=account_id,
                    nm_id=nm_id,
                    product_name=prod.get('productName', f'Товар {nm_id}')[:200],
                    brand_name=prod.get('brandName', '')[:100]
                )
                new += 1
            
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
            
            if analytic.views > 0:
                analytic.conversion_to_cart = round((analytic.cart_adds / analytic.views) * 100, 2)
                analytic.conversion_to_order = round((analytic.orders / analytic.views) * 100, 2)
                analytic.conversion_to_sale = round((analytic.sales / analytic.views) * 100, 2)
            else:
                analytic.conversion_to_cart = 0
                analytic.conversion_to_order = 0
                analytic.conversion_to_sale = 0
            
            analytic.period_start = selected.get('dateFrom', (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
            analytic.period_end = selected.get('dateTo', datetime.now().strftime("%Y-%m-%d"))
            analytic.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            carpet = Carpet.query.filter_by(carpet_id=f"CARPET-{nm_id:04d}").first()
            if carpet:
                analytic.carpet_id = carpet.carpet_id
            
            db.session.add(analytic)
            updated += 1
        
        db.session.commit()
        
        cache = WBAnalyticsCache.query.filter_by(account_id=account_id).first()
        if not cache:
            cache = WBAnalyticsCache(account_id=account_id)
        
        cache.cached_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cache.period_start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        cache.period_end = datetime.now().strftime("%Y-%m-%d")
        db.session.add(cache)
        db.session.commit()
        
        if new > 0 or updated > 0:
            flash(f'📊 WB Аналитика: {new} новых, {updated} обновлено', 'success')
        else:
            flash(f'📊 WB Аналитика: данных нет', 'info')
        
        return updated
        
    except Exception as e:
        logger.exception(f"Ошибка синхронизации аналитики: {e}")
        flash(f'❌ Ошибка синхронизации аналитики WB: {str(e)[:200]}', 'error')
        return 0

def sync_account_orders(account_id):
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
            
            url_completed = "https://marketplace-api.wildberries.ru/api/v3/dbs/orders"
            params = {
                "limit": 100, "next": 0,
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
            
            if not request_success:
                flash(f'❌ {acc.account_name}: не удалось подключиться к Wildberries API. Проверьте API-ключ и интернет.', 'error')
                return 0
            
            logger.info(f"Всего заказов для обработки: {len(all_orders)}")
            
            for o in all_orders:
                existing = MarketplaceOrder.query.filter_by(marketplace='wb', order_id=str(o.get('id'))).first()
                
                if not existing:
                    address = o.get('address', {})
                    mo = MarketplaceOrder(
                        account_id=acc.id, marketplace='wb', order_id=str(o.get('id')),
                        customer_name='', customer_phone='',
                        delivery_address=address.get('fullAddress', ''), status='new',
                        ordered_at=o.get('createdAt', ''), price=o.get('price', 0),
                        products_info=json.dumps(o.get('skus', [])), wb_supply_id=str(o.get('warehouseId', ''))
                    )
                    db.session.add(mo)
                    new += 1
            
            db.session.commit()
            
            if new > 0:
                flash(f'✅ {acc.account_name}: получено {new} новых заказов', 'success')
                    
        elif acc.marketplace == 'ozon':
            url = "https://api-seller.ozon.ru/v3/posting/fbs/list"
            headers = {"Api-Key": acc.api_key, "Client-Id": acc.client_id, "Content-Type": "application/json"}
            payload = {"dir": "desc", "filter": {"since": (datetime.now() - timedelta(days=30)).isoformat(), "status": "awaiting_packaging"}, "limit": 100}
            
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
                                account_id=acc.id, marketplace='ozon', order_id=o.get('posting_number'),
                                customer_name=cust.get('name', ''), customer_phone=cust.get('phone', ''),
                                delivery_address=deliv.get('address', {}).get('address_txt', ''), status='new',
                                ordered_at=o.get('created_at', ''),
                                price=sum(p.get('price', 0) * p.get('quantity', 1) for p in prods),
                                products_info=json.dumps(prods), ozon_posting_number=o.get('posting_number')
                            )
                            db.session.add(mo)
                            new += 1
                    
                    db.session.commit()
                    
                    if new > 0:
                        flash(f'✅ {acc.account_name}: получено {new} новых заказов', 'success')
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
        
        acc.last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.session.commit()
        
        sync_log = MarketplaceSyncLog(
            account_id=acc.id, sync_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            orders_found=len(all_orders) if acc.marketplace == 'wb' else len(orders) if 'orders' in locals() else 0,
            orders_new=new, status='success'
        )
        db.session.add(sync_log)
        db.session.commit()
        
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Ошибка синхронизации аккаунта {acc.account_name}: {error_msg}")
        
        sync_log = MarketplaceSyncLog(
            account_id=acc.id, sync_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error_message=error_msg, status='error'
        )
        db.session.add(sync_log)
        db.session.commit()
        
        flash(f'❌ Ошибка синхронизации {acc.account_name}: {error_msg[:200]}', 'error')
    
    return new

# ========== МАРШРУТЫ ДЛЯ ТОКЕНА ==========
@app.route('/wb_token_input')
def wb_token_input():
    return render_template('wb_token_input.html')

@app.route('/test_token_api', methods=['POST'])
def test_token_api():
    data = request.get_json()
    api_key = data.get('api_key', '').strip()
    
    if not api_key:
        return jsonify({'success': False, 'error': 'Токен не может быть пустым'})
    
    try:
        headers = {"Authorization": api_key}
        url = "https://marketplace-api.wildberries.ru/api/v3/dbs/orders/new"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return jsonify({'success': True, 'message': '✅ Токен работает! API отвечает корректно.'})
        elif response.status_code == 401:
            return jsonify({
                'success': False, 
                'error': '❌ Токен недействителен или не имеет прав на заказы!\n\nПолучите новый токен в настройках WB: Настройки → Доступ к API'
            })
        else:
            return jsonify({
                'success': False, 
                'error': f'⚠️ API вернул код {response.status_code}'
            })
    except Exception as e:
        return jsonify({'success': False, 'error': f'❌ Ошибка: {str(e)}'})

@app.route('/save_wb_token', methods=['POST'])
def save_wb_token():
    data = request.get_json()
    api_key = data.get('api_key', '').strip()
    account_name = data.get('account_name', 'Wildberries Аккаунт').strip()
    
    if not api_key:
        return jsonify({'success': False, 'error': 'Токен не может быть пустым'})
    
    existing = MarketplaceAccount.query.filter_by(api_key=api_key).first()
    if existing:
        return jsonify({'success': True, 'message': 'Токен уже существует в системе'})
    
    account = MarketplaceAccount(
        marketplace='wb',
        account_name=account_name,
        api_key=api_key,
        is_active=True
    )
    db.session.add(account)
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'✅ Токен для "{account_name}" успешно сохранен!'})

# ========== ИНИЦИАЛИЗАЦИЯ ==========
with app.app_context():
    # Сначала инициализируем БД (создаем таблицы и добавляем недостающие колонки)
    init_database()
    
    # Затем создаем начальные данные (если их нет)
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
            qr_path, thumb_path = generate_qr_code(c.carpet_id, {})
            c.qr_code_path = qr_path
            c.qr_thumb_path = thumb_path
        db.session.commit()
    
    # Только после создания всех данных - запускаем очистку
    try:
        deleted = auto_cleanup()
        if deleted > 0:
            print(f"[CLEANUP] Автоматически удалено {deleted} старых отсканированных ковров")
    except Exception as e:
        print(f"[CLEANUP] Ошибка при очистке (игнорируем): {e}")

# ========== ОСНОВНЫЕ МАРШРУТЫ ==========
@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 30
    
    pagination = Carpet.query.order_by(Carpet.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    total_carpets = Carpet.query.count()
    
    return render_template('index.html',
        carpets=pagination.items,
        pagination=pagination,
        total_carpets=total_carpets,
        craftsmen=get_cached_craftsmen(),
        carpet_types=get_cached_carpet_types(),
        new_orders_count=MarketplaceOrder.query.filter_by(status='new').count(),
        processing_orders_count=MarketplaceOrder.query.filter_by(status='processing').count(),
        ready_orders_count=MarketplaceOrder.query.filter_by(status='ready').count(),
        accounts_count=MarketplaceAccount.query.filter_by(is_active=True).count()
    )

@app.route('/get_qr/<carpet_id>')
def get_qr(carpet_id):
    carpet = Carpet.query.filter_by(carpet_id=carpet_id).first()
    if carpet and carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
        response = send_file(carpet.qr_code_path, mimetype='image/png')
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
    return "QR не найден", 404

@app.route('/get_qr_thumb/<carpet_id>')
def get_qr_thumb(carpet_id):
    carpet = Carpet.query.filter_by(carpet_id=carpet_id).first()
    if carpet and carpet.qr_thumb_path and os.path.exists(carpet.qr_thumb_path):
        response = send_file(carpet.qr_thumb_path, mimetype='image/png')
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
    return "", 204

@app.route('/wb_analytics')
def wb_analytics():
    accounts = MarketplaceAccount.query.filter_by(marketplace='wb', is_active=True).all()
    analytics = WBProductAnalytics.query.all()
    
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
    
    top_by_views = sorted(analytics, key=lambda x: x.views, reverse=True)[:10]
    top_by_sales = sorted(analytics, key=lambda x: x.sales, reverse=True)[:10]
    top_by_conversion = sorted([a for a in analytics if a.views > 50], key=lambda x: x.conversion_to_sale, reverse=True)[:10]
    
    return render_template('wb_analytics.html',
                          accounts=accounts, analytics=analytics,
                          total_stats=total_stats, top_by_views=top_by_views,
                          top_by_sales=top_by_sales, top_by_conversion=top_by_conversion)

@app.route('/sync_wb_analytics/<int:account_id>')
def sync_wb_analytics_route(account_id):
    sync_wb_analytics(account_id)
    return redirect(url_for('wb_analytics'))

@app.route('/sync_all_wb_analytics')
def sync_all_wb_analytics():
    for acc in MarketplaceAccount.query.filter_by(marketplace='wb', is_active=True).all():
        sync_wb_analytics(acc.id)
    return redirect(url_for('wb_analytics'))

@app.route('/wb_product_detail/<int:nm_id>')
def wb_product_detail(nm_id):
    analytic = WBProductAnalytics.query.filter_by(nm_id=nm_id).first_or_404()
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
    try:
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
        qr_path, thumb_path = generate_qr_code(cid, {})
        carpet.qr_code_path = qr_path
        carpet.qr_thumb_path = thumb_path
        db.session.commit()
        invalidate_cache()
        flash(f'✅ Ковёр {cid} добавлен', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка добавления ковра: {e}")
        flash(f'❌ Ошибка добавления ковра: {str(e)[:100]}', 'error')
    
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
    errors = []
    
    for i in range(count):
        try:
            cid = generate_next_id()
            
            carpet = Carpet(
                carpet_id=cid, 
                carpet_type_id=type_id, 
                craftsman_id=craftsman_id,
                price=ct.base_price, 
                size=size, 
                material=material, 
                color=color,
                status='created', 
                notes=f'Групповое {i+1}/{count}'
            )
            db.session.add(carpet)
            db.session.flush()
            
            qr_path, thumb_path = generate_qr_code(cid, {})
            carpet.qr_code_path = qr_path
            carpet.qr_thumb_path = thumb_path
            
            created.append(cid)
            
            if (i+1) % 50 == 0:
                db.session.commit()
                logger.info(f"[GROUP] Создано {i+1} ковров из {count}")
                
        except Exception as e:
            db.session.rollback()
            errors.append(f"Ковер {i+1}: {str(e)[:50]}")
            logger.error(f"[GROUP] Ошибка при создании ковра {i+1}: {e}")
            continue
    
    try:
        db.session.commit()
        invalidate_cache()
        
        if created:
            flash(f'✅ Создано {len(created)} ковров типа "{ct.name}"', 'success')
        if errors:
            flash(f'⚠️ Ошибки при создании {len(errors)} ковров: {"; ".join(errors[:3])}', 'warning')
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"[GROUP] Ошибка сохранения: {e}")
        flash(f'❌ Ошибка сохранения: {str(e)[:200]}', 'error')
    
    return redirect(url_for('index'))

@app.route('/edit_carpet/<int:id>', methods=['GET','POST'])
def edit_carpet(id):
    carpet = Carpet.query.get_or_404(id)
    if request.method == 'POST':
        try:
            carpet.carpet_type_id = request.form['carpet_type_id']
            carpet.craftsman_id = request.form['craftsman_id']
            carpet.price = float(request.form['price'])
            carpet.size = request.form.get('size','')
            carpet.material = request.form.get('material','')
            carpet.color = request.form.get('color','')
            carpet.notes = request.form.get('notes','')
            db.session.commit()
            qr_path, thumb_path = generate_qr_code(carpet.carpet_id, {})
            carpet.qr_code_path = qr_path
            carpet.qr_thumb_path = thumb_path
            db.session.commit()
            invalidate_cache()
            flash(f'✅ Ковёр {carpet.carpet_id} обновлён', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Ошибка: {str(e)[:100]}', 'error')
        return redirect(url_for('index'))
    return render_template('edit_carpet.html', carpet=carpet,
                          craftsmen=Craftsman.query.all(),
                          carpet_types=CarpetType.query.all())

@app.route('/delete_carpet/<int:id>')
def delete_carpet(id):
    carpet = Carpet.query.get_or_404(id)
    for path in [carpet.qr_code_path, carpet.qr_thumb_path]:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except:
                pass
    db.session.delete(carpet)
    db.session.commit()
    invalidate_cache()
    flash(f'Ковёр {carpet.carpet_id} удалён', 'info')
    return redirect(url_for('index'))

@app.route('/add_craftsman', methods=['POST'])
def add_craftsman():
    try:
        db.session.add(Craftsman(name=request.form['name'], phone=request.form.get('phone','')))
        db.session.commit()
        invalidate_cache()
        flash('✅ Швея добавлена', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Ошибка: {str(e)[:100]}', 'error')
    return redirect(url_for('index'))

@app.route('/edit_craftsman/<int:id>', methods=['GET','POST'])
def edit_craftsman(id):
    c = Craftsman.query.get_or_404(id)
    if request.method == 'POST':
        try:
            c.name = request.form['name']
            c.phone = request.form['phone']
            db.session.commit()
            invalidate_cache()
            flash('✅ Данные швеи обновлены', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Ошибка: {str(e)[:100]}', 'error')
        return redirect(url_for('index'))
    return render_template('edit_craftsman.html', craftsman=c)

@app.route('/delete_craftsman/<int:id>')
def delete_craftsman(id):
    c = Craftsman.query.get_or_404(id)
    cnt = len(c.carpets)
    for carpet in c.carpets:
        for path in [carpet.qr_code_path, carpet.qr_thumb_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
    db.session.delete(c)
    db.session.commit()
    invalidate_cache()
    flash(f'Швея "{c.name}" удалена с {cnt} коврами', 'success')
    return redirect(url_for('index'))

@app.route('/craftsman/<int:id>')
def craftsman_detail(id):
    c = Craftsman.query.get_or_404(id)
    carpets = Carpet.query.filter_by(craftsman_id=id).all()
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
                          type_stats=type_stats, month_stats=month_stats)

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
        invalidate_cache()
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
        invalidate_cache()
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
        invalidate_cache()
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
    
    MAX_PRINT = 200
    
    query = Carpet.query
    if t:
        query = query.filter(Carpet.carpet_type_id == t)
    if c:
        query = query.filter(Carpet.craftsman_id == c)
    if s:
        query = query.filter(Carpet.status == s)
    
    total_count = query.count()
    
    if total_count == 0:
        flash('❌ Нет ковров для печати по выбранным фильтрам', 'error')
        return render_template('mass_print.html', 
            carpets=[], total_count=0,
            carpet_types=CarpetType.query.all(),
            craftsmen=Craftsman.query.all(),
            selected_type=t, selected_craftsman=c, selected_status=s)
    
    if total_count > MAX_PRINT:
        flash(f'⚠️ Найдено {total_count} ковров. Для печати будет взято только {MAX_PRINT}. Уточните фильтры.', 'warning')
        carpets = query.limit(MAX_PRINT).all()
    else:
        carpets = query.all()
    
    return render_template('mass_print.html', 
        carpets=carpets,
        total_count=total_count,
        carpet_types=CarpetType.query.all(),
        craftsmen=Craftsman.query.all(),
        selected_type=t, selected_craftsman=c, selected_status=s)

@app.route('/generate_qr_zip')
def generate_qr_zip():
    t = request.args.get('carpet_type_id','')
    c = request.args.get('craftsman_id','')
    s = request.args.get('status','')
    start = int(request.args.get('start', 0))
    end = int(request.args.get('end', 500))
    
    q = Carpet.query
    if t: q = q.filter(Carpet.carpet_type_id == t)
    if c: q = q.filter(Carpet.craftsman_id == c)
    if s: q = q.filter(Carpet.status == s)
    
    carpets = q.offset(start).limit(end - start).all()
    
    if not carpets:
        flash('Нет ковров для печати', 'error')
        return redirect(url_for('mass_print_qr'))
    
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for carpet in carpets:
            if carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
                zf.write(carpet.qr_code_path, f"{carpet.carpet_id}.png")
    
    zip_buf.seek(0)
    return send_file(zip_buf, mimetype='application/zip', as_attachment=True, 
                     download_name=f'qr_codes_{start+1}-{start+len(carpets)}.zip')

@app.route('/generate_qr_pdf')
def generate_qr_pdf():
    t = request.args.get('carpet_type_id','')
    c = request.args.get('craftsman_id','')
    s = request.args.get('status','')
    q = Carpet.query
    if t: q = q.filter(Carpet.carpet_type_id == t)
    if c: q = q.filter(Carpet.craftsman_id == c)
    if s: q = q.filter(Carpet.status == s)
    carpets = q.limit(500).all()
    
    if not carpets:
        flash('Нет ковров для печати', 'error')
        return redirect(url_for('mass_print_qr'))
    
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        from PIL import Image
        from reportlab.lib.units import mm
        
        buffer = io.BytesIO()
        
        # Размеры листа
        page_width, page_height = A4
        
        # Параметры сетки 3x4 (12 наклеек)
        cols = 3   # 3 колонки
        rows = 4   # 4 строки
        spacing = 5 * mm
        margin = 10 * mm
        
        # Размер каждой наклейки
        sticker_width = (page_width - 2 * margin - (cols - 1) * spacing) / cols
        sticker_height = (page_height - 2 * margin - (rows - 1) * spacing) / rows
        
        # Размер QR внутри наклейки
        qr_size = min(sticker_width * 0.6, sticker_height * 0.6)
        
        c = canvas.Canvas(buffer, pagesize=A4)
        
        for i, carpet in enumerate(carpets):
            # Определяем позицию наклейки на листе
            pos_in_page = i % 12
            col = pos_in_page % cols
            row = pos_in_page // cols
            
            x = margin + col * (sticker_width + spacing)
            y = page_height - margin - (row + 1) * sticker_height - row * spacing
            
            # Рисуем рамку наклейки
            c.setStrokeColorRGB(0.8, 0.8, 0.8)
            c.setLineWidth(0.5)
            c.rect(x, y, sticker_width, sticker_height)
            
            # Загружаем QR-код
            if carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
                try:
                    pil_img = Image.open(carpet.qr_code_path)
                    
                    # QR в центре наклейки
                    qr_x = x + (sticker_width - qr_size) / 2
                    qr_y = y + (sticker_height - qr_size) / 2 + 5 * mm
                    
                    # Конвертируем в нужный формат
                    temp_buffer = io.BytesIO()
                    pil_img.save(temp_buffer, format='PNG')
                    temp_buffer.seek(0)
                    
                    qr_img = ImageReader(temp_buffer)
                    c.drawImage(qr_img, qr_x, qr_y, qr_size, qr_size)
                    
                    # Текст под QR
                    c.setFillColorRGB(0, 0, 0)
                    c.setFont("Helvetica-Bold", 7)
                    
                    # ID ковра
                    text_x = x + sticker_width / 2
                    text_y = y + 3 * mm
                    c.drawCentredString(text_x, text_y, carpet.carpet_id)
                    
                    # Цена (поменьше)
                    c.setFont("Helvetica", 6)
                    price_y = y + 1 * mm
                    c.drawCentredString(text_x, price_y, f"{carpet.price} ₽")
                    
                except Exception as e:
                    logger.error(f"Ошибка обработки QR для {carpet.carpet_id}: {e}")
            
            # Если закончилась страница - сохраняем и создаем новую
            if (i + 1) % 12 == 0:
                c.showPage()
                c = canvas.Canvas(buffer, pagesize=A4)
        
        # Сохраняем последнюю страницу если есть
        if len(carpets) % 12 != 0:
            c.save()
        else:
            # Если последняя страница была полной, canvas уже сохранен
            pass
        
        buffer.seek(0)
        
        return send_file(
            buffer, 
            mimetype='application/pdf', 
            as_attachment=True, 
            download_name=f'qr_stickers_{len(carpets)}_pages.pdf'
        )
    except Exception as e:
        logger.error(f"Ошибка генерации PDF: {e}")
        traceback.print_exc()
        flash(f'❌ Ошибка генерации PDF: {str(e)[:200]}', 'error')
        return redirect(url_for('mass_print_qr'))
    
@app.route('/generate_single_pages_pdf')
def generate_single_pages_pdf():
    carpet_type_id = request.args.get('carpet_type_id', '')
    craftsman_id = request.args.get('craftsman_id', '')
    status = request.args.get('status', '')
    start = int(request.args.get('start', 0))
    end = int(request.args.get('end', 200))
    
    qr_scale = float(request.args.get('qr_scale', 0.85))
    font_id_size = int(request.args.get('font_id_size', 26))
    font_type_size = float(request.args.get('font_type_size', 18.5))
    font_price_size = int(request.args.get('font_price_size', 22))
    text_height = int(request.args.get('text_height', 105))
    show_id = request.args.get('show_id', 'true').lower() == 'true'
    show_type = request.args.get('show_type', 'true').lower() == 'true'
    show_price = request.args.get('show_price', 'true').lower() == 'true'
    show_size = request.args.get('show_size', 'true').lower() == 'true'
    
    qr_scale = max(0.5, min(1.0, qr_scale))
    font_id_size = max(14, min(60, font_id_size))
    font_type_size = max(10, min(45, font_type_size))
    font_price_size = max(12, min(55, font_price_size))
    text_height = max(60, min(250, text_height))
    
    query = Carpet.query
    if carpet_type_id:
        query = query.filter(Carpet.carpet_type_id == carpet_type_id)
    if craftsman_id:
        query = query.filter(Carpet.craftsman_id == craftsman_id)
    if status:
        query = query.filter(Carpet.status == status)
    
    carpets = query.offset(start).limit(end - start).all()
    
    if not carpets:
        flash('Нет ковров для печати!', 'error')
        return redirect(url_for('mass_print_qr'))
    
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        from PIL import Image
        import gc
        
        buffer = io.BytesIO()
        width, height = A4
        
        new_width = width * qr_scale
        new_height = height * qr_scale
        x_offset = (width - new_width) / 2
        y_offset = (height - new_height) / 2
        
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
            
            y_pos = text_height - 22
            
            if show_id:
                c.setFont("Helvetica-Bold", font_id_size)
                c.drawCentredString(width / 2, y_pos, carpet.carpet_id)
                y_pos -= font_id_size + 4
            
            if show_type:
                if FONT_REGISTERED:
                    c.setFont("RussianFont", font_type_size)
                else:
                    c.setFont("Helvetica", font_type_size)
                c.drawCentredString(width / 2, y_pos, f"{type_name} | {craftsman_name}")
                y_pos -= font_type_size + 4
            
            if show_price:
                c.setFont("Helvetica-Bold", font_price_size)
                price_str = f"{carpet.price:,} ₽".replace(',', ' ')
                c.drawCentredString(width / 2, y_pos, price_str)
                y_pos -= font_price_size + 4
            
            if show_size:
                size_material = ""
                if carpet.size:
                    size_material += f"Размер: {carpet.size}"
                if carpet.material:
                    if size_material:
                        size_material += f" | Материал: {carpet.material}"
                    else:
                        size_material += f"Материал: {carpet.material}"
                if size_material:
                    c.setFont("Helvetica", 11)
                    c.drawCentredString(width / 2, y_pos, size_material)
            
            c.setFont("Helvetica", 7)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawRightString(width - 20, 8, f"Страница {i+1} из {len(carpets)}")
            
            c.showPage()
            
            if i % 50 == 0:
                gc.collect()
        
        c.save()
        buffer.seek(0)
        
        return send_file(
            buffer, mimetype='application/pdf', as_attachment=True,
            download_name=f'qr_full_page_{len(carpets)}_pages.pdf'
        )
    except MemoryError:
        flash('❌ Слишком много ковров для одного PDF. Используйте печать по частям.', 'error')
        return redirect(url_for('mass_print_qr'))
    except Exception as e:
        print(f"Ошибка: {e}")
        traceback.print_exc()
        flash(f'❌ Ошибка генерации PDF: {str(e)[:200]}', 'error')
        return redirect(url_for('mass_print_qr'))

@app.route('/generate_single_pages_pdf_part')
def generate_single_pages_pdf_part():
    carpet_type_id = request.args.get('carpet_type_id', '')
    craftsman_id = request.args.get('craftsman_id', '')
    status = request.args.get('status', '')
    start = int(request.args.get('start', 0))
    end = int(request.args.get('end', 200))
    
    qr_scale = float(request.args.get('qr_scale', 0.85))
    font_id_size = int(request.args.get('font_id_size', 26))
    font_type_size = float(request.args.get('font_type_size', 18.5))
    font_price_size = int(request.args.get('font_price_size', 22))
    text_height = int(request.args.get('text_height', 105))
    show_id = request.args.get('show_id', 'true').lower() == 'true'
    show_type = request.args.get('show_type', 'true').lower() == 'true'
    show_price = request.args.get('show_price', 'true').lower() == 'true'
    show_size = request.args.get('show_size', 'true').lower() == 'true'
    
    qr_scale = max(0.5, min(1.0, qr_scale))
    font_id_size = max(14, min(60, font_id_size))
    font_type_size = max(10, min(45, font_type_size))
    font_price_size = max(12, min(55, font_price_size))
    text_height = max(60, min(250, text_height))
    
    query = Carpet.query
    if carpet_type_id:
        query = query.filter(Carpet.carpet_type_id == carpet_type_id)
    if craftsman_id:
        query = query.filter(Carpet.craftsman_id == craftsman_id)
    if status:
        query = query.filter(Carpet.status == status)
    
    carpets = query.offset(start).limit(end - start).all()
    
    if not carpets:
        flash('Нет ковров для печати!', 'error')
        return redirect(url_for('mass_print_qr'))
    
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        from PIL import Image
        import gc
        
        buffer = io.BytesIO()
        width, height = A4
        
        new_width = width * qr_scale
        new_height = height * qr_scale
        x_offset = (width - new_width) / 2
        y_offset = (height - new_height) / 2
        
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
            
            y_pos = text_height - 22
            
            if show_id:
                c.setFont("Helvetica-Bold", font_id_size)
                c.drawCentredString(width / 2, y_pos, carpet.carpet_id)
                y_pos -= font_id_size + 4
            
            if show_type:
                if FONT_REGISTERED:
                    c.setFont("RussianFont", font_type_size)
                else:
                    c.setFont("Helvetica", font_type_size)
                c.drawCentredString(width / 2, y_pos, f"{type_name} | {craftsman_name}")
                y_pos -= font_type_size + 4
            
            if show_price:
                c.setFont("Helvetica-Bold", font_price_size)
                price_str = f"{carpet.price:,} ₽".replace(',', ' ')
                c.drawCentredString(width / 2, y_pos, price_str)
                y_pos -= font_price_size + 4
            
            if show_size:
                size_material = ""
                if carpet.size:
                    size_material += f"Размер: {carpet.size}"
                if carpet.material:
                    if size_material:
                        size_material += f" | Материал: {carpet.material}"
                    else:
                        size_material += f"Материал: {carpet.material}"
                if size_material:
                    c.setFont("Helvetica", 11)
                    c.drawCentredString(width / 2, y_pos, size_material)
            
            c.setFont("Helvetica", 7)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawRightString(width - 20, 8, f"Страница {i+1} из {len(carpets)}")
            
            c.showPage()
            
            if i % 50 == 0:
                gc.collect()
        
        c.save()
        buffer.seek(0)
        
        return send_file(
            buffer, mimetype='application/pdf', as_attachment=True,
            download_name=f'qr_full_page_{len(carpets)}_pages_part_{start+1}-{start+len(carpets)}.pdf'
        )
    except MemoryError:
        flash('❌ Слишком много ковров для одного PDF. Используйте печать по частям.', 'error')
        return redirect(url_for('mass_print_qr'))
    except Exception as e:
        print(f"Ошибка: {e}")
        traceback.print_exc()
        flash(f'❌ Ошибка генерации PDF: {str(e)[:200]}', 'error')
        return redirect(url_for('mass_print_qr'))

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

@app.route('/check_ids')
def check_ids():
    all_ids = Carpet.query.all()
    ids_list = [c.carpet_id for c in all_ids]
    duplicates = [id for id in ids_list if ids_list.count(id) > 1]
    
    max_num = 0
    for cid in ids_list:
        try:
            if cid and '-' in cid:
                num = int(cid.split('-')[1])
                if num > max_num:
                    max_num = num
        except:
            continue
    
    return jsonify({
        'total_carpets': len(all_ids),
        'duplicates': duplicates,
        'max_id': max_num,
        'next_id': f"CARPET-{max_num + 1:04d}",
        'all_ids': ids_list[:20]
    })

@app.route('/cleanup_old_carpets')
def cleanup_old_carpets_route():
    days = request.args.get('days', 60, type=int)
    deleted = cleanup_old_carpets(days)
    
    if deleted > 0:
        flash(f'🧹 Удалено {deleted} старых отсканированных ковров (старше {days} дней)', 'success')
    else:
        flash(f'✅ Старых отсканированных ковров для удаления не найдено', 'info')
    
    return redirect(url_for('index'))

@app.route('/cleanup_settings')
def cleanup_settings():
    settings = CleanupSettings.query.first()
    if not settings:
        settings = CleanupSettings(auto_cleanup=True, cleanup_days=60)
        db.session.add(settings)
        db.session.commit()
    return render_template('cleanup_settings.html', settings=settings)

@app.route('/update_cleanup_settings', methods=['POST'])
def update_cleanup_settings():
    settings = CleanupSettings.query.first()
    if not settings:
        settings = CleanupSettings()
    
    settings.auto_cleanup = 'auto_cleanup' in request.form
    settings.cleanup_days = int(request.form.get('cleanup_days', 60))
    db.session.commit()
    
    flash('✅ Настройки очистки сохранены', 'success')
    return redirect(url_for('cleanup_settings'))

@app.route('/export_db')
def export_db():
    if os.path.exists(DB_PATH):
        return send_file(
            DB_PATH,
            as_attachment=True,
            download_name=f'carpets_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        )
    flash('❌ База данных не найдена', 'error')
    return redirect(url_for('index'))

@app.route('/check_db')
def check_db():
    try:
        db.session.execute(text('SELECT 1'))
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
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)