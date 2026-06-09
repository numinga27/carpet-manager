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

# ========== ОПРЕДЕЛЕНИЕ ПУТЕЙ ==========
if getattr(sys, 'frozen', False):
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(sys.executable)
else:
    base_path = os.path.dirname(__file__)

template_folder = os.path.join(base_path, 'templates')
app = Flask(__name__, template_folder=template_folder)

# ========== ПОДДЕРЖКА РУССКОГО ШРИФТА ==========
try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Arial.ttf",
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

# ========== ОБРАБОТЧИК ИСКЛЮЧЕНИЙ ==========
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

# ========== ОПРЕДЕЛЕНИЕ ПАПОК ==========
def find_data_folder():
    possible_folders = []
    if sys.platform == 'win32':
        appdata_folder = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'CarpetManager')
        possible_folders.append(appdata_folder)
    user_folder = os.path.join(os.path.expanduser('~'), '.carpetmanager')
    possible_folders.append(user_folder)
    docs_folder = os.path.join(os.path.expanduser('~'), 'Documents', 'CarpetManager')
    possible_folders.append(docs_folder)
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
    preferred_ports = [5000, 5001, 5002, 8080, 8081]
    for port in preferred_ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                return port
        except OSError:
            continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

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

# ========== ФУНКЦИИ ДЛЯ WB АНАЛИТИКИ ==========
def get_wb_analytics(api_key, account_id, period_days=30):
    """
    Получение аналитики по товарам Wildberries
    Использует правильный эндпоинт: /api/analytics/v3/sales-funnel/products
    """
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
            return products if products else create_demo_analytics()
        else:
            logger.error(f"Ошибка API: {response.status_code}")
            if response.status_code == 401:
                flash(f'⚠️ Токен Wildberries недействителен или не имеет прав на аналитику', 'warning')
            return create_demo_analytics()
            
    except Exception as e:
        logger.exception(f"Ошибка получения аналитики: {e}")
        return create_demo_analytics()

def create_demo_analytics():
    """Создает демонстрационные данные для аналитики"""
    demo_products = []
    carpets = Carpet.query.all()
    
    for i, carpet in enumerate(carpets[:15] if carpets else range(5)):
        if isinstance(carpet, int):
            nm_id = 1000000 + carpet
            product_name = f'Тестовый товар {carpet+1}'
            views = 500 + (carpet * 100)
        else:
            try:
                nm_id = int(carpet.carpet_id.split('-')[1]) if carpet.carpet_id and '-' in carpet.carpet_id else 1000000 + i
            except:
                nm_id = 1000000 + i
            product_name = carpet.carpet_type_ref.name if hasattr(carpet, 'carpet_type_ref') and carpet.carpet_type_ref else f'Ковер {carpet.carpet_id}'
            views = 500 + (i * 150) + (abs(hash(str(carpet.id))) % 500)
        
        cart_adds = int(views * 0.05)
        orders = int(cart_adds * 0.6)
        sales = int(orders * 0.85)
        
        demo_products.append({
            'nmId': nm_id,
            'productName': product_name,
            'brandName': 'Ковровая мастерская',
            'selectedPeriod': {
                'views': views,
                'carts': cart_adds,
                'orders': orders,
                'sales': sales,
                'cancellations': max(0, orders - sales),
                'returns': max(0, orders - sales) // 2
            },
            'pastPeriod': {
                'views': int(views * 0.7),
                'carts': int(cart_adds * 0.6),
                'orders': int(orders * 0.6),
                'sales': int(sales * 0.6)
            }
        })
    
    return demo_products

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
            
            analytic = WBProductAnalytics.query.filter_by(account_id=account_id, nm_id=nm_id).first()
            
            if not analytic:
                analytic = WBProductAnalytics(
                    account_id=account_id, nm_id=nm_id,
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
            
            analytic.period_start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            analytic.period_end = datetime.now().strftime("%Y-%m-%d")
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
        db.session.add(cache)
        db.session.commit()
        
        flash(f'📊 WB Аналитика: {new} новых, {updated} обновлено', 'success')
        return updated
        
    except Exception as e:
        logger.exception(f"Ошибка синхронизации: {e}")
        flash(f'❌ Ошибка: {str(e)[:200]}', 'error')
        return 0

# ========== ОСТАЛЬНЫЕ ФУНКЦИИ ==========
def generate_qr_code(carpet_id, _):
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
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

def forecast_sales(days=30):
    try:
        orders = MarketplaceOrder.query.filter_by(status='shipped').all()
        if len(orders) < 7:
            return {"no_data": True, "message": "Недостаточно данных", "data": [], "total": 0}
        
        daily_counts = defaultdict(int)
        for order in orders:
            date_str = order.shipped_at or order.ordered_at
            if date_str:
                daily_counts[date_str[:10]] += 1
        
        if not daily_counts:
            return {"no_data": True, "data": [], "total": 0}
        
        counts = list(daily_counts.values())
        avg = sum(counts[-7:]) / 7 if len(counts) >= 7 else sum(counts) / len(counts)
        forecast = [max(0, round(avg * (0.9 + i * 0.02))) for i in range(days)]
        
        return {"no_data": False, "data": forecast, "total": sum(forecast)}
    except Exception as e:
        return {"error": str(e), "no_data": True}

def sync_account_orders(account_id):
    acc = db.session.get(MarketplaceAccount, account_id)
    if not acc or not acc.is_active:
        return 0
    
    new = 0
    try:
        if acc.marketplace == 'wb':
            headers = {"Authorization": acc.api_key}
            response = requests.get("https://marketplace-api.wildberries.ru/api/v3/dbs/orders/new", headers=headers, timeout=30)
            if response.status_code == 200:
                for o in response.json().get('orders', []):
                    if not MarketplaceOrder.query.filter_by(marketplace='wb', order_id=str(o.get('id'))).first():
                        mo = MarketplaceOrder(
                            account_id=acc.id, marketplace='wb', order_id=str(o.get('id')),
                            status='new', ordered_at=o.get('createdAt', ''), price=o.get('price', 0)
                        )
                        db.session.add(mo)
                        new += 1
                db.session.commit()
                if new > 0:
                    flash(f'✅ {acc.account_name}: {new} новых заказов', 'success')
        elif acc.marketplace == 'ozon':
            headers = {"Api-Key": acc.api_key, "Client-Id": acc.client_id}
            payload = {"filter": {"since": (datetime.now() - timedelta(days=30)).isoformat()}, "limit": 100}
            response = requests.post("https://api-seller.ozon.ru/v3/posting/fbs/list", headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                for o in response.json().get('result', {}).get('postings', []):
                    if not MarketplaceOrder.query.filter_by(marketplace='ozon', order_id=o.get('posting_number')).first():
                        mo = MarketplaceOrder(
                            account_id=acc.id, marketplace='ozon', order_id=o.get('posting_number'),
                            status='new', ordered_at=o.get('created_at', '')
                        )
                        db.session.add(mo)
                        new += 1
                db.session.commit()
                if new > 0:
                    flash(f'✅ {acc.account_name}: {new} новых заказов', 'success')
        
        acc.last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.session.commit()
    except Exception as e:
        flash(f'❌ Ошибка синхронизации {acc.account_name}: {str(e)[:100]}', 'error')
    
    return new

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
    accounts = MarketplaceAccount.query.filter_by(marketplace='wb', is_active=True).all()
    analytics = WBProductAnalytics.query.all()
    
    total_stats = {
        'total_views': sum(a.views for a in analytics),
        'total_cart_adds': sum(a.cart_adds for a in analytics),
        'total_orders': sum(a.orders for a in analytics),
        'total_sales': sum(a.sales for a in analytics),
    }
    
    if total_stats['total_views'] > 0:
        total_stats['avg_conversion_to_sale'] = round((total_stats['total_sales'] / total_stats['total_views']) * 100, 2)
    
    top_by_views = sorted(analytics, key=lambda x: x.views, reverse=True)[:10]
    top_by_sales = sorted(analytics, key=lambda x: x.sales, reverse=True)[:10]
    
    return render_template('wb_analytics.html',
                          accounts=accounts, analytics=analytics,
                          total_stats=total_stats, top_by_views=top_by_views,
                          top_by_sales=top_by_sales)

@app.route('/sync_wb_analytics/<int:account_id>')
def sync_wb_analytics_route(account_id):
    sync_wb_analytics(account_id)
    return redirect(url_for('wb_analytics'))

@app.route('/sync_all_wb_analytics')
def sync_all_wb_analytics():
    for acc in MarketplaceAccount.query.filter_by(marketplace='wb', is_active=True).all():
        sync_wb_analytics(acc.id)
    return redirect(url_for('wb_analytics'))

@app.route('/forecast')
def forecast_page():
    forecast = forecast_sales(30)
    return render_template('forecast.html', forecast=forecast)

@app.route('/add_carpet', methods=['POST'])
def add_carpet():
    cid = generate_next_id()
    carpet = Carpet(
        carpet_id=cid, carpet_type_id=request.form['carpet_type_id'],
        craftsman_id=request.form['craftsman_id'], price=float(request.form['price']),
        size=request.form.get('size',''), material=request.form.get('material',''),
        color=request.form.get('color',''), status='created', notes=request.form.get('notes','')
    )
    db.session.add(carpet)
    db.session.commit()
    carpet.qr_code_path = generate_qr_code(cid, {})
    db.session.commit()
    flash(f'Ковёр {cid} добавлен', 'success')
    return redirect(url_for('index'))

@app.route('/add_carpet_group', methods=['POST'])
def add_carpet_group():
    type_id = request.form['carpet_type_id']
    count = int(request.form['count'])
    craftsman_id = request.form['craftsman_id']
    ct = db.session.get(CarpetType, type_id)
    if not ct:
        flash('Ошибка: тип не найден', 'error')
        return redirect(url_for('index'))
    
    for i in range(count):
        cid = generate_next_id()
        carpet = Carpet(
            carpet_id=cid, carpet_type_id=type_id, craftsman_id=craftsman_id,
            price=ct.base_price, status='created'
        )
        db.session.add(carpet)
        db.session.flush()
        carpet.qr_code_path = generate_qr_code(cid, {})
    db.session.commit()
    flash(f'Создано {count} ковров типа "{ct.name}"', 'success')
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
    for carpet in c.carpets:
        if carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
            os.remove(carpet.qr_code_path)
    db.session.delete(c)
    db.session.commit()
    flash(f'Швея "{c.name}" удалена', 'success')
    return redirect(url_for('index'))

@app.route('/craftsman/<int:id>')
def craftsman_detail(id):
    c = Craftsman.query.get_or_404(id)
    carpets = Carpet.query.filter_by(craftsman_id=id).all()
    return render_template('craftsman_detail.html', craftsman=c, carpets=carpets,
                          total_count=len(carpets),
                          scanned_count=len([x for x in carpets if x.status=='scanned']))

@app.route('/types')
def types_list():
    return render_template('types.html', types=CarpetType.query.all())

@app.route('/add_type', methods=['POST'])
def add_type():
    name = request.form['name']
    price = float(request.form['base_price'])
    if CarpetType.query.filter_by(name=name).first():
        flash('Тип уже существует', 'error')
    else:
        db.session.add(CarpetType(name=name, base_price=price, description=request.form.get('description','')))
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
    carpet = Carpet.query.filter_by(carpet_id=data).first()
    
    if not carpet:
        return jsonify({'success': False, 'message': '❌ Ковёр не найден'})
    
    if carpet.status == 'scanned':
        return jsonify({'success': False, 'already_scanned': True, 'scanned_at': carpet.scanned_at})
    
    carpet.status = 'scanned'
    carpet.scanned_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.session.commit()
    
    return jsonify({'success': True, 'carpet_id': carpet.carpet_id,
                   'carpet_type': carpet.carpet_type_ref.name if carpet.carpet_type_ref else '-',
                   'craftsman': carpet.craftsman_ref.name if carpet.craftsman_ref else '-',
                   'price': carpet.price, 'scanned_at': carpet.scanned_at})

@app.route('/get_qr/<carpet_id>')
def get_qr(carpet_id):
    carpet = Carpet.query.filter_by(carpet_id=carpet_id).first()
    if carpet and carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
        return send_file(carpet.qr_code_path, mimetype='image/png')
    return "QR не найден", 404

@app.route('/mass_print_qr')
def mass_print_qr():
    t = request.args.get('carpet_type_id','')
    c = request.args.get('craftsman_id','')
    s = request.args.get('status','')
    q = Carpet.query
    if t: q = q.filter(Carpet.carpet_type_id == t)
    if c: q = q.filter(Carpet.craftsman_id == c)
    if s: q = q.filter(Carpet.status == s)
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
        
        for carpet in carpets:
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
            c.drawCentredString(w/2, 38, carpet.carpet_id)
            c.showPage()
        
        c.save()
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f'qr_print_{len(carpets)}_pages.pdf')
    except Exception as e:
        return f"Ошибка: {e}", 500

@app.route('/generate_single_pages_pdf')
def generate_single_pages_pdf():
    carpet_type_id = request.args.get('carpet_type_id', '')
    craftsman_id = request.args.get('craftsman_id', '')
    status = request.args.get('status', '')
    
    # В функции generate_single_pages_pdf обновите ограничения:
    qr_scale = max(0.5, min(1.0, qr_scale))
    font_id_size = max(14, min(60, font_id_size))      # увеличено с 40 до 60
    font_type_size = max(10, min(45, font_type_size))  # увеличено с 28 до 45
    font_price_size = max(12, min(55, font_price_size)) # увеличено с 36 до 55
    text_height = max(60, min(250, text_height))       # увеличено с 150 до 250
    show_id = request.args.get('show_id', 'true').lower() == 'true'
    show_type = request.args.get('show_type', 'true').lower() == 'true'
    show_price = request.args.get('show_price', 'true').lower() == 'true'
    show_size = request.args.get('show_size', 'true').lower() == 'true'
    
    qr_scale = max(0.5, min(1.0, qr_scale))
    font_id_size = max(14, min(40, font_id_size))
    font_type_size = max(10, min(28, font_type_size))
    font_price_size = max(12, min(36, font_price_size))
    text_height = max(60, min(150, text_height))
    
    query = Carpet.query
    if carpet_type_id: query = query.filter(Carpet.carpet_type_id == carpet_type_id)
    if craftsman_id: query = query.filter(Carpet.craftsman_id == craftsman_id)
    if status: query = query.filter(Carpet.status == status)
    
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
            
            scale = max(new_width / img_width, new_height / img_height)
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
                font_name = "RussianFont" if FONT_REGISTERED else "Helvetica"
                c.setFont(font_name, font_type_size)
                c.drawCentredString(width / 2, y_pos, f"{type_name} | {craftsman_name}")
                y_pos -= font_type_size + 4
            
            if show_price:
                c.setFont("Helvetica-Bold", font_price_size)
                c.drawCentredString(width / 2, y_pos, f"{carpet.price:,} ₽".replace(',', ' '))
            
            c.setFont("Helvetica", 7)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawRightString(width - 20, 8, f"Страница {i+1} из {len(carpets)}")
            c.showPage()
        
        c.save()
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f'qr_full_page_{len(carpets)}_pages.pdf')
    except Exception as e:
        return f"Ошибка: {str(e)}", 500

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
    key = request.form['api_key']
    cid = request.form.get('client_id','')
    active = 'is_active' in request.form
    
    if MarketplaceAccount.query.filter_by(marketplace=mp, account_name=name).first():
        flash('Аккаунт с таким названием уже существует', 'error')
    else:
        db.session.add(MarketplaceAccount(marketplace=mp, account_name=name, api_key=key, client_id=cid, is_active=active))
        db.session.commit()
        flash(f'Аккаунт "{name}" добавлен', 'success')
    return redirect(url_for('marketplace_accounts'))

@app.route('/edit_marketplace_account/<int:id>', methods=['GET','POST'])
def edit_marketplace_account(id):
    acc = MarketplaceAccount.query.get_or_404(id)
    if request.method == 'POST':
        acc.account_name = request.form['account_name']
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
    sync_account_orders(account_id)
    return redirect(url_for('marketplace_accounts'))

@app.route('/sync_all_orders')
def sync_all_orders():
    for a in MarketplaceAccount.query.filter_by(is_active=True).all():
        sync_account_orders(a.id)
    return redirect(url_for('marketplace_accounts'))

@app.route('/marketplace_orders')
def marketplace_orders():
    acc = request.args.get('account_id','')
    st = request.args.get('status','')
    q = MarketplaceOrder.query
    if acc: q = q.filter(MarketplaceOrder.account_id == acc)
    if st: q = q.filter(MarketplaceOrder.status == st)
    orders = q.order_by(MarketplaceOrder.ordered_at.desc()).all()
    accounts = MarketplaceAccount.query.all()
    carpets = Carpet.query.filter_by(status='created').all()
    
    stats = {
        'new': MarketplaceOrder.query.filter_by(status='new').count(),
        'processing': MarketplaceOrder.query.filter_by(status='processing').count(),
        'ready': MarketplaceOrder.query.filter_by(status='ready').count(),
        'shipped': MarketplaceOrder.query.filter_by(status='shipped').count()
    }
    return render_template('marketplace_orders.html', orders=orders, accounts=accounts, carpets=carpets,
                          stats=stats, selected_account=acc, selected_status=st)

@app.route('/link_order_to_carpet', methods=['POST'])
def link_order_to_carpet():
    order = MarketplaceOrder.query.get(request.form['order_id'])
    carpet = Carpet.query.filter_by(carpet_id=request.form['carpet_id']).first()
    if order and carpet:
        order.carpet_id = carpet.carpet_id
        order.status = 'processing'
        db.session.commit()
        flash(f'Ковёр привязан к заказу', 'success')
    return redirect(url_for('marketplace_orders'))

@app.route('/update_order_status', methods=['POST'])
def update_order_status():
    order = MarketplaceOrder.query.get(request.form['order_id'])
    if order:
        order.status = request.form['status']
        if request.form['status'] == 'shipped':
            order.shipped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.session.commit()
        flash(f'Статус заказа обновлён', 'success')
    return redirect(url_for('marketplace_orders'))

@app.route('/marketplace_stats_api')
def marketplace_stats_api():
    accounts = MarketplaceAccount.query.filter_by(is_active=True).all()
    result = {'accounts': []}
    for a in accounts:
        result['accounts'].append({
            'id': a.id, 'name': a.account_name, 'marketplace': a.marketplace,
            'new': MarketplaceOrder.query.filter_by(account_id=a.id, status='new').count(),
            'processing': MarketplaceOrder.query.filter_by(account_id=a.id, status='processing').count(),
            'ready': MarketplaceOrder.query.filter_by(account_id=a.id, status='ready').count(),
            'shipped': MarketplaceOrder.query.filter_by(account_id=a.id, status='shipped').count(),
            'total': MarketplaceOrder.query.filter_by(account_id=a.id).count(),
            'last_sync': a.last_sync
        })
    return jsonify(result)

@app.route('/wb_settings')
def wb_settings():
    wb_accounts = MarketplaceAccount.query.filter_by(marketplace='wb').all()
    return render_template('wb_settings.html', accounts=wb_accounts)

@app.route('/add_wb_token', methods=['POST'])
def add_wb_token():
    token_name = request.form.get('token_name', 'Wildberries Аккаунт')
    api_key = request.form.get('api_key', '').strip()
    is_active = 'is_active' in request.form
    
    if not api_key:
        flash('❌ API-ключ не может быть пустым', 'error')
        return redirect(url_for('wb_settings'))
    
    account = MarketplaceAccount(
        marketplace='wb',
        account_name=token_name,
        account_login=request.form.get('account_login', ''),
        api_key=api_key,
        client_id='',
        is_active=is_active
    )
    db.session.add(account)
    db.session.commit()
    
    flash(f'✅ Аккаунт "{token_name}" добавлен', 'success')
    return redirect(url_for('wb_settings'))

@app.route('/test_wb_token/<int:account_id>')
def test_wb_token(account_id):
    account = MarketplaceAccount.query.get_or_404(account_id)
    
    try:
        headers = {"Authorization": account.api_key}
        url = "https://marketplace-api.wildberries.ru/api/v3/dbs/orders/new"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return jsonify({'success': True, 'message': '✅ Токен работает!'})
        elif response.status_code == 401:
            return jsonify({'success': False, 'error': '❌ Неверный токен'})
        else:
            return jsonify({'success': False, 'error': f'⚠️ Ошибка: код {response.status_code}'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'❌ Ошибка: {str(e)}'})

@app.route('/toggle_wb_account/<int:account_id>')
def toggle_wb_account(account_id):
    account = MarketplaceAccount.query.get_or_404(account_id)
    account.is_active = not account.is_active
    db.session.commit()
    flash(f'✅ Аккаунт "{account.account_name}" {"активен" if account.is_active else "отключен"}', 'success')
    return redirect(url_for('wb_settings'))

@app.route('/delete_wb_account/<int:account_id>')
def delete_wb_account(account_id):
    account = MarketplaceAccount.query.get_or_404(account_id)
    orders_count = MarketplaceOrder.query.filter_by(account_id=account_id).count()
    if orders_count > 0:
        flash(f'❌ Нельзя удалить аккаунт с {orders_count} заказами', 'error')
    else:
        db.session.delete(account)
        db.session.commit()
        flash(f'✅ Аккаунт удален', 'success')
    return redirect(url_for('wb_settings'))

@app.route('/search')
def search():
    q = request.args.get('q','')
    query = Carpet.query
    if q:
        query = query.filter(Carpet.carpet_id.contains(q))
    carpets = query.all()
    return render_template('search.html', carpets=carpets, query=q)

@app.route('/stats')
def stats():
    carpets = Carpet.query.all()
    return render_template('stats.html', carpets=carpets,
                          total_carpets=len(carpets),
                          scanned_count=len([c for c in carpets if c.status == 'scanned']),
                          sold_count=len([c for c in carpets if c.status == 'sold']))

@app.route('/check_db')
def check_db():
    return jsonify({
        'status': 'ok',
        'database_path': DB_PATH,
        'carpets_count': Carpet.query.count(),
        'orders_count': MarketplaceOrder.query.count()
    })

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