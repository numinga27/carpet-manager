from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import sys
import qrcode
import webbrowser
import threading
import time

# Определяем пути
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(__file__)

template_folder = os.path.join(base_path, 'templates')
app = Flask(__name__, template_folder=template_folder)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///carpets.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key-here'
db = SQLAlchemy(app)

# Папка для QR-кодов
QR_FOLDER = 'qr_codes'
if not os.path.exists(QR_FOLDER):
    os.makedirs(QR_FOLDER)

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
    """Швеи"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    carpets = db.relationship('Carpet', backref='craftsman_ref', lazy=True)

class Carpet(db.Model):
    """Ковры"""
    id = db.Column(db.Integer, primary_key=True)
    carpet_id = db.Column(db.String(50), unique=True, nullable=False)
    carpet_type_id = db.Column(db.Integer, db.ForeignKey('carpet_type.id'), nullable=False)
    craftsman_id = db.Column(db.Integer, db.ForeignKey('craftsman.id'), nullable=False)
    price = db.Column(db.Float, nullable=False)
    size = db.Column(db.String(50))
    material = db.Column(db.String(100))
    color = db.Column(db.String(50))
    date_created = db.Column(db.String(20), nullable=False)
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
    qr_info = f"КОВЁР #{carpet_id}\nТип: {carpet_data['carpet_type_name']}\nШвея: {carpet_data['craftsman_name']}\nЦена: {carpet_data['price']} руб.\nДата: {carpet_data['date_created']}"
    
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

def get_carpet_type_dict():
    """Возвращает словарь типов ковров"""
    types = CarpetType.query.all()
    return {t.id: {'name': t.name, 'base_price': t.base_price} for t in types}

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
            ("CARPET-0001", 1, 1, 15000, "2025-03-15", "created"),
            ("CARPET-0002", 2, 2, 12000, "2025-03-20", "scanned"),
            ("CARPET-0003", 3, 1, 8000, "2025-03-25", "created")
        ]
        for qr, type_id, cm_id, price, date, status in test_data:
            carpet = Carpet(
                carpet_id=qr, 
                carpet_type_id=type_id, 
                craftsman_id=cm_id, 
                price=price, 
                date_created=date, 
                status=status
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
                'price': carpet.price,
                'date_created': carpet.date_created
            }
            carpet.qr_code_path = generate_qr_code(carpet.carpet_id, carpet_data)
        db.session.commit()

# ========== МАРШРУТЫ ==========

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html', 
                         carpets=Carpet.query.all(),
                         craftsmen=Craftsman.query.all(),
                         carpet_types=CarpetType.query.all())

# ========== УПРАВЛЕНИЕ КОВРАМИ ==========

@app.route('/add_carpet', methods=['POST'])
def add_carpet():
    """Добавление нового ковра"""
    carpet_id = generate_next_id()
    
    carpet = Carpet(
        carpet_id=carpet_id,
        carpet_type_id=request.form['carpet_type_id'],
        craftsman_id=request.form['craftsman_id'],
        price=float(request.form['price']),
        size=request.form.get('size', ''),
        material=request.form.get('material', ''),
        color=request.form.get('color', ''),
        date_created=request.form['date_created'],
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
        'price': carpet.price,
        'date_created': carpet.date_created
    }
    carpet.qr_code_path = generate_qr_code(carpet_id, carpet_data)
    db.session.commit()
    
    flash(f'Ковёр {carpet_id} успешно добавлен!', 'success')
    return redirect(url_for('index'))

@app.route('/edit_carpet/<int:id>', methods=['GET', 'POST'])
def edit_carpet(id):
    """Редактирование ковра"""
    carpet = Carpet.query.get_or_404(id)
    
    if request.method == 'POST':
        carpet.carpet_type_id = request.form['carpet_type_id']
        carpet.craftsman_id = request.form['craftsman_id']
        carpet.price = float(request.form['price'])
        carpet.size = request.form.get('size', '')
        carpet.material = request.form.get('material', '')
        carpet.color = request.form.get('color', '')
        carpet.date_created = request.form['date_created']
        carpet.notes = request.form.get('notes', '')
        db.session.commit()
        
        carpet_type = CarpetType.query.get(carpet.carpet_type_id)
        craftsman = Craftsman.query.get(carpet.craftsman_id)
        carpet_data = {
            'carpet_type_name': carpet_type.name,
            'craftsman_name': craftsman.name,
            'price': carpet.price,
            'date_created': carpet.date_created
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
    """Удаление ковра"""
    carpet = Carpet.query.get_or_404(id)
    if carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
        os.remove(carpet.qr_code_path)
    db.session.delete(carpet)
    db.session.commit()
    flash(f'Ковёр {carpet.carpet_id} удалён', 'info')
    return redirect(url_for('index'))

# ========== УПРАВЛЕНИЕ ШВЕЯМИ ==========

@app.route('/add_craftsman', methods=['POST'])
def add_craftsman():
    """Добавление швеи"""
    db.session.add(Craftsman(
        name=request.form['name'], 
        phone=request.form.get('phone', '')
    ))
    db.session.commit()
    flash('Швея успешно добавлена!', 'success')
    return redirect(url_for('index'))

@app.route('/edit_craftsman/<int:id>', methods=['GET', 'POST'])
def edit_craftsman(id):
    """Редактирование швеи"""
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
    """Удаление швеи"""
    craftsman = Craftsman.query.get_or_404(id)
    if len(craftsman.carpets) > 0:
        flash('Нельзя удалить швею с коврами!', 'error')
        return redirect(url_for('index'))
    db.session.delete(craftsman)
    db.session.commit()
    flash('Швея удалена', 'info')
    return redirect(url_for('index'))

# ========== УПРАВЛЕНИЕ ТИПАМИ КОВРОВ ==========

@app.route('/types')
def types_list():
    """Список типов ковров"""
    types = CarpetType.query.all()
    return render_template('types.html', types=types)

@app.route('/add_type', methods=['POST'])
def add_type():
    """Добавление нового типа ковра"""
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

@app.route('/edit_type/<int:id>', methods=['POST'])
def edit_type(id):
    """Редактирование типа ковра"""
    carpet_type = CarpetType.query.get_or_404(id)
    carpet_type.name = request.form['name']
    carpet_type.base_price = float(request.form['base_price'])
    carpet_type.description = request.form.get('description', '')
    db.session.commit()
    flash(f'Тип "{carpet_type.name}" обновлён!', 'success')
    return redirect(url_for('types_list'))

@app.route('/delete_type/<int:id>')
def delete_type(id):
    """Удаление типа ковра"""
    carpet_type = CarpetType.query.get_or_404(id)
    if len(carpet_type.carpets) > 0:
        flash('Нельзя удалить тип, у которого есть ковры!', 'error')
        return redirect(url_for('types_list'))
    db.session.delete(carpet_type)
    db.session.commit()
    flash('Тип удалён', 'info')
    return redirect(url_for('types_list'))

# ========== СКАНИРОВАНИЕ QR ==========

@app.route('/scan_qr', methods=['POST'])
def scan_qr():
    """Сканирование QR-кода с защитой от повторного сканирования"""
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
            'message': f'⚠️ Этот ковёр уже был отсканирован {carpet.scanned_at}! Повторное сканирование запрещено.'
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
        'date_created': carpet.date_created,
        'scanned_at': carpet.scanned_at,
        'message': f'✅ Ковёр {carpet.carpet_id} успешно отсканирован и готов к продаже!'
    })

@app.route('/mark_sold/<int:id>', methods=['POST'])
def mark_sold(id):
    """Отметить ковёр как проданный"""
    carpet = Carpet.query.get_or_404(id)
    if carpet.status == 'scanned':
        carpet.status = 'sold'
        db.session.commit()
        return jsonify({'success': True, 'message': 'Ковёр отмечен как проданный'})
    return jsonify({'success': False, 'message': 'Ковёр ещё не отсканирован'})

# ========== QR-КОДЫ ==========

@app.route('/get_qr/<carpet_id>')
def get_qr(carpet_id):
    """Получить QR-код"""
    carpet = Carpet.query.filter_by(carpet_id=carpet_id).first()
    if carpet and carpet.qr_code_path and os.path.exists(carpet.qr_code_path):
        return send_file(carpet.qr_code_path, mimetype='image/png')
    return "QR не найден", 404

@app.route('/print_qr/<carpet_id>')
def print_qr(carpet_id):
    """Страница для печати QR-кода"""
    carpet = Carpet.query.filter_by(carpet_id=carpet_id).first()
    if carpet:
        return render_template('print_qr.html', carpet=carpet, carpet_types=CarpetType.query.all())
    return "Ковёр не найден", 404

# ========== ПОИСК И СТАТИСТИКА ==========

@app.route('/search')
def search():
    """Поиск ковров"""
    q = request.args.get('q', '')
    status = request.args.get('status', '')
    
    query = Carpet.query
    if q:
        query = query.filter(
            Carpet.carpet_id.contains(q) | 
            Carpet.craftsman_ref.has(name=q)
        )
    if status:
        query = query.filter(Carpet.status == status)
    
    carpets = query.all()
    return render_template('search.html', 
                         carpets=carpets, 
                         query=q, 
                         status=status,
                         carpet_types=CarpetType.query.all())

@app.route('/stats')
def stats():
    """Статистика"""
    total_carpets = Carpet.query.count()
    scanned_count = Carpet.query.filter_by(status='scanned').count()
    sold_count = Carpet.query.filter_by(status='sold').count()
    created_count = Carpet.query.filter_by(status='created').count()
    
    from datetime import timedelta
    scans_stats = []
    for i in range(7):
        date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        count = ScanLog.query.filter(
            ScanLog.scanned_at.like(f'{date}%'), 
            ScanLog.result == 'success'
        ).count()
        scans_stats.append({'date': date, 'count': count})
    
    return render_template('stats.html',
        total_carpets=total_carpets,
        scanned_count=scanned_count,
        sold_count=sold_count,
        created_count=created_count,
        scans_stats=scans_stats,
        craftsmen_stats=[{
            'name': c.name, 
            'count': len(c.carpets), 
            'scanned': Carpet.query.filter_by(craftsman_id=c.id, status='scanned').count()
        } for c in Craftsman.query.all()],
        carpet_types=CarpetType.query.all()
    )

# ========== ЗАПУСК ==========

def open_browser():
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:5000')

if __name__ == '__main__':
    print("=" * 60)
    print("🧵 КОВРОВЫЙ УЧЁТ - Система управления")
    print("=" * 60)
    print("✅ QR-коды генерируются автоматически при создании ковра")
    print("✅ Сканирование отмечает ковёр как готовый к продаже")
    print("❌ Защита от повторного сканирования")
    print("🏷️ Типы ковров можно создавать и редактировать")
    print("=" * 60)
    print("🌐 Открывается браузер...")
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host='127.0.0.1', port=5000, debug=False)