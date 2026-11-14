import os
import re
import json
import sqlite3
import feedparser
import requests
import random
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# --- KONFIGURASI PATH & DOMAIN ---
DB_PATH = "database.sqlite"
RSS_FILE = "rss_list.txt"
OUTPUT_DIR = "."
BASE_URL = "https://thenewsday112.github.io/semuaartikel34"

# Header HTTP agar scraping tidak diblokir
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Kamus sinonim bahasa Inggris untuk variasi kata alami (judul & isi)
EN_SYNONYMS = {
    r'\bannounced\b': ['unveiled', 'revealed', 'declared', 'confirmed'],
    r'\bannounces\b': ['unveils', 'reveals', 'introduces', 'confirms'],
    r'\bsaid\b': ['stated', 'noted', 'remarked', 'mentioned'],
    r'\bsays\b': ['states', 'notes', 'indicates', 'claims'],
    r'\bnew\b': ['latest', 'upcoming', 'newly introduced', 'fresh'],
    r'\bbig\b': ['major', 'significant', 'massive', 'substantial'],
    r'\bissue\b': ['problem', 'concern', 'glitch', 'matter'],
    r'\bissues\b': ['problems', 'concerns', 'complications', 'challenges'],
    r'\busers\b': ['customers', 'consumers', 'owners', 'people'],
    r'\bcompany\b': ['firm', 'tech giant', 'organization', 'manufacturer'],
    r'\blaunched\b': ['rolled out', 'introduced', 'released', 'debuted'],
    r'\blaunches\b': ['rolls out', 'introduces', 'releases', 'debuts'],
    r'\bplan\b': ['strategy', 'initiative', 'proposal', 'blueprint'],
    r'\bplans\b': ['aims', 'intends', 'prepares', 'looks'],
    r'\bshowed\b': ['demonstrated', 'indicated', 'highlighted', 'revealed'],
    r'\bshows\b': ['demonstrates', 'indicates', 'highlights', 'reveals'],
    r'\bupdate\b': ['upgrade', 'revision', 'enhancement', 'patch'],
    r'\bimportant\b': ['crucial', 'key', 'notable', 'vital'],
    r'\bquickly\b': ['rapidly', 'swiftly', 'promptly'],
    r'\bcurrently\b': ['presently', 'at the moment', 'right now']
}

def apply_synonym_spin(text):
    for pattern, replacements in EN_SYNONYMS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            # Ganti secara acak dengan probabilitas 60% agar tidak terlalu kaku
            if random.random() < 0.6:
                rep = random.choice(replacements)
                def replace_match(match):
                    word = match.group(0)
                    if word.istitle():
                        return rep.capitalize()
                    elif word.isupper():
                        return rep.upper()
                    return rep
                text = re.sub(pattern, replace_match, text, count=1, flags=re.IGNORECASE)
    return text

# --------------------------------------------------------------------------
# FUNGSI PARAFRASE JUDUL BAHASA INGGRIS
# --------------------------------------------------------------------------
def paraphrase_title(title):
    if not title or title == 'Tanpa Judul':
        return title
    
    spun_title = apply_synonym_spin(title.strip())
    
    # Opsional: tambahkan variasi prefix berita ringan pada 30% judul
    prefixes = ["Latest Update: ", "Tech Report: ", "Industry News: ", "Breaking: "]
    if random.random() < 0.30 and not any(spun_title.startswith(p) for p in prefixes):
        spun_title = random.choice(prefixes) + spun_title
        
    return spun_title

# --------------------------------------------------------------------------
# FUNGSI PARAFRASE KONTEN BAHASA INGGRIS (Tanpa AI / Tanpa API Key)
# --------------------------------------------------------------------------
def local_paraphrase(text_html):
    if not text_html:
        return text_html
    
    try:
        soup = BeautifulSoup(text_html, 'html.parser')
        paragraphs = soup.find_all('p')
        
        transition_phrases = [
            "According to recent reports, ",
            "Sources indicate that ",
            "In a recent development, ",
            "Industry observers note that ",
            "It has been revealed that ",
            "Recent findings suggest that "
        ]
        
        new_paragraphs = []
        for idx, p in enumerate(paragraphs):
            text = p.get_text().strip()
            if not text:
                continue
            
            # Terapkan penggantian sinonim bahasa Inggris
            text = apply_synonym_spin(text)
            
            # Pecah kalimat berdasarkan titik + spasi agar singkatan seperti U.S. tidak terpotong
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
            
            if sentences:
                # Sisipkan frase transisi bahasa Inggris pada beberapa paragraf (tidak semua agar natural)
                if len(sentences) > 1 and random.random() < 0.55:
                    first_sent = sentences[0]
                    if not first_sent.startswith(tuple(transition_phrases)):
                        # Pertahankan huruf kapital jika kata pertama adalah nama entitas/akronim (2 huruf besar)
                        if len(first_sent) > 1 and not first_sent[:2].isupper():
                            first_sent = first_sent[0].lower() + first_sent[1:]
                        sentences[0] = random.choice(transition_phrases) + first_sent
            
            modified_text = ' '.join(sentences)
            if not modified_text.endswith(('.', '!', '?')):
                modified_text += '.'
                
            new_paragraphs.append(f"<p>{modified_text}</p>")
            
        if not new_paragraphs:
            return text_html
            
        return "\n".join(new_paragraphs)
    except Exception:
        return text_html

# --------------------------------------------------------------------------
# KODE IKLAN ADSTERRA
# --------------------------------------------------------------------------
ADSTERRA_CODE = """
<div style="text-align:center; margin:20px 0;">
    <script type="text/javascript">
        atOptions = {
            'key' : 'f9e40eb3b3cd05f1038aac7b36b33ad2',
            'format' : 'iframe',
            'height' : 90,
            'width' : 728,
            'params' : {}
        };
    </script>
    <script type="text/javascript" src="https://upholdbrilliancerecast.com/f9e40eb3b3cd05f1038aac7b36b33ad2/invoke.js"></script>
</div>
"""

# --------------------------------------------------------------------------
# INISIALISASI DATABASE
# --------------------------------------------------------------------------
def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS artikel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link TEXT UNIQUE,
            judul TEXT,
            konten TEXT,
            gambar TEXT,
            tanggal_publish TEXT,
            tanggal_update TEXT
        )
    """)
    
    cursor.execute("PRAGMA table_info(artikel)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'gambar' not in columns:
        cursor.execute("ALTER TABLE artikel ADD COLUMN gambar TEXT")
    if 'tanggal_publish' not in columns:
        cursor.execute("ALTER TABLE artikel ADD COLUMN tanggal_publish TEXT")
    if 'tanggal_update' not in columns:
        cursor.execute("ALTER TABLE artikel ADD COLUMN tanggal_update TEXT")
    
    conn.commit()
    conn.close()

# --------------------------------------------------------------------------
# EXTRACT KONTEN + GAMBAR + TANGGAL
# --------------------------------------------------------------------------
def extract_full_content(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=8)
        if response.status_code != 200:
            return None, None, None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        image_url = None
        og_image = soup.find('meta', property='og:image') or soup.find('meta', attrs={'name': 'og:image'})
        if og_image and og_image.get('content'):
            image_url = og_image['content']
        
        tanggal = None
        for meta_prop in ['article:published_time', 'article:modified_time', 'datePublished']:
            meta = soup.find('meta', property=meta_prop) or soup.find('meta', attrs={'name': meta_prop})
            if meta and meta.get('content'):
                tanggal = meta['content']
                break
        
        paragraphs = soup.find_all('p')
        full_text = []
        for p in paragraphs:
            text = p.get_text().strip()
            if len(text) > 40 and not any(x in text.lower() for x in ['cookie', 'privacy policy', 'subscribe', 'all rights reserved', 'terms of use']):
                full_text.append(f"<p>{text}</p>")
                
        if not full_text:
            return None, image_url, tanggal
            
        return "\n".join(full_text), image_url, tanggal
    except Exception:
        return None, None, None

# --------------------------------------------------------------------------
# PROCESS SINGLE FEED
# --------------------------------------------------------------------------
def process_single_feed(feed_url):
    feed_url = feed_url.strip()
    if not feed_url or feed_url.startswith("#"):
        return 0, 0

    baru = 0
    duplikat = 0
    
    try:
        feed = feedparser.parse(feed_url)
        conn = sqlite3.connect(DB_PATH, timeout=15)
        cursor = conn.cursor()
        
        for entry in feed.entries:
            link = entry.get('link', '')
            raw_judul = entry.get('title', 'No Title')
            
            if not link:
                continue

            cursor.execute("SELECT id FROM artikel WHERE link = ?", (link,))
            if cursor.fetchone():
                duplikat += 1
                continue

            full_text_html, image_url, tanggal = extract_full_content(link)
            
            if not full_text_html:
                summary = entry.get('summary', entry.get('description', 'Content not available.'))
                full_text_html = f"<p>{summary}</p>"
            
            # --- JALANKAN PARAFRASE BAHASA INGGRIS (JUDUL & KONTEN) ---
            judul = paraphrase_title(raw_judul)
            print(f"[*] Paraphrasing (EN): {judul[:45]}...")
            full_text_html = local_paraphrase(full_text_html)

            if not tanggal:
                published_parsed = entry.get('published_parsed')
                if published_parsed:
                    tanggal = datetime(*published_parsed[:6]).isoformat()
                else:
                    tanggal = datetime.now().isoformat()
            
            tanggal_update = datetime.now().isoformat()
            
            img_tag = f'<div style="text-align:center; margin-bottom:20px;"><img src="{image_url}" alt="{judul}" style="max-width:100%; height:auto; border-radius:8px;" loading="lazy"></div>' if image_url else ""
            
            konten_lengkap = f"""
            {img_tag}
            {ADSTERRA_CODE}
            <div class="article-body" style="font-size: 16px; line-height: 1.8; color: #333;">
                {full_text_html}
                <p style="margin-top: 25px;">
                    <a href="{link}" target="_blank" rel="nofollow noopener" style="color: #0d6efd; text-decoration: none; font-weight: bold;">
                        &rarr; Read original article
                    </a>
                </p>
            </div>
            {ADSTERRA_CODE}
            """
            
            try:
                cursor.execute(
                    "INSERT INTO artikel (link, judul, konten, gambar, tanggal_publish, tanggal_update) VALUES (?, ?, ?, ?, ?, ?)",
                    (link, judul, konten_lengkap, image_url, tanggal, tanggal_update)
                )
                conn.commit()
                baru += 1
            except sqlite3.IntegrityError:
                duplikat += 1
            except Exception:
                pass
                
        conn.close()
    except Exception:
        pass
        
    return baru, duplikat

# --------------------------------------------------------------------------
# GENERATE SITEMAP.XML & ROBOTS.TXT
# --------------------------------------------------------------------------
def generate_sitemap_and_robots():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, tanggal_update FROM artikel ORDER BY id DESC")
    articles = cursor.fetchall()
    conn.close()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    sitemap_path = os.path.join(OUTPUT_DIR, "sitemap.xml")
    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_parts.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    xml_parts.append(f'<url><loc>{BASE_URL}/</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq><priority>1.0</priority></url>')
    xml_parts.append(f'<url><loc>{BASE_URL}/page2.html</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq><priority>0.9</priority></url>')
    
    for artikel_id, tanggal_update in articles:
        lastmod = tanggal_update[:10] if tanggal_update else today
        xml_parts.append(f'<url><loc>{BASE_URL}/index.html#artikel-{artikel_id}</loc><lastmod>{lastmod}</lastmod><changefreq>weekly</changefreq><priority>0.7</priority></url>')
    xml_parts.append('</urlset>')
    
    with open(sitemap_path, "w", encoding="utf-8") as f:
        f.write("\n".join(xml_parts))
    
    robots_path = os.path.join(OUTPUT_DIR, "robots.txt")
    robots_content = f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\nCrawl-delay: 1\n"
    with open(robots_path, "w", encoding="utf-8") as f:
        f.write(robots_content)

# --------------------------------------------------------------------------
# EXPORT KE INDEX.HTML & PAGE2.HTML
# --------------------------------------------------------------------------
def export_to_two_files():
    if not os.path.exists(DB_PATH):
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, judul, konten, gambar, tanggal_publish, tanggal_update, link FROM artikel ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return

    total_articles = len(rows)
    mid_point = (total_articles + 1) // 2

    parts = [
        ("index.html", rows[:mid_point], "Halaman Utama (Update Terkini)", "page2.html", "Halaman 1"),
        ("page2.html", rows[mid_point:], "Halaman 2 (Arsip Berita)", "index.html", "Halaman 2")
    ]

    for filename, chunk, part_name, other_part, page_label in parts:
        output_file = os.path.join(OUTPUT_DIR, filename)
        sample_titles = ", ".join([row[1][:50] for row in chunk[:5]])
        meta_desc = f"Katalog berita interaktif: {sample_titles}. Update harian dengan informasi terpercaya."[:160]
        
        html_parts = []
        html_parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Portal Berita Interaktif - {part_name}</title>
    <meta name="description" content="{meta_desc}">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
    <style>
        :root {{
            --primary: #2563eb;
            --primary-dark: #1d4ed8;
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --text-main: #1e293b;
            --text-muted: #64748b;
            --border: #e2e8f0;
        }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header-box {{
            background: var(--card-bg);
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
            text-align: center;
            margin-bottom: 30px;
        }}
        .header-box h1 {{
            margin: 0 0 10px 0;
            font-size: 28px;
            color: var(--text-main);
        }}
        .search-box {{
            margin-top: 20px;
            max-width: 500px;
            margin-left: auto;
            margin-right: auto;
        }}
        .search-box input {{
            width: 100%;
            padding: 12px 20px;
            border: 2px solid var(--border);
            border-radius: 8px;
            font-size: 16px;
            outline: none;
            transition: border-color 0.2s;
        }}
        .search-box input:focus {{
            border-color: var(--primary);
        }}
        .grid-container {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 25px;
            margin-bottom: 40px;
        }}
        .article-card {{
            background: var(--card-bg);
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
            padding: 20px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: transform 0.2s, box-shadow 0.2s;
            position: relative;
        }}
        .article-card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1);
        }}
        .article-card img {{
            width: 100%;
            height: 180px;
            object-fit: cover;
            border-radius: 8px;
            margin-bottom: 15px;
        }}
        .article-card h2 {{
            font-size: 18px;
            margin: 0 0 10px 0;
            color: var(--text-main);
            line-height: 1.4;
        }}
        .article-meta {{
            font-size: 13px;
            color: var(--text-muted);
            margin-bottom: 15px;
        }}
        .card-actions {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-top: 1px solid var(--border);
            padding-top: 15px;
            margin-top: auto;
        }}
        .btn {{
            background-color: var(--primary);
            color: white;
            border: none;
            padding: 8px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            text-decoration: none;
            transition: background 0.2s;
        }}
        .btn:hover {{
            background-color: var(--primary-dark);
        }}
        .btn-pdf {{
            background-color: #ef4444;
        }}
        .btn-pdf:hover {{
            background-color: #dc2626;
        }}
        .pagination {{
            text-align: center;
            margin: 40px 0;
        }}
        .pagination a {{
            display: inline-block;
            padding: 10px 20px;
            margin: 0 5px;
            background: white;
            border-radius: 6px;
            text-decoration: none;
            color: var(--text-main);
            font-weight: bold;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        .pagination a.active {{
            background: var(--primary);
            color: white;
        }}
        .modal {{
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        .modal-content {{
            background: white;
            width: 100%;
            max-width: 800px;
            max-height: 85vh;
            border-radius: 12px;
            padding: 30px;
            overflow-y: auto;
            position: relative;
        }}
        .close-modal {{
            position: absolute;
            top: 15px;
            right: 20px;
            font-size: 24px;
            cursor: pointer;
            color: var(--text-muted);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header-box">
            <h1>Katalog Berita & Artikel Interaktif - {part_name}</h1>
            <p>Total {total_articles} artikel tersedia dalam direktori berita harian.</p>
            <div class="search-box">
                <input type="text" id="searchInput" placeholder="Cari judul artikel..." onkeyup="filterArticles()">
            </div>
            <div style="margin-top: 15px;">
                <a href="{other_part}" style="color: var(--primary); text-decoration: none; font-weight: bold;">📄 Beralih ke {("Halaman 2" if filename == "index.html" else "Halaman Utama")} →</a>
            </div>
        </div>

        <div class="grid-container" id="articleGrid">""")

        for item in chunk:
            artikel_id, judul, konten, gambar, tanggal_publish, tanggal_update, link = item
            safe_title = str(judul).replace('"', '').replace("'", '').replace('/', '_').replace('\\', '_')
            img_thumb = gambar if gambar else "https://via.placeholder.com/350x180?text=Portal+Berita"
            
            try:
                tgl_pub = datetime.fromisoformat(tanggal_publish.replace('Z', '+00:00')).strftime('%d %b %Y') if tanggal_publish else '-'
            except Exception:
                tgl_pub = tanggal_publish[:10] if tanggal_publish else '-'

            html_parts.append(f"""
            <div class="article-card" data-title="{judul.lower()}">
                <div>
                    <img src="{img_thumb}" alt="{judul}" loading="lazy">
                    <h2>#{artikel_id}. {judul}</h2>
                    <div class="article-meta">📅 {tgl_pub}</div>
                </div>
                <div class="card-actions">
                    <button class="btn" onclick="openModal({artikel_id})">📖 Baca Selengkapnya</button>
                    <button class="btn btn-pdf" onclick="downloadPDF('content-{artikel_id}', '{safe_title}')">📄 PDF</button>
                </div>
                <div id="content-{artikel_id}" style="display:none;">
                    <h2 style="color:#111;">{judul}</h2>
                    <p style="font-size:12px; color:#666;">Tanggal: {tgl_pub} | Sumber: {link}</p>
                    <hr style="border:0; border-top:1px solid #ddd; margin:15px 0;">
                    {konten}
                </div>
            </div>""")

        idx1_active = "active" if filename == "index.html" else ""
        idx2_active = "active" if filename == "page2.html" else ""

        html_parts.append(f"""
        </div>
        <div class="pagination">
            <a href="index.html" class="{idx1_active}">⬅️ Halaman 1</a>
            <a href="page2.html" class="{idx2_active}">Halaman 2 ➡️</a>
        </div>
    </div>

    <div id="articleModal" class="modal">
        <div class="modal-content">
            <span class="close-modal" onclick="closeModal()">&times;</span>
            <div id="modalBody"></div>
        </div>
    </div>

    <script>
        function filterArticles() {{
            let input = document.getElementById('searchInput').value.toLowerCase();
            let cards = document.getElementsByClassName('article-card');
            for (let i = 0; i < cards.length; i++) {{
                let title = cards[i].getAttribute('data-title');
                if (title.includes(input)) {{
                    cards[i].style.display = "";
                }} else {{
                    cards[i].style.display = "none";
                }}
            }}
        }}

        function openModal(id) {{
            let content = document.getElementById('content-' + id).innerHTML;
            document.getElementById('modalBody').innerHTML = content;
            document.getElementById('articleModal').style.display = 'flex';
        }}

        function closeModal() {{
            document.getElementById('articleModal').style.display = 'none';
        }}

        window.onclick = function(event) {{
            let modal = document.getElementById('articleModal');
            if (event.target == modal) {{
                modal.style.display = 'none';
            }}
        }}

        function downloadPDF(elementId, filename) {{
            let element = document.getElementById(elementId);
            let originalDisplay = element.style.display;
            element.style.display = 'block';
            
            const opt = {{
                margin: 10,
                filename: filename + '.pdf',
                image: {{ type: 'jpeg', quality: 0.98 }},
                html2canvas: {{ scale: 2, useCORS: true }},
                jsPDF: {{ unit: 'mm', format: 'a4', orientation: 'portrait' }}
            }};

            html2pdf().set(opt).from(element).save().then(() => {{
                element.style.display = originalDisplay;
            }});
        }}
    </script>
</body>
</html>""")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(html_parts))

        print(f"✅ Katalog Grid HTML: {output_file} ({len(chunk)} artikel)")

# --------------------------------------------------------------------------
# SCRAPE UTAMA
# --------------------------------------------------------------------------
def scrape_massive_rss():
    if not os.path.exists(RSS_FILE):
        print(f"[ERROR] File {RSS_FILE} tidak ditemukan!")
        return

    init_db()
    
    with open(RSS_FILE, "r", encoding="utf-8") as f:
        rss_urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    print(f"[*] Memulai penarikan data dari {len(rss_urls)} sumber RSS...\n")

    total_baru = 0
    total_duplikat = 0

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_single_feed, url): url for url in rss_urls}
        for future in as_completed(futures):
            b, d = future.result()
            total_baru += b
            total_duplikat += d

    print("\n" + "="*45)
    print(f"[SELESAI PEMANENAN]")
    print(f" - Artikel Baru : {total_baru}")
    print(f" - Duplikat/Eksis: {total_duplikat}")
    print("="*45)

    print("\n[*] Generate Katalog HTML (index.html & page2.html)...")
    export_to_two_files()
    
    print("\n[*] Generate sitemap.xml & robots.txt...")
    generate_sitemap_and_robots()
    
    print("\n" + "="*45)
    print("[SELESAI] Proses build selesai dengan sukses!")
    print("="*45)

if __name__ == "__main__":
    scrape_massive_rss()
