#!/usr/bin/env python3
"""
Parse TUS 2026/1 Kontenjan PDF and generate an interactive HTML dashboard.
Run: python3 build.py
Output: index.html
"""

import re
import json
import sys
import os

# Add local libs to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))

import pdfplumber

PDF_PATH = os.path.join(os.path.dirname(__file__), 'kont_tablo12032026.pdf')
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), 'index.html')

# All known specialties sorted by length descending (to avoid partial matches)
SPECIALTIES = sorted([
    'PLASTİK, REKONSTRÜKTİF VE ESTETİK CERRAHİ',
    'ÇOCUK VE ERGEN RUH SAĞLIĞI VE HASTALIKLARI',
    'ENFEKSİYON HASTALIKLARI VE KLİNİK MİKROBİYOLOJİ',
    'SUALTI HEKİMLİĞİ VE HİPERBARİK TIP',
    'HAVA VE UZAY HEKİMLİĞİ',
    'ANESTEZİYOLOJİ VE REANİMASYON',
    'KADIN HASTALIKLARI VE DOĞUM',
    'KALP VE DAMAR CERRAHİSİ',
    'KULAK BURUN BOĞAZ HASTALIKLARI',
    'ORTOPEDİ VE TRAVMATOLOJİ',
    'ÇOCUK SAĞLIĞI VE HASTALIKLARI',
    'RUH SAĞLIĞI VE HASTALIKLARI',
    'FİZİKSEL TIP VE REHABİLİTASYON',
    'DERİ VE ZÜHREVİ HASTALIKLARI',
    'RADYASYON ONKOLOJİSİ',
    'BEYİN VE SİNİR CERRAHİSİ',
    'ASKERİ SAĞLIK HİZMETLERİ',
    'GÖĞÜS CERRAHİSİ',
    'GÖĞÜS HASTALIKLARI',
    'ÇOCUK CERRAHİSİ',
    'AİLE HEKİMLİĞİ',
    'İÇ HASTALIKLARI',
    'GÖZ HASTALIKLARI',
    'TIBBİ BİYOKİMYA',
    'TIBBİ GENETİK',
    'TIBBİ MİKROBİYOLOJİ',
    'TIBBİ PATOLOJİ',
    'HALK SAĞLIĞI',
    'GENEL CERRAHİ',
    'SPOR HEKİMLİĞİ',
    'KARDİYOLOJİ',
    'NÜKLEER TIP',
    'RADYOLOJİ',
    'NÖROLOJİ',
    'ADLİ TIP',
    'ACİL TIP',
    'ÜROLOJİ',
], key=len, reverse=True)

SINIF_LABELS = {
    'S': 'Sağlık Bakanlığı',
    'T': 'Askeri / Özel',
    'K': 'Kıbrıs (KKTC)',
    'A': 'Adli',
}

TUR_LABELS = {
    'EAH': 'Eğitim ve Araştırma Hastanesi',
    'KKTC': 'KKTC Kontenjanlı',
    'MAP': 'MAP (Milli Savunma)',
    'MSB': 'MSB (Milli Savunma Bakanlığı)',
    'BNDH': 'Burhan Nalbantoğlu Devlet Hastanesi',
    'ADL': 'Adli Tıp',
    'İçişleri Bakanlığı': 'İçişleri Bakanlığı',
}


def extract_hospital_short(kurum_full):
    """Extract a short display name for the institution."""
    # Try to find the hospital name in common patterns
    patterns = [
        r'T\.C\. Sağlık Bakanlığı (.+?)(?:\s+Sağlık Bilimleri|\s+Ankara Yıldırım|$)',
        r'Adli Tıp Kurumu',
        r'Dr\. Burhan Nalbantoğlu Devlet Hastanesi',
    ]
    for pat in patterns:
        m = re.search(pat, kurum_full)
        if m:
            return m.group(0).replace('T.C. Sağlık Bakanlığı ', '').strip()
    # Fallback: first 60 chars
    return kurum_full[:60].strip() if len(kurum_full) > 60 else kurum_full


def parse_data_line(line):
    line = line.strip()
    if not line:
        return None

    parts = line.split()
    if not parts or parts[0] not in ('S', 'T', 'K', 'A'):
        return None

    # Find specialty anchor (longest match first)
    specialty = None
    specialty_pos = -1
    for spec in SPECIALTIES:
        pos = line.find(spec)
        if pos > 0:
            specialty = spec
            specialty_pos = pos
            break

    if specialty is None:
        return None

    prefix = line[:specialty_pos].strip()
    suffix = line[specialty_pos + len(specialty):].strip()

    # Parse suffix: NUMBER [dipnot N]
    suffix_parts = suffix.split()
    if not suffix_parts:
        return None

    try:
        kontenjan = int(suffix_parts[0])
    except ValueError:
        return None

    dipnot = None
    if len(suffix_parts) >= 3 and suffix_parts[1] == 'dipnot':
        try:
            dipnot = int(suffix_parts[2])
        except ValueError:
            pass

    # Parse prefix: SINIF [TÜR] İL KURUM_FULL
    prefix_parts = prefix.split()
    if len(prefix_parts) < 3:
        return None

    sinif = prefix_parts[0]

    # "İçişleri Bakanlığı" is a two-word TÜR
    if prefix_parts[1] == 'İçişleri' and len(prefix_parts) > 2 and prefix_parts[2] == 'Bakanlığı':
        tur = 'İçişleri Bakanlığı'
        rest_start = 3
    else:
        tur = prefix_parts[1]
        rest_start = 2

    if len(prefix_parts) <= rest_start:
        return None

    il = prefix_parts[rest_start]
    kurum_full = ' '.join(prefix_parts[rest_start + 1:])
    hospital_short = extract_hospital_short(kurum_full)

    return {
        's': sinif,
        't': tur,
        'i': il,
        'k': hospital_short,
        'kf': kurum_full,
        'u': specialty,
        'n': kontenjan,
        'd': dipnot,
    }


def main():
    print(f"Reading PDF: {PDF_PATH}")
    records = []

    with pdfplumber.open(PDF_PATH) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                record = parse_data_line(line)
                if record:
                    records.append(record)

    print(f"Parsed {len(records)} records")
    total_quota = sum(r['n'] for r in records)
    print(f"Total quota: {total_quota}")

    html = generate_html(records)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Generated: {OUTPUT_PATH}")


def generate_html(records):
    data_json = json.dumps(records, ensure_ascii=False, separators=(',', ':'))
    sinif_labels_json = json.dumps(SINIF_LABELS, ensure_ascii=False)
    tur_labels_json = json.dumps(TUR_LABELS, ensure_ascii=False)

    return f'''<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TUS 2026/1 — Kontenjan Tablosu</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --bg: #f0f4f8;
  --surface: #ffffff;
  --surface2: #f8fafc;
  --border: #e2e8f0;
  --primary: #2563eb;
  --primary-light: #dbeafe;
  --primary-dark: #1d4ed8;
  --accent: #0891b2;
  --text: #1e293b;
  --text-muted: #64748b;
  --success: #059669;
  --warning: #d97706;
  --radius: 12px;
  --shadow: 0 1px 3px rgba(0,0,0,.08), 0 4px 12px rgba(0,0,0,.05);
  --shadow-lg: 0 4px 6px rgba(0,0,0,.07), 0 10px 25px rgba(0,0,0,.1);
}}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}
header {{ background: linear-gradient(135deg, #1e40af 0%, #0891b2 100%); color: white; padding: 20px 24px; box-shadow: var(--shadow-lg); }}
header h1 {{ font-size: 1.5rem; font-weight: 700; letter-spacing: -.02em; }}
header p {{ font-size: .85rem; opacity: .85; margin-top: 4px; }}
.container {{ max-width: 1600px; margin: 0 auto; padding: 20px 16px; }}

/* Summary Cards */
.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 20px; }}
@media (max-width: 900px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 500px) {{ .cards {{ grid-template-columns: 1fr; }} }}
.card {{ background: var(--surface); border-radius: var(--radius); padding: 18px 20px; box-shadow: var(--shadow); border-left: 4px solid var(--primary); }}
.card.accent1 {{ border-color: #2563eb; }}
.card.accent2 {{ border-color: #0891b2; }}
.card.accent3 {{ border-color: #7c3aed; }}
.card.accent4 {{ border-color: #059669; }}
.card-label {{ font-size: .75rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); }}
.card-value {{ font-size: 2rem; font-weight: 800; margin-top: 4px; color: var(--text); line-height: 1; }}
.card-sub {{ font-size: .8rem; color: var(--text-muted); margin-top: 6px; }}

/* Filters */
.filters-wrap {{ background: var(--surface); border-radius: var(--radius); padding: 18px 20px; box-shadow: var(--shadow); margin-bottom: 20px; }}
.filters-wrap h2 {{ font-size: .9rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 14px; }}
.filter-grid {{ display: grid; grid-template-columns: 2fr 1fr 1fr 1fr 1fr auto; gap: 10px; align-items: end; }}
@media (max-width: 1100px) {{ .filter-grid {{ grid-template-columns: 1fr 1fr 1fr; }} }}
@media (max-width: 650px) {{ .filter-grid {{ grid-template-columns: 1fr; }} }}
.filter-group label {{ display: block; font-size: .75rem; font-weight: 600; color: var(--text-muted); margin-bottom: 5px; text-transform: uppercase; letter-spacing: .04em; }}
.filter-group input, .filter-group select {{
  width: 100%; padding: 8px 12px; border: 1.5px solid var(--border);
  border-radius: 8px; font-size: .875rem; background: var(--surface2); color: var(--text);
  transition: border-color .15s;
  -webkit-appearance: none; appearance: none;
}}
.filter-group select {{ cursor: pointer; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%2364748b' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 10px center; padding-right: 30px; }}
.filter-group input:focus, .filter-group select:focus {{ outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(37,99,235,.1); }}
.sinif-btns {{ display: flex; gap: 6px; flex-wrap: wrap; }}
.sinif-btn {{ padding: 7px 14px; border-radius: 8px; border: 1.5px solid var(--border); background: var(--surface2); font-size: .8rem; font-weight: 600; cursor: pointer; transition: all .15s; color: var(--text-muted); white-space: nowrap; }}
.sinif-btn.active {{ background: var(--primary); border-color: var(--primary); color: white; }}
.sinif-btn:hover:not(.active) {{ border-color: var(--primary); color: var(--primary); }}
.btn-reset {{ padding: 8px 18px; background: #ef4444; color: white; border: none; border-radius: 8px; font-size: .875rem; font-weight: 600; cursor: pointer; transition: background .15s; white-space: nowrap; }}
.btn-reset:hover {{ background: #dc2626; }}

/* Charts */
.charts-grid {{ display: grid; grid-template-columns: 1fr 1fr 300px; gap: 16px; margin-bottom: 20px; }}
@media (max-width: 1200px) {{ .charts-grid {{ grid-template-columns: 1fr 1fr; }} .chart-donut {{ grid-column: 1 / -1; }} }}
@media (max-width: 700px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}
.chart-card {{ background: var(--surface); border-radius: var(--radius); padding: 18px; box-shadow: var(--shadow); }}
.chart-card h3 {{ font-size: .85rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 14px; }}
.chart-wrap {{ position: relative; height: 260px; }}
.chart-donut .chart-wrap {{ height: 260px; }}

/* Table */
.table-wrap {{ background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }}
.table-header {{ display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid var(--border); flex-wrap: wrap; gap: 10px; }}
.table-header h3 {{ font-size: .9rem; font-weight: 700; color: var(--text); }}
.table-info {{ font-size: .8rem; color: var(--text-muted); }}
.table-scroll {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: .83rem; }}
thead tr {{ background: var(--surface2); }}
th {{ padding: 10px 12px; text-align: left; font-size: .73rem; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); white-space: nowrap; cursor: pointer; user-select: none; border-bottom: 2px solid var(--border); }}
th:hover {{ color: var(--primary); }}
th.sorted-asc::after {{ content: ' ↑'; color: var(--primary); }}
th.sorted-desc::after {{ content: ' ↓'; color: var(--primary); }}
td {{ padding: 9px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
tr:last-child td {{ border-bottom: none; }}
tr:hover td {{ background: #f8faff; }}
.badge {{ display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px; font-size: .72rem; font-weight: 700; white-space: nowrap; }}
.badge-S {{ background: #dbeafe; color: #1d4ed8; }}
.badge-T {{ background: #fef3c7; color: #92400e; }}
.badge-K {{ background: #d1fae5; color: #065f46; }}
.badge-A {{ background: #fce7f3; color: #9d174d; }}
.quota-cell {{ font-weight: 800; font-size: .95rem; color: var(--primary); }}
.quota-bar {{ display: inline-block; height: 6px; background: var(--primary-light); border-radius: 3px; margin-left: 6px; vertical-align: middle; }}
.quota-bar-fill {{ height: 6px; background: var(--primary); border-radius: 3px; }}
.kurum-cell {{ max-width: 280px; }}
.kurum-cell span {{ display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .8rem; color: var(--text-muted); }}
.uzmanlik-cell {{ font-weight: 600; }}
.pagination {{ display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-top: 1px solid var(--border); flex-wrap: wrap; gap: 10px; }}
.page-btns {{ display: flex; gap: 4px; }}
.page-btn {{ padding: 5px 10px; border: 1.5px solid var(--border); background: var(--surface2); border-radius: 6px; font-size: .8rem; cursor: pointer; transition: all .15s; }}
.page-btn:hover, .page-btn.active {{ background: var(--primary); border-color: var(--primary); color: white; }}
.page-btn:disabled {{ opacity: .4; cursor: not-allowed; }}
.page-info {{ font-size: .8rem; color: var(--text-muted); }}
.no-data {{ text-align: center; padding: 40px; color: var(--text-muted); font-size: .9rem; }}
</style>
</head>
<body>
<header>
  <h1>TUS 2026 — 1. Dönem Uzmanlık Öğrencisi Kontenjan Tablosu</h1>
  <p>Kaynak: Tıpta Uzmanlık Kurulu — 12 Mart 2026</p>
</header>
<div class="container">
  <!-- Summary Cards -->
  <div class="cards">
    <div class="card accent1">
      <div class="card-label">Toplam Kontenjan</div>
      <div class="card-value" id="stat-total">—</div>
      <div class="card-sub" id="stat-total-sub">Filtrelenmiş kontenjan</div>
    </div>
    <div class="card accent2">
      <div class="card-label">Kayıt Sayısı</div>
      <div class="card-value" id="stat-rows">—</div>
      <div class="card-sub" id="stat-rows-sub">Uzmanlık alanı kaydı</div>
    </div>
    <div class="card accent3">
      <div class="card-label">İl Sayısı</div>
      <div class="card-value" id="stat-cities">—</div>
      <div class="card-sub">Farklı il</div>
    </div>
    <div class="card accent4">
      <div class="card-label">Kurum Sayısı</div>
      <div class="card-value" id="stat-kurums">—</div>
      <div class="card-sub">Farklı kurum</div>
    </div>
  </div>

  <!-- Filters -->
  <div class="filters-wrap">
    <h2>Filtreler</h2>
    <div class="filter-grid">
      <div class="filter-group">
        <label>Kurum veya Uzmanlık Ara</label>
        <input type="text" id="search" placeholder="Kurum adı, şehir veya uzmanlık alanı...">
      </div>
      <div class="filter-group">
        <label>İl</label>
        <select id="filter-il"><option value="">Tüm İller</option></select>
      </div>
      <div class="filter-group">
        <label>Uzmanlık Alanı</label>
        <select id="filter-uzmanlik"><option value="">Tüm Alanlar</option></select>
      </div>
      <div class="filter-group">
        <label>Tür</label>
        <select id="filter-tur"><option value="">Tüm Türler</option></select>
      </div>
      <div class="filter-group">
        <label>Sınıf</label>
        <div class="sinif-btns" id="sinif-btns">
          <button class="sinif-btn active" data-sinif="">Tümü</button>
          <button class="sinif-btn" data-sinif="S">S</button>
          <button class="sinif-btn" data-sinif="T">T</button>
          <button class="sinif-btn" data-sinif="K">K</button>
          <button class="sinif-btn" data-sinif="A">A</button>
        </div>
      </div>
      <div class="filter-group">
        <label>&nbsp;</label>
        <button class="btn-reset" onclick="resetFilters()">Sıfırla</button>
      </div>
    </div>
  </div>

  <!-- Charts -->
  <div class="charts-grid">
    <div class="chart-card">
      <h3>En Yüksek Kontenjan — Uzmanlık Alanları (İlk 15)</h3>
      <div class="chart-wrap"><canvas id="chartSpec"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>En Yüksek Kontenjan — İller (İlk 15)</h3>
      <div class="chart-wrap"><canvas id="chartCity"></canvas></div>
    </div>
    <div class="chart-card chart-donut">
      <h3>Sınıf Dağılımı</h3>
      <div class="chart-wrap"><canvas id="chartSinif"></canvas></div>
    </div>
  </div>

  <!-- Data Table -->
  <div class="table-wrap">
    <div class="table-header">
      <h3>Kontenjan Listesi</h3>
      <div class="table-info" id="table-info">Yükleniyor...</div>
    </div>
    <div class="table-scroll">
      <table id="main-table">
        <thead>
          <tr>
            <th onclick="sortBy('s')">Sınıf</th>
            <th onclick="sortBy('t')">Tür</th>
            <th onclick="sortBy('i')">İl</th>
            <th>Kurum</th>
            <th onclick="sortBy('u')">Uzmanlık Alanı</th>
            <th onclick="sortBy('n')">Kontenjan</th>
          </tr>
        </thead>
        <tbody id="table-body"></tbody>
      </table>
      <div class="no-data" id="no-data" style="display:none">Filtrelere uygun kayıt bulunamadı.</div>
    </div>
    <div class="pagination">
      <div class="page-info" id="page-info"></div>
      <div class="page-btns" id="page-btns"></div>
    </div>
  </div>
</div>

<script>
const ALL_DATA = {data_json};
const SINIF_LABELS = {sinif_labels_json};
const TUR_LABELS = {tur_labels_json};

// State
let filtered = [...ALL_DATA];
let sortCol = 'n';
let sortDir = -1; // -1 = desc
let page = 1;
const PAGE_SIZE = 50;
let activeSinif = '';

// Max quota for bar visualization
const MAX_N = Math.max(...ALL_DATA.map(r => r.n));

// Chart instances
let chartSpec, chartCity, chartSinif;

// ---- Initialize ----
function init() {{
  populateDropdowns();
  document.getElementById('search').addEventListener('input', applyFilters);
  document.getElementById('filter-il').addEventListener('change', applyFilters);
  document.getElementById('filter-uzmanlik').addEventListener('change', applyFilters);
  document.getElementById('filter-tur').addEventListener('change', applyFilters);
  document.querySelectorAll('.sinif-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
      activeSinif = btn.dataset.sinif;
      document.querySelectorAll('.sinif-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      applyFilters();
    }});
  }});
  applyFilters();
  updateHeaderSortIndicators();
}}

function populateDropdowns() {{
  const ils = [...new Set(ALL_DATA.map(r => r.i))].sort();
  const uzmanliklar = [...new Set(ALL_DATA.map(r => r.u))].sort();
  const turler = [...new Set(ALL_DATA.map(r => r.t))].sort();

  const ilSel = document.getElementById('filter-il');
  ils.forEach(v => ilSel.insertAdjacentHTML('beforeend', `<option value="${{v}}">${{v}}</option>`));

  const uzSel = document.getElementById('filter-uzmanlik');
  uzmanliklar.forEach(v => uzSel.insertAdjacentHTML('beforeend', `<option value="${{v}}">${{v}}</option>`));

  const turSel = document.getElementById('filter-tur');
  turler.forEach(v => turSel.insertAdjacentHTML('beforeend', `<option value="${{v}}">${{TUR_LABELS[v] || v}} (${{v}})</option>`));
}}

// ---- Filtering ----
function applyFilters() {{
  const search = document.getElementById('search').value.toLowerCase().trim();
  const filterIl = document.getElementById('filter-il').value;
  const filterUz = document.getElementById('filter-uzmanlik').value;
  const filterTur = document.getElementById('filter-tur').value;

  filtered = ALL_DATA.filter(r => {{
    if (activeSinif && r.s !== activeSinif) return false;
    if (filterIl && r.i !== filterIl) return false;
    if (filterUz && r.u !== filterUz) return false;
    if (filterTur && r.t !== filterTur) return false;
    if (search) {{
      const haystack = (r.i + ' ' + r.k + ' ' + r.kf + ' ' + r.u + ' ' + r.t).toLowerCase();
      if (!haystack.includes(search)) return false;
    }}
    return true;
  }});

  page = 1;
  sortData();
  updateStats();
  updateCharts();
  renderTable();
}}

function resetFilters() {{
  document.getElementById('search').value = '';
  document.getElementById('filter-il').value = '';
  document.getElementById('filter-uzmanlik').value = '';
  document.getElementById('filter-tur').value = '';
  activeSinif = '';
  document.querySelectorAll('.sinif-btn').forEach(b => b.classList.remove('active'));
  document.querySelector('.sinif-btn[data-sinif=""]').classList.add('active');
  applyFilters();
}}

// ---- Sorting ----
function sortBy(col) {{
  if (sortCol === col) {{ sortDir *= -1; }} else {{ sortCol = col; sortDir = col === 'n' ? -1 : 1; }}
  page = 1;
  sortData();
  renderTable();
  updateHeaderSortIndicators();
}}

function sortData() {{
  filtered.sort((a, b) => {{
    let av = a[sortCol], bv = b[sortCol];
    if (typeof av === 'string') av = av.toLowerCase();
    if (typeof bv === 'string') bv = bv.toLowerCase();
    if (av < bv) return -sortDir;
    if (av > bv) return sortDir;
    return 0;
  }});
}}

function updateHeaderSortIndicators() {{
  document.querySelectorAll('th').forEach(th => {{
    th.classList.remove('sorted-asc', 'sorted-desc');
  }});
  const cols = ['s', 't', 'i', null, 'u', 'n'];
  const thEls = document.querySelectorAll('#main-table thead th');
  cols.forEach((col, i) => {{
    if (col === sortCol) {{
      thEls[i].classList.add(sortDir === 1 ? 'sorted-asc' : 'sorted-desc');
    }}
  }});
}}

// ---- Stats ----
function updateStats() {{
  const total = filtered.reduce((s, r) => s + r.n, 0);
  const cities = new Set(filtered.map(r => r.i)).size;
  const kurums = new Set(filtered.map(r => r.kf)).size;
  document.getElementById('stat-total').textContent = total.toLocaleString('tr-TR');
  document.getElementById('stat-total-sub').textContent = `${{filtered.length}} kayıtta toplam kontenjan`;
  document.getElementById('stat-rows').textContent = filtered.length.toLocaleString('tr-TR');
  document.getElementById('stat-rows-sub').textContent = `Toplam ${{ALL_DATA.length}} kayıttan`;
  document.getElementById('stat-cities').textContent = cities;
  document.getElementById('stat-kurums').textContent = kurums;
}}

// ---- Charts ----
function aggregateTop(field, n = 15) {{
  const map = {{}};
  filtered.forEach(r => {{
    map[r[field]] = (map[r[field]] || 0) + r.n;
  }});
  return Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, n);
}}

const COLORS = [
  '#2563eb','#0891b2','#7c3aed','#059669','#d97706',
  '#dc2626','#db2777','#ea580c','#16a34a','#9333ea',
  '#0284c7','#b45309','#be185d','#15803d','#4f46e5'
];

function shortLabel(label, max = 28) {{
  return label.length > max ? label.slice(0, max) + '…' : label;
}}

function updateCharts() {{
  const specData = aggregateTop('u', 15);
  const cityData = aggregateTop('i', 15);

  // Specialty bar chart
  if (chartSpec) chartSpec.destroy();
  const ctxSpec = document.getElementById('chartSpec').getContext('2d');
  chartSpec = new Chart(ctxSpec, {{
    type: 'bar',
    data: {{
      labels: specData.map(d => shortLabel(d[0], 30)),
      datasets: [{{ data: specData.map(d => d[1]), backgroundColor: COLORS, borderRadius: 5, borderSkipped: false }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.raw.toLocaleString('tr-TR')}} kontenjan` }} }} }},
      scales: {{ x: {{ grid: {{ color: '#f1f5f9' }}, ticks: {{ font: {{ size: 11 }} }} }}, y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }} }}
    }}
  }});

  // City bar chart
  if (chartCity) chartCity.destroy();
  const ctxCity = document.getElementById('chartCity').getContext('2d');
  chartCity = new Chart(ctxCity, {{
    type: 'bar',
    data: {{
      labels: cityData.map(d => d[0]),
      datasets: [{{ data: cityData.map(d => d[1]), backgroundColor: COLORS, borderRadius: 5, borderSkipped: false }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.raw.toLocaleString('tr-TR')}} kontenjan` }} }} }},
      scales: {{ x: {{ grid: {{ color: '#f1f5f9' }}, ticks: {{ font: {{ size: 11 }} }} }}, y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }} }}
    }}
  }});

  // Sinif donut
  const sinifMap = {{}};
  filtered.forEach(r => {{ sinifMap[r.s] = (sinifMap[r.s] || 0) + r.n; }});
  const sinifEntries = Object.entries(sinifMap).sort((a, b) => b[1] - a[1]);
  if (chartSinif) chartSinif.destroy();
  const ctxSinif = document.getElementById('chartSinif').getContext('2d');
  chartSinif = new Chart(ctxSinif, {{
    type: 'doughnut',
    data: {{
      labels: sinifEntries.map(d => `${{d[0]}} — ${{SINIF_LABELS[d[0]] || d[0]}}`),
      datasets: [{{ data: sinifEntries.map(d => d[1]), backgroundColor: COLORS, hoverOffset: 6 }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      cutout: '60%',
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ font: {{ size: 11 }}, padding: 12 }} }},
        tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.label}}: ${{ctx.raw.toLocaleString('tr-TR')}}` }} }}
      }}
    }}
  }});
}}

// ---- Table Rendering ----
function renderTable() {{
  const tbody = document.getElementById('table-body');
  const noData = document.getElementById('no-data');
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE) || 1;
  if (page > totalPages) page = totalPages;

  const start = (page - 1) * PAGE_SIZE;
  const pageData = filtered.slice(start, start + PAGE_SIZE);

  if (pageData.length === 0) {{
    tbody.innerHTML = '';
    noData.style.display = 'block';
  }} else {{
    noData.style.display = 'none';
    tbody.innerHTML = pageData.map(r => {{
      const barW = Math.round((r.n / MAX_N) * 60);
      const dipnotBadge = r.d ? `<span style="font-size:.7rem;color:var(--text-muted);margin-left:4px">*${{r.d}}</span>` : '';
      return `<tr>
        <td><span class="badge badge-${{r.s}}" title="${{SINIF_LABELS[r.s] || r.s}}">${{r.s}}</span></td>
        <td><span style="font-size:.78rem;color:var(--text-muted)">${{TUR_LABELS[r.t] || r.t}}</span></td>
        <td><strong>${{r.i}}</strong></td>
        <td class="kurum-cell"><span title="${{r.kf}}">${{r.k || r.kf}}</span></td>
        <td class="uzmanlik-cell">${{r.u}}</td>
        <td class="quota-cell">
          ${{r.n}}${{dipnotBadge}}
          <span class="quota-bar"><span class="quota-bar-fill" style="width:${{barW}}px;display:inline-block"></span></span>
        </td>
      </tr>`;
    }}).join('');
  }}

  // Pagination
  document.getElementById('page-info').textContent =
    `${{start + 1}}–${{Math.min(start + PAGE_SIZE, filtered.length)}} / ${{filtered.length.toLocaleString('tr-TR')}} kayıt gösteriliyor`;
  document.getElementById('table-info').textContent =
    `${{filtered.length.toLocaleString('tr-TR')}} kayıt`;

  const pageBtns = document.getElementById('page-btns');
  pageBtns.innerHTML = '';

  const addBtn = (label, p, disabled = false) => {{
    const btn = document.createElement('button');
    btn.className = 'page-btn' + (p === page ? ' active' : '');
    btn.textContent = label;
    btn.disabled = disabled;
    if (!disabled) btn.onclick = () => {{ page = p; renderTable(); window.scrollTo({{top: document.querySelector('.table-wrap').offsetTop - 20, behavior: 'smooth'}}); }};
    pageBtns.appendChild(btn);
  }};

  addBtn('‹', page - 1, page <= 1);
  const pageRange = getPageRange(page, totalPages);
  pageRange.forEach(p => {{
    if (p === '…') {{
      const span = document.createElement('span');
      span.textContent = '…';
      span.style.cssText = 'padding:5px 6px;color:var(--text-muted);font-size:.8rem';
      pageBtns.appendChild(span);
    }} else addBtn(p, p);
  }});
  addBtn('›', page + 1, page >= totalPages);
}}

function getPageRange(current, total) {{
  if (total <= 7) return Array.from({{length: total}}, (_, i) => i + 1);
  const pages = [1];
  if (current > 3) pages.push('…');
  for (let p = Math.max(2, current - 1); p <= Math.min(total - 1, current + 1); p++) pages.push(p);
  if (current < total - 2) pages.push('…');
  pages.push(total);
  return pages;
}}

init();
</script>
</body>
</html>'''


if __name__ == '__main__':
    main()
