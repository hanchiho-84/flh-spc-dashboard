import http.server, json, os, glob, csv, webbrowser, threading, sqlite3, math, time
import xml.etree.ElementTree as ET
from collections import defaultdict
from urllib.parse import urlparse, parse_qs
from datetime import datetime

PORT     = 8503
FOLDER   = os.path.dirname(os.path.abspath(__file__))
DB_FILE  = os.path.join(FOLDER, 'cmm_data.db')
SPECS_FILE = os.path.join(FOLDER, 'specs.json')

_DATE_FMTS = ['%Y/%m/%d', '%m/%d/%Y', '%Y-%m-%d', '%Y-%m-%d %H:%M']

def _norm_dt(date_str, time_str=''):
    """Normalize any date string to ISO YYYY-MM-DD HH:MM for correct text sort."""
    ds = date_str.strip()
    ts = time_str.strip() if time_str else ''
    for fmt in _DATE_FMTS:
        try:
            d = datetime.strptime(ds, fmt)
            iso = d.strftime('%Y-%m-%d')
            if ts:
                parts = ts.split(':')
                if len(parts) >= 2:
                    try:
                        return f'{iso} {int(parts[0]):02d}:{int(parts[1]):02d}'
                    except ValueError:
                        pass
            return iso
        except ValueError:
            continue
    # Handle year-less formats: "6-Jan", "27-Mar" (%d-%b) and "9/4" (%m/%d)
    now = datetime.now()
    for fmt in ('%d-%b', '%m/%d'):
        try:
            d = datetime.strptime(ds, fmt).replace(year=now.year)
            # If parsed date is more than 60 days in the future, assume previous year
            if (d - now).days > 60:
                d = d.replace(year=now.year - 1)
            iso = d.strftime('%Y-%m-%d')
            if ts:
                parts = ts.split(':')
                if len(parts) >= 2:
                    try:
                        return f'{iso} {int(parts[0]):02d}:{int(parts[1]):02d}'
                    except ValueError:
                        pass
            return iso
        except ValueError:
            continue
    return ds  # fallback: keep original if unparseable

META_COLS = {'Date','Time','Collector ID','OPERATOR','SHIFT','Serial No.','MODEL','Build','MSA','PART'}

W_DATA_FOLDER  = r'W:\MFG\public\SPC raw data\CSV\Backup'
W_XML_FOLDER   = r'W:\MFG\public\SPC raw data\XML\Backup'

CMM_PATTERNS = {
    '6x': ['CX743MCA2_FS1-6X*.XML'],
    '7x': ['CX743MCA2_7X*.XML', 'CX743MCA2_FS1-7X*.XML'],
    '8x': ['CX743MCA2_FS1-8X*.XML'],
}

_cmm_stats_cache = {'6x': {}, '7x': {}, '8x': {}}
_cmm_files_cache = {'6x': [], '7x': [], '8x': []}
_cmm_mtimes      = {'6x': {}, '7x': {}, '8x': {}}
_cmm_ready       = {'6x': False, '7x': False, '8x': False}
BATTERY_FOLDER = W_DATA_FOLDER
BATTERY_META   = {'Date','Time','OPERATOR','Serial No.'}
BATTERY_SPECS  = {
    'SOC':          {'usl':65.0, 'lsl':45.0, 'nom':60.0},
    'Pack_Air Leak':{'usl':55.0, 'lsl':-55.0,'nom': 0.0}
}

DOOR_FOLDER = W_DATA_FOLDER
DOOR_META   = {'Date','Time','Collector ID','OPERATOR','MODEL','VIN#','Engine','Build','MSA','PART'}
DOOR_SPECS  = {
    'FL@EFF': {'usl':1.18, 'lsl':None, 'nom':None, 'unit':'m/s', 'label':'FL 前左門'},
    'FR@EFF': {'usl':1.18, 'lsl':None, 'nom':None, 'unit':'m/s', 'label':'FR 前右門'},
    'RL@EFF': {'usl':1.35, 'lsl':None, 'nom':None, 'unit':'m/s', 'label':'RL 後左門'},
    'RR@EFF': {'usl':1.35, 'lsl':None, 'nom':None, 'unit':'m/s', 'label':'RR 後右門'},
}

VOW_FOLDER = W_DATA_FOLDER
VOW_META   = {'Date','Time','OPERATOR','VIN#','Sunroof','Temp interior','Temp ambient','Humidity'}
VOW_SPECS  = {
    'Vacuum_250Pa': {'usl':60.0, 'lsl':None, 'nom':50.0, 'unit':'Pa', 'label':'成車氣密 Vacuum_250Pa'},
    '1m try':       {'usl':60.0, 'lsl':None, 'nom':50.0, 'unit':'Pa', 'label':'1分鐘初測 1m try'},
}

SC_FOLDER = W_DATA_FOLDER
SC_META   = {'Date','Time','OPERATOR','VIN#','Build_phase'}
SC_SPECS  = {
    'ICE': {
        'ICE Static Current (mA)': {'usl':18.0,'lsl':None,'nom':None,'unit':'mA','label':'ICE 靜態電流'}
    },
    'FHEV': {
        'FHEV Static Current (mA)': {'usl':14.8,'lsl':None,'nom':None,'unit':'mA','label':'FHEV 靜態電流'}
    }
}

HUNTER_FOLDER = W_DATA_FOLDER
HUNTER_META   = {'Date','Time','Operator','Production Date','Model','VIN#','Rot#','Decking Cart#'}
HUNTER_SPECS  = {
    'Camber Front Left':        {'usl': 0.050,'lsl':-0.950,'nom':-0.450,'unit':'deg','label':'Camber FL',      'group':'Camber'},
    'Camber Front Right':       {'usl': 0.000,'lsl':-1.000,'nom':-0.450,'unit':'deg','label':'Camber FR',      'group':'Camber'},
    'Camber Front Cross (L-R)': {'usl': 0.700,'lsl':-0.700,'nom': 0.000,'unit':'deg','label':'Camber F Cross', 'group':'Camber'},
    'Camber Rear Left':         {'usl':-0.830,'lsl':-1.830,'nom':-1.330,'unit':'deg','label':'Camber RL',      'group':'Camber'},
    'Camber Rear Right':        {'usl':-0.830,'lsl':-1.830,'nom':-1.330,'unit':'deg','label':'Camber RR',      'group':'Camber'},
    'Caster Front Left':        {'usl': 7.750,'lsl': 6.250,'nom': 7.000,'unit':'deg','label':'Caster FL',      'group':'Caster'},
    'Caster Front Right':       {'usl': 7.750,'lsl': 6.250,'nom': 7.000,'unit':'deg','label':'Caster FR',      'group':'Caster'},
    'Caster Front Cross (L-R)': {'usl': 0.700,'lsl':-0.700,'nom': 0.000,'unit':'deg','label':'Caster F Cross', 'group':'Caster'},
    'Toe-in Front Toe L':       {'usl': 0.200,'lsl':-0.040,'nom': 0.080,'unit':'deg','label':'Toe F-L',        'group':'Toe-in'},
    'Toe-in Front Toe R':       {'usl': 0.200,'lsl':-0.040,'nom': 0.080,'unit':'deg','label':'Toe F-R',        'group':'Toe-in'},
    'Toe-in Front Total':       {'usl': 0.320,'lsl': 0.000,'nom': 0.160,'unit':'deg','label':'Toe F Total',    'group':'Toe-in'},
    'Toe-in Rear Toe L':        {'usl': 0.200,'lsl':-0.040,'nom': 0.080,'unit':'deg','label':'Toe R-L',        'group':'Toe-in'},
    'Toe-in Rear Toe R':        {'usl': 0.200,'lsl':-0.040,'nom': 0.080,'unit':'deg','label':'Toe R-R',        'group':'Toe-in'},
    'Toe-in Rear Total':        {'usl': 0.320,'lsl': 0.000,'nom': 0.160,'unit':'deg','label':'Toe R Total',    'group':'Toe-in'},
    'Thrust Angle':             {'usl': 0.500,'lsl':-0.500,'nom': 0.000,'unit':'deg','label':'Thrust Angle',   'group':'Angle'},
    'Ride Height Front Left':   {'usl': 465.0,'lsl': 435.0,'nom': 450.0,'unit':'mm', 'label':'RH F-L',         'group':'Ride Height'},
    'Ride Height Front Right':  {'usl': 465.0,'lsl': 435.0,'nom': 450.0,'unit':'mm', 'label':'RH F-R',         'group':'Ride Height'},
    'Ride Height Rear Left':    {'usl': 470.0,'lsl': 440.0,'nom': 455.0,'unit':'mm', 'label':'RH R-L',         'group':'Ride Height'},
    'Ride Height Rear Right':   {'usl': 470.0,'lsl': 440.0,'nom': 455.0,'unit':'mm', 'label':'RH R-R',         'group':'Ride Height'},
    'CV':                       {'usl': 2.000,'lsl':-2.000,'nom': 0.000,'unit':'deg','label':'CV',             'group':'Angle'},
}

LAMP_FOLDER = W_DATA_FOLDER
LAMP_META   = {'Date','Time','Operator','Model','VIN#','Rot#'}
LAMP_SPECS  = {
    'Left-V':  {'usl':85.90, 'lsl':75.90, 'nom':80.90, 'unit':'mrad', 'label':'左燈垂直 Left-V'},
    'Left-H':  {'usl':-58.00,'lsl':-88.00,'nom':-73.00,'unit':'mrad', 'label':'左燈水平 Left-H'},
    'Right-V': {'usl':84.80, 'lsl':74.80, 'nom':79.80, 'unit':'mrad', 'label':'右燈垂直 Right-V'},
    'Right-H': {'usl':88.00, 'lsl':58.00, 'nom':80.90, 'unit':'mrad', 'label':'右燈水平 Right-H'},
}

_lock        = threading.Lock()
_stats_cache = {}
_files_cache = []
_stats_mtimes = {}      # {fname: mtime} — in-memory fast check

_sg_stats_cache = {}
_sg_files_cache = []
_sg_stats_mtimes = {}

_battery_stats = {}
_battery_files = []
_battery_mtimes = {}

_door_stats = {}
_door_files = []
_door_mtimes = {}

_lamp_stats = {}
_lamp_files = []
_lamp_mtimes = {}

_vow_stats = {}
_vow_files = []
_vow_mtimes = {}

# _sc_stats/files/mtimes keyed by powertrain ('ICE' | 'FHEV')
_sc_stats  = {'ICE':{}, 'FHEV':{}}
_sc_files  = {'ICE':[], 'FHEV':[]}
_sc_mtimes = {'ICE':{}, 'FHEV':{}}

# _hunter_* keyed by powertrain
_hunter_stats  = {'ICE':{}, 'FHEV':{}}
_hunter_files  = {'ICE':[], 'FHEV':[]}
_hunter_mtimes = {'ICE':{}, 'FHEV':{}}

# ── Database init ──────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB_FILE, timeout=30) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.executescript('''
            CREATE TABLE IF NOT EXISTS file_meta (
                filename TEXT PRIMARY KEY,
                mtime    REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS car_rows (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                filename   TEXT NOT NULL,
                serial_no  TEXT,
                date       TEXT,
                shift      TEXT,
                model      TEXT
            );
            CREATE TABLE IF NOT EXISTS measurements (
                row_id  INTEGER NOT NULL,
                col     TEXT    NOT NULL,
                val     REAL,
                PRIMARY KEY (row_id, col)
            );
            CREATE INDEX IF NOT EXISTS idx_col  ON measurements(col);
            CREATE INDEX IF NOT EXISTS idx_date ON car_rows(date);
        ''')
        # Migrate: add columns if missing (existing databases)
        for _sql in [
            'ALTER TABLE point_settings ADD COLUMN control_nominal REAL',
            "ALTER TABLE point_settings ADD COLUMN engineer TEXT DEFAULT ''",
            "ALTER TABLE point_settings ADD COLUMN countermeasure TEXT DEFAULT ''",
            "ALTER TABLE point_settings ADD COLUMN issue_status TEXT DEFAULT 'open'",
            "ALTER TABLE point_settings ADD COLUMN follow_up_date TEXT DEFAULT ''",
        ]:
            try:
                c.execute(_sql)
            except Exception:
                pass
        c.executescript('''
            CREATE TABLE IF NOT EXISTS battery_files (
                filename TEXT PRIMARY KEY, mtime REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS battery_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL, serial_no TEXT, date TEXT, operator TEXT
            );
            CREATE TABLE IF NOT EXISTS battery_meas (
                row_id INTEGER NOT NULL, col TEXT NOT NULL, val REAL,
                PRIMARY KEY (row_id, col)
            );
            CREATE INDEX IF NOT EXISTS idx_bat_col ON battery_meas(col);
            CREATE TABLE IF NOT EXISTS battery_settings (
                col TEXT PRIMARY KEY, ucl REAL, lcl REAL, nom REAL, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS door_files (
                filename TEXT PRIMARY KEY, mtime REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS door_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL, vin TEXT, date TEXT, operator TEXT, model TEXT
            );
            CREATE TABLE IF NOT EXISTS door_meas (
                row_id INTEGER NOT NULL, col TEXT NOT NULL, val REAL,
                PRIMARY KEY (row_id, col)
            );
            CREATE INDEX IF NOT EXISTS idx_door_col ON door_meas(col);
            CREATE TABLE IF NOT EXISTS door_settings (
                col TEXT PRIMARY KEY, ucl REAL, lcl REAL, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS lamp_files (
                filename TEXT PRIMARY KEY, mtime REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS lamp_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL, vin TEXT, date TEXT, operator TEXT, rot TEXT
            );
            CREATE TABLE IF NOT EXISTS lamp_meas (
                row_id INTEGER NOT NULL, col TEXT NOT NULL, val REAL,
                PRIMARY KEY (row_id, col)
            );
            CREATE INDEX IF NOT EXISTS idx_lamp_col ON lamp_meas(col);
            CREATE TABLE IF NOT EXISTS lamp_settings (
                col TEXT PRIMARY KEY, ucl REAL, lcl REAL, nom REAL, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS vow_files (
                filename TEXT PRIMARY KEY, mtime REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS vow_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL, vin TEXT, date TEXT, operator TEXT, sunroof TEXT
            );
            CREATE TABLE IF NOT EXISTS vow_meas (
                row_id INTEGER NOT NULL, col TEXT NOT NULL, val REAL,
                PRIMARY KEY (row_id, col)
            );
            CREATE INDEX IF NOT EXISTS idx_vow_col ON vow_meas(col);
            CREATE TABLE IF NOT EXISTS vow_settings (
                col TEXT PRIMARY KEY, ucl REAL, lcl REAL, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sc_files (
                filename TEXT PRIMARY KEY, mtime REAL NOT NULL, powertrain TEXT
            );
            CREATE TABLE IF NOT EXISTS sc_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL, vin TEXT, date TEXT,
                operator TEXT, build_phase TEXT, powertrain TEXT
            );
            CREATE TABLE IF NOT EXISTS sc_meas (
                row_id INTEGER NOT NULL, col TEXT NOT NULL, val REAL,
                PRIMARY KEY (row_id, col)
            );
            CREATE INDEX IF NOT EXISTS idx_sc_col ON sc_meas(col);
            CREATE TABLE IF NOT EXISTS sc_settings (
                col TEXT PRIMARY KEY, ucl REAL, lcl REAL, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS hunter_files (
                filename TEXT PRIMARY KEY, mtime REAL NOT NULL, powertrain TEXT
            );
            CREATE TABLE IF NOT EXISTS hunter_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL, vin TEXT, date TEXT,
                operator TEXT, rot TEXT, powertrain TEXT
            );
            CREATE TABLE IF NOT EXISTS hunter_meas (
                row_id INTEGER NOT NULL, col TEXT NOT NULL, val REAL,
                PRIMARY KEY (row_id, col)
            );
            CREATE INDEX IF NOT EXISTS idx_hunter_col ON hunter_meas(col);
            CREATE TABLE IF NOT EXISTS hunter_settings (
                col TEXT PRIMARY KEY, ucl REAL, lcl REAL, nom REAL, updated_at TEXT
            );
        ''')
        c.executescript('''
            CREATE TABLE IF NOT EXISTS cmm_files (
                filename TEXT PRIMARY KEY, mtime REAL NOT NULL, line_type TEXT
            );
            CREATE TABLE IF NOT EXISTS cmm_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL, line_type TEXT, hand TEXT, job_id TEXT, date TEXT
            );
            CREATE TABLE IF NOT EXISTS cmm_meas (
                row_id INTEGER NOT NULL, col TEXT NOT NULL, val REAL,
                PRIMARY KEY (row_id, col)
            );
            CREATE INDEX IF NOT EXISTS idx_cmm_col  ON cmm_meas(col);
            CREATE INDEX IF NOT EXISTS idx_cmm_line ON cmm_rows(line_type);
            CREATE TABLE IF NOT EXISTS cmm_specs (
                col TEXT NOT NULL, line_type TEXT NOT NULL,
                usl REAL, lsl REAL, unit TEXT DEFAULT \'mm\',
                PRIMARY KEY (col, line_type)
            );
        ''')
        c.executescript('''
            CREATE TABLE IF NOT EXISTS point_settings (
                col              TEXT PRIMARY KEY,
                risk_level       TEXT,
                control_usl      REAL,
                control_lsl      REAL,
                control_nominal  REAL,
                risk_description TEXT,
                updated_at       TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                col        TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                changes    TEXT NOT NULL
            );
        ''')

# ── Incremental CSV sync ───────────────────────────────────────
def _parse_file(conn, f):
    fname = os.path.basename(f)
    mtime = os.path.getmtime(f)
    try:
        with open(f, encoding='utf-8-sig') as fh:
            data = list(csv.reader(fh))
    except Exception as e:
        print(f'  [skip] {fname}: {e}')
        return
    if len(data) < 4:
        return

    headers = data[2]

    # Remove stale data for this file
    old_ids = [r[0] for r in conn.execute('SELECT id FROM car_rows WHERE filename=?', (fname,))]
    if old_ids:
        ph = ','.join('?' * len(old_ids))
        conn.execute(f'DELETE FROM measurements WHERE row_id IN ({ph})', old_ids)
    conn.execute('DELETE FROM car_rows WHERE filename=?', (fname,))

    for row_data in data[3:]:
        if not row_data or not row_data[0].strip():
            continue
        obj = {headers[i]: (row_data[i].strip() if i < len(row_data) else '')
               for i in range(len(headers))}
        cur = conn.execute(
            'INSERT INTO car_rows (filename,serial_no,date,shift,model) VALUES (?,?,?,?,?)',
            (fname, obj.get('Serial No.',''),
             _norm_dt(obj.get('Date',''), obj.get('Time','')),
             obj.get('SHIFT',''), obj.get('MODEL',''))
        )
        row_id = cur.lastrowid
        meas = []
        for col in headers:
            if col in META_COLS or not col.strip():
                continue
            v = obj.get(col, '').strip()
            if v:
                try:
                    meas.append((row_id, col, float(v)))
                except ValueError:
                    pass
        if meas:
            conn.executemany(
                'INSERT OR REPLACE INTO measurements (row_id,col,val) VALUES (?,?,?)', meas)

    conn.execute('INSERT OR REPLACE INTO file_meta (filename,mtime) VALUES (?,?)', (fname, mtime))
    print(f'  [sync] {fname}')

def sync_csv_files():
    global _stats_cache, _files_cache, _stats_mtimes
    csv_files = sorted(glob.glob(os.path.join(W_DATA_FOLDER, 'BIW CX743 MF MP1*.csv')))

    # Fast path: cache populated, file count same, all mtimes match
    if _stats_cache and len(csv_files) == len(_files_cache):
        if all(_stats_mtimes.get(os.path.basename(f)) == os.path.getmtime(f) for f in csv_files):
            return

    # Slow path: parse changed files, rebuild cache
    with sqlite3.connect(DB_FILE, timeout=30) as conn:
        changed = False
        for f in csv_files:
            fname = os.path.basename(f)
            mtime = os.path.getmtime(f)
            if _stats_mtimes.get(fname) == mtime:
                continue
            _parse_file(conn, f)
            _stats_mtimes[fname] = mtime
            changed = True
        if changed:
            conn.commit()

        raw = conn.execute(
            "SELECT col, val FROM measurements "
            "WHERE (col LIKE '%AF%' OR col LIKE '%AM%') AND val IS NOT NULL "
            "AND col NOT IN ('MF_BIW_AFIT','CX743MCA2_2025','B','FLH','LDVersion XX')"
        ).fetchall()

    col_vals = defaultdict(list)
    for col, val in raw:
        col_vals[col].append(val)

    cache = {}
    for col, vals in col_vals.items():
        n = len(vals)
        if n < 2:
            cache[col] = {'n': n, 'mean': None, 'std': None, 'min': None, 'max': None}
            continue
        mean = sum(vals) / n
        std  = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
        cache[col] = {'n': n, 'mean': round(mean,6), 'std': round(std,6),
                      'min': min(vals), 'max': max(vals)}

    _stats_cache = cache
    _files_cache = [os.path.basename(f) for f in csv_files]
    print(f'快取完成：{len(_files_cache)} 個 CSV，{len(_stats_cache)} 個 AF 點位')

# ── Battery Pack CSV sync ───────────────────────────────────────
def _parse_battery_csv(conn, f):
    fname = os.path.basename(f)
    mtime = os.path.getmtime(f)
    try:
        with open(f, encoding='utf-8-sig') as fh:
            rows = list(csv.reader(fh))
    except Exception as e:
        print(f'  [skip battery] {fname}: {e}'); return
    if len(rows) < 4: return
    headers = [h.strip() for h in rows[2]]
    old_ids = [r[0] for r in conn.execute('SELECT id FROM battery_rows WHERE filename=?', (fname,))]
    if old_ids:
        ph = ','.join('?'*len(old_ids))
        conn.execute(f'DELETE FROM battery_meas WHERE row_id IN ({ph})', old_ids)
    conn.execute('DELETE FROM battery_rows WHERE filename=?', (fname,))
    for row in rows[3:]:
        if not row or not row[0].strip(): continue
        obj = {headers[i]: (row[i].strip() if i < len(row) else '') for i in range(len(headers))}
        cur = conn.execute(
            'INSERT INTO battery_rows (filename,serial_no,date,operator) VALUES (?,?,?,?)',
            (fname, obj.get('Serial No.',''),
             _norm_dt(obj.get('Date',''), obj.get('Time','')),
             obj.get('OPERATOR',''))
        )
        rid = cur.lastrowid
        meas = []
        for col in headers:
            if col in BATTERY_META or not col: continue
            v = obj.get(col,'').strip()
            if v:
                try: meas.append((rid, col, float(v)))
                except ValueError: pass
        if meas:
            conn.executemany('INSERT OR REPLACE INTO battery_meas (row_id,col,val) VALUES (?,?,?)', meas)
    conn.execute('INSERT OR REPLACE INTO battery_files (filename,mtime) VALUES (?,?)', (fname, mtime))
    print(f'  [sync battery] {fname}')

def sync_battery():
    global _battery_stats, _battery_files, _battery_mtimes
    if not os.path.isdir(BATTERY_FOLDER): return
    csvs = sorted(glob.glob(os.path.join(BATTERY_FOLDER, 'QD CX743MCA2*.csv')))

    # Fast path
    if _battery_stats and len(csvs) == len(_battery_files):
        if all(_battery_mtimes.get(os.path.basename(f)) == os.path.getmtime(f) for f in csvs):
            return

    # Slow path: parse changed files, rebuild cache
    with sqlite3.connect(DB_FILE, timeout=30) as conn:
        changed = False
        for f in csvs:
            fname = os.path.basename(f)
            mtime = os.path.getmtime(f)
            if _battery_mtimes.get(fname) == mtime:
                continue
            _parse_battery_csv(conn, f)
            _battery_mtimes[fname] = mtime
            changed = True
        if changed:
            conn.commit()
        raw = conn.execute('SELECT col,val FROM battery_meas WHERE val IS NOT NULL').fetchall()
    cv = defaultdict(list)
    for col, val in raw: cv[col].append(val)
    cache = {}
    for col, vals in cv.items():
        n = len(vals)
        if n < 2: cache[col] = {'n':n,'mean':None,'std':None,'min':None,'max':None}; continue
        m = sum(vals)/n
        s = math.sqrt(sum((v-m)**2 for v in vals)/(n-1))
        cache[col] = {'n':n,'mean':round(m,6),'std':round(s,6),'min':min(vals),'max':max(vals)}
    _battery_stats = cache
    _battery_files = [os.path.basename(f) for f in csvs]
    print(f'Battery 快取：{len(_battery_files)} CSV，{len(_battery_stats)} 欄位')

# ── Door Closing Effort CSV sync ───────────────────────────────
def _parse_door_csv(conn, f):
    fname = os.path.basename(f)
    mtime = os.path.getmtime(f)
    try:
        with open(f, encoding='utf-8-sig') as fh:
            rows = list(csv.reader(fh))
    except Exception as e:
        print(f'  [skip door] {fname}: {e}'); return
    if len(rows) < 4: return
    headers = [h.strip() for h in rows[2]]
    old_ids = [r[0] for r in conn.execute('SELECT id FROM door_rows WHERE filename=?', (fname,))]
    if old_ids:
        ph = ','.join('?'*len(old_ids))
        conn.execute(f'DELETE FROM door_meas WHERE row_id IN ({ph})', old_ids)
    conn.execute('DELETE FROM door_rows WHERE filename=?', (fname,))
    for row in rows[3:]:
        if not row or not row[0].strip(): continue
        obj = {headers[i]: (row[i].strip() if i < len(row) else '') for i in range(len(headers))}
        cur = conn.execute(
            'INSERT INTO door_rows (filename,vin,date,operator,model) VALUES (?,?,?,?,?)',
            (fname, obj.get('VIN#',''),
             _norm_dt(obj.get('Date',''), obj.get('Time','')),
             obj.get('OPERATOR',''), obj.get('MODEL',''))
        )
        rid = cur.lastrowid
        meas = []
        for col in headers:
            if col in DOOR_META or not col: continue
            v = obj.get(col,'').strip()
            if v:
                try: meas.append((rid, col, float(v)))
                except ValueError: pass
        if meas:
            conn.executemany('INSERT OR REPLACE INTO door_meas (row_id,col,val) VALUES (?,?,?)', meas)
    conn.execute('INSERT OR REPLACE INTO door_files (filename,mtime) VALUES (?,?)', (fname, mtime))
    print(f'  [sync door] {fname}')

def sync_door():
    global _door_stats, _door_files, _door_mtimes
    csvs = sorted(glob.glob(os.path.join(DOOR_FOLDER, 'QD CX743 Door Closing Effort*.csv')))

    # Fast path
    if _door_stats and len(csvs) == len(_door_files):
        if all(_door_mtimes.get(os.path.basename(f)) == os.path.getmtime(f) for f in csvs):
            return

    # Slow path: parse changed files, rebuild cache
    with sqlite3.connect(DB_FILE, timeout=30) as conn:
        changed = False
        for f in csvs:
            fname = os.path.basename(f)
            mtime = os.path.getmtime(f)
            if _door_mtimes.get(fname) == mtime:
                continue
            _parse_door_csv(conn, f)
            _door_mtimes[fname] = mtime
            changed = True
        if changed:
            conn.commit()
        raw = conn.execute('SELECT col,val FROM door_meas WHERE val IS NOT NULL').fetchall()
    cv = defaultdict(list)
    for col, val in raw: cv[col].append(val)
    cache = {}
    for col, vals in cv.items():
        n = len(vals)
        if n < 2: cache[col] = {'n':n,'mean':None,'std':None,'min':None,'max':None}; continue
        m = sum(vals)/n
        s = math.sqrt(sum((v-m)**2 for v in vals)/(n-1))
        cache[col] = {'n':n,'mean':round(m,6),'std':round(s,6),'min':min(vals),'max':max(vals)}
    _door_stats = cache
    _door_files = [os.path.basename(f) for f in csvs]
    print(f'Door 快取：{len(_door_files)} CSV，{len(_door_stats)} 欄位')

# ── HeadLamp Aiming CSV sync ────────────────────────────────────
def _parse_lamp_csv(conn, f):
    fname = os.path.basename(f)
    mtime = os.path.getmtime(f)
    try:
        with open(f, encoding='utf-8-sig') as fh:
            rows = list(csv.reader(fh))
    except Exception as e:
        print(f'  [skip lamp] {fname}: {e}'); return
    if len(rows) < 4: return
    headers = [h.strip() for h in rows[2]]
    old_ids = [r[0] for r in conn.execute('SELECT id FROM lamp_rows WHERE filename=?', (fname,))]
    if old_ids:
        ph = ','.join('?'*len(old_ids))
        conn.execute(f'DELETE FROM lamp_meas WHERE row_id IN ({ph})', old_ids)
    conn.execute('DELETE FROM lamp_rows WHERE filename=?', (fname,))
    for row in rows[3:]:
        if not row or not row[0].strip(): continue
        obj = {headers[i]: (row[i].strip() if i < len(row) else '') for i in range(len(headers))}
        cur = conn.execute(
            'INSERT INTO lamp_rows (filename,vin,date,operator,rot) VALUES (?,?,?,?,?)',
            (fname, obj.get('VIN#',''),
             _norm_dt(obj.get('Date',''), obj.get('Time','')),
             obj.get('Operator',''), obj.get('Rot#',''))
        )
        rid = cur.lastrowid
        meas = []
        for col in headers:
            if col in LAMP_META or not col: continue
            v = obj.get(col,'').strip()
            if v:
                try: meas.append((rid, col, float(v)))
                except ValueError: pass
        if meas:
            conn.executemany('INSERT OR REPLACE INTO lamp_meas (row_id,col,val) VALUES (?,?,?)', meas)
    conn.execute('INSERT OR REPLACE INTO lamp_files (filename,mtime) VALUES (?,?)', (fname, mtime))
    print(f'  [sync lamp] {fname}')

def sync_lamp():
    global _lamp_stats, _lamp_files, _lamp_mtimes
    csvs = sorted(glob.glob(os.path.join(LAMP_FOLDER, 'QD CX743 Head lamp aiming*.csv')))

    # Fast path
    if _lamp_stats and len(csvs) == len(_lamp_files):
        if all(_lamp_mtimes.get(os.path.basename(f)) == os.path.getmtime(f) for f in csvs):
            return

    # Slow path: parse changed files, rebuild cache
    with sqlite3.connect(DB_FILE, timeout=30) as conn:
        changed = False
        for f in csvs:
            fname = os.path.basename(f)
            mtime = os.path.getmtime(f)
            if _lamp_mtimes.get(fname) == mtime:
                continue
            _parse_lamp_csv(conn, f)
            _lamp_mtimes[fname] = mtime
            changed = True
        if changed:
            conn.commit()
        raw = conn.execute('SELECT col,val FROM lamp_meas WHERE val IS NOT NULL').fetchall()
    cv = defaultdict(list)
    for col, val in raw: cv[col].append(val)
    cache = {}
    for col, vals in cv.items():
        n = len(vals)
        if n < 2: cache[col] = {'n':n,'mean':None,'std':None,'min':None,'max':None}; continue
        m = sum(vals)/n
        s = math.sqrt(sum((v-m)**2 for v in vals)/(n-1))
        cache[col] = {'n':n,'mean':round(m,6),'std':round(s,6),'min':min(vals),'max':max(vals)}
    _lamp_stats = cache
    _lamp_files = [os.path.basename(f) for f in csvs]
    print(f'Lamp 快取：{len(_lamp_files)} CSV，{len(_lamp_stats)} 欄位')

# ── VOW Air Leakage CSV sync ────────────────────────────────────
def _parse_vow_csv(conn, f):
    fname = os.path.basename(f)
    mtime = os.path.getmtime(f)
    try:
        with open(f, encoding='utf-8-sig') as fh:
            rows = list(csv.reader(fh))
    except Exception as e:
        print(f'  [skip vow] {fname}: {e}'); return
    if len(rows) < 4: return
    headers = [h.strip() for h in rows[2]]
    old_ids = [r[0] for r in conn.execute('SELECT id FROM vow_rows WHERE filename=?', (fname,))]
    if old_ids:
        ph = ','.join('?'*len(old_ids))
        conn.execute(f'DELETE FROM vow_meas WHERE row_id IN ({ph})', old_ids)
    conn.execute('DELETE FROM vow_rows WHERE filename=?', (fname,))
    for row in rows[3:]:
        if not row or not row[0].strip(): continue
        obj = {headers[i]: (row[i].strip() if i < len(row) else '') for i in range(len(headers))}
        cur = conn.execute(
            'INSERT INTO vow_rows (filename,vin,date,operator,sunroof) VALUES (?,?,?,?,?)',
            (fname, obj.get('VIN#',''),
             _norm_dt(obj.get('Date',''), obj.get('Time','')),
             obj.get('OPERATOR',''), obj.get('Sunroof',''))
        )
        rid = cur.lastrowid
        meas = []
        for col in headers:
            if col in VOW_META or not col: continue
            v = obj.get(col,'').strip()
            if v:
                try: meas.append((rid, col, float(v)))
                except ValueError: pass
        if meas:
            conn.executemany('INSERT OR REPLACE INTO vow_meas (row_id,col,val) VALUES (?,?,?)', meas)
    conn.execute('INSERT OR REPLACE INTO vow_files (filename,mtime) VALUES (?,?)', (fname, mtime))
    print(f'  [sync vow] {fname}')

def sync_vow():
    global _vow_stats, _vow_files, _vow_mtimes
    csvs = sorted(glob.glob(os.path.join(VOW_FOLDER, 'QD CX743 VOW Air leakage*.csv')))

    # Fast path
    if _vow_stats and len(csvs) == len(_vow_files):
        if all(_vow_mtimes.get(os.path.basename(f)) == os.path.getmtime(f) for f in csvs):
            return

    # Slow path: parse changed files, rebuild cache
    with sqlite3.connect(DB_FILE, timeout=30) as conn:
        changed = False
        for f in csvs:
            fname = os.path.basename(f)
            mtime = os.path.getmtime(f)
            if _vow_mtimes.get(fname) == mtime:
                continue
            _parse_vow_csv(conn, f)
            _vow_mtimes[fname] = mtime
            changed = True
        if changed:
            conn.commit()
        raw = conn.execute('SELECT col,val FROM vow_meas WHERE val IS NOT NULL').fetchall()
    cv = defaultdict(list)
    for col, val in raw: cv[col].append(val)
    cache = {}
    for col, vals in cv.items():
        n = len(vals)
        if n < 2: cache[col] = {'n':n,'mean':None,'std':None,'min':None,'max':None}; continue
        m = sum(vals)/n
        s = math.sqrt(sum((v-m)**2 for v in vals)/(n-1))
        cache[col] = {'n':n,'mean':round(m,6),'std':round(s,6),'min':min(vals),'max':max(vals)}
    _vow_stats = cache
    _vow_files = [os.path.basename(f) for f in csvs]
    print(f'VOW 快取：{len(_vow_files)} CSV，{len(_vow_stats)} 欄位')

# ── Static Current CSV sync ─────────────────────────────────────
def _parse_sc_csv(conn, f, pt):
    fname = os.path.basename(f)
    mtime = os.path.getmtime(f)
    try:
        with open(f, encoding='utf-8-sig') as fh:
            rows = list(csv.reader(fh))
    except Exception as e:
        print(f'  [skip sc] {fname}: {e}'); return
    if len(rows) < 4: return
    headers = [h.strip() for h in rows[2]]
    old_ids = [r[0] for r in conn.execute('SELECT id FROM sc_rows WHERE filename=?', (fname,))]
    if old_ids:
        ph = ','.join('?'*len(old_ids))
        conn.execute(f'DELETE FROM sc_meas WHERE row_id IN ({ph})', old_ids)
    conn.execute('DELETE FROM sc_rows WHERE filename=?', (fname,))
    for row in rows[3:]:
        if not row or not row[0].strip(): continue
        obj = {headers[i]: (row[i].strip() if i < len(row) else '') for i in range(len(headers))}
        cur = conn.execute(
            'INSERT INTO sc_rows (filename,vin,date,operator,build_phase,powertrain) VALUES (?,?,?,?,?,?)',
            (fname, obj.get('VIN#',''),
             _norm_dt(obj.get('Date',''), obj.get('Time','')),
             obj.get('OPERATOR',''), obj.get('Build_phase',''), pt)
        )
        rid = cur.lastrowid
        meas = []
        for col in headers:
            if col in SC_META or not col: continue
            v = obj.get(col,'').strip()
            if v:
                try: meas.append((rid, col, float(v)))
                except ValueError: pass
        if meas:
            conn.executemany('INSERT OR REPLACE INTO sc_meas (row_id,col,val) VALUES (?,?,?)', meas)
    conn.execute('INSERT OR REPLACE INTO sc_files (filename,mtime,powertrain) VALUES (?,?,?)', (fname, mtime, pt))
    print(f'  [sync sc/{pt}] {fname}')

def _rebuild_sc_cache(conn, pt):
    col_name = list(SC_SPECS[pt].keys())[0]
    raw = conn.execute(
        'SELECT m.val FROM sc_meas m JOIN sc_rows r ON m.row_id=r.id '
        'WHERE r.powertrain=? AND m.col=? AND m.val IS NOT NULL',
        (pt, col_name)
    ).fetchall()
    vals = [r[0] for r in raw]
    n = len(vals)
    if n < 2:
        _sc_stats[pt] = {col_name: {'n':n,'mean':None,'std':None,'min':None,'max':None}}
    else:
        m = sum(vals)/n
        s = math.sqrt(sum((v-m)**2 for v in vals)/(n-1))
        _sc_stats[pt] = {col_name: {'n':n,'mean':round(m,6),'std':round(s,6),'min':min(vals),'max':max(vals)}}
    _sc_files[pt] = [r[0] for r in conn.execute(
        'SELECT filename FROM sc_files WHERE powertrain=? ORDER BY filename', (pt,)).fetchall()]

def sync_sc():
    for pt, glob_pat in [('ICE','QD CX743 VOW Static Current_ICE*.csv'),
                         ('FHEV','QD CX743 VOW Static Current_FHEV*.csv')]:
        csvs = sorted(glob.glob(os.path.join(SC_FOLDER, glob_pat)))
        # Fast path
        if _sc_stats[pt] and len(csvs) == len(_sc_files[pt]):
            if all(_sc_mtimes[pt].get(os.path.basename(f)) == os.path.getmtime(f) for f in csvs):
                continue
        with sqlite3.connect(DB_FILE, timeout=30) as conn:
            changed = False
            for f in csvs:
                fname = os.path.basename(f)
                mtime = os.path.getmtime(f)
                if _sc_mtimes[pt].get(fname) == mtime:
                    continue
                _parse_sc_csv(conn, f, pt)
                _sc_mtimes[pt][fname] = mtime
                changed = True
            if changed:
                conn.commit()
            _rebuild_sc_cache(conn, pt)
    print(f'SC 快取：ICE {len(_sc_files["ICE"])} CSV，FHEV {len(_sc_files["FHEV"])} CSV')

# ── Hunter Wheel Alignment CSV sync ────────────────────────────
def _parse_hunter_csv(conn, f, pt):
    fname = os.path.basename(f)
    mtime = os.path.getmtime(f)
    try:
        with open(f, encoding='utf-8-sig') as fh:
            rows = list(csv.reader(fh))
    except Exception as e:
        print(f'  [skip hunter] {fname}: {e}'); return
    if len(rows) < 4: return
    headers = [h.strip() for h in rows[2]]
    old_ids = [r[0] for r in conn.execute('SELECT id FROM hunter_rows WHERE filename=?', (fname,))]
    if old_ids:
        ph = ','.join('?'*len(old_ids))
        conn.execute(f'DELETE FROM hunter_meas WHERE row_id IN ({ph})', old_ids)
    conn.execute('DELETE FROM hunter_rows WHERE filename=?', (fname,))
    for row in rows[3:]:
        if not row or not row[0].strip(): continue
        obj = {headers[i]: (row[i].strip() if i < len(row) else '') for i in range(len(headers))}
        cur = conn.execute(
            'INSERT INTO hunter_rows (filename,vin,date,operator,rot,powertrain) VALUES (?,?,?,?,?,?)',
            (fname, obj.get('VIN#',''),
             _norm_dt(obj.get('Date',''), obj.get('Time','')),
             obj.get('Operator',''), obj.get('Rot#',''), pt)
        )
        rid = cur.lastrowid
        meas = []
        for col in headers:
            if col in HUNTER_META or not col: continue
            v = obj.get(col,'').strip()
            if v:
                try: meas.append((rid, col, float(v)))
                except ValueError: pass
        if meas:
            conn.executemany('INSERT OR REPLACE INTO hunter_meas (row_id,col,val) VALUES (?,?,?)', meas)
    conn.execute('INSERT OR REPLACE INTO hunter_files (filename,mtime,powertrain) VALUES (?,?,?)', (fname, mtime, pt))
    print(f'  [sync hunter/{pt}] {fname}')

def _rebuild_hunter_cache(conn, pt):
    raw = conn.execute(
        'SELECT m.col,m.val FROM hunter_meas m JOIN hunter_rows r ON m.row_id=r.id '
        'WHERE r.powertrain=? AND m.val IS NOT NULL', (pt,)
    ).fetchall()
    cv = defaultdict(list)
    for col, val in raw: cv[col].append(val)
    cache = {}
    for col, vals in cv.items():
        n = len(vals)
        if n < 2: cache[col] = {'n':n,'mean':None,'std':None,'min':None,'max':None}; continue
        m = sum(vals)/n
        s = math.sqrt(sum((v-m)**2 for v in vals)/(n-1))
        cache[col] = {'n':n,'mean':round(m,6),'std':round(s,6),'min':min(vals),'max':max(vals)}
    _hunter_stats[pt] = cache
    _hunter_files[pt] = [r[0] for r in conn.execute(
        'SELECT filename FROM hunter_files WHERE powertrain=? ORDER BY filename', (pt,)).fetchall()]

def sync_hunter():
    for pt, glob_pat in [('ICE','QD CX743 Hunter-ICE*.csv'),
                         ('FHEV','QD CX743 Hunter-FHEV*.csv')]:
        csvs = sorted(glob.glob(os.path.join(HUNTER_FOLDER, glob_pat)))
        if _hunter_stats[pt] and len(csvs) == len(_hunter_files[pt]):
            if all(_hunter_mtimes[pt].get(os.path.basename(f)) == os.path.getmtime(f) for f in csvs):
                continue
        with sqlite3.connect(DB_FILE, timeout=30) as conn:
            changed = False
            for f in csvs:
                fname = os.path.basename(f)
                mtime = os.path.getmtime(f)
                if _hunter_mtimes[pt].get(fname) == mtime:
                    continue
                _parse_hunter_csv(conn, f, pt)
                _hunter_mtimes[pt][fname] = mtime
                changed = True
            if changed:
                conn.commit()
            _rebuild_hunter_cache(conn, pt)
    print(f'Hunter 快取：ICE {len(_hunter_files["ICE"])} CSV，FHEV {len(_hunter_files["FHEV"])} CSV')

# ── HTTP helpers ────────────────────────────────────────────────
def send_json(handler, data):
    body = json.dumps(data, ensure_ascii=False).encode('utf-8')
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', len(body))
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.end_headers()
    handler.wfile.write(body)

SG_SPECS_FILE = os.path.join(FOLDER, 'sg_specs.json')

def load_specs(mode='mf'):
    f_path = SG_SPECS_FILE if mode == 'sg' else SPECS_FILE
    if os.path.exists(f_path):
        with open(f_path, encoding='utf-8') as f:
            return json.load(f)
    return {'matched': {}, 'unmatched': []}

def sync_sg_files():
    global _sg_stats_cache, _sg_files_cache, _sg_stats_mtimes
    csv_files = sorted(glob.glob(os.path.join(W_DATA_FOLDER, 'BIW CX743 SG*.csv')))

    if _sg_stats_cache and len(csv_files) == len(_sg_files_cache):
        if all(_sg_stats_mtimes.get(os.path.basename(f)) == os.path.getmtime(f) for f in csv_files):
            return

    with sqlite3.connect(DB_FILE, timeout=30) as conn:
        changed = False
        for f in csv_files:
            fname = os.path.basename(f)
            mtime = os.path.getmtime(f)
            if _sg_stats_mtimes.get(fname) == mtime:
                continue
            _parse_file(conn, f)
            _sg_stats_mtimes[fname] = mtime
            changed = True
        if changed:
            conn.commit()

        raw = conn.execute(
            "SELECT col, val FROM measurements "
            "WHERE col LIKE '%AG%' AND val IS NOT NULL"
        ).fetchall()

    col_vals = defaultdict(list)
    for col, val in raw:
        col_vals[col].append(val)

    cache = {}
    for col, vals in col_vals.items():
        n = len(vals)
        if n < 2:
            cache[col] = {'n': n, 'mean': None, 'std': None, 'min': None, 'max': None}
            continue
        mean = sum(vals) / n
        std  = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
        cache[col] = {'n': n, 'mean': round(mean, 6), 'std': round(std, 6),
                      'min': min(vals), 'max': max(vals)}

    _sg_stats_cache = cache
    _sg_files_cache = [os.path.basename(f) for f in csv_files]
    print(f'SG 快取完成：{len(_sg_files_cache)} 個 CSV，{len(_sg_stats_cache)} 個 AG 點位')

# ── CMM XML sync ────────────────────────────────────────────────
def _parse_xml_cmm(conn, f, line_type):
    fname = os.path.basename(f)
    mtime = os.path.getmtime(f)
    try:
        tree = ET.parse(f)
    except Exception as e:
        print(f'  [skip cmm] {fname}: {e}')
        return
    root = tree.getroot()

    hand = job_id = date = ''
    for cmd in root.iter('Command'):
        if cmd.get('Type') == 'Trace Field':
            n = v = ''
            for df in cmd:
                if df.get('Description') == 'Name':  n = df.get('Value', '')
                if df.get('Description') == 'Value': v = df.get('Value', '')
            if n == 'TRACE: Hand':    hand   = v
            elif n == 'TRACE: Job_ID': job_id = v
            elif n == 'START_TIME':
                try:
                    d = datetime.strptime(v.split('-')[0], '%m/%d/%y')
                    date = d.strftime('%Y-%m-%d')
                except ValueError:
                    date = v

    old_ids = [r[0] for r in conn.execute('SELECT id FROM cmm_rows WHERE filename=?', (fname,))]
    if old_ids:
        ph = ','.join('?'*len(old_ids))
        conn.execute(f'DELETE FROM cmm_meas WHERE row_id IN ({ph})', old_ids)
    conn.execute('DELETE FROM cmm_rows WHERE filename=?', (fname,))

    cur = conn.execute(
        'INSERT INTO cmm_rows (filename,line_type,hand,job_id,date) VALUES (?,?,?,?,?)',
        (fname, line_type, hand, job_id, date))
    row_id = cur.lastrowid

    meas = []
    specs = []
    in_dim = False
    ref_id = ''
    for cmd in root.iter('Command'):
        t = cmd.get('Type', '')
        if t == 'Dimension Location':
            in_dim = True
            ref_id = ''
            for df in cmd:
                if df.get('Description') == 'Reference Id':
                    ref_id = df.get('Value', '')
        elif t in ('X Location', 'Y Location', 'Z Location') and in_dim and ref_id:
            axis = nom = measured = plus_tol = minus_tol = None
            for df in cmd:
                d = df.get('Description', '')
                v = df.get('Value', '')
                if d == 'Axis':
                    axis = v
                elif d == 'Nominal':
                    try: nom = float(v)
                    except: pass
                elif d == 'Measured':
                    try: measured = float(v)
                    except: pass
                elif d == 'Plus Tolerance':
                    try: plus_tol = float(v)
                    except: pass
                elif d == 'Minus Tolerance':
                    try: minus_tol = float(v)
                    except: pass
            if axis and nom is not None and measured is not None:
                col = f'{ref_id}_{axis}'
                meas.append((row_id, col, round(measured - nom, 6)))
                if plus_tol is not None and minus_tol is not None:
                    specs.append((col, line_type, plus_tol, minus_tol))
        elif t == 'End Dimension':
            in_dim = False

    if meas:
        conn.executemany('INSERT OR REPLACE INTO cmm_meas (row_id,col,val) VALUES (?,?,?)', meas)
    if specs:
        conn.executemany(
            'INSERT OR REPLACE INTO cmm_specs (col,line_type,usl,lsl) VALUES (?,?,?,?)', specs)
    conn.execute('INSERT OR REPLACE INTO cmm_files (filename,mtime,line_type) VALUES (?,?,?)',
                 (fname, mtime, line_type))
    print(f'  [sync cmm] {fname}')


def sync_cmm_files(line_type):
    global _cmm_stats_cache, _cmm_files_cache, _cmm_mtimes, _cmm_ready
    patterns = CMM_PATTERNS.get(line_type, [])
    xml_files = []
    for pat in patterns:
        xml_files.extend(glob.glob(os.path.join(W_XML_FOLDER, pat)))
    xml_files = sorted(set(xml_files))

    # Pre-load mtimes from DB so already-parsed files are skipped after restart
    if not _cmm_mtimes[line_type]:
        with sqlite3.connect(DB_FILE, timeout=30) as _c:
            _cmm_mtimes[line_type] = {r[0]: r[1] for r in _c.execute(
                'SELECT filename, mtime FROM cmm_files WHERE line_type=?', (line_type,))}

    cached_mtimes = _cmm_mtimes[line_type]
    # Fast path: all files already parsed
    if _cmm_ready[line_type] and len(xml_files) == len(_cmm_files_cache[line_type]):
        if all(cached_mtimes.get(os.path.basename(f)) == os.path.getmtime(f) for f in xml_files):
            return

    with sqlite3.connect(DB_FILE, timeout=30) as conn:
        changed = False
        for f in xml_files:
            fname = os.path.basename(f)
            mtime = os.path.getmtime(f)
            if cached_mtimes.get(fname) == mtime:
                continue
            _parse_xml_cmm(conn, f, line_type)
            cached_mtimes[fname] = mtime
            changed = True
        if changed:
            conn.commit()

        raw = conn.execute(
            'SELECT m.col, m.val FROM cmm_meas m '
            'JOIN cmm_rows r ON m.row_id = r.id '
            'WHERE r.line_type = ? AND m.val IS NOT NULL',
            (line_type,)
        ).fetchall()

    col_vals = defaultdict(list)
    for col, val in raw:
        col_vals[col].append(val)

    cache = {}
    for col, vals in col_vals.items():
        n = len(vals)
        if n < 2:
            cache[col] = {'n': n, 'mean': None, 'std': None, 'min': None, 'max': None}
            continue
        mean = sum(vals) / n
        std  = math.sqrt(sum((v - mean)**2 for v in vals) / (n - 1))
        cache[col] = {'n': n, 'mean': round(mean, 6), 'std': round(std, 6),
                      'min': round(min(vals), 6), 'max': round(max(vals), 6)}

    _cmm_stats_cache[line_type] = cache
    _cmm_files_cache[line_type] = [os.path.basename(f) for f in xml_files]
    _cmm_ready[line_type] = True
    print(f'CMM {line_type.upper()} 完成：{len(xml_files)} 個 XML，{len(cache)} 個點位')


def _init_cmm_background():
    for lt in ('6x', '7x', '8x'):
        try:
            sync_cmm_files(lt)
        except Exception as e:
            print(f'CMM {lt} 初始化失敗: {e}')
    print('=' * 60)
    print('✅ CMM 資料同步完成（6X / 7X / 8X）')
    print('   監控台已就緒，可以正式使用。')
    print('=' * 60)

# ── Request handler ─────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FOLDER, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path   = parsed.path

        # ── /api/stats ──────────────────────────────────────────
        if path == '/api/stats':
            mode = params.get('mode', ['mf'])[0]
            line = params.get('line', ['6x'])[0]
            if mode == 'cmm':
                ready = _cmm_ready.get(line, False)
                cache = _cmm_stats_cache.get(line, {})
                files = _cmm_files_cache.get(line, [])
                result = [{'col': col, **s} for col, s in sorted(cache.items())]
                send_json(self, {'stats': result, 'files': files, 'loading': not ready})
            else:
                with _lock:
                    if mode == 'sg':
                        sync_sg_files()
                        result = [{'col': col, **s} for col, s in sorted(_sg_stats_cache.items())]
                        send_json(self, {'stats': result, 'files': _sg_files_cache})
                    else:
                        sync_csv_files()
                        result = [{'col': col, **s} for col, s in sorted(_stats_cache.items())]
                        send_json(self, {'stats': result, 'files': _files_cache})

        # ── /api/trends/all  (bulk, for front-end preload) ──────
        elif path == '/api/trends/all':
            mode = params.get('mode', ['mf'])[0]
            line = params.get('line', ['6x'])[0]
            if mode == 'cmm':
                # Return only the last 30 dates to keep payload small
                with sqlite3.connect(DB_FILE, timeout=30) as conn:
                    recent = [r[0] for r in conn.execute(
                        'SELECT DISTINCT date FROM cmm_rows WHERE line_type=? '
                        'ORDER BY date DESC LIMIT 30', (line,))]
                    if recent:
                        ph = ','.join('?'*len(recent))
                        rows = conn.execute(
                            f'SELECT m.col, r.job_id, r.date, m.val '
                            f'FROM cmm_meas m JOIN cmm_rows r ON m.row_id = r.id '
                            f'WHERE r.line_type=? AND r.date IN ({ph}) '
                            f'ORDER BY m.col, r.date, r.id',
                            [line]+recent
                        ).fetchall()
                    else:
                        rows = []
                grouped = {}
                for col, job_id, dt, val in rows:
                    if col not in grouped: grouped[col] = []
                    grouped[col].append({'serial_no': job_id, 'date': dt, 'val': val})
                send_json(self, grouped)
            else:
                if mode == 'sg':
                    col_filter = "m.col LIKE '%AG%'"
                else:
                    col_filter = ("(m.col LIKE '%AF%' OR m.col LIKE '%AM%') "
                                  "AND m.col NOT IN ('MF_BIW_AFIT','CX743MCA2_2025','B','FLH','LDVersion XX')")
                with sqlite3.connect(DB_FILE, timeout=30) as conn:
                    rows = conn.execute(
                        f"SELECT m.col, r.serial_no, r.date, m.val "
                        f"FROM measurements m JOIN car_rows r ON m.row_id = r.id "
                        f"WHERE {col_filter} ORDER BY m.col, r.date, r.id"
                    ).fetchall()
                grouped = {}
                for col, sn, dt, val in rows:
                    if col not in grouped: grouped[col] = []
                    grouped[col].append({'serial_no': sn, 'date': dt, 'val': val})
                send_json(self, grouped)

        # ── /api/trend ──────────────────────────────────────────
        elif path == '/api/trend':
            col       = params.get('col',  [''])[0]
            mode      = params.get('mode', ['mf'])[0]
            line      = params.get('line', ['6x'])[0]
            date_from = params.get('from', [''])[0]
            date_to   = params.get('to',   [''])[0]
            if not col:
                send_json(self, {'error': 'col required'}); return

            if mode == 'cmm':
                with sqlite3.connect(DB_FILE, timeout=30) as conn:
                    rows = conn.execute(
                        'SELECT r.job_id, r.date, m.val '
                        'FROM cmm_meas m JOIN cmm_rows r ON m.row_id = r.id '
                        'WHERE r.line_type=? AND m.col=? ORDER BY r.date, r.id',
                        (line, col)
                    ).fetchall()
                data = [{'serial_no': r[0], 'date': r[1], 'val': r[2]} for r in rows]
                send_json(self, {'col': col, 'data': data}); return

            q    = ('SELECT r.serial_no, r.date, m.val '
                    'FROM measurements m JOIN car_rows r ON m.row_id = r.id '
                    'WHERE m.col = ?')
            args = [col]
            if date_from: q += ' AND r.date >= ?'; args.append(date_from)
            if date_to:   q += ' AND r.date <= ?'; args.append(date_to)
            q += ' ORDER BY r.date, r.id'

            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                rows = conn.execute(q, args).fetchall()

            data = [{'serial_no': r[0], 'date': r[1], 'val': r[2]} for r in rows]
            send_json(self, {'col': col, 'data': data})

        # ── /api/specs ──────────────────────────────────────────
        elif path == '/api/specs':
            mode = params.get('mode', ['mf'])[0]
            line = params.get('line', ['6x'])[0]
            if mode == 'cmm':
                def _load_set(fname):
                    p = os.path.join(FOLDER, fname)
                    if os.path.exists(p):
                        with open(p, encoding='utf-8') as f:
                            return set(json.load(f).get(line, []))
                    return set()
                ctq_set  = _load_set('cmm_ctq.json')
                bccp_set = _load_set('cmm_bccp.json')
                with sqlite3.connect(DB_FILE, timeout=30) as conn:
                    rows = conn.execute(
                        'SELECT col, usl, lsl FROM cmm_specs WHERE line_type=?', (line,)
                    ).fetchall()
                matched = {col: {'usl': usl, 'lsl': lsl, 'nom': 0, 'unit': 'mm', 'type': 'CMM', 'area': '',
                                 'is_ctq': col in ctq_set, 'is_bccp': col in bccp_set}
                           for col, usl, lsl in rows}
                send_json(self, {'matched': matched, 'unmatched': []})
            else:
                send_json(self, load_specs(mode))

        # ── /api/settings ───────────────────────────────────────
        elif path == '/api/settings':
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                s_rows = conn.execute(
                    'SELECT col, risk_level, control_usl, control_lsl, control_nominal, risk_description, updated_at, engineer, countermeasure, issue_status, follow_up_date FROM point_settings'
                ).fetchall()
                a_rows = conn.execute(
                    'SELECT col, changed_at, changes FROM audit_log ORDER BY changed_at DESC'
                ).fetchall()
            settings  = {r[0]: {'risk_level': r[1], 'control_usl': r[2], 'control_lsl': r[3],
                                 'control_nominal': r[4], 'risk_description': r[5], 'updated_at': r[6],
                                 'engineer': r[7] or '', 'countermeasure': r[8] or '',
                                 'issue_status': r[9] or 'open', 'follow_up_date': r[10] or ''} for r in s_rows}
            audit_log = [{'col': r[0], 'changed_at': r[1], 'changes': json.loads(r[2])} for r in a_rows]
            send_json(self, {'settings': settings, 'audit_log': audit_log})

        # ── /api/open_report ────────────────────────────────────────
        elif path == '/api/open_report':
            col  = params.get('col', [''])[0]
            line = params.get('line', [''])[0]
            if not line and col:
                with sqlite3.connect(DB_FILE, timeout=30) as _c:
                    r = _c.execute('SELECT line_type FROM cmm_specs WHERE col=? LIMIT 1', (col,)).fetchone()
                    line = r[0] if r else ''
            BIW_REPORT = r'W:\MFG\public\SPC report\BIW'
            folders = {'6x': ['6X'], '7x': ['7XL', '7XR'], '8x': ['8X']}.get(line, [])
            best, best_t = None, 0
            for sub in folders:
                base = os.path.join(BIW_REPORT, sub)
                for root, _, files in os.walk(base):
                    for fn in files:
                        if fn.lower().endswith('.pdf'):
                            fp = os.path.join(root, fn)
                            mt = os.path.getmtime(fp)
                            if mt > best_t:
                                best_t, best = mt, fp
            if best:
                import subprocess
                subprocess.Popen(['explorer', best])
                send_json(self, {'ok': True, 'path': best})
            else:
                send_json(self, {'ok': False, 'error': 'No PDF found'})

        # ── /api/battery/* ──────────────────────────────────────────
        elif path == '/api/battery/specs':
            send_json(self, BATTERY_SPECS)

        elif path == '/api/battery/stats':
            with _lock: sync_battery()
            result = [{'col':col,**s} for col,s in sorted(_battery_stats.items())]
            send_json(self, {'stats':result,'files':_battery_files})

        elif path == '/api/battery/settings':
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                try: conn.execute('ALTER TABLE battery_settings ADD COLUMN nom REAL')
                except Exception: pass
                rows = conn.execute('SELECT col,ucl,lcl,nom,updated_at FROM battery_settings').fetchall()
            send_json(self, {r[0]:{'ucl':r[1],'lcl':r[2],'nom':r[3],'updated_at':r[4]} for r in rows})

        elif path == '/api/battery/trends/all':
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                rows = conn.execute(
                    'SELECT m.col,r.serial_no,r.date,m.val '
                    'FROM battery_meas m JOIN battery_rows r ON m.row_id=r.id '
                    'ORDER BY m.col,r.date,r.id'
                ).fetchall()
            g = {}
            for col,sn,dt,val in rows:
                if col not in g: g[col]=[]
                g[col].append({'serial_no':sn,'date':dt,'val':val})
            send_json(self, g)

        # ── /api/door/* ─────────────────────────────────────────────
        elif path == '/api/door/specs':
            send_json(self, DOOR_SPECS)

        elif path == '/api/door/stats':
            with _lock: sync_door()
            result = [{'col':col,**s} for col,s in sorted(_door_stats.items())]
            send_json(self, {'stats':result,'files':_door_files})

        elif path == '/api/door/settings':
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                rows = conn.execute('SELECT col,ucl,lcl,updated_at FROM door_settings').fetchall()
            send_json(self, {r[0]:{'ucl':r[1],'lcl':r[2],'updated_at':r[3]} for r in rows})

        elif path == '/api/door/trends/all':
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                rows = conn.execute(
                    'SELECT m.col,r.vin,r.date,m.val '
                    'FROM door_meas m JOIN door_rows r ON m.row_id=r.id '
                    'ORDER BY m.col,r.date,r.id'
                ).fetchall()
            g = {}
            for col,vin,dt,val in rows:
                if col not in g: g[col]=[]
                g[col].append({'serial_no':vin,'date':dt,'val':val})
            send_json(self, g)

        # ── /api/lamp/* ─────────────────────────────────────────────
        elif path == '/api/lamp/specs':
            send_json(self, LAMP_SPECS)

        elif path == '/api/lamp/stats':
            with _lock: sync_lamp()
            result = [{'col':col,**s} for col,s in sorted(_lamp_stats.items())]
            send_json(self, {'stats':result,'files':_lamp_files})

        elif path == '/api/lamp/settings':
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                rows = conn.execute('SELECT col,ucl,lcl,nom,updated_at FROM lamp_settings').fetchall()
            send_json(self, {r[0]:{'ucl':r[1],'lcl':r[2],'nom':r[3],'updated_at':r[4]} for r in rows})

        elif path == '/api/lamp/trends/all':
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                rows = conn.execute(
                    'SELECT m.col,r.vin,r.date,m.val '
                    'FROM lamp_meas m JOIN lamp_rows r ON m.row_id=r.id '
                    'ORDER BY m.col,r.date,r.id'
                ).fetchall()
            g = {}
            for col,vin,dt,val in rows:
                if col not in g: g[col]=[]
                g[col].append({'serial_no':vin,'date':dt,'val':val})
            send_json(self, g)

        # ── /api/sc/* ────────────────────────────────────────────────
        elif path == '/api/sc/specs':
            send_json(self, SC_SPECS)

        elif path in ('/api/sc/ice/stats', '/api/sc/fhev/stats'):
            pt = 'ICE' if 'ice' in path else 'FHEV'
            with _lock: sync_sc()
            result = [{'col':col,**s} for col,s in _sc_stats[pt].items()]
            send_json(self, {'stats':result,'files':_sc_files[pt],'powertrain':pt})

        elif path in ('/api/sc/ice/settings', '/api/sc/fhev/settings'):
            pt = 'ICE' if 'ice' in path else 'FHEV'
            col_name = list(SC_SPECS[pt].keys())[0]
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                row = conn.execute('SELECT ucl,lcl,updated_at FROM sc_settings WHERE col=?', (col_name,)).fetchone()
            send_json(self, {col_name:{'ucl':row[0],'lcl':row[1],'updated_at':row[2]}} if row else {})

        elif path in ('/api/sc/ice/trends/all', '/api/sc/fhev/trends/all'):
            pt = 'ICE' if 'ice' in path else 'FHEV'
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                rows = conn.execute(
                    'SELECT m.col,r.vin,r.date,r.build_phase,m.val '
                    'FROM sc_meas m JOIN sc_rows r ON m.row_id=r.id '
                    'WHERE r.powertrain=? ORDER BY m.col,r.date,r.id', (pt,)
                ).fetchall()
            g = {}
            for col,vin,dt,bp,val in rows:
                if col not in g: g[col]=[]
                g[col].append({'serial_no':vin,'date':dt,'build_phase':bp,'val':val})
            send_json(self, g)

        # ── /api/vow/* ───────────────────────────────────────────────
        elif path == '/api/vow/specs':
            send_json(self, VOW_SPECS)

        elif path == '/api/vow/stats':
            with _lock: sync_vow()
            result = [{'col':col,**s} for col,s in sorted(_vow_stats.items())]
            send_json(self, {'stats':result,'files':_vow_files})

        elif path == '/api/vow/settings':
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                rows = conn.execute('SELECT col,ucl,lcl,updated_at FROM vow_settings').fetchall()
            send_json(self, {r[0]:{'ucl':r[1],'lcl':r[2],'updated_at':r[3]} for r in rows})

        elif path == '/api/vow/trends/all':
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                rows = conn.execute(
                    'SELECT m.col,r.vin,r.date,r.sunroof,m.val '
                    'FROM vow_meas m JOIN vow_rows r ON m.row_id=r.id '
                    'ORDER BY m.col,r.date,r.id'
                ).fetchall()
            g = {}
            for col,vin,dt,sunroof,val in rows:
                if col not in g: g[col]=[]
                g[col].append({'serial_no':vin,'date':dt,'sunroof':sunroof,'val':val})
            send_json(self, g)

        # ── /api/hunter/* ────────────────────────────────────────────
        elif path == '/api/hunter/specs':
            send_json(self, HUNTER_SPECS)

        elif path in ('/api/hunter/ice/stats', '/api/hunter/fhev/stats'):
            pt = 'ICE' if 'ice' in path else 'FHEV'
            with _lock: sync_hunter()
            result = [{'col':col,**s} for col,s in sorted(_hunter_stats[pt].items())]
            send_json(self, {'stats':result,'files':_hunter_files[pt],'powertrain':pt})

        elif path in ('/api/hunter/ice/settings', '/api/hunter/fhev/settings'):
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                rows = conn.execute('SELECT col,ucl,lcl,nom,updated_at FROM hunter_settings').fetchall()
            send_json(self, {r[0]:{'ucl':r[1],'lcl':r[2],'nom':r[3],'updated_at':r[4]} for r in rows})

        elif path in ('/api/hunter/ice/trends/all', '/api/hunter/fhev/trends/all'):
            pt = 'ICE' if 'ice' in path else 'FHEV'
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                rows = conn.execute(
                    'SELECT m.col,r.vin,r.date,r.rot,m.val '
                    'FROM hunter_meas m JOIN hunter_rows r ON m.row_id=r.id '
                    'WHERE r.powertrain=? ORDER BY m.col,r.date,r.id', (pt,)
                ).fetchall()
            g = {}
            for col,vin,dt,rot,val in rows:
                if col not in g: g[col]=[]
                g[col].append({'serial_no':vin,'date':dt,'rot':rot,'val':val})
            send_json(self, g)

        else:
            super().do_GET()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in ('/api/settings', '/api/battery/settings', '/api/door/settings', '/api/lamp/settings', '/api/vow/settings', '/api/sc/ice/settings', '/api/sc/fhev/settings', '/api/hunter/settings'):
            self.send_error(404); return

        length = int(self.headers.get('Content-Length', 0))
        body   = json.loads(self.rfile.read(length))

        if parsed.path == '/api/battery/settings':
            col = body.get('col')
            if not col:
                send_json(self, {'error': 'col required'}); return
            ucl = body.get('ucl'); lcl = body.get('lcl'); nom = body.get('nom')
            now = datetime.now().isoformat(timespec='seconds')
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                try: conn.execute('ALTER TABLE battery_settings ADD COLUMN nom REAL')
                except Exception: pass
                conn.execute('INSERT OR REPLACE INTO battery_settings (col,ucl,lcl,nom,updated_at) VALUES (?,?,?,?,?)',
                             (col, ucl, lcl, nom, now))
                conn.commit()
            send_json(self, {'ok': True, 'updated_at': now}); return

        if parsed.path == '/api/door/settings':
            col = body.get('col')
            if not col:
                send_json(self, {'error': 'col required'}); return
            ucl = body.get('ucl'); lcl = body.get('lcl')
            now = datetime.now().isoformat(timespec='seconds')
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                conn.execute('INSERT OR REPLACE INTO door_settings (col,ucl,lcl,updated_at) VALUES (?,?,?,?)',
                             (col, ucl, lcl, now))
                conn.commit()
            send_json(self, {'ok': True, 'updated_at': now}); return

        if parsed.path == '/api/lamp/settings':
            col = body.get('col')
            if not col:
                send_json(self, {'error': 'col required'}); return
            ucl = body.get('ucl'); lcl = body.get('lcl'); nom = body.get('nom')
            now = datetime.now().isoformat(timespec='seconds')
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                conn.execute('INSERT OR REPLACE INTO lamp_settings (col,ucl,lcl,nom,updated_at) VALUES (?,?,?,?,?)',
                             (col, ucl, lcl, nom, now))
                conn.commit()
            send_json(self, {'ok': True, 'updated_at': now}); return

        if parsed.path == '/api/vow/settings':
            col = body.get('col')
            if not col:
                send_json(self, {'error': 'col required'}); return
            ucl = body.get('ucl'); lcl = body.get('lcl')
            now = datetime.now().isoformat(timespec='seconds')
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                conn.execute('INSERT OR REPLACE INTO vow_settings (col,ucl,lcl,updated_at) VALUES (?,?,?,?)',
                             (col, ucl, lcl, now))
                conn.commit()
            send_json(self, {'ok': True, 'updated_at': now}); return

        if parsed.path in ('/api/sc/ice/settings', '/api/sc/fhev/settings'):
            col = body.get('col')
            if not col:
                send_json(self, {'error': 'col required'}); return
            ucl = body.get('ucl'); lcl = body.get('lcl')
            now = datetime.now().isoformat(timespec='seconds')
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                conn.execute('INSERT OR REPLACE INTO sc_settings (col,ucl,lcl,updated_at) VALUES (?,?,?,?)',
                             (col, ucl, lcl, now))
                conn.commit()
            send_json(self, {'ok': True, 'updated_at': now}); return

        if parsed.path == '/api/hunter/settings':
            col = body.get('col')
            if not col:
                send_json(self, {'error': 'col required'}); return
            ucl = body.get('ucl'); lcl = body.get('lcl'); nom = body.get('nom')
            now = datetime.now().isoformat(timespec='seconds')
            with sqlite3.connect(DB_FILE, timeout=30) as conn:
                conn.execute('INSERT OR REPLACE INTO hunter_settings (col,ucl,lcl,nom,updated_at) VALUES (?,?,?,?,?)',
                             (col, ucl, lcl, nom, now))
                conn.commit()
            send_json(self, {'ok': True, 'updated_at': now}); return

        col    = body.get('col')
        if not col:
            send_json(self, {'error': 'col required'}); return

        with sqlite3.connect(DB_FILE, timeout=30) as conn:
            row = conn.execute(
                'SELECT risk_level, control_usl, control_lsl, control_nominal, risk_description, engineer, countermeasure, issue_status, follow_up_date FROM point_settings WHERE col=?', (col,)
            ).fetchone()
            old = {'risk_level': row[0], 'control_usl': row[1], 'control_lsl': row[2],
                   'control_nominal': row[3], 'risk_description': row[4],
                   'engineer': row[5] or '', 'countermeasure': row[6] or '',
                   'issue_status': row[7] or 'open', 'follow_up_date': row[8] or ''} if row else \
                  {'risk_level': None, 'control_usl': None, 'control_lsl': None, 'control_nominal': None,
                   'risk_description': None, 'engineer': '', 'countermeasure': '', 'issue_status': 'open',
                   'follow_up_date': ''}

            new_risk  = body.get('risk_level') or None
            new_usl   = body.get('control_usl')
            new_lsl   = body.get('control_lsl')
            new_nom   = body.get('control_nominal')
            new_desc  = body.get('risk_description', '') or ''
            new_eng   = body.get('engineer', '') or ''
            new_cm    = body.get('countermeasure', '') or ''
            new_status= body.get('issue_status', 'open') or 'open'
            new_fud   = body.get('follow_up_date', '') or ''

            changes = {}
            for k, nv in [('risk_level', new_risk), ('control_usl', new_usl),
                          ('control_lsl', new_lsl), ('control_nominal', new_nom),
                          ('risk_description', new_desc), ('engineer', new_eng),
                          ('countermeasure', new_cm), ('issue_status', new_status),
                          ('follow_up_date', new_fud)]:
                if old[k] != nv:
                    changes[k] = {'from': old[k], 'to': nv}

            now = datetime.now().isoformat(timespec='seconds')
            conn.execute(
                'INSERT OR REPLACE INTO point_settings (col,risk_level,control_usl,control_lsl,control_nominal,risk_description,updated_at,engineer,countermeasure,issue_status,follow_up_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (col, new_risk, new_usl, new_lsl, new_nom, new_desc, now, new_eng, new_cm, new_status, new_fud)
            )
            if changes:
                conn.execute('INSERT INTO audit_log (col,changed_at,changes) VALUES (?,?,?)',
                             (col, now, json.dumps(changes, ensure_ascii=False)))
            conn.commit()

        send_json(self, {'ok': True, 'changed_at': now})

    def log_message(self, *a): pass

# ── Entry point ─────────────────────────────────────────────────
def _kill_old_server():
    """Kill any existing process listening on PORT so hot-restart works cleanly."""
    import subprocess
    NO_WIN = 0x08000000  # CREATE_NO_WINDOW
    my_pid = str(os.getpid())
    try:
        r = subprocess.run(['netstat', '-ano'], capture_output=True, text=True,
                           creationflags=NO_WIN)
        for line in r.stdout.splitlines():
            if f':{PORT}' in line and 'LISTENING' in line:
                pid = line.strip().split()[-1]
                if pid != my_pid:
                    subprocess.run(['taskkill', '/F', '/PID', pid],
                                   capture_output=True, creationflags=NO_WIN)
                    print(f'已結束舊伺服器程序 PID {pid}')
                    time.sleep(0.5)
    except Exception:
        pass

def open_browser():
    time.sleep(1.5)
    webbrowser.open(f'http://localhost:{PORT}/index.html')

if __name__ == '__main__':
    _kill_old_server()
    print('=== BIW CMM Dashboard ===')
    init_db()
    sync_csv_files()
    sync_sg_files()
    sync_battery()
    sync_door()
    sync_lamp()
    sync_vow()
    sync_sc()
    sync_hunter()
    threading.Thread(target=open_browser, daemon=True).start()
    threading.Thread(target=_init_cmm_background, daemon=True).start()
    print(f'伺服器啟動  →  http://localhost:{PORT}/cmm_dashboard.html')
    print('按 Ctrl+C 停止\n')
    with http.server.ThreadingHTTPServer(('', PORT), Handler) as s:
        s.serve_forever()
