import json
import os
import re
import html
import unicodedata
from collections import defaultdict

def clean_cell(cell_html):
    # remove footnotes: <a id="notetext_..." ...>...</a>
    s = re.sub(r'<a id="notetext_[^"]*"[^>]*>.*?</a>', '', cell_html)
    s = re.sub(r'<a class="anchor[^"]*"[^>]*>.*?</a>', '', s)
    s = re.sub(r'<(br|div|p|tr|td|th)[^>]*>', ' ', s, flags=re.I)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    return ' '.join(s.split())

def clean_bpm(bpm_str):
    # remove [LP] marker from BPM
    s = bpm_str.replace('[LP]', '').strip()
    return ' '.join(s.split())

def parse_level(val):
    if not val:
        return None
    val = val.replace('[LP]', '').strip()
    if val.isdigit():
        return int(val)
    return None

def norm(s):
    if not s:
        return ''
    s = s.replace('Ⓤ', '[UPPER]').replace('🪐', '●')
    s = unicodedata.normalize('NFKC', s)
    s = s.replace('～', '〜')
    s = ' '.join(s.split())
    return s.strip().lower()

def parse_html_table(table_html):
    rows_html = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)
    grid = []
    cell_metadata = []
    for r_idx, r_html in enumerate(rows_html):
        while len(grid) <= r_idx:
            grid.append([])
            cell_metadata.append([])
        
        tds = re.findall(r'<t([dh])([^>]*)>(.*?)</t\1>', r_html, re.DOTALL)
        col_idx = 0
        for tag, attrs, content in tds:
            while col_idx < len(grid[r_idx]) and grid[r_idx][col_idx] is not None:
                col_idx += 1
            
            colspan_m = re.search(r'colspan="?(\d+)"?', attrs)
            colspan = int(colspan_m.group(1)) if colspan_m else 1
            rowspan_m = re.search(r'rowspan="?(\d+)"?', attrs)
            rowspan = int(rowspan_m.group(1)) if rowspan_m else 1
            
            cleaned = clean_cell(content)
            
            for dr in range(rowspan):
                tr = r_idx + dr
                while len(grid) <= tr:
                    grid.append([])
                    cell_metadata.append([])
                while len(grid[tr]) < col_idx + colspan:
                    grid[tr].append(None)
                    cell_metadata[tr].append(None)
                for dc in range(colspan):
                    grid[tr][col_idx + dc] = cleaned
                    cell_metadata[tr][col_idx + dc] = {'colspan': colspan, 'rowspan': rowspan, 'is_origin': (dr == 0 and dc == 0), 'tag': tag}
            
            col_idx += colspan
    return grid, cell_metadata

def build_music_list(shinkyoku_html_path, kyukyoku_html_path, lively_html_path):
    # 1. Parse Lively Table 2
    with open(lively_html_path, 'r', encoding='utf-8') as f:
        l_text = f.read()

    pos = 0
    l_tables = []
    while True:
        start = l_text.find('<table', pos)
        if start == -1: break
        end = l_text.find('</table>', start) + 8
        l_tables.append(l_text[start:end])
        pos = end

    lively_grid, lively_meta = parse_html_table(l_tables[2])
    lively_songs = []
    current_ver = 'Unknown'

    for r in range(len(lively_grid)):
        row = lively_grid[r]
        if not row or len(row) < 8: continue
        if row[0] in ('区分', 'B'): continue
        if lively_meta[r][0]['colspan'] >= 8:
            current_ver = re.sub(r'[▲▼/△]', '', row[0]).strip()
            continue
        k = row[0]
        if lively_meta[r][1]['colspan'] == 2:
            genre = ''
            title = row[1]
            artist = row[3]
            bpm = clean_bpm(row[4])
            easy = parse_level(row[6])
            normal = parse_level(row[7])
            hyper = parse_level(row[8])
            ex = parse_level(row[9])
        else:
            genre = row[1]
            title = row[2]
            artist = row[3]
            bpm = clean_bpm(row[4])
            easy = parse_level(row[6])
            normal = parse_level(row[7])
            hyper = parse_level(row[8])
            ex = parse_level(row[9])
        if title in ('曲名', 'Lv'): continue
        lively_songs.append({
            'ver': current_ver,
            'genre': genre,
            'title': title,
            'artist': artist,
            'bpm': bpm,
            'easy': easy,
            'normal': normal,
            'hyper': hyper,
            'ex': ex,
            'pack': k
        })

    # Build Lively lookup tables
    lively_by_gta = {}
    lively_by_gt = {}
    lively_by_ta = {}
    lively_by_t = defaultdict(list)

    for l in lively_songs:
        gn = norm(l['genre'])
        tn = norm(l['title'])
        an = norm(l['artist'])
        k = l['pack']
        lively_by_gta[(gn, tn, an)] = k
        if (gn, tn) not in lively_by_gt:
            lively_by_gt[(gn, tn)] = k
        if (tn, an) not in lively_by_ta:
            lively_by_ta[(tn, an)] = k
        lively_by_t[tn].append(l)

    def match_pack(genre, title, artist):
        gn = norm(genre)
        tn = norm(title)
        an = norm(artist)
        if (gn, tn, an) in lively_by_gta:
            return lively_by_gta[(gn, tn, an)]
        if (gn, tn) in lively_by_gt:
            return lively_by_gt[(gn, tn)]
        if (tn, an) in lively_by_ta:
            return lively_by_ta[(tn, an)]
        if tn in lively_by_t:
            return lively_by_t[tn][0]['pack']
        return ''

    # 2. Parse Shinkyoku Table 0
    with open(shinkyoku_html_path, 'r', encoding='utf-8') as f:
        s_text = f.read()

    t0 = s_text[s_text.find('<table'):s_text.find('</table>')+8]
    s_grid, s_meta = parse_html_table(t0)

    shinkyoku_songs = []
    for r in range(len(s_grid)):
        row = s_grid[r]
        if not row or len(row) < 8: continue
        if row[0] in ('ジャンル名', 'B'): continue
        if s_meta[r][0]['colspan'] >= 8: continue
        if s_meta[r][0]['colspan'] == 2:
            genre = ''
            title = row[0]
            artist = row[2]
            bpm = clean_bpm(row[3])
            easy = parse_level(row[5])
            normal = parse_level(row[6])
            hyper = parse_level(row[7])
            ex = parse_level(row[8])
        else:
            genre = row[0]
            title = row[1]
            artist = row[2]
            bpm = clean_bpm(row[3])
            easy = parse_level(row[5])
            normal = parse_level(row[6])
            hyper = parse_level(row[7])
            ex = parse_level(row[8])
        if title in ('曲名', 'Lv'): continue
        pack = match_pack(genre, title, artist)
        shinkyoku_songs.append({
            'ver': "pop'n music High☆Cheers!!",
            'genre': genre,
            'title': title,
            'artist': artist,
            'bpm': bpm,
            'easy': easy,
            'normal': normal,
            'hyper': hyper,
            'ex': ex,
            'pack': pack
        })

    # 3. Parse Kyukyoku Tables 1, 2, 3
    with open(kyukyoku_html_path, 'r', encoding='utf-8') as f:
        k_text = f.read()

    pos = 0
    k_tables = []
    while True:
        start = k_text.find('<table', pos)
        if start == -1: break
        end = k_text.find('</table>', start) + 8
        k_tables.append(k_text[start:end])
        pos = end

    kyukyoku_songs = []
    for t_idx in (1, 2, 3):
        grid, meta = parse_html_table(k_tables[t_idx])
        current_ver = "Unknown"
        for r in range(len(grid)):
            row = grid[r]
            if not row or len(row) < 8: continue
            if row[0] in ('ジャンル名', 'B'): continue
            if meta[r][0]['colspan'] >= 8:
                v = row[0]
                v = re.sub(r'[▲▼/△]', '', v).strip()
                current_ver = v
                continue
            if meta[r][0]['colspan'] == 2:
                genre = ''
                title = row[0]
                artist = row[2]
                bpm = clean_bpm(row[3])
                easy = parse_level(row[5])
                normal = parse_level(row[6])
                hyper = parse_level(row[7])
                ex = parse_level(row[8])
            else:
                genre = row[0]
                title = row[1]
                artist = row[2]
                bpm = clean_bpm(row[3])
                easy = parse_level(row[5])
                normal = parse_level(row[6])
                hyper = parse_level(row[7])
                ex = parse_level(row[8])
            if title in ('曲名', 'Lv'): continue
            pack = match_pack(genre, title, artist)
            kyukyoku_songs.append({
                'ver': current_ver,
                'genre': genre,
                'title': title,
                'artist': artist,
                'bpm': bpm,
                'easy': easy,
                'normal': normal,
                'hyper': hyper,
                'ex': ex,
                'pack': pack
            })

    # Combine HC songs
    hc_songs = shinkyoku_songs + kyukyoku_songs

    # 4. Check for Lively-only songs (songs present in Lively but not in HC)
    hc_title_set = set(norm(s['title']) for s in hc_songs)
    hc_gta_set = set((norm(s['genre']), norm(s['title']), norm(s['artist'])) for s in hc_songs)

    lively_only_songs = []
    for l in lively_songs:
        gn = norm(l['genre'])
        tn = norm(l['title'])
        an = norm(l['artist'])
        if (gn, tn, an) not in hc_gta_set and tn not in hc_title_set:
            lively_only_songs.append(l)

    all_songs = hc_songs + lively_only_songs

    return all_songs, len(shinkyoku_songs), len(kyukyoku_songs), len(lively_only_songs)

if __name__ == '__main__':
    songs, n_new, n_old, n_lively_only = build_music_list(
        'tmp_scrape/shinkyoku.html',
        'tmp_scrape/kyukyoku.html',
        'tmp_scrape/lively.html'
    )
    print(f'Done! New: {n_new}, Old: {n_old}, Lively-only: {n_lively_only}, Total: {len(songs)}')

    out_path = 'popn_music_list.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(songs, f, ensure_ascii=False, indent=2)
    print(f'Wrote {len(songs)} songs to {out_path} ({os.path.getsize(out_path)} bytes)')
