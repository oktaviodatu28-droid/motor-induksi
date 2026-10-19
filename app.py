import os
import sqlite3
from flask import Flask, render_template_string, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = 'kunci_rahasia_proyek_teknik_listrik'

DB_NAME = 'motor_diagnosis.db'

# ==========================================
# 1. DATABASE SETUP & INITIALIZATION
# ==========================================
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS motor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            motor_code TEXT NOT NULL,
            power_kw REAL,
            voltage_v REAL,
            current_a REAL,
            frequency_hz REAL,
            poles INTEGER,
            rpm_nominal REAL,
            v_l1 REAL,
            v_l2 REAL,
            v_l3 REAL,
            i_l1 REAL,
            i_l2 REAL,
            i_l3 REAL,
            temperature REAL,
            load_condition TEXT,
            cooling_condition TEXT,
            noise_condition TEXT,
            vibration_condition TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS symptoms (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fault_types (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS diagnosis_rules (
            id TEXT PRIMARY KEY,
            fault_id TEXT,
            condition_desc TEXT,
            FOREIGN KEY(fault_id) REFERENCES fault_types(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS diagnosis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            motor_id INTEGER,
            diagnosis_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            summary_result TEXT,
            FOREIGN KEY(motor_id) REFERENCES motor_data(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS diagnosis_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            history_id INTEGER,
            fault_id TEXT,
            evidence_text TEXT,
            rule_code TEXT,
            FOREIGN KEY(history_id) REFERENCES diagnosis_history(id),
            FOREIGN KEY(fault_id) REFERENCES fault_types(id)
        )
    ''')

    # Seed Initial Data
    symptoms_data = [
        ('S1', 'Motor tidak dapat beroperasi', 'Motor gagal melakukan start atau berhenti total.'),
        ('S2', 'Motor sulit melakukan starting', 'Memerlukan waktu lama untuk mencapai kecepatan nominal atau gagal start tanpa beban.'),
        ('S3', 'Arus tidak normal', 'Arus operasi melebihi nilai nominal atau tidak seimbang antar fasa.'),
        ('S4', 'Tegangan tidak seimbang', 'Tegangan antar fasa catu daya memiliki selisih yang signifikan.'),
        ('S5', 'Motor mengalami panas berlebih', 'Suhu bodi atau belitan motor melebihi batas kelas isolasi normal.'),
        ('S6', 'Suara bantalan kasar', 'Terdengar bunyi mendengung tidak normal atau ketukan dari area bearing.'),
        ('S7', 'Getaran berlebihan', 'Vibrasi mekanis tinggi terdeteksi pada bodi atau poros motor.'),
        ('S8', 'Kecepatan turun ketika berbeban', 'Slip meningkat drastis atau putaran drop di bawah spesifikasi.'),
        ('S9', 'Pendinginan atau ventilasi terganggu', 'Kipas rusak, sirip kotor, atau aliran udara terhambat.'),
        ('S10', 'Motor mengalami trip proteksi', 'Thermal overload relay atau MCCB trip otomatis.'),
        ('S11', 'Indikasi gangguan isolasi', 'Hasil tes Megger menunjukkan tahanan isolasi rendah.')
    ]
    cursor.executemany('INSERT OR IGNORE INTO symptoms (id, name, description) VALUES (?, ?, ?)', symptoms_data)

    faults_data = [
        ('F1', 'Kehilangan salah satu fasa', 'Putusnya salah satu saluran fasa catu daya (Single phasing).'),
        ('F2', 'Ketidakseimbangan tegangan', 'Deviasi tegangan antar fasa melampaui batas toleransi operasional.'),
        ('F3', 'Beban lebih', 'Motor beroperasi melampaui kapasitas daya/arus nominal (Overload).'),
        ('F4', 'Gangguan bantalan', 'Kerusakan fisik atau kurang pelumasan pada bearing.'),
        ('F5', 'Gangguan pendinginan', 'Sistem ventilasi atau pembuangan panas motor tidak optimal.'),
        ('F6', 'Gangguan isolasi atau hubung singkat belitan', 'Penurunan tahanan isolasi atau korsleting antar lilitan stator.'),
        ('F7', 'Dugaan gangguan rotor', 'Kerusakan batang rotor sangkar (broken rotor bar) atau eksentrisitas.'),
        ('F8', 'Gangguan mekanis', 'Misalignment poros, ketidakseimbangan mekanis, atau kopling longgar.')
    ]
    cursor.executemany('INSERT OR IGNORE INTO fault_types (id, name, description) VALUES (?, ?, ?)', faults_data)

    rules_data = [
        ('R1', 'F1', 'Arus salah satu fasa bernilai 0 atau sangat rendah, disertai trip proteksi atau motor berdengung.'),
        ('R2', 'F2', 'Ketidakseimbangan tegangan suplai melebihi 2% atau terdeteksi tegangan tidak seimbang.'),
        ('R3', 'F3', 'Arus terukur melebihi arus nominal (I > I_nom) dan/atau motor panas berlebih saat berbeban.'),
        ('R4', 'F4', 'Suara bantalan kasar dan getaran berlebihan pada area bearing.'),
        ('R5', 'F5', 'Suhu operasi tinggi dengan kondisi pendinginan atau ventilasi terganggu.'),
        ('R6', 'F6', 'Indikasi gangguan isolasi terdeteksi atau arus tidak seimbang parah tanpa ketidakseimbangan tegangan ekstrem.'),
        ('R7', 'F7', 'Kecepatan turun signifikan saat berbeban disertai getaran dan fluktuasi arus periodik.'),
        ('R8', 'F8', 'Getaran berlebihan tanpa adanya indikasi elektrik yang dominan (suara/getaran mekanis poros).')
    ]
    cursor.executemany('INSERT OR IGNORE INTO diagnosis_rules (id, fault_id, condition_desc) VALUES (?, ?, ?)', rules_data)

    conn.commit()
    conn.close()

# ==========================================
# 2. CALCULATIONS MODULE
# ==========================================
def calculate_synchronous_speed(frequency, poles):
    if not frequency or not poles or poles <= 0:
        return None
    return (120 * frequency) / poles

def calculate_slip(ns, nr):
    if ns is None or nr is None or ns <= 0:
        return None
    if ns < nr:
        return 0.0
    return ((ns - nr) / ns) * 100.0

def calculate_average_voltage(v1, v2, v3):
    voltages = [v for v in [v1, v2, v3] if v is not None]
    if not voltages:
        return None
    return sum(voltages) / len(voltages)

def calculate_voltage_unbalance(v1, v2, v3):
    voltages = [v for v in [v1, v2, v3] if v is not None]
    if len(voltages) < 3:
        return 0.0
    v_avg = calculate_average_voltage(v1, v2, v3)
    if not v_avg or v_avg == 0:
        return 0.0
    max_deviation = max(abs(v - v_avg) for v in voltages)
    return (max_deviation / v_avg) * 100.0

def calculate_current_ratio(i1, i2, i3, i_nominal):
    currents = [c for c in [i1, i2, i3] if c is not None]
    if not currents or not i_nominal or i_nominal <= 0:
        return None
    i_avg = sum(currents) / len(currents)
    return (i_avg / i_nominal) * 100.0

# ==========================================
# 3. DIAGNOSIS ENGINE (FORWARD CHAINING)
# ==========================================
def run_forward_chaining(motor_data, selected_symptoms):
    inferred_faults = []
    missing_data = []

    f = motor_data.get('frequency_hz')
    p = motor_data.get('poles')
    nr = motor_data.get('rpm_nominal')
    i_nom = motor_data.get('current_a')
    
    v1 = motor_data.get('v_l1')
    v2 = motor_data.get('v_l2')
    v3 = motor_data.get('v_l3')
    
    i1 = motor_data.get('i_l1')
    i2 = motor_data.get('i_l2')
    i3 = motor_data.get('i_l3')
    
    temp = motor_data.get('temperature')
    load = motor_data.get('load_condition')
    cooling = motor_data.get('cooling_condition')
    noise = motor_data.get('noise_condition')
    vibration = motor_data.get('vibration_condition')

    if f is None or p is None:
        missing_data.append("Frekuensi dan Jumlah Kutub (diperlukan untuk kecepatan sinkron).")
    if nr is None:
        missing_data.append("Kecepatan nominal / rotor rpm (diperlukan untuk perhitungan slip).")

    v_unbalance = calculate_voltage_unbalance(v1, v2, v3)
    
    currents = [c for c in [i1, i2, i3] if c is not None]
    current_imbalance = False
    if len(currents) == 3:
        i_avg = sum(currents) / 3
        if any(abs(c - i_avg) > 0.15 * i_avg for c in currents):
            current_imbalance = True

    if 'S1' in selected_symptoms or 'S10' in selected_symptoms:
        zero_current = any(c is not None and c == 0.0 for c in [i1, i2, i3])
        if zero_current or 'S1' in selected_symptoms:
            inferred_faults.append({
                'fault_id': 'F1',
                'fault_name': 'Kehilangan salah satu fasa',
                'rule_code': 'R1',
                'evidence': 'Terdeteksi arus fasa bernilai nol atau gejala motor tidak dapat beroperasi / trip proteksi.'
            })

    if 'S4' in selected_symptoms or v_unbalance > 2.0:
        inferred_faults.append({
            'fault_id': 'F2',
            'fault_name': 'Ketidakseimbangan tegangan',
            'rule_code': 'R2',
            'evidence': f'Ketidakseimbangan tegangan terukur sebesar {v_unbalance:.2f}% (melebihi ambang batas 2%) atau gejala tegangan tidak seimbang dipilih.'
        })

    if 'S3' in selected_symptoms or 'S5' in selected_symptoms:
        high_current = False
        if i_nom and currents:
            if max(currents) > i_nom:
                high_current = True
        if high_current or load == 'Berat' or 'S3' in selected_symptoms:
            inferred_faults.append({
                'fault_id': 'F3',
                'fault_name': 'Beban lebih',
                'rule_code': 'R3',
                'evidence': 'Arus operasi melebihi arus nominal atau kondisi beban dilaporkan berat / panas berlebih.'
            })

    if 'S6' in selected_symptoms or 'S7' in selected_symptoms:
        if noise == 'Kasar' or vibration == 'Tinggi' or 'S6' in selected_symptoms:
            inferred_faults.append({
                'fault_id': 'F4',
                'fault_name': 'Gangguan bantalan',
                'rule_code': 'R4',
                'evidence': 'Dilaporkan suara bantalan kasar dan/atau getaran berlebihan pada area bearing.'
            })

    if 'S9' in selected_symptoms or 'S5' in selected_symptoms:
        if cooling == 'Buruk' or temp and temp > 75.0:
            inferred_faults.append({
                'fault_id': 'F5',
                'fault_name': 'Gangguan pendinginan',
                'rule_code': 'R5',
                'evidence': 'Suhu operasi tinggi disertai sistem pendinginan atau ventilasi terganggu/buruk.'
            })

    if 'S11' in selected_symptoms or (current_imbalance and v_unbalance < 1.5):
        inferred_faults.append({
            'fault_id': 'F6',
            'fault_name': 'Gangguan isolasi atau hubung singkat belitan',
            'rule_code': 'R6',
            'evidence': 'Terdapat indikasi hasil pemeriksaan isolasi (Megger) rendah atau ketidakseimbangan arus tanpa ketidakseimbangan tegangan.'
        })

    if 'S8' in selected_symptoms or 'S2' in selected_symptoms:
        ns = calculate_synchronous_speed(f, p)
        slip_val = calculate_slip(ns, nr)
        if (slip_val and slip_val > 8.0) or 'S8' in selected_symptoms:
            inferred_faults.append({
                'fault_id': 'F7',
                'fault_name': 'Dugaan gangguan rotor',
                'rule_code': 'R7',
                'evidence': f'Slip bernilai {slip_val:.2f}% (cukup tinggi) atau kecepatan turun drastis saat berbeban.'
            })

    if 'S7' in selected_symptoms and 'S6' not in selected_symptoms:
        inferred_faults.append({
            'fault_id': 'F8',
            'fault_name': 'Gangguan mekanis seperti ketidakselarasan poros atau ketidakseimbangan rotor',
            'rule_code': 'R8',
            'evidence': 'Terdeteksi getaran berlebihan tanpa dominasi suara bantalan kasar.'
        })

    return inferred_faults, missing_data

# ==========================================
# 4. HTML TEMPLATES (EMBEDDED)
# ==========================================
CSS_STYLE = """
:root { --primary: #1e293b; --accent: #2563eb; --bg-light: #f8fafc; --text-dark: #334155; --border: #cbd5e1; }
* { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
body { background: var(--bg-light); color: var(--text-dark); }
.app-container { display: flex; min-height: 100vh; }
.sidebar { width: 260px; background: var(--primary); color: #fff; padding: 20px; }
.brand h2 { font-size: 1.2rem; margin-bottom: 5px; }
.brand p { font-size: 0.8rem; color: #94a3b8; }
.nav-menu { margin-top: 30px; display: flex; flex-direction: column; gap: 10px; }
.nav-item { color: #cbd5e1; text-decoration: none; padding: 10px 15px; border-radius: 6px; transition: 0.2s; }
.nav-item:hover, .nav-item.active { background: var(--accent); color: #fff; }
.main-content { flex: 1; display: flex; flex-direction: column; }
.topbar { background: #fff; padding: 15px 30px; border-bottom: 1px solid var(--border); }
.content-body { padding: 30px; flex: 1; }
.card { background: #fff; padding: 20px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 20px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; }
.stat-card { background: #fff; padding: 20px; border-radius: 8px; border: 1px solid var(--border); border-left: 5px solid var(--accent); }
.stat-number { font-size: 1.8rem; font-weight: bold; margin-top: 5px; color: var(--accent); }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.full-width { grid-column: span 2; }
.form-group { margin-bottom: 15px; }
.form-group label { display: block; margin-bottom: 5px; font-weight: 600; font-size: 0.9rem; }
.form-group input, .form-group select { width: 100%; padding: 8px 12px; border: 1px solid var(--border); border-radius: 4px; }
.form-row { display: flex; gap: 10px; }
.checkbox-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 10px; margin-top: 10px; }
.checkbox-item { display: flex; align-items: flex-start; gap: 10px; background: #f1f5f9; padding: 10px; border-radius: 6px; cursor: pointer; }
.btn { background: var(--accent); color: #fff; padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; font-size: 0.9rem; }
.btn-secondary { background: #475569; }
.btn-sm { padding: 4px 8px; font-size: 0.8rem; }
.btn:hover { opacity: 0.9; }
.data-table { width: 100%; border-collapse: collapse; margin-top: 10px; }
.data-table th, .data-table td { padding: 10px; text-align: left; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
.data-table th { background: #f1f5f9; }
.alert { padding: 10px 15px; border-radius: 4px; margin-bottom: 20px; }
.alert-danger { background: #fee2e2; color: #991b1b; }
.fault-box { background: #fff5f5; border-left: 4px solid #ef4444; padding: 15px; margin-bottom: 10px; border-radius: 4px; }
.warning-box { background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; border-radius: 4px; }
.safety-card { border-left: 5px solid #059669; }
.search-form { display: flex; gap: 10px; margin-top: 15px; }
.search-form input { max-width: 300px; padding: 8px; border: 1px solid var(--border); border-radius: 4px; }
"""

BASE_TEMPLATE = f"""
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sistem Diagnosis Motor Induksi</title>
    <style>{CSS_STYLE}</style>
</head>
<body>
    <div class="app-container">
        <aside class="sidebar">
            <div class="brand">
                <h2>⚡ DIAGNOSIS MOTOR</h2>
                <p>Teknik Listrik - Politeknik</p>
            </div>
            <nav class="nav-menu">
                <a href="{{{{ url_for('dashboard') }}}}" class="nav-item">Dashboard</a>
                <a href="{{{{ url_for('input_motor') }}}}" class="nav-item">Input Data & Diagnosis</a>
                <a href="{{{{ url_for('history_list') }}}}" class="nav-item">Riwayat Diagnosis</a>
            </nav>
        </aside>
        <main class="main-content">
            <header class="topbar">
                <h3>Sistem Pakar Forward Chaining Motor Induksi Tiga Fasa</h3>
            </header>
            <div class="content-body">
                {% with messages = get_flashed_messages(with_categories=true) %}
                    {% if messages %}
                        {% for category, message in messages %}
                            <div class="alert alert-{{{{ category }}}}">{{{{ message }}}}</div>
                        {% endfor %}
                    {% endif %}
                {% endwith %}
                {% block content %}{% endblock %}
            </div>
        </main>
    </div>
</body>
</html>
"""

DASHBOARD_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<h2>Dashboard Utama</h2>
<p class="subtitle">Ringkasan operasional sistem diagnosis gangguan motor induksi.</p>

<div class="stats-grid">
    <div class="stat-card">
        <h4>Total Pemeriksaan</h4>
        <p class="stat-number">{{ total_checks }}</p>
    </div>
    <div class="stat-card">
        <h4>Kategori Gangguan Teridentifikasi</h4>
        <p class="stat-number">{{ total_faults_found }}</p>
    </div>
</div>

<div class="card mt-4" style="margin-top: 20px;">
    <h3>Riwayat Diagnosis Terbaru</h3>
    {% if recent_history %}
    <table class="data-table">
        <thead>
            <tr>
                <th>ID</th>
                <th>Kode Motor</th>
                <th>Waktu Pemeriksaan</th>
                <th>Ringkasan Hasil</th>
                <th>Aksi</th>
            </tr>
        </thead>
        <tbody>
            {% for h in recent_history %}
            <tr>
                <td>{{ h.id }}</td>
                <td><strong>{{ h.motor_code }}</strong></td>
                <td>{{ h.diagnosis_time }}</td>
                <td>{{ h.summary_result }}</td>
                <td><a href="{{ url_for('diagnosis_result', history_id=h.id) }}" class="btn btn-sm">Detail</a></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p class="text-muted" style="margin-top: 10px;">Belum ada data pemeriksaan. Silakan lakukan diagnosis baru melalui menu Input Data.</p>
    {% endif %}
</div>
{% endblock %}
"""

MOTOR_FORM_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<h2>Formulir Input Data Motor & Pemilihan Gejala</h2>
<p class="subtitle">Masukkan parameter teknis motor dan centang gejala yang diamati di lapangan.</p>

<form action="{{ url_for('input_motor') }}" method="POST" class="form-grid" id="motorForm" style="margin-top: 20px;">
    <div class="card">
        <h3>1. Spesifikasi Nameplate Motor</h3>
        <div class="form-group" style="margin-top: 10px;">
            <label>Nama / Kode Motor *</label>
            <input type="text" name="motor_code" required placeholder="Contoh: MOT-01">
        </div>
        <div class="form-row">
            <div class="form-group">
                <label>Daya Nominal (kW)</label>
                <input type="number" step="0.1" name="power_kw" placeholder="Contoh: 7.5">
            </div>
            <div class="form-group">
                <label>Tegangan Nominal (V)</label>
                <input type="number" step="0.1" name="voltage_v" placeholder="Contoh: 380">
            </div>
        </div>
        <div class="form-row">
            <div class="form-group">
                <label>Arus Nominal (A)</label>
                <input type="number" step="0.1" name="current_a" placeholder="Contoh: 15.2">
            </div>
            <div class="form-group">
                <label>Frekuensi (Hz)</label>
                <input type="number" step="0.1" name="frequency_hz" value="50">
            </div>
        </div>
        <div class="form-row">
            <div class="form-group">
                <label>Jumlah Kutub (Poles)</label>
                <input type="number" name="poles" value="4">
            </div>
            <div class="form-group">
                <label>Kecepatan Nominal (rpm)</label>
                <input type="number" step="1" name="rpm_nominal" placeholder="Contoh: 1450">
            </div>
        </div>
    </div>

    <div class="card">
        <h3>2. Pengukuran Parameter Operasi</h3>
        <div class="form-group" style="margin-top: 10px;">
            <label>Tegangan Terukur (V)</label>
            <div class="form-row">
                <input type="number" step="0.1" name="v_l1" placeholder="L1">
                <input type="number" step="0.1" name="v_l2" placeholder="L2">
                <input type="number" step="0.1" name="v_l3" placeholder="L3">
            </div>
        </div>
        <div class="form-group">
            <label>Arus Terukur (A)</label>
            <div class="form-row">
                <input type="number" step="0.1" name="i_l1" placeholder="L1">
                <input type="number" step="0.1" name="i_l2" placeholder="L2">
                <input type="number" step="0.1" name="i_l3" placeholder="L3">
            </div>
        </div>
        <div class="form-row">
            <div class="form-group">
                <label>Suhu Operasi (°C)</label>
                <input type="number" step="0.1" name="temperature" placeholder="Contoh: 65">
            </div>
            <div class="form-group">
                <label>Kondisi Beban</label>
                <select name="load_condition">
                    <option value="">-- Pilih --</option>
                    <option value="Ringan">Ringan</option>
                    <option value="Normal">Normal</option>
                    <option value="Berat">Berat</option>
                </select>
            </div>
        </div>
        <div class="form-row">
            <div class="form-group">
                <label>Kondisi Pendinginan</label>
                <select name="cooling_condition">
                    <option value="">-- Pilih --</option>
                    <option value="Normal">Normal</option>
                    <option value="Buruk">Buruk / Terhambat</option>
                </select>
            </div>
            <div class="form-group">
                <label>Kondisi Suara</label>
                <select name="noise_condition">
                    <option value="">-- Pilih --</option>
                    <option value="Normal">Normal</option>
                    <option value="Kasar">Kasar / Berdengung</option>
                </select>
            </div>
        </div>
        <div class="form-group">
            <label>Kondisi Getaran</label>
            <select name="vibration_condition">
                <option value="">-- Pilih --</option>
                <option value="Normal">Normal</option>
                <option value="Tinggi">Tinggi / Berlebihan</option>
            </select>
        </div>
    </div>

    <div class="card full-width">
        <h3>3. Pemilihan Gejala Lapangan</h3>
        <p class="text-muted" style="margin-top: 5px;">Centang gejala yang teramati secara visual atau fungsional:</p>
        <div class="checkbox-grid">
            {% for s in symptoms %}
            <label class="checkbox-item">
                <input type="checkbox" name="symptoms" value="{{ s.id }}">
                <span><strong>{{ s.name }}</strong>: {{ s.description }}</span>
            </label>
            {% endfor %}
        </div>
    </div>

    <div class="form-actions full-width">
        <button type="submit" class="btn btn-primary">Jalankan Mesin Diagnosis</button>
    </div>
</form>
{% endblock %}
"""

RESULT_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<div style="display: flex; justify-content: space-between; align-items: center;">
    <h2>Hasil Diagnosis & Analisis Parameter</h2>
    <div>
        <a href="{{ url_for('report', history_id=history.id) }}" class="btn btn-secondary" target="_blank">Cetak / Simpan PDF</a>
        <a href="{{ url_for('history_list') }}" class="btn">Kembali ke Riwayat</a>
    </div>
</div>

<div class="card" style="margin-top: 20px;">
    <h3>Identitas Motor & Waktu Pemeriksaan</h3>
    <p style="margin-top: 8px;"><strong>Kode Motor:</strong> {{ motor.motor_code }}</p>
    <p><strong>Waktu Pemeriksaan:</strong> {{ history.diagnosis_time }}</p>
</div>

<div class="card">
    <h3>Hasil Perhitungan Parameter Listrik</h3>
    <ul style="margin-left: 20px; margin-top: 10px; line-height: 1.6;">
        <li><strong>Kecepatan Sinkron (ns):</strong> {% if calculations.ns %}{{ "%.2f"|format(calculations.ns) }} rpm{% else %}<em>Data tidak cukup</em>{% endif %}</li>
        <li><strong>Slip (s):</strong> {% if calculations.slip %}{{ "%.2f"|format(calculations.slip) }}%{% else %}<em>Kecepatan rotor tidak tersedia</em>{% endif %}</li>
        <li><strong>Tegangan Rata-rata 3 Fasa:</strong> {% if calculations.v_avg %}{{ "%.2f"|format(calculations.v_avg) }} V{% else %}<em>Tidak tersedia</em>{% endif %}</li>
        <li><strong>Ketidakseimbangan Tegangan:</strong> {{ "%.2f"|format(calculations.v_unbalance) }}%</li>
        <li><strong>Rasio Arus Terhadap Nominal:</strong> {% if calculations.current_ratio %}{{ "%.2f"|format(calculations.current_ratio) }}%{% else %}<em>Arus nominal / terukur kosong</em>{% endif %}</li>
    </ul>
</div>

<div class="card">
    <h3>Dugaan Kemungkinan Gangguan (Forward Chaining)</h3>
    <div style="margin-top: 10px;">
    {% if evidence %}
        {% for ev in evidence %}
        <div class="fault-box">
            <h4>⚠️ {{ ev.fault_name }}</h4>
            <p style="margin-top: 4px;"><strong>Aturan Aktif ({{ ev.rule_code }}):</strong> {{ ev.condition_desc }}</p>
            <p style="margin-top: 4px;"><strong>Bukti Pendukung:</strong> {{ ev.evidence_text }}</p>
        </div>
        {% endfor %}
    {% else %}
        <p style="color: #166534;">Tidak ada gangguan terdeteksi berdasarkan aturan dan gejala yang dimasukkan.</p>
    {% endif %}
    </div>

    {% if missing_data %}
    <div class="warning-box" style="margin-top: 15px;">
        <h4>Data yang Masih Kurang:</h4>
        <ul style="margin-left: 20px; margin-top: 5px;">
            {% for m in missing_data %}
            <li>{{ m }}</li>
            {% endfor %}
        </ul>
    </div>
    {% endif %}
</div>

<div class="card safety-card">
    <h3>Peringatan Keselamatan & Rekomendasi Pemeriksaan Lanjutan</h3>
    <ul style="margin-left: 20px; margin-top: 10px; line-height: 1.6;">
        <li><strong>Keselamatan Utama:</strong> Jangan menyentuh terminal, kabel, atau belitan motor yang sedang bertegangan! Pastikan catu daya diputus sebelum pemeriksaan fisik.</li>
        <li><strong>Pemeriksaan Isolasi:</strong> Pengujian tahanan isolasi wajib dilakukan menggunakan Megger oleh personel kompeten sesuai prosedur K3 listrik.</li>
        <li><strong>Tindakan Lanjutan:</strong> Lakukan pengukuran getaran presisi dan analisis termografi jika suhu atau vibrasi melampaui batas normal.</li>
    </ul>
</div>
{% endblock %}
"""

HISTORY_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<h2>Riwayat Diagnosis</h2>
<p class="subtitle">Daftar seluruh pemeriksaan gangguan motor yang pernah dilakukan.</p>

<form method="GET" action="{{ url_for('history_list') }}" class="search-form">
    <input type="text" name="q" value="{{ query }}" placeholder="Cari berdasarkan kode motor...">
    <button type="submit" class="btn">Cari</button>
</form>

<div class="card" style="margin-top: 20px;">
    {% if histories %}
    <table class="data-table">
        <thead>
            <tr>
                <th>ID</th>
                <th>Kode Motor</th>
                <th>Waktu</th>
                <th>Ringkasan</th>
                <th>Aksi</th>
            </tr>
        </thead>
        <tbody>
            {% for h in histories %}
            <tr>
                <td>{{ h.id }}</td>
                <td><strong>{{ h.motor_code }}</strong></td>
                <td>{{ h.diagnosis_time }}</td>
                <td>{{ h.summary_result }}</td>
                <td><a href="{{ url_for('diagnosis_result', history_id=h.id) }}" class="btn btn-sm">Lihat Detail</a></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p class="text-muted" style="margin-top: 10px;">Tidak ada riwayat ditemukan.</p>
    {% endif %}
</div>
{% endblock %}
"""

REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <title>Laporan Diagnosis - {{ motor.motor_code }}</title>
    <style>
        body { font-family: Arial, sans-serif; padding: 30px; color: #000; }
        h1 { font-size: 20px; margin-bottom: 10px; }
        .report-table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        .report-table td { border: 1px solid #ccc; padding: 8px; font-size: 14px; }
        ul { margin-left: 20px; line-height: 1.6; }
    </style>
</head>
<body onload="window.print()">
    <h1>LAPORAN RESMI DIAGNOSIS GANGGUAN MOTOR INDUKSI</h1>
    <hr style="margin-bottom: 15px;">
    <p><strong>Waktu Cetak / Pemeriksaan:</strong> {{ history.diagnosis_time }}</p>
    <p><strong>Kode Motor:</strong> {{ motor.motor_code }}</p>

    <h3>Parameter Operasi</h3>
    <table class="report-table">
        <tr><td>Daya Nominal</td><td>{{ motor.power_kw }} kW</td><td>Tegangan Nominal</td><td>{{ motor.voltage_v }} V</td></tr>
        <tr><td>Arus Nominal</td><td>{{ motor.current_a }} A</td><td>Kecepatan</td><td>{{ motor.rpm_nominal }} rpm</td></tr>
    </table>

    <h3>Hasil Perhitungan Kelistrikan</h3>
    <ul>
        <li>Kecepatan Sinkron: {{ "%.2f"|format(calculations.ns) if calculations.ns else '-' }} rpm</li>
        <li>Slip: {{ "%.2f"|format(calculations.slip) if calculations.slip else '-' }}%</li>
        <li>Ketidakseimbangan Tegangan: {{ "%.2f"|format(calculations.v_unbalance) }}%</li>
    </ul>

    <h3>Kemungkinan Gangguan Teridentifikasi</h3>
    {% if evidence %}
        <ul>
        {% for ev in evidence %}
            <li><strong>{{ ev.fault_name }}</strong> (Aturan: {{ ev.rule_code }}) - Bukti: {{ ev.evidence_text }}</li>
        {% endfor %}
        </ul>
    {% else %}
        <p>Tidak ada gangguan terdeteksi.</p>
    {% endif %}

    <div style="margin-top: 30px;">
        <h4>Catatan & Keselamatan Kerja</h4>
        <p style="font-size: 13px; margin-top: 5px;">Laporan ini dihasilkan oleh sistem pakar berbasis web. Perbaikan dan pembongkaran fisik motor wajib dilakukan oleh tenaga teknis bersertifikat sesuai standar PUIL dan K3.</p>
    </div>
</body>
</html>
"""

# ==========================================
# 5. FLASK ROUTES
# ==========================================
@app.route('/')
def dashboard():
    conn = get_db_connection()
    total_checks = conn.execute('SELECT COUNT(*) FROM diagnosis_history').fetchone()[0]
    total_faults_found = conn.execute('SELECT COUNT(DISTINCT fault_id) FROM diagnosis_evidence').fetchone()[0]
    recent_history = conn.execute('''
        SELECT h.id, m.motor_code, h.diagnosis_time, h.summary_result
        FROM diagnosis_history h
        JOIN motor_data m ON h.motor_id = m.id
        ORDER BY h.diagnosis_time DESC LIMIT 5
    ''').fetchall()
    conn.close()
    
    # Mock template loading for base inheritance
    app.jinja_env.loader.mapping['base.html'] = BASE_TEMPLATE
    return render_template_string(DASHBOARD_TEMPLATE, total_checks=total_checks, total_faults_found=total_faults_found, recent_history=recent_history)

@app.route('/input-motor', methods=['GET', 'POST'])
def input_motor():
    conn = get_db_connection()
    symptoms = conn.execute('SELECT * FROM symptoms').fetchall()
    conn.close()

    if request.method == 'POST':
        motor_code = request.form.get('motor_code')
        if not motor_code:
            flash('Kode motor wajib diisi!', 'danger')
            return redirect(url_for('input_motor'))

        def parse_float(val):
            return float(val) if val and val.strip() != '' else None

        def parse_int(val):
            return int(val) if val and val.strip() != '' else None

        motor_data = {
            'motor_code': motor_code,
            'power_kw': parse_float(request.form.get('power_kw')),
            'voltage_v': parse_float(request.form.get('voltage_v')),
            'current_a': parse_float(request.form.get('current_a')),
            'frequency_hz': parse_float(request.form.get('frequency_hz')),
            'poles': parse_int(request.form.get('poles')),
            'rpm_nominal': parse_float(request.form.get('rpm_nominal')),
            'v_l1': parse_float(request.form.get('v_l1')),
            'v_l2': parse_float(request.form.get('v_l2')),
            'v_l3': parse_float(request.form.get('v_l3')),
            'i_l1': parse_float(request.form.get('i_l1')),
            'i_l2': parse_float(request.form.get('i_l2')),
            'i_l3': parse_float(request.form.get('i_l3')),
            'temperature': parse_float(request.form.get('temperature')),
            'load_condition': request.form.get('load_condition'),
            'cooling_condition': request.form.get('cooling_condition'),
            'noise_condition': request.form.get('noise_condition'),
            'vibration_condition': request.form.get('vibration_condition')
        }

        selected_symptoms = request.form.getlist('symptoms')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO motor_data (
                motor_code, power_kw, voltage_v, current_a, frequency_hz, poles, rpm_nominal,
                v_l1, v_l2, v_l3, i_l1, i_l2, i_l3, temperature,
                load_condition, cooling_condition, noise_condition, vibration_condition
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            motor_data['motor_code'], motor_data['power_kw'], motor_data['voltage_v'],
            motor_data['current_a'], motor_data['frequency_hz'], motor_data['poles'],
            motor_data['rpm_nominal'], motor_data['v_l1'], motor_data['v_l2'],
            motor_data['v_l3'], motor_data['i_l1'], motor_data['i_l2'],
            motor_data['i_l3'], motor_data['temperature'],
            motor_data['load_condition'], motor_data['cooling_condition'],
            motor_data['noise_condition'], motor_data['vibration_condition']
        ))
        motor_id = cursor.lastrowid

        inferred_faults, missing_data = run_forward_chaining(motor_data, selected_symptoms)
        summary_text = f"Ditemukan {len(inferred_faults)} kemungkinan gangguan." if inferred_faults else "Belum ada gangguan terdeteksi."

        cursor.execute('INSERT INTO diagnosis_history (motor_id, summary_result) VALUES (?, ?)', (motor_id, summary_text))
        history_id = cursor.lastrowid

        for fault in inferred_faults:
            cursor.execute('''
                INSERT INTO diagnosis_evidence (history_id, fault_id, evidence_text, rule_code)
                VALUES (?, ?, ?, ?)
            ''', (history_id, fault['fault_id'], fault['evidence'], fault['rule_code']))

        conn.commit()
        conn.close()

        return redirect(url_for('diagnosis_result', history_id=history_id))

    app.jinja_env.loader.mapping['base.html'] = BASE_TEMPLATE
    return render_template_string(MOTOR_FORM_TEMPLATE, symptoms=symptoms)

@app.route('/diagnosis-result/<int:history_id>')
def diagnosis_result(history_id):
    conn = get_db_connection()
    history = conn.execute('SELECT * FROM diagnosis_history WHERE id = ?', (history_id,)).fetchone()
    if not history:
        conn.close()
        flash('Data riwayat diagnosis tidak ditemukan.', 'danger')
        return redirect(url_for('dashboard'))

    motor = conn.execute('SELECT * FROM motor_data WHERE id = ?', (history['motor_id'],)).fetchone()
    evidence = conn.execute('''
        SELECT e.*, f.name as fault_name, r.condition_desc
        FROM diagnosis_evidence e
        JOIN fault_types f ON e.fault_id = f.id
        LEFT JOIN diagnosis_rules r ON e.rule_code = r.id
        WHERE e.history_id = ?
    ''', (history_id,)).fetchall()
    conn.close()

    ns = calculate_synchronous_speed(motor['frequency_hz'], motor['poles'])
    slip = calculate_slip(ns, motor['rpm_nominal'])
    v_avg = calculate_average_voltage(motor['v_l1'], motor['v_l2'], motor['v_l3'])
    v_unbalance = calculate_voltage_unbalance(motor['v_l1'], motor['v_l2'], motor['v_l3'])
    current_ratio = calculate_current_ratio(motor['i_l1'], motor['i_l2'], motor['i_l3'], motor['current_a'])

    motor_dict = dict(motor)
    _, missing_data = run_forward_chaining(motor_dict, [])

    calculations = {
        'ns': ns, 'slip': slip, 'v_avg': v_avg, 'v_unbalance': v_unbalance, 'current_ratio': current_ratio
    }

    app.jinja_env.loader.mapping['base.html'] = BASE_TEMPLATE
    return render_template_string(RESULT_TEMPLATE, history=history, motor=motor, evidence=evidence, calculations=calculations, missing_data=missing_data)

@app.route('/history')
def history_list():
    query = request.args.get('q', '')
    conn = get_db_connection()
    if query:
        histories = conn.execute('''
            SELECT h.id, m.motor_code, h.diagnosis_time, h.summary_result
            FROM diagnosis_history h
            JOIN motor_data m ON h.motor_id = m.id
            WHERE m.motor_code LIKE ?
            ORDER BY h.diagnosis_time DESC
        ''', (f'%{query}%',)).fetchall()
    else:
        histories = conn.execute('''
            SELECT h.id, m.motor_code, h.diagnosis_time, h.summary_result
            FROM diagnosis_history h
            JOIN motor_data m ON h.motor_id = m.id
            ORDER BY h.diagnosis_time DESC
        ''').fetchall()
    conn.close()
    
    app.jinja_env.loader.mapping['base.html'] = BASE_TEMPLATE
    return render_template_string(HISTORY_TEMPLATE, histories=histories, query=query)

@app.route('/report/<int:history_id>')
def report(history_id):
    conn = get_db_connection()
    history = conn.execute('SELECT * FROM diagnosis_history WHERE id = ?', (history_id,)).fetchone()
    motor = conn.execute('SELECT * FROM motor_data WHERE id = ?', (history['motor_id'],)).fetchone()
    evidence = conn.execute('''
        SELECT e.*, f.name as fault_name, r.condition_desc
        FROM diagnosis_evidence e
        JOIN fault_types f ON e.fault_id = f.id
        LEFT JOIN diagnosis_rules r ON e.rule_code = r.id
        WHERE e.history_id = ?
    ''', (history_id,)).fetchall()
    conn.close()

    ns = calculate_synchronous_speed(motor['frequency_hz'], motor['poles'])
    slip = calculate_slip(ns, motor['rpm_nominal'])
    v_avg = calculate_average_voltage(motor['v_l1'], motor['v_l2'], motor['v_l3'])
    v_unbalance = calculate_voltage_unbalance(motor['v_l1'], motor['v_l2'], motor['v_l3'])
    current_ratio = calculate_current_ratio(motor['i_l1'], motor['i_l2'], motor['i_l3'], motor['current_a'])

    calculations = {
        'ns': ns, 'slip': slip, 'v_avg': v_avg, 'v_unbalance': v_unbalance, 'current_ratio': current_ratio
    }

    return render_template_string(REPORT_TEMPLATE, history=history, motor=motor, evidence=evidence, calculations=calculations)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)