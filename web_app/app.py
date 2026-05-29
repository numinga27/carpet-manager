from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import sys
import qrcode
import webbrowser
import threading
import time
import io
import zipfile

# ========== ОПРЕДЕЛЕНИЕ ПУТЕЙ ДЛЯ РАЗНЫХ ПЛАТФОРМ ==========
if getattr(sys, 'frozen', False):
    # Запуск как .exe
    base_path = os.path.dirname(sys.executable)
else:
    # Запуск как скрипт
    base_path = os.path.dirname(__file__)

# Папка для данных (с возможностью записи)
DATA_FOLDER = None

# Пробуем создать папку рядом с программой
local_data_folder = os.path.join(base_path, 'CarpetManagerData')
try:
    os.makedirs(local_data_folder, exist_ok=True)
    # Проверяем, можем ли писать в эту папку
    test_file = os.path.join(local_data_folder, 'test.txt')
    with open(test_file, 'w') as f:
        f.write('test')
    os.remove(test_file)
    DATA_FOLDER = local_data_folder
    print(f"✅ Используется локальная папка: {DATA_FOLDER}")
except (PermissionError, OSError):
    # Если нет прав, используем папку пользователя
    if sys.platform == 'win32':
        DATA_FOLDER = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'CarpetManager')
    else:
        DATA_FOLDER = os.path.join(os.path.expanduser('~'), '.carpetmanager')
    os.makedirs(DATA_FOLDER, exist_ok=True)
    print(f"✅ Используется папка пользователя: {DATA_FOLDER}")

# Папка для шаблонов
template_folder = os.path.join(base_path, 'templates')
# Папка для статических файлов (если есть)
static_folder = os.path.join(base_path, 'static')
if not os.path.exists(static_folder):
    os.makedirs(static_folder, exist_ok=True)

app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)

# База данных
DB_PATH = os.path.join(DATA_FOLDER, 'carpets.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key-here'

db = SQLAlchemy(app)

# Папка для QR-кодов
QR_FOLDER = os.path.join(DATA_FOLDER, 'qr_codes')
os.makedirs(QR_FOLDER, exist_ok=True)

print(f"📁 База данных: {DB_PATH}")
print(f"📁 QR-коды: {QR_FOLDER}")

# ========== МОДЕЛИ ДАННЫХ ==========

class CarpetType(db.Model):
    """Типы ковров (создаются пользователем)"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    base_price = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    carpets = db.relationship('Carpet', backref='carpet_type_ref', lazy=True)

class Craftsman(db.Model):
    """Швеи с каскадным удалением"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    carpets = db.relationship('Carpet', backref='craftsman_ref', cascade="all, delete-orphan")

class Carpet(db.Model):
    """Ковры (только дата сканирования)"""
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
    """Лог сканирований"""
    id = db.Column(db.Integer, primary_key=True)
    carpet_id = db.Column(db.String(50), nullable=False)
    scanned_at = db.Column(db.String(20), nullable=False)
    scanned_by = db.Column(db.String(50), default='admin')
    result = db.Column(db.String(20))

# ========== ФУНКЦИИ ==========

def generate_qr_code(carpet_id, carpet_data):
    """Генерирует QR-код с информацией о ковре"""
    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=4,
        error_correction=qrcode.constants.ERROR_CORRECT_M
    )
    qr.add_data(carpet_id)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    filename = f"carpet_{carpet_id}.png"
    filepath = os.path.join(QR_FOLDER, filename)
    img.save(filepath)
    return filepath

def generate_next_id():
    """Генерирует следующий ID ковра"""
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

def find_free_port():
    """Находит свободный порт"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port

# ========== СОЗДАНИЕ БД И ТЕСТОВЫХ ДАННЫХ ==========

with app.app_context():
    db.create_all()
    
    # Добавляем тестовые типы ковров
    if CarpetType.query.count() == 0:
        default_types = [
            CarpetType(name="Персидский", base_price=15000, description="Классический персидский ковёр ручной работы"),
            CarpetType(name="Турецкий", base_price=12000, description="Турецкий ковёр из натуральной шерсти"),
            CarpetType(name="Современный", base_price=8000, description="Современный дизайн, синтетические материалы"),
            CarpetType(name="Винтажный", base_price=20000, description="Винтажный ковёр с эффектом состаренности")
        ]
        for t in default_types:
            db.session.add(t)
        db.session.commit()
    
    # Добавляем тестовых швей
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
    
    # Добавляем тестовые ковры
    if Carpet.query.count() == 0:
        test_data = [
            ("CARPET-0001", 1, 1, 15000, "scanned", "2025-05-28 14:30:00"),
            ("CARPET-0002", 2, 2, 12000, "created", None),
            ("CARPET-0003", 3, 1, 8000, "created", None),
            ("CARPET-0004", 1, 3, 49, "created", None)
        ]
        for qr, type_id, cm_id, price, status, scanned_at in test_data:
            carpet = Carpet(
                carpet_id=qr, 
                carpet_type_id=type_id, 
                craftsman_id=cm_id, 
                price=price, 
                status=status,
                scanned_at=scanned_at
            )
            db.session.add(carpet)
        db.session.commit()
        
        # Генерируем QR-коды для тестовых ковров
        for carpet in Carpet.query.all():
            carpet_type = CarpetType.query.get(carpet.carpet_type_id)
            craftsman = Craftsman.query.get(carpet.craftsman_id)
            carpet_data = {
                'carpet_type_name': carpet_type.name,
                'craftsman_name': craftsman.name,
                'price': carpet.price
            }
            carpet.qr_code_path = generate_qr_code(carpet.carpet_id, carpet_data)
        db.session.commit()

# ========== МАРШРУТЫ ==========

@app.route('/')
def index():
    return render_template('index.html', 
                         carpets=Carpet.query.all(),
                         craftsmen=Craftsman.query.all(),
                         carpet_types=CarpetType.query.all())

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
    
    carpet_type = CarpetType.query.get(carpet.carpet_type_id)
    craftsman = Craftsman.query.get(carpet.craftsman_id)
    carpet_data = {
        'carpet_type_name': carpet_type.name,
        'craftsman_name': craftsman.name,
        'price': carpet.price
    }
    carpet.qr_code_path = generate_qr_code(carpet_id, carpet_data)
    db.session.commit()
    
    flash(f'Ковёр {carpet_id} успешно добавлен!', 'success')
    return redirect(url_for('index'))

@app.route('/add_carpet_group', methods=['POST'])
def add_carpet_group():
    """Групповое добавление ковров одного типа (до 2000 шт)"""
    carpet_type_id = request.form['carpet_type_id']
    count = int(request.form['count'])
    craftsman_id = request.form['craftsman_id']
    size = request.form.get('size', '')
    material = request.form.get('material', '')
    color = request.form.get('color', '')
    
    if count > 2000:
        flash('⚠️ Максимальное количество - 2000 ковров за раз!', 'error')
        return redirect(url_for('index'))
    
    if count < 1:
        flash('⚠️ Количество должно быть не менее 1!', 'error')
        return redirect(url_for('index'))
    
    carpet_type = CarpetType.query.get(carpet_type_id)
    craftsman = Craftsman.query.get(craftsman_id)
    
    if not carpet_type or not craftsman:
        flash('❌ Тип или швея не найдены!', 'error')
        return redirect(url_for('index'))
    
    created = []
    errors = []
    
    for i in range(count):
        try:
            carpet_id = generate_next_id()
            carpet = Carpet(
                carpet_id=carpet_id,
                carpet_type_id=carpet_type_id,
                craftsman_id=craftsman_id,
                price=carpet_type.base_price,
                size=size,
                material=material,
                color=color,
                status='created',
                notes=f'Групповое добавление {i+1}/{count}'
            )
            db.session.add(carpet)
            db.session.flush()
            
            carpet_data = {
                'carpet_type_name': carpet_type.name,
                'craftsman_name': craftsman.name,
                'price': carpet.price
            }
            carpet.qr_code_path = generate_qr_code(carpet_id, carpet_data)
            created.append(carpet_id)
            
            if (i + 1) % 100 == 0:
                print(f"📦 Прогресс: {i+1}/{count} ковров создано")
                
        except Exception as e:
            errors.append(f"{carpet_id if 'carpet_id' in locals() else '?'}: {str(e)}")
    
    db.session.commit()
    
    if errors:
        flash(f'⚠️ Создано {len(created)} из {count}. Ошибки: {", ".join(errors[:3])}', 'warning')
    else:
        flash(f'✅ Успешно создано {len(created)} ковров типа "{carpet_type.name}"', 'success')
    
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
        
        carpet_type = CarpetType.query.get(carpet.carpet_type_id)
        craftsman = Craftsman.query.get(carpet.craftsman_id)
        carpet_data = {
            'carpet_type_name': carpet_type.name,
            'craftsman_name': craftsman.name,
            'price': carpet.price
        }
        carpet.qr_code_path = generate_qr_code(carpet.carpet_id, carpet_data)
        db.session.commit()
        
        flash(f'Ковёр {carpet.carpet_id} успешно обновлён!', 'success')
        return redirect(url_for('index'))
    
    return render_template('edit_carpet.html', 
                         carpet=carpet,
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
    db.session.add(Craftsman(
        name=request.form['name'], 
        phone=request.form.get('phone', '')
    ))
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
    
    if carpet_count > 0:
        flash(f'Швея "{craftsman.name}" удалена вместе с {carpet_count} коврами', 'success')
    else:
        flash(f'Швея "{craftsman.name}" удалена', 'success')
    
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
    
    return render_template('craftsman_detail.html',
        craftsman=craftsman,
        carpets=carpets,
        total_count=total_count,
        scanned_count=scanned_count,
        total_price=total_price,
        type_stats=type_stats,
        month_stats=month_stats,
        scan_date_from=scan_date_from,
        scan_date_to=scan_date_to
    )

@app.route('/types')
def types_list():
    types = CarpetType.query.all()
    return render_template('types.html', types=types)

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
    
    log = ScanLog(
        carpet_id=qr_data,
        scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        scanned_by=scanner_name
    )
    
    if not carpet:
        log.result = 'not_found'
        db.session.add(log)
        db.session.commit()
        return jsonify({'success': False, 'message': '❌ Ковёр не найден в базе данных!'})
    
    if carpet.status == 'scanned':
        log.result = 'already_scanned'
        db.session.add(log)
        db.session.commit()
        return jsonify({
            'success': False,
            'already_scanned': True,
            'carpet_id': carpet.carpet_id,
            'scanned_at': carpet.scanned_at,
            'message': f'⚠️ Этот ковёр уже был отсканирован {carpet.scanned_at}!'
        })
    
    carpet.status = 'scanned'
    carpet.scanned_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    carpet.scanned_by = scanner_name
    
    log.result = 'success'
    db.session.add(log)
    db.session.commit()
    
    carpet_type = CarpetType.query.get(carpet.carpet_type_id)
    craftsman = Craftsman.query.get(carpet.craftsman_id)
    
    return jsonify({
        'success': True,
        'first_time': True,
        'carpet_id': carpet.carpet_id,
        'carpet_type': carpet_type.name,
        'craftsman': craftsman.name,
        'price': carpet.price,
        'size': carpet.size or '-',
        'material': carpet.material or '-',
        'color': carpet.color or '-',
        'scanned_at': carpet.scanned_at,
        'message': f'✅ Ковёр {carpet.carpet_id} успешно отсканирован!'
    })

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

@app.route('/mass_print_qr')
def mass_print_qr():
    carpet_type_id = request.args.get('carpet_type_id', '')
    status = request.args.get('status', '')
    
    query = Carpet.query
    if carpet_type_id:
        query = query.filter(Carpet.carpet_type_id == carpet_type_id)
    if status:
        query = query.filter(Carpet.status == status)
    
    carpets = query.all()
    
    return render_template('mass_print.html', 
                         carpets=carpets,
                         carpet_types=CarpetType.query.all(),
                         selected_type=carpet_type_id,
                         selected_status=status)

@app.route('/generate_qr_zip')
def generate_qr_zip():
    carpet_type_id = request.args.get('carpet_type_id', '')
    status = request.args.get('status', '')
    
    query = Carpet.query
    if carpet_type_id:
        query = query.filter(Carpet.carpet_type_id == carpet_type_id)
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
    status = request.args.get('status', '')
    
    query = Carpet.query
    if carpet_type_id:
        query = query.filter(Carpet.carpet_type_id == carpet_type_id)
    if status:
        query = query.filter(Carpet.status == status)
    
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        x_pos = 20
        y_pos = height - 50
        count = 0
        
        for carpet in query.all():
            if carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
                c.rect(x_pos, y_pos - 100, 180, 100)
                img = ImageReader(carpet.qr_code_path)
                c.drawImage(img, x_pos + 10, y_pos - 85, 50, 50)
                c.setFont("Helvetica", 8)
                c.drawString(x_pos + 70, y_pos - 15, carpet.carpet_id)
                c.drawString(x_pos + 70, y_pos - 28, carpet.carpet_type_ref.name if carpet.carpet_type_ref else '-')
                c.drawString(x_pos + 70, y_pos - 41, f"{carpet.price} ₽")
                
                x_pos += 200
                count += 1
                
                if count % 3 == 0:
                    x_pos = 20
                    y_pos -= 120
                
                if count % 12 == 0:
                    c.showPage()
                    x_pos = 20
                    y_pos = height - 50
        
        c.save()
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name='qr_stickers.pdf')
    except ImportError:
        return "Установите reportlab: pip install reportlab", 500

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
        query = query.filter(
            Carpet.carpet_id.contains(q) | 
            Carpet.craftsman_ref.has(name=q)
        )
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
    
    return render_template('search.html',
        carpets=carpets,
        query=q,
        status=status,
        craftsmen_stats=craftsmen_stats,
        craftsmen=Craftsman.query.all(),
        carpet_types=CarpetType.query.all(),
        selected_craftsman=craftsman_id,
        selected_type=carpet_type_id,
        scan_date_from=scan_date_from,
        scan_date_to=scan_date_to
    )

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
    
    from datetime import timedelta
    scans_stats = []
    for i in range(7):
        date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        count = ScanLog.query.filter(
            ScanLog.scanned_at.like(f'{date}%'), 
            ScanLog.result == 'success'
        ).count()
        scans_stats.append({'date': date, 'count': count})
    
    craftsmen_stats = []
    for c in Craftsman.query.all():
        craft_carpets = [carp for carp in carpets if carp.craftsman_id == c.id]
        if craft_carpets:
            craftsmen_stats.append({
                'name': c.name,
                'count': len(craft_carpets),
                'scanned': len([cr for cr in craft_carpets if cr.status == 'scanned'])
            })
    
    return render_template('stats.html',
        carpets=carpets,
        total_carpets=total_carpets,
        scanned_count=scanned_count,
        sold_count=sold_count,
        created_count=created_count,
        scans_stats=scans_stats,
        craftsmen_stats=craftsmen_stats,
        craftsmen=Craftsman.query.all(),
        carpet_types=CarpetType.query.all(),
        selected_craftsman=craftsman_id,
        selected_type=carpet_type_id,
        selected_status=status,
        scan_date_from=scan_date_from,
        scan_date_to=scan_date_to
    )

# ========== ЗАПУСК ==========

def open_browser(port):
    time.sleep(1.5)
    webbrowser.open(f'http://127.0.0.1:{port}')

if __name__ == '__main__':
    port = find_free_port()
    print("=" * 60)
    print("🧵 КОВРОВЫЙ УЧЁТ - Система управления")
    print("=" * 60)
    print(f"📁 Папка с данными: {DATA_FOLDER}")
    print(f"🗄️ База данных: {DB_PATH}")
    print(f"📁 QR-коды: {QR_FOLDER}")
    print("=" * 60)
    print("✅ QR-коды генерируются автоматически при создании ковра")
    print("✅ Сканирование отмечает ковёр с датой и временем")
    print("❌ Защита от повторного сканирования")
    print("🏷️ Типы ковров можно создавать и редактировать")
    print("🗑️ При удалении швеи удаляются все её ковры (каскадно)")
    print("💰 Цена автоматически подставляется из типа ковра")
    print("📦 Групповое добавление - до 2000 ковров за раз")
    print("=" * 60)
    print(f"🌐 Сервер запущен на порту: {port}")
    print(f"📱 Открой в браузере: http://localhost:{port}")
    print("=" * 60)
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    app.run(host='0.0.0.0', port=port, debug=False)