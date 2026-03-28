#!/usr/bin/env python3
"""
Parse TUS 2025/2 and 2026/1 kontenjan PDFs and generate an interactive
comparison HTML dashboard.
Run: python3 build.py
Output: index.html
"""

import re, json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))
import pdfplumber

PDF_2026 = os.path.join(os.path.dirname(__file__), 'kont_tablo12032026.pdf')
PDF_2025 = os.path.join(os.path.dirname(__file__), 'kont_tablo02102025.pdf')
OUTPUT   = os.path.join(os.path.dirname(__file__), 'index.html')

SPECIALTIES = sorted([
    'PLASTİK, REKONSTRÜKTİF VE ESTETİK CERRAHİ',
    'ÇOCUK VE ERGEN RUH SAĞLIĞI VE HASTALIKLARI',
    'ENFEKSİYON HASTALIKLARI VE KLİNİK MİKROBİYOLOJİ',
    'TIBBİ EKOLOJİ VE HİDROKLİMATOLOJİ',
    'SUALTI HEKİMLİĞİ VE HİPERBARİK TIP',
    'HİSTOLOJİ VE EMBRİYOLOJİ',
    'HAVA VE UZAY HEKİMLİĞİ', 'ANESTEZİYOLOJİ VE REANİMASYON',
    'KADIN HASTALIKLARI VE DOĞUM', 'KALP VE DAMAR CERRAHİSİ',
    'KULAK BURUN BOĞAZ HASTALIKLARI', 'ORTOPEDİ VE TRAVMATOLOJİ',
    'ÇOCUK SAĞLIĞI VE HASTALIKLARI', 'RUH SAĞLIĞI VE HASTALIKLARI',
    'FİZİKSEL TIP VE REHABİLİTASYON', 'DERİ VE ZÜHREVİ HASTALIKLARI',
    'RADYASYON ONKOLOJİSİ', 'BEYİN VE SİNİR CERRAHİSİ',
    'ASKERİ SAĞLIK HİZMETLERİ', 'GÖĞÜS CERRAHİSİ', 'GÖĞÜS HASTALIKLARI',
    'TIBBİ FARMAKOLOJİ', 'ÇOCUK CERRAHİSİ', 'AİLE HEKİMLİĞİ', 'İÇ HASTALIKLARI',
    'GÖZ HASTALIKLARI', 'TIBBİ BİYOKİMYA', 'TIBBİ GENETİK',
    'TIBBİ MİKROBİYOLOJİ', 'TIBBİ PATOLOJİ', 'HALK SAĞLIĞI',
    'GENEL CERRAHİ', 'SPOR HEKİMLİĞİ', 'KARDİYOLOJİ', 'NÜKLEER TIP',
    'RADYOLOJİ', 'NÖROLOJİ', 'ADLİ TIP', 'ACİL TIP', 'ÜROLOJİ',
    'FİZYOLOJİ', 'ANATOMİ',
], key=len, reverse=True)

SINIF_LABELS = {'S': 'Sağlık Bak.', 'T': 'Askeri/Özel', 'K': 'Kıbrıs (KKTC)', 'A': 'Adli'}
TUR_LABELS   = {
    'EAH': 'Eğitim ve Araştırma Hast.',
    'KKTC': 'KKTC Kontenjanlı',
    'MAP': 'MAP (Gülhane)',
    'MSB': 'MSB (Kuvvet Komutanlıkları)',
    'SBA': 'SBÜ Bağlı Üniversite',
    'BNDH': 'Burhan Nalbantoğlu D.H.',
    'ADL': 'Adli Tıp Kurumu',
    'İçişleri Bakanlığı': 'İçişleri Bakanlığı',
    'ÜNİ': 'Üniversite Hastanesi',
    'YBU': 'Yabancı Uyruklu',
}


# ── Shared helper ────────────────────────────────────────────────────────────

def find_specialty(line):
    for spec in SPECIALTIES:
        pos = line.find(spec)
        if pos > 0:
            return spec, pos
    return None, -1


_HOSP_FROM_SUFFIX = re.compile(
    r'((?:\S+\s+)*?Hastanesi)\s+T\.C\.\s+Sağlık\s+Bakanlığı\s+(.+)', re.I)

def extract_s_hospital_from_suffix(sparts):
    """For 2025 S EAH records the hospital name is printed AFTER the quota in
    the PDF. Extract it from sparts[3:] and reconstruct the proper name."""
    tail = re.sub(r'^[\d,\s\*]+', '', ' '.join(sparts[3:])).strip()
    m = _HOSP_FROM_SUFFIX.search(tail)
    if m:
        # e.g. group(1)='Hastanesi', group(2)='Bağcılar Eğitim ve Araştırma'
        return (m.group(2).strip() + ' ' + m.group(1).strip()).strip()
    return ''


def extract_hospital_key(sinif, tur, kurum_full):
    """Normalised name used as comparison key.

    T ÜNİ / YBU / SBA: university name is reliably in the prefix of both PDFs.
    S EAH: hospital short name (stripped of ministry/university affiliation).
           For 2026 this comes from the clean prefix; for 2025 it comes from
           the suffix-extracted name stored in kf by parse_2025_line.
    All other types: city-level fallback (empty key).
    """
    s = kurum_full.strip()
    if tur in ('ÜNİ', 'YBU', 'SBA'):
        s = re.sub(r'\s+Tıp\s+Fakültesi\s*$', '', s, flags=re.I).strip()
        return s.upper()
    if tur == 'EAH' and s:
        # Strip ministry prefix and university affiliation, keep hospital core
        s = re.sub(r'^T\.C\.\s+Sağlık\s+Bakanlığı\s+', '', s, flags=re.I)
        for marker in ['Sağlık Bilimleri Üniversitesi', 'Ankara Yıldırım']:
            p = s.find(marker)
            if p > 2:
                s = s[:p]
                break
            elif p == 0:
                # kf is purely university affiliation (hospital extraction failed)
                return ''
        m = re.search(r'\s+\S+\s+Üniversitesi', s)
        if m and m.start() > 3:
            s = s[:m.start()]
        result = s.strip().upper()
        return result if len(result) > 4 else ''   # discard garbage short keys
    return ''   # city-level fallback for MAP, MSB, KKTC, etc.


def make_key(sinif, tur, il, hospital_key, uzmanlik):
    # T SBA is a new 2026 category for institutions that were T ÜNİ in 2025.
    # Normalize to ÜNİ so they match across years.
    tur_key = 'ÜNİ' if tur == 'SBA' else tur
    if hospital_key:
        # Hospital-level key: university name is globally unique, city not needed.
        return f"{sinif}|{tur_key}|{hospital_key}|{uzmanlik}"
    # City-level fallback (S EAH, MAP, MSB, etc.)
    return f"{sinif}|{tur_key}|{il.upper()}|{uzmanlik}"


def extract_hospital_short(kurum_full, tur=''):
    """Human-readable short label."""
    if tur in ('ÜNİ', 'YBU', 'SBA'):
        # For university hospitals just strip "Tıp Fakültesi" suffix
        s = re.sub(r'\s+Tıp\s+Fakültesi\s*$', '', kurum_full.strip(), flags=re.I)
        return s.strip() or kurum_full
    s = re.sub(r'^T\.C\.\s+Sağlık\s+Bakanlığı\s+', '', kurum_full, flags=re.I)
    for marker in ['Sağlık Bilimleri Üniversitesi', 'Ankara Yıldırım']:
        p = s.find(marker)
        if p > 2:
            s = s[:p]
            break
    m = re.search(r'\s+\S+\s+Üniversitesi', s)
    if m and m.start() > 3:
        s = s[:m.start()]
    s = s.strip()
    # If result is too short the kf was a university affiliation with no hospital name.
    # Derive a compact label from the university name instead.
    if len(s) < 8 and 'Sağlık Bilimleri Üniversitesi' in kurum_full:
        s = re.sub(r'^.*?Sağlık Bilimleri Üniversitesi\s+', 'SBÜ ', kurum_full, flags=re.I)
        s = re.sub(r'\s+Tıp\s+Fakültesi.*$', '', s, flags=re.I).strip()
    return s if s else (kurum_full[:60] if len(kurum_full) > 60 else kurum_full)


# ── 2026 parser ──────────────────────────────────────────────────────────────

def parse_2026_line(line):
    line = line.strip()
    if not line or line.split()[0] not in ('S', 'T', 'K', 'A'):
        return None

    spec, pos = find_specialty(line)
    if spec is None:
        return None

    prefix = line[:pos].strip()
    suffix = line[pos + len(spec):].strip()

    sparts = suffix.split()
    if not sparts:
        return None
    try:
        n = int(sparts[0])
    except ValueError:
        return None
    dipnot = int(sparts[2]) if len(sparts) >= 3 and sparts[1] == 'dipnot' else None

    pparts = prefix.split()
    if len(pparts) < 3:
        return None
    sinif = pparts[0]
    if pparts[1] == 'İçişleri' and len(pparts) > 2 and pparts[2] == 'Bakanlığı':
        tur, rest_start = 'İçişleri Bakanlığı', 3
    else:
        tur, rest_start = pparts[1], 2
    if len(pparts) <= rest_start:
        return None

    il       = pparts[rest_start]
    kf       = ' '.join(pparts[rest_start + 1:])

    # Some S EAH rows in the 2026 PDF have the city name repeated between the
    # hospital name and the university-affiliation columns (PDF column bleed).
    # e.g. "...Şehir Hastanesi İstanbul Medeniyet Üniversitesi..."
    # Only strip when the city name is followed by ANOTHER word before
    # 'Üniversitesi' (so "Hastanesi Adıyaman Üniversitesi" is NOT touched —
    # 'Adıyaman' IS the university name there).
    if sinif == 'S' and tur == 'EAH' and il:
        kf = re.sub(r'(Hastanesi)\s+' + re.escape(il) + r'\s+(?=\S+\s+Üniversitesi)',
                    r'\1 ', kf, flags=re.I)

    hkey     = extract_hospital_key(sinif, tur, kf)
    k        = extract_hospital_short(kf, tur)
    ckey     = make_key(sinif, tur, il, hkey, spec)

    return dict(s=sinif, t=tur, i=il, k=k, kf=kf, u=spec, n=n, d=dipnot,
                p=None, ckey=ckey)


def parse_2026(path):
    records = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                for line in text.split('\n'):
                    r = parse_2026_line(line)
                    if r:
                        records.append(r)
    return records


# ── 2025 parser ──────────────────────────────────────────────────────────────

CODE_RE = re.compile(r'^\d{9}\s')

def collect_2025_lines(path):
    """Join multi-line records using the 9-digit code as record separator."""
    raw = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                raw.extend(text.split('\n'))

    joined, cur = [], ''
    for line in raw:
        line = line.strip()
        if not line:
            continue
        if CODE_RE.match(line):
            if cur:
                joined.append(cur)
            cur = line
        elif cur:
            cur = cur + ' ' + line
    if cur:
        joined.append(cur)
    return joined


def parse_2025_line(line):
    """
    2025 format after stripping 9-digit code:
      SINIF TÜR İL [KURUM…] UZMANLIK PUAN_TÜR GENEL YBU [FOOTNOTES]
    For T/MAP the KURUM text appears *after* the quota due to PDF column order.
    Skips only T/İçişleri (garbled text in PDF).
    """
    m = CODE_RE.match(line)
    if not m:
        return None
    rest = line[m.end():]

    pparts = rest.split()
    if not pparts or pparts[0] not in ('S', 'T', 'K', 'A'):
        return None

    sinif = pparts[0]
    if len(pparts) < 2:
        return None

    # İçişleri Bakanlığı (garbled in PDF – skip)
    if pparts[1] in ('Ba', 'İçişleri'):
        return None

    tur = pparts[1]

    spec, pos = find_specialty(rest)
    if spec is None:
        return None

    prefix = rest[:pos].strip()
    suffix = rest[pos + len(spec):].strip()

    # suffix: PUAN_TÜR GENEL YBU [footnotes…]
    sparts = suffix.split()
    if len(sparts) < 3:
        return None
    if sparts[0] not in ('K', 'T'):
        return None
    try:
        genel = int(sparts[1]) if sparts[1] != '--' else 0
        ybu   = int(sparts[2]) if sparts[2] != '--' else 0
    except ValueError:
        return None
    total = genel + ybu

    pprts = prefix.split()
    if tur == 'MAP':
        il = pprts[2] if len(pprts) > 2 else ''
        kf = ''
    else:
        il = pprts[2] if len(pprts) > 2 else ''
        kf = ' '.join(pprts[3:])

    # For S EAH the hospital name is in the suffix (PDF column order differs).
    # Try to extract it; on success replace kf with the proper hospital name.
    if sinif == 'S' and tur == 'EAH':
        extracted = extract_s_hospital_from_suffix(sparts)
        if extracted:
            kf = extracted

    # For T ÜNİ/YBU/SBA, sometimes the university name ends up in the suffix
    # instead of the prefix (PDF column bleed at page boundaries).
    # e.g. prefix='T ÜNİ İSTANBUL', suffix='K 6 -- Fakültesi İstanbul Üniversitesi-Cerrahpaşa...'
    # Detect empty kf and try to recover from suffix tail.
    if tur in ('ÜNİ', 'YBU', 'SBA') and not kf:
        tail_tokens = sparts[3:]
        tail = ' '.join(tail_tokens)
        # Skip leading footnote numbers and Tıp/Fakültesi fragments
        tail_clean = re.sub(r'^[\d,\s\*]+', '', tail).strip()
        tail_clean = re.sub(r'^(?:Tıp\s+)?Fakültesi\s+', '', tail_clean, flags=re.I).strip()
        # Find the university name (word before 'Üniversitesi')
        m_uni = re.search(r'(\S+\s+Üniversitesi\S*(?:\s+\S+)*)', tail_clean, re.I)
        if m_uni:
            uni_name = m_uni.group(1).strip()
            # Strip any trailing 'Tıp' fragment (suffix cut at page boundary)
            uni_name = re.sub(r'\s+Tıp\s*$', '', uni_name, flags=re.I).strip()
            kf = uni_name + ' Tıp Fakültesi'

    hkey = extract_hospital_key(sinif, tur, kf)
    k    = extract_hospital_short(kf, tur) if kf else ''
    ckey = make_key(sinif, tur, il, hkey, spec)

    return dict(s=sinif, t=tur, i=il.title(), k=k, kf=kf, u=spec,
                n=total, d=None, ckey=ckey)


def parse_2025(path):
    records = []
    for line in collect_2025_lines(path):
        r = parse_2025_line(line)
        if r:
            records.append(r)
    return records


# ── Comparison ───────────────────────────────────────────────────────────────

def enrich_with_comparison(records_26, records_25):
    """Add p and pc fields to each 2026 record.

    p  = previous quota (only set for unambiguous 1-to-1 matches).
    pc = city-level aggregate (set when multiple hospitals share a key so we
         can't do individual matching, but the city DID have quota in 2025).
         Displayed as '~' in the UI so the user knows data existed.
    """
    lookup_n   = {}   # key → summed 2025 quota
    lookup_cnt = {}   # key → number of 2025 records
    for r in records_25:
        k = r['ckey']
        lookup_n[k]   = lookup_n.get(k, 0) + r['n']
        lookup_cnt[k] = lookup_cnt.get(k, 0) + 1

    cnt_26 = {}
    for r in records_26:
        cnt_26[r['ckey']] = cnt_26.get(r['ckey'], 0) + 1

    for r in records_26:
        k = r['ckey']
        if k not in lookup_n:
            r['p']  = None   # genuinely new in 2026/1
            r['pc'] = None
        elif cnt_26[k] == 1 and lookup_cnt.get(k, 0) == 1:
            r['p']  = lookup_n[k]   # clean 1-to-1 match
            r['pc'] = None
        else:
            r['p']  = None
            r['pc'] = lookup_n[k]   # ambiguous — store city total for context


# ── HTML generator ───────────────────────────────────────────────────────────

def generate_html(records_26, records_25):
    # Build combined comparison list: 2026 records (with p) + removed 2025 records
    used_keys = {r['ckey'] for r in records_26 if r.get('p') is not None}
    # 2025-only records (not present in 2026)
    removed = []
    seen_rm = set()
    for r in records_25:
        if r['ckey'] not in used_keys and r['ckey'] not in seen_rm:
            seen_rm.add(r['ckey'])
            removed.append(dict(s=r['s'], t=r['t'], i=r['i'], k=r['k'],
                                kf=r['kf'], u=r['u'], n=0, p=r['n'], d=None,
                                ckey=r['ckey']))

    d26   = json.dumps(records_26,  ensure_ascii=False, separators=(',', ':'))
    d25   = json.dumps(records_25,  ensure_ascii=False, separators=(',', ':'))
    drm   = json.dumps(removed,     ensure_ascii=False, separators=(',', ':'))
    slj   = json.dumps(SINIF_LABELS, ensure_ascii=False)
    tlj   = json.dumps(TUR_LABELS,   ensure_ascii=False)

    return f'''<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TUS Kontenjan — 2025/2 vs 2026/1</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#f0f4f8;--surface:#fff;--surface2:#f8fafc;--border:#e2e8f0;
  --primary:#2563eb;--pl:#dbeafe;--pdark:#1d4ed8;--accent:#0891b2;
  --text:#1e293b;--muted:#64748b;--green:#059669;--red:#dc2626;
  --r:12px;--sh:0 1px 3px rgba(0,0,0,.08),0 4px 12px rgba(0,0,0,.05);
  --shl:0 4px 6px rgba(0,0,0,.07),0 10px 25px rgba(0,0,0,.1);
}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:var(--bg);color:var(--text);min-height:100vh}}
header{{background:linear-gradient(135deg,#1e40af 0%,#0891b2 100%);
  color:#fff;padding:18px 24px;box-shadow:var(--shl)}}
header h1{{font-size:1.4rem;font-weight:700;letter-spacing:-.02em}}
header p{{font-size:.82rem;opacity:.85;margin-top:3px}}

/* Tabs */
.tabs{{background:var(--surface);border-bottom:2px solid var(--border);
  display:flex;gap:0;overflow-x:auto}}
.tab-btn{{padding:13px 22px;font-size:.875rem;font-weight:600;cursor:pointer;
  border:none;background:none;color:var(--muted);border-bottom:3px solid transparent;
  margin-bottom:-2px;white-space:nowrap;transition:all .15s}}
.tab-btn.active{{color:var(--primary);border-bottom-color:var(--primary)}}
.tab-btn:hover:not(.active){{color:var(--text)}}
.tab-content{{display:none}}.tab-content.active{{display:block}}

.container{{max-width:1600px;margin:0 auto;padding:20px 16px}}

/* Cards */
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}}
@media(max-width:900px){{.cards{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:500px){{.cards{{grid-template-columns:1fr}}}}
.card{{background:var(--surface);border-radius:var(--r);padding:16px 18px;
  box-shadow:var(--sh);border-left:4px solid var(--primary)}}
.card.c1{{border-color:#2563eb}}.card.c2{{border-color:#0891b2}}
.card.c3{{border-color:#059669}}.card.c4{{border-color:#7c3aed}}
.card.c5{{border-color:#dc2626}}
.card-label{{font-size:.72rem;font-weight:700;text-transform:uppercase;
  letter-spacing:.05em;color:var(--muted)}}
.card-value{{font-size:1.9rem;font-weight:800;margin-top:3px;line-height:1}}
.card-sub{{font-size:.75rem;color:var(--muted);margin-top:5px}}
.up{{color:var(--green)}}.dn{{color:var(--red)}}

/* Filters */
.filters-wrap{{background:var(--surface);border-radius:var(--r);
  padding:16px 18px;box-shadow:var(--sh);margin-bottom:18px}}
.filters-wrap h2{{font-size:.78rem;font-weight:700;color:var(--muted);
  text-transform:uppercase;letter-spacing:.05em;margin-bottom:12px}}
.filter-grid{{display:grid;grid-template-columns:2fr 1fr 1fr 1fr 1fr auto;
  gap:10px;align-items:end}}
@media(max-width:1100px){{.filter-grid{{grid-template-columns:1fr 1fr 1fr}}}}
@media(max-width:650px){{.filter-grid{{grid-template-columns:1fr}}}}
.fg label{{display:block;font-size:.72rem;font-weight:600;color:var(--muted);
  margin-bottom:4px;text-transform:uppercase;letter-spacing:.04em}}
.fg input,.fg select{{width:100%;padding:7px 11px;border:1.5px solid var(--border);
  border-radius:8px;font-size:.875rem;background:var(--surface2);color:var(--text);
  transition:border-color .15s;-webkit-appearance:none;appearance:none}}
.fg select{{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%2364748b' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 10px center;padding-right:30px}}
.fg input:focus,.fg select:focus{{outline:none;border-color:var(--primary);box-shadow:0 0 0 3px rgba(37,99,235,.1)}}
.sinif-btns{{display:flex;gap:5px;flex-wrap:wrap}}
.sbn{{padding:6px 13px;border-radius:7px;border:1.5px solid var(--border);
  background:var(--surface2);font-size:.78rem;font-weight:600;cursor:pointer;
  transition:all .15s;color:var(--muted);white-space:nowrap}}
.sbn.active{{background:var(--primary);border-color:var(--primary);color:#fff}}
.sbn:hover:not(.active){{border-color:var(--primary);color:var(--primary)}}
.btn-reset{{padding:7px 16px;background:#ef4444;color:#fff;border:none;
  border-radius:7px;font-size:.875rem;font-weight:600;cursor:pointer;transition:background .15s}}
.btn-reset:hover{{background:var(--red)}}

/* Charts */
.charts-grid{{display:grid;grid-template-columns:1fr 1fr 280px;gap:14px;margin-bottom:18px}}
@media(max-width:1200px){{.charts-grid{{grid-template-columns:1fr 1fr}}
  .chart-donut{{grid-column:1/-1}}}}
@media(max-width:700px){{.charts-grid{{grid-template-columns:1fr}}}}
.chart-card{{background:var(--surface);border-radius:var(--r);padding:16px;box-shadow:var(--sh)}}
.chart-card h3{{font-size:.75rem;font-weight:700;color:var(--muted);
  text-transform:uppercase;letter-spacing:.05em;margin-bottom:12px}}
.chart-wrap{{position:relative;height:250px}}

/* Comparison chart */
.comp-chart-card{{background:var(--surface);border-radius:var(--r);padding:16px;
  box-shadow:var(--sh);margin-bottom:18px}}
.comp-chart-card h3{{font-size:.78rem;font-weight:700;color:var(--muted);
  text-transform:uppercase;letter-spacing:.05em;margin-bottom:12px}}
.comp-chart-wrap{{position:relative;height:320px}}

/* Change filter pills */
.change-pills{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}}
.cpill{{padding:6px 14px;border-radius:999px;border:1.5px solid var(--border);
  background:var(--surface2);font-size:.78rem;font-weight:600;cursor:pointer;
  color:var(--muted);transition:all .15s;white-space:nowrap}}
.cpill.active{{background:var(--text);border-color:var(--text);color:#fff}}
.cpill.cp-up.active{{background:var(--green);border-color:var(--green)}}
.cpill.cp-dn.active{{background:var(--red);border-color:var(--red)}}
.cpill.cp-new.active{{background:var(--primary);border-color:var(--primary)}}
.cpill.cp-rm.active{{background:#f97316;border-color:#f97316}}

/* Table */
.tbl-wrap{{background:var(--surface);border-radius:var(--r);box-shadow:var(--sh);overflow:hidden}}
.tbl-header{{display:flex;justify-content:space-between;align-items:center;
  padding:12px 16px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:8px}}
.tbl-header h3{{font-size:.875rem;font-weight:700}}
.tbl-info{{font-size:.78rem;color:var(--muted)}}
.tbl-scroll{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:.82rem}}
thead tr{{background:var(--surface2)}}
th{{padding:9px 11px;text-align:left;font-size:.7rem;font-weight:700;
  text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
  white-space:nowrap;cursor:pointer;user-select:none;border-bottom:2px solid var(--border)}}
th:hover{{color:var(--primary)}}
th.sa::after{{content:' ↑';color:var(--primary)}}
th.sd::after{{content:' ↓';color:var(--primary)}}
td{{padding:8px 11px;border-bottom:1px solid var(--border);vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#f8faff}}
tr.row-up td{{background:#f0fdf4}}
tr.row-dn td{{background:#fef2f2}}
tr.row-new td{{background:#eff6ff}}
tr.row-rm td{{background:#fff7ed;opacity:.8}}
tr.row-up:hover td{{background:#dcfce7}}
tr.row-dn:hover td{{background:#fee2e2}}
tr.row-new:hover td{{background:#dbeafe}}
.badge{{display:inline-flex;align-items:center;padding:2px 7px;
  border-radius:999px;font-size:.7rem;font-weight:700;white-space:nowrap}}
.bS{{background:#dbeafe;color:#1d4ed8}}.bT{{background:#fef3c7;color:#92400e}}
.bK{{background:#d1fae5;color:#065f46}}.bA{{background:#fce7f3;color:#9d174d}}
.quota{{font-weight:800;font-size:.92rem;color:var(--primary)}}
.qbar{{display:inline-block;height:5px;background:var(--pl);
  border-radius:3px;margin-left:5px;vertical-align:middle;width:60px;overflow:hidden}}
.qbar-fill{{height:5px;background:var(--primary);border-radius:3px}}
.kurum-cell{{max-width:260px}}
.kurum-cell span{{display:block;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;font-size:.78rem;color:var(--muted)}}
.uzmanlik-cell{{font-weight:600}}
.diff-cell{{font-weight:800;font-size:.9rem}}
.diff-pos{{color:var(--green)}}.diff-neg{{color:var(--red)}}
.diff-zero{{color:var(--muted)}}.diff-na{{color:var(--muted);font-weight:400}}
.pct-badge{{display:inline-block;padding:1px 6px;border-radius:4px;
  font-size:.7rem;font-weight:700;margin-left:4px}}
.pct-up{{background:#dcfce7;color:#166534}}.pct-dn{{background:#fee2e2;color:#991b1b}}
.pct-zero{{background:#f1f5f9;color:var(--muted)}}
.tag-new{{background:#eff6ff;color:#1d4ed8;padding:2px 7px;
  border-radius:999px;font-size:.7rem;font-weight:700}}
.tag-rm{{background:#fff7ed;color:#c2410c;padding:2px 7px;
  border-radius:999px;font-size:.7rem;font-weight:700}}
.pagination{{display:flex;align-items:center;justify-content:space-between;
  padding:10px 16px;border-top:1px solid var(--border);flex-wrap:wrap;gap:8px}}
.page-btns{{display:flex;gap:3px}}
.pbtn{{padding:4px 9px;border:1.5px solid var(--border);background:var(--surface2);
  border-radius:5px;font-size:.78rem;cursor:pointer;transition:all .15s}}
.pbtn:hover,.pbtn.active{{background:var(--primary);border-color:var(--primary);color:#fff}}
.pbtn:disabled{{opacity:.4;cursor:not-allowed}}
.page-info{{font-size:.78rem;color:var(--muted)}}
.no-data{{text-align:center;padding:36px;color:var(--muted);font-size:.875rem}}
</style>
</head>
<body>
<header>
  <h1>TUS Kontenjan Tablosu — 2025/2 · 2026/1 Karşılaştırması</h1>
  <p>Kaynak: Tıpta Uzmanlık Kurulu resmi kontenjan tabloları</p>
</header>

<!-- Tab Navigation -->
<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('t26',this)">TUS 2026/1</button>
  <button class="tab-btn" onclick="switchTab('t25',this)">TUS 2025/2</button>
  <button class="tab-btn" onclick="switchTab('tcmp',this)">Dönem Karşılaştırması</button>
</div>

<!-- ══ TAB 2026/1 ══════════════════════════════════════════════════════════ -->
<div id="t26" class="tab-content active">
<div class="container">
  <div class="cards" id="cards26"></div>
  <div class="filters-wrap">
    <h2>Filtreler — TUS 2026/1</h2>
    <div class="filter-grid">
      <div class="fg"><label>Ara</label><input type="text" id="s26" placeholder="Kurum, şehir veya uzmanlık..."></div>
      <div class="fg"><label>İl</label><select id="fi26"><option value="">Tüm İller</option></select></div>
      <div class="fg"><label>Uzmanlık Alanı</label><select id="fu26"><option value="">Tüm Alanlar</option></select></div>
      <div class="fg"><label>Tür</label><select id="ft26"><option value="">Tüm Türler</option></select></div>
      <div class="fg"><label>Sınıf</label><div class="sinif-btns" id="sb26">
        <button class="sbn active" data-v="">Tümü</button>
        <button class="sbn" data-v="S">S</button><button class="sbn" data-v="T">T</button>
        <button class="sbn" data-v="K">K</button><button class="sbn" data-v="A">A</button>
      </div></div>
      <div class="fg"><label>&nbsp;</label><button class="btn-reset" onclick="reset26()">Sıfırla</button></div>
    </div>
  </div>
  <div class="charts-grid" id="charts26grid">
    <div class="chart-card"><h3>Uzmanlık Alanları (İlk 15)</h3><div class="chart-wrap"><canvas id="ch26spec"></canvas></div></div>
    <div class="chart-card"><h3>İller (İlk 15)</h3><div class="chart-wrap"><canvas id="ch26city"></canvas></div></div>
    <div class="chart-card chart-donut"><h3>Sınıf Dağılımı</h3><div class="chart-wrap"><canvas id="ch26sinif"></canvas></div></div>
  </div>
  <div class="tbl-wrap">
    <div class="tbl-header"><h3>Kontenjan Listesi — 2026/1</h3><div class="tbl-info" id="ti26"></div></div>
    <div class="tbl-scroll"><table>
      <thead><tr>
        <th onclick="sort26('s')">Sınıf</th><th onclick="sort26('t')">Tür</th>
        <th onclick="sort26('i')">İl</th><th>Kurum</th>
        <th onclick="sort26('u')">Uzmanlık Alanı</th>
        <th onclick="sort26('n')">2026/1</th>
        <th onclick="sort26('p')">2025/2</th>
        <th onclick="sort26('diff')">Fark</th>
      </tr></thead>
      <tbody id="tb26"></tbody>
    </table>
    <div class="no-data" id="nd26" style="display:none">Filtrelere uygun kayıt bulunamadı.</div></div>
    <div class="pagination"><div class="page-info" id="pi26"></div><div class="page-btns" id="pb26"></div></div>
  </div>
</div>
</div>

<!-- ══ TAB 2025/2 ══════════════════════════════════════════════════════════ -->
<div id="t25" class="tab-content">
<div class="container">
  <div class="cards" id="cards25"></div>
  <div class="filters-wrap">
    <h2>Filtreler — TUS 2025/2</h2>
    <div class="filter-grid">
      <div class="fg"><label>Ara</label><input type="text" id="s25" placeholder="Kurum, şehir veya uzmanlık..."></div>
      <div class="fg"><label>İl</label><select id="fi25"><option value="">Tüm İller</option></select></div>
      <div class="fg"><label>Uzmanlık Alanı</label><select id="fu25"><option value="">Tüm Alanlar</option></select></div>
      <div class="fg"><label>Tür</label><select id="ft25"><option value="">Tüm Türler</option></select></div>
      <div class="fg"><label>Sınıf</label><div class="sinif-btns" id="sb25">
        <button class="sbn active" data-v="">Tümü</button>
        <button class="sbn" data-v="S">S</button><button class="sbn" data-v="T">T</button>
        <button class="sbn" data-v="K">K</button><button class="sbn" data-v="A">A</button>
      </div></div>
      <div class="fg"><label>&nbsp;</label><button class="btn-reset" onclick="reset25()">Sıfırla</button></div>
    </div>
  </div>
  <div class="charts-grid">
    <div class="chart-card"><h3>Uzmanlık Alanları (İlk 15)</h3><div class="chart-wrap"><canvas id="ch25spec"></canvas></div></div>
    <div class="chart-card"><h3>İller (İlk 15)</h3><div class="chart-wrap"><canvas id="ch25city"></canvas></div></div>
    <div class="chart-card chart-donut"><h3>Sınıf Dağılımı</h3><div class="chart-wrap"><canvas id="ch25sinif"></canvas></div></div>
  </div>
  <div class="tbl-wrap">
    <div class="tbl-header"><h3>Kontenjan Listesi — 2025/2</h3><div class="tbl-info" id="ti25"></div></div>
    <div class="tbl-scroll"><table>
      <thead><tr>
        <th onclick="sort25('s')">Sınıf</th><th onclick="sort25('t')">Tür</th>
        <th onclick="sort25('i')">İl</th><th>Kurum</th>
        <th onclick="sort25('u')">Uzmanlık Alanı</th>
        <th onclick="sort25('n')">2025/2 Kontenjan</th>
      </tr></thead>
      <tbody id="tb25"></tbody>
    </table>
    <div class="no-data" id="nd25" style="display:none">Filtrelere uygun kayıt bulunamadı.</div></div>
    <div class="pagination"><div class="page-info" id="pi25"></div><div class="page-btns" id="pb25"></div></div>
  </div>
</div>
</div>

<!-- ══ TAB KARŞILAŞTIRMA ════════════════════════════════════════════════════ -->
<div id="tcmp" class="tab-content">
<div class="container">
  <div class="cards" id="cardsCmp"></div>

  <div class="comp-chart-card">
    <h3>Uzmanlık Alanı Bazında Kontenjan — 2025/2 vs 2026/1 (İlk 20)</h3>
    <div class="comp-chart-wrap"><canvas id="chCmpSpec"></canvas></div>
  </div>

  <div class="filters-wrap">
    <h2>Filtreler — Karşılaştırma</h2>
    <div class="filter-grid">
      <div class="fg"><label>Ara</label><input type="text" id="sCmp" placeholder="Kurum, şehir veya uzmanlık..."></div>
      <div class="fg"><label>İl</label><select id="fiCmp"><option value="">Tüm İller</option></select></div>
      <div class="fg"><label>Uzmanlık Alanı</label><select id="fuCmp"><option value="">Tüm Alanlar</option></select></div>
      <div class="fg"><label>Tür</label><select id="ftCmp"><option value="">Tüm Türler</option></select></div>
      <div class="fg"><label>Sınıf</label><div class="sinif-btns" id="sbCmp">
        <button class="sbn active" data-v="">Tümü</button>
        <button class="sbn" data-v="S">S</button><button class="sbn" data-v="T">T</button>
        <button class="sbn" data-v="K">K</button><button class="sbn" data-v="A">A</button>
      </div></div>
      <div class="fg"><label>&nbsp;</label><button class="btn-reset" onclick="resetCmp()">Sıfırla</button></div>
    </div>
  </div>

  <div class="change-pills" id="changePills">
    <button class="cpill active" data-change="">Tümü</button>
    <button class="cpill cp-up" data-change="up">↑ Artan</button>
    <button class="cpill cp-dn" data-change="dn">↓ Azalan</button>
    <button class="cpill" data-change="same">= Değişmedi</button>
    <button class="cpill cp-new" data-change="new">★ Yeni (2026/1)</button>
    <button class="cpill cp-rm" data-change="rm">✕ Kaldırıldı</button>
  </div>

  <div class="tbl-wrap">
    <div class="tbl-header"><h3>Karşılaştırma Tablosu</h3><div class="tbl-info" id="tiCmp"></div></div>
    <div class="tbl-scroll"><table>
      <thead><tr>
        <th onclick="sortCmp('s')">Sınıf</th><th onclick="sortCmp('t')">Tür</th>
        <th onclick="sortCmp('i')">İl</th><th>Kurum</th>
        <th onclick="sortCmp('u')">Uzmanlık Alanı</th>
        <th onclick="sortCmp('p')">2025/2</th>
        <th onclick="sortCmp('n')">2026/1</th>
        <th onclick="sortCmp('diff')">Fark</th>
        <th onclick="sortCmp('pct')">%</th>
      </tr></thead>
      <tbody id="tbCmp"></tbody>
    </table>
    <div class="no-data" id="ndCmp" style="display:none">Filtrelere uygun kayıt bulunamadı.</div></div>
    <div class="pagination"><div class="page-info" id="piCmp"></div><div class="page-btns" id="pbCmp"></div></div>
  </div>
</div>
</div>

<script>
// ── Data ──────────────────────────────────────────────────────────────────────
const D26 = {d26};
const D25 = {d25};
const D_RM = {drm};
const SL = {slj};
const TL = {tlj};

// Combined comparison dataset: 2026 records + removed 2025 records
const DCMP = [...D26, ...D_RM];

const MAX_N26 = Math.max(...D26.map(r=>r.n), 1);
const MAX_N25 = Math.max(...D25.map(r=>r.n), 1);

// ── Tab switching ─────────────────────────────────────────────────────────────
let chartsInit = {{t26:false, t25:false, tcmp:false}};
function switchTab(id, btn) {{
  document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
  if (!chartsInit[id]) {{
    if (id==='t26')   {{ initTab26();  chartsInit.t26=true; }}
    if (id==='t25')   {{ initTab25();  chartsInit.t25=true; }}
    if (id==='tcmp')  {{ initTabCmp(); chartsInit.tcmp=true; }}
  }}
}}

// ── Colours ───────────────────────────────────────────────────────────────────
const COLORS=['#2563eb','#0891b2','#7c3aed','#059669','#d97706',
  '#dc2626','#db2777','#ea580c','#16a34a','#9333ea',
  '#0284c7','#b45309','#be185d','#15803d','#4f46e5',
  '#0369a1','#7e22ce','#047857','#b91c1c','#1d4ed8'];

function shortL(s,n=28){{return s.length>n?s.slice(0,n)+'…':s;}}

function aggTop(data,field,n=15){{
  const m={{}};
  data.forEach(r=>{{m[r[field]]=(m[r[field]]||0)+r.n;}});
  return Object.entries(m).sort((a,b)=>b[1]-a[1]).slice(0,n);
}}

function makeBarChart(ctx, data, maxN){{
  const top=aggTop(data,'u',15);
  return new Chart(ctx,{{type:'bar',
    data:{{labels:top.map(d=>shortL(d[0],30)),
      datasets:[{{data:top.map(d=>d[1]),backgroundColor:COLORS,borderRadius:4,borderSkipped:false}}]}},
    options:{{indexAxis:'y',responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:c=>` ${{c.raw.toLocaleString('tr-TR')}} kontenjan`}}}}}},
      scales:{{x:{{grid:{{color:'#f1f5f9'}},ticks:{{font:{{size:11}}}}}},y:{{grid:{{display:false}},ticks:{{font:{{size:11}}}}}}}}
    }}
  }});
}}

function makeCityChart(ctx, data){{
  const top=aggTop(data,'i',15);
  return new Chart(ctx,{{type:'bar',
    data:{{labels:top.map(d=>d[0]),
      datasets:[{{data:top.map(d=>d[1]),backgroundColor:COLORS,borderRadius:4,borderSkipped:false}}]}},
    options:{{indexAxis:'y',responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:c=>` ${{c.raw.toLocaleString('tr-TR')}} kontenjan`}}}}}},
      scales:{{x:{{grid:{{color:'#f1f5f9'}},ticks:{{font:{{size:11}}}}}},y:{{grid:{{display:false}},ticks:{{font:{{size:11}}}}}}}}
    }}
  }});
}}

function makeDonut(ctx, data){{
  const m={{}};
  data.forEach(r=>m[r.s]=(m[r.s]||0)+r.n);
  const entries=Object.entries(m).sort((a,b)=>b[1]-a[1]);
  return new Chart(ctx,{{type:'doughnut',
    data:{{labels:entries.map(d=>`${{d[0]}} — ${{SL[d[0]]||d[0]}}`),
      datasets:[{{data:entries.map(d=>d[1]),backgroundColor:COLORS,hoverOffset:6}}]}},
    options:{{responsive:true,maintainAspectRatio:false,cutout:'58%',
      plugins:{{legend:{{position:'bottom',labels:{{font:{{size:11}},padding:10}}}},
        tooltip:{{callbacks:{{label:c=>` ${{c.label}}: ${{c.raw.toLocaleString('tr-TR')}}`}}}}}}
    }}
  }});
}}

// ── Generic table renderer ────────────────────────────────────────────────────
const PS = 50;
function renderTable({{data,tbodyId,ndId,piId,pbId,tiId,page,maxN,cols,rowClass,scrollTarget}}){{
  const tbody=document.getElementById(tbodyId);
  const nd=document.getElementById(ndId);
  const total=data.length, tp=Math.ceil(total/PS)||1;
  if(page>tp) page=tp;
  const start=(page-1)*PS, slice=data.slice(start,start+PS);

  document.getElementById(tiId).textContent=`${{total.toLocaleString('tr-TR')}} kayıt`;

  if(!slice.length){{tbody.innerHTML='';nd.style.display='block';}}
  else{{
    nd.style.display='none';
    tbody.innerHTML=slice.map(r=>{{
      const rc=rowClass?rowClass(r):'';
      return `<tr class="${{rc}}">${{cols(r,maxN)}}</tr>`;
    }}).join('');
  }}

  // Pagination
  document.getElementById(piId).textContent=
    `${{start+1}}–${{Math.min(start+PS,total)}} / ${{total.toLocaleString('tr-TR')}} kayıt`;
  const pb=document.getElementById(pbId); pb.innerHTML='';
  const addBtn=(lbl,p,dis=false)=>{{
    const b=document.createElement('button');
    b.className='pbtn'+(p===page?' active':'');
    b.textContent=lbl; b.disabled=dis;
    if(!dis) b.onclick=()=>{{
      const el=document.getElementById(scrollTarget||tbodyId);
      el && el.closest('.tbl-wrap') && window.scrollTo({{top:el.closest('.tbl-wrap').offsetTop-20,behavior:'smooth'}});
      return page; // caller updates
    }};
    pb.appendChild(b);
    return b;
  }};
  const prevB=addBtn('‹',page-1,page<=1);
  if(!prevB.disabled) prevB.onclick=()=>{{ return page-1; }};
  getPageRange(page,tp).forEach(p=>{{
    if(p==='…'){{ const sp=document.createElement('span');
      sp.textContent='…';sp.style.cssText='padding:4px 5px;color:var(--muted);font-size:.78rem';
      pb.appendChild(sp); }}
    else {{ const b=addBtn(p,p); if(p!==page) b.onclick=()=>p; }}
  }});
  const nextB=addBtn('›',page+1,page>=tp);
  if(!nextB.disabled) nextB.onclick=()=>{{ return page+1; }};
  return tp;
}}

function getPageRange(cur,tot){{
  if(tot<=7) return Array.from({{length:tot}},(_,i)=>i+1);
  const p=[1];
  if(cur>3) p.push('…');
  for(let i=Math.max(2,cur-1);i<=Math.min(tot-1,cur+1);i++) p.push(i);
  if(cur<tot-2) p.push('…');
  p.push(tot);
  return p;
}}

function badgeS(s){{return `<span class="badge b${{s}}" title="${{SL[s]||s}}">${{s}}</span>`;}}
function badgeTur(t){{return `<span style="font-size:.75rem;color:var(--muted)">${{TL[t]||t}}</span>`;}}
function kurumCell(r){{return `<td class="kurum-cell"><span title="${{r.kf||r.k}}">${{r.k||r.kf||'—'}}</span></td>`;}}

// ── TAB 2026/1 ────────────────────────────────────────────────────────────────
let f26=[], sc26='n', sd26=-1, pg26=1, as26='';
let ch26s,ch26c,ch26d;

function initTab26(){{
  const ils=[...new Set(D26.map(r=>r.i))].sort();
  const uzs=[...new Set(D26.map(r=>r.u))].sort();
  const trs=[...new Set(D26.map(r=>r.t))].sort();
  const sel=(id,arr)=>arr.forEach(v=>document.getElementById(id).insertAdjacentHTML('beforeend',`<option value="${{v}}">${{v}}</option>`));
  sel('fi26',ils); sel('fu26',uzs);
  trs.forEach(v=>document.getElementById('ft26').insertAdjacentHTML('beforeend',`<option value="${{v}}">${{TL[v]||v}} (${{v}})</option>`));
  document.getElementById('s26').addEventListener('input',apply26);
  document.getElementById('fi26').addEventListener('change',apply26);
  document.getElementById('fu26').addEventListener('change',apply26);
  document.getElementById('ft26').addEventListener('change',apply26);
  document.querySelectorAll('#sb26 .sbn').forEach(b=>b.addEventListener('click',()=>{{
    as26=b.dataset.v;
    document.querySelectorAll('#sb26 .sbn').forEach(x=>x.classList.remove('active'));
    b.classList.add('active'); apply26();
  }}));
  apply26();
}}

function apply26(){{
  const sr=document.getElementById('s26').value.toLowerCase();
  const il=document.getElementById('fi26').value;
  const uz=document.getElementById('fu26').value;
  const tr=document.getElementById('ft26').value;
  f26=D26.filter(r=>
    (!as26||r.s===as26)&&(!il||r.i===il)&&(!uz||r.u===uz)&&
    (!tr||r.t===tr)&&(!sr||`${{r.i}} ${{r.k}} ${{r.kf}} ${{r.u}} ${{r.t}}`.toLowerCase().includes(sr))
  );
  pg26=1; sortApply26(); updateStats26(); updateCharts26(); render26();
}}

function sortApply26(){{
  f26.sort((a,b)=>{{
    let av=a[sc26]==='diff'?(a.n-(a.p??a.n)):a[sc26]??'';
    let bv=b[sc26]==='diff'?(b.n-(b.p??b.n)):b[sc26]??'';
    if(sc26==='diff'){{av=(a.p!=null?a.n-a.p:null);bv=(b.p!=null?b.n-b.p:null);
      if(av==null&&bv==null)return 0;if(av==null)return 1;if(bv==null)return -1;}}
    if(typeof av==='string') av=av.toLowerCase();
    if(typeof bv==='string') bv=bv.toLowerCase();
    return av<bv?-sd26:av>bv?sd26:0;
  }});
}}

function sort26(col){{if(sc26===col)sd26*=-1;else{{sc26=col;sd26=col==='n'?-1:1;}}pg26=1;sortApply26();render26();updateSortH26();}}

function updateSortH26(){{
  const ths=document.querySelectorAll('#t26 thead th');
  const cols=['s','t','i',null,'u','n','p','diff'];
  ths.forEach((th,i)=>{{th.classList.remove('sa','sd');if(cols[i]===sc26)th.classList.add(sd26===1?'sa':'sd');}});
}}

function updateStats26(){{
  const total=f26.reduce((s,r)=>s+r.n,0);
  const matched=f26.filter(r=>r.p!=null);
  const prev=matched.reduce((s,r)=>s+(r.p||0),0);
  const curr=matched.reduce((s,r)=>s+r.n,0);
  const diff=curr-prev;
  const cities=new Set(f26.map(r=>r.i)).size;
  const kurums=new Set(f26.map(r=>r.kf)).size;
  const pct=prev>0?(diff/prev*100):0;
  document.getElementById('cards26').innerHTML=`
    <div class="card c1"><div class="card-label">2026/1 Toplam Kontenjan</div>
      <div class="card-value">${{total.toLocaleString('tr-TR')}}</div>
      <div class="card-sub">${{f26.length}} kayıt</div></div>
    <div class="card c2"><div class="card-label">2025/2 Karşılığı</div>
      <div class="card-value">${{prev?prev.toLocaleString('tr-TR'):'—'}}</div>
      <div class="card-sub">${{matched.length}} eşleşen kayıt</div></div>
    <div class="card c3"><div class="card-label">Net Değişim</div>
      <div class="card-value ${{diff>0?'up':diff<0?'dn':''}}">${{diff>0?'+':''}}${{prev?diff.toLocaleString('tr-TR'):'—'}}</div>
      <div class="card-sub">${{prev?`%${{pct.toFixed(1)}} değişim`:'Karşılaştırılamadı'}}</div></div>
    <div class="card c4"><div class="card-label">İl / Kurum</div>
      <div class="card-value">${{cities}}</div><div class="card-sub">${{kurums}} farklı kurum</div></div>`;
}}

function updateCharts26(){{
  if(ch26s) ch26s.destroy();
  if(ch26c) ch26c.destroy();
  if(ch26d) ch26d.destroy();
  ch26s=makeBarChart(document.getElementById('ch26spec').getContext('2d'),f26,MAX_N26);
  ch26c=makeCityChart(document.getElementById('ch26city').getContext('2d'),f26);
  ch26d=makeDonut(document.getElementById('ch26sinif').getContext('2d'),f26);
}}

function render26(){{
  const cols=(r,mx)=>{{
    const diff=r.p!=null?r.n-r.p:null;
    const pct=r.p>0?(r.n-r.p)/r.p*100:null;
    const diffHtml=diff==null
      ?'<td class="diff-cell diff-na">—</td>'
      :`<td class="diff-cell ${{diff>0?'diff-pos':diff<0?'diff-neg':'diff-zero'}}">${{diff>0?'+':''}}${{diff}}
        ${{pct!=null?`<span class="pct-badge ${{pct>0?'pct-up':pct<0?'pct-dn':'pct-zero'}}">${{pct>0?'+':''}}${{pct.toFixed(1)}}%</span>`:''}}
       </td>`;
    const bw=Math.round(r.n/mx*60);
    return `<td>${{badgeS(r.s)}}</td><td>${{badgeTur(r.t)}}</td><td><strong>${{r.i}}</strong></td>
      ${{kurumCell(r)}}<td class="uzmanlik-cell">${{r.u}}</td>
      <td class="quota">${{r.n}}<span class="qbar"><span class="qbar-fill" style="width:${{bw}}px;display:inline-block"></span></span></td>
      <td class="quota" style="color:var(--accent)">${{r.p!=null?r.p:(r.pc!=null?`<span title="2025/2 şehir toplamı: ${{r.pc}}" style="color:var(--muted);cursor:help">~${{r.pc}}</span>`:'<span class="tag-new">YENİ</span>')}}</td>
      ${{diffHtml}}`;
  }};
  const rc=r=>r.p==null?(r.pc!=null?'':'row-new'):(r.n>r.p?'row-up':r.n<r.p?'row-dn':'');
  renderTable({{data:f26,tbodyId:'tb26',ndId:'nd26',piId:'pi26',pbId:'pb26',tiId:'ti26',
    page:pg26,maxN:MAX_N26,cols,rowClass:rc}});
  // Wire up pagination clicks
  wirePagination('pb26',(p)=>{{pg26=p;render26();}},()=>Math.ceil(f26.length/PS)||1,()=>pg26);
}}

// ── TAB 2025/2 ────────────────────────────────────────────────────────────────
let f25=[], sc25='n', sd25=-1, pg25=1, as25='';
let ch25s,ch25c,ch25d;

function initTab25(){{
  const ils=[...new Set(D25.map(r=>r.i))].sort();
  const uzs=[...new Set(D25.map(r=>r.u))].sort();
  const trs=[...new Set(D25.map(r=>r.t))].sort();
  const sel=(id,arr)=>arr.forEach(v=>document.getElementById(id).insertAdjacentHTML('beforeend',`<option value="${{v}}">${{v}}</option>`));
  sel('fi25',ils); sel('fu25',uzs);
  trs.forEach(v=>document.getElementById('ft25').insertAdjacentHTML('beforeend',`<option value="${{v}}">${{TL[v]||v}} (${{v}})</option>`));
  document.getElementById('s25').addEventListener('input',apply25);
  document.getElementById('fi25').addEventListener('change',apply25);
  document.getElementById('fu25').addEventListener('change',apply25);
  document.getElementById('ft25').addEventListener('change',apply25);
  document.querySelectorAll('#sb25 .sbn').forEach(b=>b.addEventListener('click',()=>{{
    as25=b.dataset.v;
    document.querySelectorAll('#sb25 .sbn').forEach(x=>x.classList.remove('active'));
    b.classList.add('active'); apply25();
  }}));
  apply25();
}}

function apply25(){{
  const sr=document.getElementById('s25').value.toLowerCase();
  const il=document.getElementById('fi25').value;
  const uz=document.getElementById('fu25').value;
  const tr=document.getElementById('ft25').value;
  f25=D25.filter(r=>
    (!as25||r.s===as25)&&(!il||r.i===il)&&(!uz||r.u===uz)&&
    (!tr||r.t===tr)&&(!sr||`${{r.i}} ${{r.k}} ${{r.kf}} ${{r.u}} ${{r.t}}`.toLowerCase().includes(sr))
  );
  pg25=1; f25.sort((a,b)=>{{let av=a[sc25]||'',bv=b[sc25]||'';
    if(typeof av==='string')av=av.toLowerCase();if(typeof bv==='string')bv=bv.toLowerCase();
    return av<bv?-sd25:av>bv?sd25:0;}});
  updateStats25(); updateCharts25(); render25();
}}

function sort25(col){{if(sc25===col)sd25*=-1;else{{sc25=col;sd25=col==='n'?-1:1;}}apply25();
  const ths=document.querySelectorAll('#t25 thead th');
  const cols=['s','t','i',null,'u','n'];
  ths.forEach((th,i)=>{{th.classList.remove('sa','sd');if(cols[i]===sc25)th.classList.add(sd25===1?'sa':'sd');}});
}}

function updateStats25(){{
  const total=f25.reduce((s,r)=>s+r.n,0);
  const cities=new Set(f25.map(r=>r.i)).size;
  const kurums=new Set(f25.map(r=>r.kf)).size;
  document.getElementById('cards25').innerHTML=`
    <div class="card c2"><div class="card-label">2025/2 Toplam Kontenjan</div>
      <div class="card-value">${{total.toLocaleString('tr-TR')}}</div>
      <div class="card-sub">${{f25.length}} kayıt</div></div>
    <div class="card c1"><div class="card-label">İl Sayısı</div>
      <div class="card-value">${{cities}}</div><div class="card-sub">Farklı il</div></div>
    <div class="card c4"><div class="card-label">Kurum Sayısı</div>
      <div class="card-value">${{kurums}}</div><div class="card-sub">Farklı kurum</div></div>
    <div class="card c3"><div class="card-label">Uzmanlık Alanı</div>
      <div class="card-value">${{new Set(f25.map(r=>r.u)).size}}</div><div class="card-sub">Farklı alan</div></div>`;
}}

function updateCharts25(){{
  if(ch25s) ch25s.destroy();
  if(ch25c) ch25c.destroy();
  if(ch25d) ch25d.destroy();
  ch25s=makeBarChart(document.getElementById('ch25spec').getContext('2d'),f25,MAX_N25);
  ch25c=makeCityChart(document.getElementById('ch25city').getContext('2d'),f25);
  ch25d=makeDonut(document.getElementById('ch25sinif').getContext('2d'),f25);
}}

function render25(){{
  const cols=(r,mx)=>{{
    const bw=Math.round(r.n/mx*60);
    return `<td>${{badgeS(r.s)}}</td><td>${{badgeTur(r.t)}}</td><td><strong>${{r.i}}</strong></td>
      ${{kurumCell(r)}}<td class="uzmanlik-cell">${{r.u}}</td>
      <td class="quota">${{r.n}}<span class="qbar"><span class="qbar-fill" style="width:${{bw}}px;display:inline-block"></span></span></td>`;
  }};
  renderTable({{data:f25,tbodyId:'tb25',ndId:'nd25',piId:'pi25',pbId:'pb25',tiId:'ti25',
    page:pg25,maxN:MAX_N25,cols}});
  wirePagination('pb25',(p)=>{{pg25=p;render25();}},()=>Math.ceil(f25.length/PS)||1,()=>pg25);
}}

// ── TAB KARŞILAŞTIRMA ─────────────────────────────────────────────────────────
let fCmp=[], scCmp='diff', sdCmp=-1, pgCmp=1, asCmp='', activeCh='';
let chCmpS;

function initTabCmp(){{
  const ils=[...new Set(DCMP.map(r=>r.i))].sort();
  const uzs=[...new Set(DCMP.map(r=>r.u))].sort();
  const trs=[...new Set(DCMP.map(r=>r.t))].sort();
  const sel=(id,arr)=>arr.forEach(v=>document.getElementById(id).insertAdjacentHTML('beforeend',`<option value="${{v}}">${{v}}</option>`));
  sel('fiCmp',ils); sel('fuCmp',uzs);
  trs.forEach(v=>document.getElementById('ftCmp').insertAdjacentHTML('beforeend',`<option value="${{v}}">${{TL[v]||v}} (${{v}})</option>`));
  document.getElementById('sCmp').addEventListener('input',applyCmp);
  document.getElementById('fiCmp').addEventListener('change',applyCmp);
  document.getElementById('fuCmp').addEventListener('change',applyCmp);
  document.getElementById('ftCmp').addEventListener('change',applyCmp);
  document.querySelectorAll('#sbCmp .sbn').forEach(b=>b.addEventListener('click',()=>{{
    asCmp=b.dataset.v;
    document.querySelectorAll('#sbCmp .sbn').forEach(x=>x.classList.remove('active'));
    b.classList.add('active'); applyCmp();
  }}));
  document.querySelectorAll('#changePills .cpill').forEach(b=>b.addEventListener('click',()=>{{
    activeCh=b.dataset.change;
    document.querySelectorAll('#changePills .cpill').forEach(x=>x.classList.remove('active'));
    b.classList.add('active'); applyCmp();
  }}));
  applyCmp();
}}

function changeType(r){{
  if(r.n===0&&r.p>0) return 'rm';
  if(r.p==null&&r.pc==null) return 'new';
  if(r.p==null) return 'same'; // pc exists – hospital existed, matching ambiguous
  const d=r.n-r.p;
  if(d>0) return 'up'; if(d<0) return 'dn'; return 'same';
}}

function applyCmp(){{
  const sr=document.getElementById('sCmp').value.toLowerCase();
  const il=document.getElementById('fiCmp').value;
  const uz=document.getElementById('fuCmp').value;
  const tr=document.getElementById('ftCmp').value;
  fCmp=DCMP.filter(r=>{{
    if(asCmp&&r.s!==asCmp) return false;
    if(il&&r.i!==il) return false;
    if(uz&&r.u!==uz) return false;
    if(tr&&r.t!==tr) return false;
    if(activeCh&&changeType(r)!==activeCh) return false;
    if(sr&&!`${{r.i}} ${{r.k}} ${{r.kf}} ${{r.u}} ${{r.t}}`.toLowerCase().includes(sr)) return false;
    return true;
  }});
  pgCmp=1; sortApplyCmp(); updateStatsCmp(); updateCompChart(); renderCmp();
}}

function sortApplyCmp(){{
  fCmp.sort((a,b)=>{{
    let av,bv;
    if(scCmp==='diff'){{av=(a.p!=null?a.n-a.p:null);bv=(b.p!=null?b.n-b.p:null);
      if(av==null&&bv==null)return 0;if(av==null)return 1;if(bv==null)return -1;}}
    else if(scCmp==='pct'){{
      av=(a.p>0?(a.n-a.p)/a.p*100:null); bv=(b.p>0?(b.n-b.p)/b.p*100:null);
      if(av==null&&bv==null)return 0;if(av==null)return 1;if(bv==null)return -1;}}
    else{{av=a[scCmp]||''; bv=b[scCmp]||'';
      if(typeof av==='string')av=av.toLowerCase();if(typeof bv==='string')bv=bv.toLowerCase();}}
    return av<bv?-sdCmp:av>bv?sdCmp:0;
  }});
}}

function sortCmp(col){{if(scCmp===col)sdCmp*=-1;else{{scCmp=col;sdCmp=(col==='diff'||col==='pct'||col==='n'||col==='p')?-1:1;}}pgCmp=1;sortApplyCmp();renderCmp();
  const ths=document.querySelectorAll('#tcmp thead th');
  const cols=['s','t','i',null,'u','p','n','diff','pct'];
  ths.forEach((th,i)=>{{th.classList.remove('sa','sd');if(cols[i]===scCmp)th.classList.add(sdCmp===1?'sa':'sd');}});
}}

function updateStatsCmp(){{
  const tot26=D26.reduce((s,r)=>s+r.n,0);
  const tot25=D25.reduce((s,r)=>s+r.n,0);
  const matched=D26.filter(r=>r.p!=null);
  const m26=matched.reduce((s,r)=>s+r.n,0);
  const m25=matched.reduce((s,r)=>s+(r.p||0),0);
  const netD=m26-m25;
  const pct=m25>0?netD/m25*100:0;
  const newRec=D26.filter(r=>r.p==null).length;
  const rmRec=D_RM.length;
  document.getElementById('cardsCmp').innerHTML=`
    <div class="card c2"><div class="card-label">2025/2 Toplam</div>
      <div class="card-value">${{tot25.toLocaleString('tr-TR')}}</div>
      <div class="card-sub">Karşılaştırılabilir: ${{m25.toLocaleString('tr-TR')}}</div></div>
    <div class="card c1"><div class="card-label">2026/1 Toplam</div>
      <div class="card-value">${{tot26.toLocaleString('tr-TR')}}</div>
      <div class="card-sub">Karşılaştırılabilir: ${{m26.toLocaleString('tr-TR')}}</div></div>
    <div class="card ${{netD>=0?'c3':'c5'}}"><div class="card-label">Net Değişim</div>
      <div class="card-value ${{netD>0?'up':netD<0?'dn':''}}">${{netD>0?'+':''}}${{netD.toLocaleString('tr-TR')}}</div>
      <div class="card-sub">${{pct>0?'+':''}}${{pct.toFixed(1)}}% (eşleşen kayıtlar)</div></div>
    <div class="card c4"><div class="card-label">Yeni / Kaldırılan</div>
      <div class="card-value"><span class="up">+${{newRec}}</span> / <span class="dn">-${{rmRec}}</span></div>
      <div class="card-sub">2026/1'de yeni / kapanan kontenjanlar</div></div>`;
}}

function updateCompChart(){{
  // Side-by-side bar chart: top 20 specialties by 2025+2026 combined quota
  const m25={{}},m26={{}};
  D25.forEach(r=>m25[r.u]=(m25[r.u]||0)+r.n);
  D26.forEach(r=>m26[r.u]=(m26[r.u]||0)+r.n);
  const all=new Set([...Object.keys(m25),...Object.keys(m26)]);
  const sorted=[...all].map(u=>([u,(m25[u]||0)+(m26[u]||0)])).sort((a,b)=>b[1]-a[1]).slice(0,20);
  const labels=sorted.map(d=>shortL(d[0],25));
  const v25=sorted.map(d=>m25[d[0]]||0);
  const v26=sorted.map(d=>m26[d[0]]||0);
  if(chCmpS) chCmpS.destroy();
  chCmpS=new Chart(document.getElementById('chCmpSpec').getContext('2d'),{{
    type:'bar',
    data:{{labels,datasets:[
      {{label:'2025/2',data:v25,backgroundColor:'rgba(8,145,178,.75)',borderRadius:3}},
      {{label:'2026/1',data:v26,backgroundColor:'rgba(37,99,235,.85)',borderRadius:3}}
    ]}},
    options:{{responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{position:'top',labels:{{font:{{size:12}},padding:14}}}},
        tooltip:{{callbacks:{{label:c=>` ${{c.dataset.label}}: ${{c.raw.toLocaleString('tr-TR')}} kontenjan`}}}}}},
      scales:{{x:{{grid:{{display:false}},ticks:{{font:{{size:11}},maxRotation:30}}}},
        y:{{grid:{{color:'#f1f5f9'}},ticks:{{font:{{size:11}}}}}}}}
    }}
  }});
}}

function renderCmp(){{
  const cols=(r)=>{{
    const ct=changeType(r);
    const diff=r.p!=null?r.n-r.p:null;
    const pct=r.p>0?(r.n-r.p)/r.p*100:null;
    const prevHtml=r.p!=null
      ?`<span class="quota" style="color:var(--accent)">${{r.p}}</span>`
      :(r.pc!=null?`<span title="2025/2 şehir toplamı: ${{r.pc}}" style="color:var(--muted);cursor:help">~${{r.pc}}</span>`
      :'<span class="tag-new">YENİ</span>');
    const currHtml=r.n>0?`<span class="quota">${{r.n}}</span>`:`<span class="tag-rm">KALDIRILDI</span>`;
    const diffHtml=diff!=null
      ?`<span class="diff-cell ${{diff>0?'diff-pos':diff<0?'diff-neg':'diff-zero'}}">${{diff>0?'+':''}}${{diff}}</span>`
      :'<span class="diff-na">—</span>';
    const pctHtml=pct!=null
      ?`<span class="pct-badge ${{pct>0?'pct-up':pct<0?'pct-dn':'pct-zero'}}">${{pct>0?'+':''}}${{pct.toFixed(1)}}%</span>`
      :'<span class="diff-na">—</span>';
    return `<td>${{badgeS(r.s)}}</td><td>${{badgeTur(r.t)}}</td><td><strong>${{r.i}}</strong></td>
      ${{kurumCell(r)}}<td class="uzmanlik-cell">${{r.u}}</td>
      <td>${{prevHtml}}</td><td>${{currHtml}}</td><td>${{diffHtml}}</td><td>${{pctHtml}}</td>`;
  }};
  const rc=r=>{{const ct=changeType(r);
    return ct==='up'?'row-up':ct==='dn'?'row-dn':ct==='new'?'row-new':ct==='rm'?'row-rm':'';
  }};
  renderTable({{data:fCmp,tbodyId:'tbCmp',ndId:'ndCmp',piId:'piCmp',pbId:'pbCmp',tiId:'tiCmp',
    page:pgCmp,maxN:MAX_N26,cols,rowClass:rc}});
  wirePagination('pbCmp',(p)=>{{pgCmp=p;renderCmp();}},()=>Math.ceil(fCmp.length/PS)||1,()=>pgCmp);
}}

// ── Pagination wiring helper ──────────────────────────────────────────────────
function wirePagination(pbId, setter, getTp, getCur){{
  const pb=document.getElementById(pbId);
  pb.querySelectorAll('.pbtn').forEach((btn,_)=>{{
    if(btn.disabled) return;
    const origClick=btn.onclick;
    btn.onclick=()=>{{
      const newP=origClick?.();
      if(newP!=null&&newP!==getCur()){{ setter(newP); }}
    }};
  }});
}}

function reset26(){{document.getElementById('s26').value='';document.getElementById('fi26').value='';
  document.getElementById('fu26').value='';document.getElementById('ft26').value='';
  as26='';document.querySelectorAll('#sb26 .sbn').forEach(b=>b.classList.remove('active'));
  document.querySelector('#sb26 .sbn[data-v=""]').classList.add('active');apply26();}}

function reset25(){{document.getElementById('s25').value='';document.getElementById('fi25').value='';
  document.getElementById('fu25').value='';document.getElementById('ft25').value='';
  as25='';document.querySelectorAll('#sb25 .sbn').forEach(b=>b.classList.remove('active'));
  document.querySelector('#sb25 .sbn[data-v=""]').classList.add('active');apply25();}}

function resetCmp(){{document.getElementById('sCmp').value='';document.getElementById('fiCmp').value='';
  document.getElementById('fuCmp').value='';document.getElementById('ftCmp').value='';
  asCmp='';activeCh='';
  document.querySelectorAll('#sbCmp .sbn').forEach(b=>b.classList.remove('active'));
  document.querySelector('#sbCmp .sbn[data-v=""]').classList.add('active');
  document.querySelectorAll('#changePills .cpill').forEach(b=>b.classList.remove('active'));
  document.querySelector('#changePills .cpill[data-change=""]').classList.add('active');
  applyCmp();}}

// ── Boot ──────────────────────────────────────────────────────────────────────
initTab26();
chartsInit.t26=true;
</script>
</body>
</html>'''


def main():
    print('Parsing 2026/1 PDF...')
    r26 = parse_2026(PDF_2026)
    print(f'  → {len(r26)} records, {sum(r["n"] for r in r26):,} total quota')

    print('Parsing 2025/2 PDF...')
    r25 = parse_2025(PDF_2025)
    print(f'  → {len(r25)} records, {sum(r["n"] for r in r25):,} total quota')

    print('Matching comparison keys...')
    enrich_with_comparison(r26, r25)
    matched = sum(1 for r in r26 if r['p'] is not None)
    print(f'  → {matched} / {len(r26)} records matched across years')

    html = generate_html(r26, r25)
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Generated: {OUTPUT}')


if __name__ == '__main__':
    main()
