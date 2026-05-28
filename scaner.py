import sqlite3
import datetime
import tkinter as tk
from tkinter import ttk, messagebox
import os

# Подавляем предупреждение о Tk
os.environ["TK_SILENCE_DEPRECATION"] = "1"

# --- БАЗА ДАННЫХ ---
def init_database():
    conn = sqlite3.connect('carpets.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS craftsmen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS carpets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qr_code TEXT UNIQUE NOT NULL,
                craftsman_id INTEGER,
                date_created TEXT,
                status TEXT DEFAULT 'created',
                FOREIGN KEY (craftsman_id) REFERENCES craftsmen (id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                carpet_id TEXT,
                scanned_at TEXT,
                FOREIGN KEY (carpet_id) REFERENCES carpets (qr_code)
    )''')
    
    c.execute("SELECT COUNT(*) FROM craftsmen")
    if c.fetchone()[0] == 0:
        print("Добавляем тестовые данные...")
        c.execute("INSERT INTO craftsmen (name, phone) VALUES (?, ?)", 
                  ("Анна Иванова", "+7-999-123-45-67"))
        c.execute("INSERT INTO craftsmen (name, phone) VALUES (?, ?)", 
                  ("Мария Петрова", "+7-999-234-56-78"))
        c.execute("INSERT INTO craftsmen (name, phone) VALUES (?, ?)", 
                  ("Елена Сидорова", "+7-999-345-67-89"))
        
        c.execute("INSERT INTO carpets (qr_code, craftsman_id, date_created) VALUES (?, ?, ?)",
                  ("CARPET-001", 1, "2025-03-15"))
        c.execute("INSERT INTO carpets (qr_code, craftsman_id, date_created) VALUES (?, ?, ?)",
                  ("CARPET-002", 2, "2025-03-20"))
        c.execute("INSERT INTO carpets (qr_code, craftsman_id, date_created) VALUES (?, ?, ?)",
                  ("CARPET-003", 1, "2025-03-25"))
    
    conn.commit()
    conn.close()
    print("✅ База данных готова")

def get_craftsmen_list():
    conn = sqlite3.connect('carpets.db')
    c = conn.cursor()
    c.execute("SELECT id, name FROM craftsmen")
    result = c.fetchall()
    conn.close()
    return [f"{row[0]}|{row[1]}" for row in result]

# --- ГЛАВНОЕ ОКНО ---
class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Ковровый учёт - Система управления")
        self.root.geometry("1000x650")
        self.root.configure(bg='#ecf0f1')
        
        init_database()
        self.create_ui()
        self.load_data()
        
    def create_ui(self):
        # Заголовок
        header = tk.Frame(self.root, bg='#2c3e50', height=80)
        header.pack(fill='x')
        header.pack_propagate(False)
        
        tk.Label(header, text="🧵 Ковровый учёт", font=("Arial", 26, "bold"), 
                bg='#2c3e50', fg='white').pack(expand=True)
        
        # Панель кнопок
        btn_frame = tk.Frame(self.root, bg='#ecf0f1', pady=15)
        btn_frame.pack(fill='x', padx=20)
        
        btn_open = tk.Button(btn_frame, text="📂 Открыть БД", command=self.open_db,
                           font=("Arial", 12), bg='#3498db', fg='white',
                           width=18, height=1, relief='raised', bd=2)
        btn_open.pack(side='left', padx=5, expand=True, fill='x')
        
        btn_search = tk.Button(btn_frame, text="🔍 Поиск", command=self.search,
                             font=("Arial", 12), bg='#27ae60', fg='white',
                             width=18, height=1, relief='raised', bd=2)
        btn_search.pack(side='left', padx=5, expand=True, fill='x')
        
        btn_add = tk.Button(btn_frame, text="➕ Добавить ковёр", command=self.add_carpet,
                          font=("Arial", 12), bg='#f39c12', fg='white',
                          width=18, height=1, relief='raised', bd=2)
        btn_add.pack(side='left', padx=5, expand=True, fill='x')
        
        btn_add_craftsman = tk.Button(btn_frame, text="👤 Добавить швею", command=self.add_craftsman,
                                    font=("Arial", 12), bg='#9b59b6', fg='white',
                                    width=18, height=1, relief='raised', bd=2)
        btn_add_craftsman.pack(side='left', padx=5, expand=True, fill='x')
        
        btn_scan = tk.Button(btn_frame, text="📷 Сканировать", command=self.scan,
                           font=("Arial", 12), bg='#e74c3c', fg='white',
                           width=18, height=1, relief='raised', bd=2)
        btn_scan.pack(side='left', padx=5, expand=True, fill='x')
        
        # Таблица
        table_frame = tk.Frame(self.root, bg='#ecf0f1')
        table_frame.pack(fill='both', expand=True, padx=20, pady=10)
        
        columns = ('ID', 'QR-код', 'Швея', 'Дата создания', 'Статус', 'Последнее сканирование')
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=20)
        
        widths = [50, 150, 180, 120, 120, 200]
        for col, w in zip(columns, widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor='center')
        
        vsb = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        
        self.tree.bind('<Double-Button-1>', self.show_carpet_info)
        
        self.status = tk.Label(self.root, text="✅ Готов к работе", font=("Arial", 10), 
                              bg='#ecf0f1', fg='#7f8c8d')
        self.status.pack(pady=5)
        
    def load_data(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        try:
            conn = sqlite3.connect('carpets.db')
            c = conn.cursor()
            
            c.execute('''
                SELECT 
                    c.id,
                    c.qr_code,
                    cm.name,
                    c.date_created,
                    c.status,
                    (SELECT scanned_at FROM scans WHERE carpet_id = c.qr_code 
                     ORDER BY scanned_at DESC LIMIT 1) as last_scan
                FROM carpets c
                JOIN craftsmen cm ON c.craftsman_id = cm.id
                ORDER BY c.id DESC
            ''')
            
            for row in c.fetchall():
                last_scan = row[5] if row[5] else "Не сканирован"
                self.tree.insert('', 'end', values=(row[0], row[1], row[2], row[3], row[4], last_scan))
            
            conn.close()
            self.status.config(text=f"Загружено записей: {len(self.tree.get_children())}")
            
        except Exception as e:
            self.status.config(text=f"Ошибка: {e}")
        
    def open_db(self):
        db_path = os.path.abspath("carpets.db")
        if os.path.exists(db_path):
            self.status.config(text=f"Файл БД: {db_path}")
            messagebox.showinfo("База данных", f"Файл БД находится здесь:\n{db_path}\n\nВы можете открыть его любым SQLite-браузером")
        else:
            messagebox.showerror("Ошибка", "Файл базы данных не найден!")
    
    def search(self):
        win = tk.Toplevel(self.root)
        win.title("Поиск по базе данных")
        win.geometry("650x550")
        win.configure(bg='#ecf0f1')
        
        win.update_idletasks()
        x = (win.winfo_screenwidth() // 2) - (650 // 2)
        y = (win.winfo_screenheight() // 2) - (550 // 2)
        win.geometry(f'650x550+{x}+{y}')
        
        tk.Label(win, text="Поиск ковров", font=("Arial", 18, "bold"), 
                bg='#ecf0f1', fg='#2c3e50').pack(pady=15)
        
        frame = tk.Frame(win, bg='#ecf0f1')
        frame.pack(pady=10)
        
        tk.Label(frame, text="Искать:", font=("Arial", 12), bg='#ecf0f1').pack(side='left', padx=5)
        entry = tk.Entry(frame, width=40, font=("Arial", 11))
        entry.pack(side='left', padx=5)
        
        result_frame = tk.Frame(win, bg='white', relief='sunken', bd=1)
        result_frame.pack(fill='both', expand=True, padx=20, pady=10)
        
        result_text = tk.Text(result_frame, wrap='word', font=("Arial", 11), 
                             bg='white', fg='black')
        scrollbar = tk.Scrollbar(result_frame, command=result_text.yview)
        result_text.configure(yscrollcommand=scrollbar.set)
        
        result_text.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        def do_search():
            term = entry.get().strip()
            if not term:
                messagebox.showwarning("Внимание", "Введите текст для поиска")
                return
            
            result_text.delete('1.0', 'end')
            result_text.insert('1.0', "Результаты поиска:\n\n")
            
            try:
                conn = sqlite3.connect('carpets.db')
                c = conn.cursor()
                
                c.execute('''
                    SELECT c.qr_code, cm.name, c.date_created, c.status,
                           (SELECT COUNT(*) FROM scans WHERE carpet_id = c.qr_code) as scan_count
                    FROM carpets c
                    JOIN craftsmen cm ON c.craftsman_id = cm.id
                    WHERE c.qr_code LIKE ? OR cm.name LIKE ?
                    ORDER BY c.date_created DESC
                ''', (f'%{term}%', f'%{term}%'))
                
                results = c.fetchall()
                conn.close()
                
                if results:
                    result_text.insert('end', f"Найдено {len(results)} записей:\n\n")
                    for i, (qr, name, date, status, scans) in enumerate(results, 1):
                        result_text.insert('end', f"{i}. QR-код: {qr}\n")
                        result_text.insert('end', f"   Швея: {name}\n")
                        result_text.insert('end', f"   Дата: {date}\n")
                        result_text.insert('end', f"   Статус: {status}\n")
                        result_text.insert('end', f"   Сканирований: {scans}\n")
                        result_text.insert('end', "-" * 40 + "\n\n")
                else:
                    result_text.insert('end', "Ничего не найдено\n")
                    
            except Exception as e:
                result_text.insert('end', f"Ошибка: {e}")
        
        tk.Button(win, text="Искать", command=do_search, 
                 bg='#27ae60', fg='white', font=("Arial", 12, "bold"),
                 width=15, height=1).pack(pady=10)
        
        tk.Button(win, text="Закрыть", command=win.destroy,
                 bg='#e74c3c', fg='white', font=("Arial", 11),
                 width=10, height=1).pack(pady=5)
    
    def add_carpet(self):
        win = tk.Toplevel(self.root)
        win.title("Добавить новый ковёр")
        win.geometry("500x500")
        win.configure(bg='#ecf0f1')
        win.grab_set()
        
        win.update_idletasks()
        x = (win.winfo_screenwidth() // 2) - (500 // 2)
        y = (win.winfo_screenheight() // 2) - (500 // 2)
        win.geometry(f'500x500+{x}+{y}')
        
        tk.Label(win, text="Добавление нового ковра", font=("Arial", 18, "bold"), 
                bg='#ecf0f1', fg='#2c3e50').pack(pady=15)
        
        tk.Label(win, text="QR-код:", font=("Arial", 12), bg='#ecf0f1').pack(pady=(15, 0))
        qr_entry = tk.Entry(win, width=40, font=("Arial", 12))
        qr_entry.pack(pady=5)
        
        tk.Label(win, text="Швея:", font=("Arial", 12), bg='#ecf0f1').pack(pady=(10, 0))
        
        craftsmen_list = get_craftsmen_list()
        if not craftsmen_list:
            messagebox.showwarning("Внимание", "Сначала добавьте хотя бы одну швею!")
            win.destroy()
            self.add_craftsman()
            return
        
        craftsman_combo = ttk.Combobox(win, values=craftsmen_list, width=37, font=("Arial", 11))
        craftsman_combo.pack(pady=5)
        
        tk.Label(win, text="Дата создания:", font=("Arial", 12), bg='#ecf0f1').pack(pady=(10, 0))
        date_entry = tk.Entry(win, width=40, font=("Arial", 12))
        date_entry.insert(0, datetime.datetime.now().strftime("%Y-%m-%d"))
        date_entry.pack(pady=5)
        
        tk.Label(win, text="Статус:", font=("Arial", 12), bg='#ecf0f1').pack(pady=(10, 0))
        status_combo = ttk.Combobox(win, values=["created", "in_progress", "completed", "sold"], 
                                    width=37, font=("Arial", 11))
        status_combo.set("created")
        status_combo.pack(pady=5)
        
        def save():
            if not qr_entry.get():
                messagebox.showerror("Ошибка", "Введите QR-код")
                return
            if not craftsman_combo.get():
                messagebox.showerror("Ошибка", "Выберите швею")
                return
            
            craftsman_id = craftsman_combo.get().split("|")[0]
            
            try:
                conn = sqlite3.connect('carpets.db')
                c = conn.cursor()
                c.execute('''INSERT INTO carpets (qr_code, craftsman_id, date_created, status) 
                           VALUES (?, ?, ?, ?)''',
                         (qr_entry.get(), craftsman_id, date_entry.get(), status_combo.get()))
                conn.commit()
                conn.close()
                
                messagebox.showinfo("Успех", f"Ковёр {qr_entry.get()} добавлен!")
                win.destroy()
                self.load_data()
                self.status.config(text=f"Добавлен ковёр: {qr_entry.get()}")
                
            except sqlite3.IntegrityError:
                messagebox.showerror("Ошибка", "Ковёр с таким QR-кодом уже существует!")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось добавить:\n{e}")
        
        btn_frame = tk.Frame(win, bg='#ecf0f1')
        btn_frame.pack(pady=25)
        
        tk.Button(btn_frame, text="Сохранить", command=save,
                 bg='#27ae60', fg='white', font=("Arial", 12, "bold"),
                 width=12, height=1).pack(side='left', padx=10)
        
        tk.Button(btn_frame, text="Отмена", command=win.destroy,
                 bg='#e74c3c', fg='white', font=("Arial", 12),
                 width=12, height=1).pack(side='left', padx=10)
    
    def add_craftsman(self):
        win = tk.Toplevel(self.root)
        win.title("Добавить швею")
        win.geometry("400x300")
        win.configure(bg='#ecf0f1')
        win.grab_set()
        
        win.update_idletasks()
        x = (win.winfo_screenwidth() // 2) - (400 // 2)
        y = (win.winfo_screenheight() // 2) - (300 // 2)
        win.geometry(f'400x300+{x}+{y}')
        
        tk.Label(win, text="Добавление швеи", font=("Arial", 18, "bold"), 
                bg='#ecf0f1', fg='#2c3e50').pack(pady=15)
        
        tk.Label(win, text="ФИО:", font=("Arial", 12), bg='#ecf0f1').pack(pady=(15, 0))
        name_entry = tk.Entry(win, width=35, font=("Arial", 12))
        name_entry.pack(pady=5)
        
        tk.Label(win, text="Телефон:", font=("Arial", 12), bg='#ecf0f1').pack(pady=(10, 0))
        phone_entry = tk.Entry(win, width=35, font=("Arial", 12))
        phone_entry.pack(pady=5)
        
        def save():
            if not name_entry.get():
                messagebox.showerror("Ошибка", "Введите имя швеи")
                return
            
            try:
                conn = sqlite3.connect('carpets.db')
                c = conn.cursor()
                c.execute("INSERT INTO craftsmen (name, phone) VALUES (?, ?)",
                         (name_entry.get(), phone_entry.get()))
                conn.commit()
                conn.close()
                
                messagebox.showinfo("Успех", f"Швея {name_entry.get()} добавлена!")
                win.destroy()
                self.status.config(text=f"Добавлена швея: {name_entry.get()}")
                
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось добавить:\n{e}")
        
        btn_frame = tk.Frame(win, bg='#ecf0f1')
        btn_frame.pack(pady=25)
        
        tk.Button(btn_frame, text="Сохранить", command=save,
                 bg='#27ae60', fg='white', font=("Arial", 12, "bold"),
                 width=12, height=1).pack(side='left', padx=10)
        
        tk.Button(btn_frame, text="Отмена", command=win.destroy,
                 bg='#e74c3c', fg='white', font=("Arial", 12),
                 width=12, height=1).pack(side='left', padx=10)
    
    def show_carpet_info(self, event):
        selection = self.tree.selection()
        if not selection:
            return
        
        item = self.tree.item(selection[0])
        values = item['values']
        
        if values:
            info = f"""ИНФОРМАЦИЯ О КОВРЕ
{'='*40}

ID: {values[0]}
QR-код: {values[1]}
Швея: {values[2]}
Дата создания: {values[3]}
Статус: {values[4]}
Последнее сканирование: {values[5]}
"""
            messagebox.showinfo("Информация о ковре", info)
    
    def scan(self):
        win = tk.Toplevel(self.root)
        win.title("Сканирование QR-кода")
        win.geometry("500x400")
        win.configure(bg='#ecf0f1')
        
        win.update_idletasks()
        x = (win.winfo_screenwidth() // 2) - (500 // 2)
        y = (win.winfo_screenheight() // 2) - (400 // 2)
        win.geometry(f'500x400+{x}+{y}')
        
        main_frame = tk.Frame(win, bg='#ecf0f1')
        main_frame.pack(fill='both', expand=True)
        
        tk.Label(main_frame, text="Сканирование QR-кода", 
                font=("Arial", 22, "bold"), bg='#ecf0f1', fg='#2c3e50').pack(pady=40)
        
        tk.Label(main_frame, text="Подготовка модуля сканирования...", 
                font=("Arial", 14), bg='#ecf0f1', fg='#7f8c8d').pack(pady=10)
        
        info_frame = tk.Frame(main_frame, bg='#3498db', relief='raised', bd=2)
        info_frame.pack(pady=30, padx=50, fill='x')
        
        tk.Label(info_frame, text="Информация", 
                font=("Arial", 14, "bold"), bg='#3498db', fg='white').pack(pady=10)
        tk.Label(info_frame, text="Для сканирования QR-кодов необходимо\nподключить USB-сканер.\n\nФункция будет добавлена в следующей версии.", 
                font=("Arial", 11), bg='#3498db', fg='white', justify='center').pack(pady=10)
        
        tk.Button(main_frame, text="Закрыть", command=win.destroy,
                 bg='#e74c3c', fg='white', font=("Arial", 12, "bold"),
                 width=15, height=1).pack(pady=20)
        
        self.status.config(text="Открыто окно сканирования (демо-режим)")
    
    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    print("Запуск приложения...")
    app = App()
    app.run()