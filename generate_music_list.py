import json
import os
import re
import html
import unicodedata
import uuid
import sys
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

def assign_music_ids(songs, existing_songs):
    """既存リストを基に music_id を割り当てる。見つからない曲は新しい UUID を振る。

    music_id はスコアとの紐づけに使われるので、既存の曲は必ず同じ ID を引き継ぐ。
    照合は厳しい条件から順に行い、既存の1曲は1回しか使わない
    (同名・同アーティストの曲が複数あっても ID が重複しない)。
    戻り値は (引き継いだ数, 新規に振った数, 使われなかった既存の曲のリスト)。
    """
    key_funcs = [
        lambda x: (norm(x['genre']), norm(x['title']), norm(x['artist'])),
        lambda x: (norm(x['title']), norm(x['artist'])),
        lambda x: (norm(x['genre']), norm(x['title'])),
    ]
    pools = [defaultdict(list) for _ in key_funcs]
    for e in existing_songs:
        if not e.get('music_id'):
            continue
        for pool, kf in zip(pools, key_funcs):
            pool[kf(e)].append(e)

    used = set()
    for song in songs:
        song['music_id'] = None

    # 緩い条件の照合が、厳しい条件で一致する曲の ID を奪わないよう、条件ごとに全曲を処理する
    for pool, kf in zip(pools, key_funcs):
        for song in songs:
            if song['music_id']:
                continue
            for e in pool.get(kf(song), []):
                if e['music_id'] not in used:
                    used.add(e['music_id'])
                    song['music_id'] = e['music_id']
                    break

    n_kept = sum(1 for s in songs if s['music_id'])
    for song in songs:
        if not song['music_id']:
            song['music_id'] = str(uuid.uuid4())
    unused = [e for e in existing_songs if e.get('music_id') and e['music_id'] not in used]
    return n_kept, len(songs) - n_kept, unused

_ENTRY_KEY_FUNCS = [
    lambda x: (norm(x['genre']), norm(x['title']), norm(x['artist'])),
    lambda x: (norm(x['title']), norm(x['artist'])),
    lambda x: (norm(x['genre']), norm(x['title'])),
    lambda x: norm(x['title']),
]

def build_entry_pools(entries):
    """公式サイトの曲 (genre / title / artist / banner を持つ dict) の照合用索引を作る。"""
    pools = [defaultdict(list) for _ in _ENTRY_KEY_FUNCS]
    for e in entries:
        for pool, kf in zip(pools, _ENTRY_KEY_FUNCS):
            pool[kf(e)].append(e)
    return pools

def find_entry(song, pools):
    """曲に対応する公式サイトの曲を返す。見つからない (または同じキーに別のバナーが複数ある) ときは None。"""
    for pool, kf in zip(pools, _ENTRY_KEY_FUNCS):
        found = pool.get(kf(song), [])
        # 同じキーに別のバナーが複数あるときは決められないので、より厳しいキーで探す
        if found and len({e['banner'] for e in found}) == 1:
            return found[0]
    return None

def attach_banners(songs, existing_songs, banner_dir):
    """各曲にバナー画像の特徴量 (banner) を付ける。

    banner_dir は tools/fetch_banners.py の出力 (index.json と banners/*.png)。
    公式サイトの曲と照合できて画像がある曲は、その画像から特徴量を作る。照合できなかった曲、
    画像が無い曲、または banner_dir が無いときは、既存の曲リストの特徴量を (music_id で) 引き継ぐ。
    戻り値は (画像から作った数, 引き継いだ数, バナーが無い曲のリスト)。
    """
    from PIL import Image
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from src.banner_reader import banner_feature, encode_feature

    entries = []
    index_path = os.path.join(banner_dir, 'index.json')
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            entries = json.load(f)

    pools = build_entry_pools(entries)

    features = {}   # バナーのファイル名 → 特徴量の文字列
    def feature_of(entry):
        name = entry['banner']
        if name not in features:
            try:
                with Image.open(os.path.join(banner_dir, 'banners', name)) as im:
                    features[name] = encode_feature(banner_feature(im))
            except (OSError, ValueError):
                features[name] = ''
        return features[name]

    old_banner = {e['music_id']: e['banner'] for e in existing_songs if e.get('music_id') and e.get('banner')}
    n_new = n_kept = 0
    missing = []
    for song in songs:
        entry = find_entry(song, pools)
        banner = feature_of(entry) if entry else ''
        if banner:
            n_new += 1
        elif song['music_id'] in old_banner:
            banner = old_banner[song['music_id']]
            n_kept += 1
        else:
            missing.append(song)
        if banner:
            song['banner'] = banner
    return n_new, n_kept, missing

def write_music_list(songs, out_path):
    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(songs, f, ensure_ascii=False, indent=2)
    print(f'Wrote {len(songs)} songs to {out_path} ({os.path.getsize(out_path)} bytes)')

def report_banners(n_new, n_kept, missing):
    print(f'banner: new {n_new}, kept {n_kept}, missing {len(missing)}')
    for s in missing[:20]:
        print(f"  no banner: {s['genre']} / {s['title']} / {s['artist']}")

if __name__ == '__main__':
    out_path = 'popn_music_list.json'
    if '--attach-banners' in sys.argv:
        # 既存の曲リストに、tools/fetch_banners.py で取得したバナーの特徴量を足す (曲の追加・削除はしない)
        with open(out_path, 'r', encoding='utf-8') as f:
            songs = json.load(f)
        report_banners(*attach_banners(songs, songs, 'tmp_banners'))
        write_music_list(songs, out_path)
        sys.exit(0)

    songs, n_new, n_old, n_lively_only = build_music_list(
        'tmp_scrape/shinkyoku.html',
        'tmp_scrape/kyukyoku.html',
        'tmp_scrape/lively.html'
    )
    print(f'Done! New: {n_new}, Old: {n_old}, Lively-only: {n_lively_only}, Total: {len(songs)}')

    existing = []
    if os.path.exists(out_path):
        with open(out_path, 'r', encoding='utf-8') as f:
            existing = json.load(f)
    n_kept, n_added, unused = assign_music_ids(songs, existing)
    print(f'music_id: kept {n_kept}, new {n_added}, dropped {len(unused)}')
    for e in unused:
        print(f"  dropped: {e['title']} / {e['artist']} ({e['music_id']})")

    # バナーの特徴量は既存の曲リストから引き継ぐ。新しい曲の分は --attach-banners で足す
    report_banners(*attach_banners(songs, existing, 'tmp_banners'))
    write_music_list(songs, out_path)
