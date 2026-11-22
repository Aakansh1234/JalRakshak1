import os
import uuid
import json
import csv
import io
import random
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, session, send_from_directory, Response
from werkzeug.utils import secure_filename

import database
from ai_engine import analyze_civic_image, detect_duplicacy, calculate_priority_score

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = 'aquacivic_super_secret_hackathon_key_2026'

if os.environ.get('VERCEL') or os.environ.get('AWS_LAMBDA_FUNCTION_NAME'):
    UPLOAD_FOLDER = '/tmp/uploads'
else:
    UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads')
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except Exception:
    pass
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32 MB for photos/video frames

# Initialize database safely
try:
    database.init_db()
except Exception as e:
    print(f"Database init warning: {e}")

def get_current_user():
    if 'user_id' in session:
        conn = database.get_db_connection()
        user = conn.execute("SELECT id, name, email, role, department, karma_score, badges FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        conn.close()
        if user:
            u = dict(user)
            try:
                u['badges'] = json.loads(u['badges'])
            except:
                u['badges'] = ["Civic Citizen"]
            return u
    return None

# ==================== PAGE ROUTES ====================
@app.route('/')
def index():
    user = get_current_user()
    return render_template('index.html', current_user=user)

# ==================== HOME PAGE INTELLIGENCE API ====================
@app.route('/api/home/stats', methods=['GET'])
def home_stats():
    conn = database.get_db_connection()
    cursor = conn.cursor()

    # Calculate Total Water Loss and Water Saved
    water_loss_row = cursor.execute("SELECT SUM(estimated_water_loss_liters) FROM complaints WHERE status != 'Resolved'").fetchone()
    total_water_loss = water_loss_row[0] or 142000.0

    water_saved_row = cursor.execute("SELECT SUM(water_saved_liters) FROM wards").fetchone()
    total_water_saved = water_saved_row[0] or 1640000.0

    # Total and Resolved Cases
    total_cases = cursor.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
    resolved_cases = cursor.execute("SELECT COUNT(*) FROM complaints WHERE status = 'Resolved'").fetchone()[0]
    pending_cases = total_cases - resolved_cases

    # Worst Ward (Most issues / Highest water loss)
    worst_ward_row = cursor.execute('''
        SELECT name, zone, active_issues_count, water_loss_liters, hotspot_severity
        FROM wards ORDER BY active_issues_count DESC, water_loss_liters DESC LIMIT 1
    ''').fetchone()
    worst_ward = dict(worst_ward_row) if worst_ward_row else {
        'name': 'Ward 4 - Central Zone', 'zone': 'Central Zone',
        'active_issues_count': 4, 'water_loss_liters': 142000, 'hotspot_severity': 'Critical Hotspot'
    }

    # Best Ward (Zero Issues - Model Ward)
    best_ward_row = cursor.execute('''
        SELECT name, zone, active_issues_count, resolved_issues_count, water_saved_liters, is_model_ward
        FROM wards WHERE active_issues_count = 0 ORDER BY resolved_issues_count DESC LIMIT 1
    ''').fetchone()
    best_ward = dict(best_ward_row) if best_ward_row else {
        'name': 'Ward 12 - Model Green Town', 'zone': 'North Zone',
        'active_issues_count': 0, 'resolved_issues_count': 14, 'water_saved_liters': 520000, 'is_model_ward': 1
    }

    # All Wards for Dropdown
    wards = cursor.execute("SELECT name, zone, active_issues_count, resolved_issues_count, water_loss_liters FROM wards").fetchall()
    wards_list = [dict(w) for w in wards]

    conn.close()

    return jsonify({
        'total_water_loss_liters': total_water_loss,
        'total_water_saved_liters': total_water_saved,
        'total_cases': total_cases,
        'pending_cases': pending_cases,
        'resolved_cases': resolved_cases,
        'worst_ward': worst_ward,
        'best_ward': best_ward,
        'wards': wards_list,
        'avg_response_hours': 3.8
    })


# ==================== ALL-INDIA PLACES & SHOPS AUTOCOMPLETE SEARCH ====================
POPULAR_PLACES_PATH = os.path.join(app.static_folder, 'popular_places.json')
try:
    with open(POPULAR_PLACES_PATH, 'r', encoding='utf-8') as _f:
        LOCAL_PLACES_DB = json.load(_f)
except Exception as _e:
    LOCAL_PLACES_DB = []

INDIA_CITY_COORDS = {
    'mohali': (30.7046, 76.7179),
    'chandigarh': (30.7333, 76.7794),
    'panchkula': (30.6942, 76.8606),
    'kharar': (30.7488, 76.6429),
    'zirakpur': (30.6425, 76.8173),
    'derabassi': (30.5960, 76.8433),
    'kalka': (30.8385, 76.9329),
    'pinjore': (30.7954, 76.9174),
    'morinda': (30.7925, 76.4947),
    'kurali': (30.8252, 76.5746),
    'ropar': (30.9664, 76.5331),
    'rupnagar': (30.9664, 76.5331),
    'rajpura': (30.4842, 76.5937),
    'ambala': (30.3782, 76.7767),
    'kurukshetra': (29.9695, 76.8783),
    'karnal': (29.6857, 76.9905),
    'panipat': (29.3909, 76.9635),
    'sonipat': (28.9931, 77.0151),
    'delhi': (28.6139, 77.2090),
    'new delhi': (28.6139, 77.2090),
    'noida': (28.5355, 77.3910),
    'greater noida': (28.4744, 77.5040),
    'gurugram': (28.4595, 77.0266),
    'gurgaon': (28.4595, 77.0266),
    'faridabad': (28.4089, 77.3178),
    'ghaziabad': (28.6692, 77.4538),
    'ludhiana': (30.9010, 75.8573),
    'amritsar': (31.6340, 74.8723),
    'jalandhar': (31.3260, 75.5762),
    'patiala': (30.3398, 76.3869),
    'mumbai': (19.0760, 72.8777),
    'bengaluru': (12.9716, 77.5946),
    'bangalore': (12.9716, 77.5946),
    'hyderabad': (17.3850, 78.4867),
    'chennai': (13.0827, 80.2707),
    'kolkata': (22.5726, 88.3639),
    'jaipur': (26.9124, 75.7873),
    'lucknow': (26.8467, 80.9462),
}

CATEGORY_ICONS = {
    'mall': '🏬',
    'shop': '🛍️',
    'clothes': '🛍️',
    'supermarket': '🛒',
    'convenience': '🏪',
    'confectionery': '🍬',
    'food': '🍽️',
    'restaurant': '🍽️',
    'fast_food': '🍔',
    'cafe': '☕',
    'hospital': '🏥',
    'clinic': '🏥',
    'pharmacy': '💊',
    'transit': '🚏',
    'bus_stop': '🚌',
    'station': '🚆',
    'airport': '✈️',
    'sector': '🏢',
    'residential': '🏘️',
    'suburb': '🏘️',
    'society': '🏢',
    'techpark': '💻',
    'market': '🛍️',
    'landmark': '📍',
    'fuel': '⛽',
    'bank': '🏦',
    'atm': '🏧',
    'school': '🏫',
    'university': '🎓',
}

def resolve_location_coordinates(query_str, user_lat=None, user_lon=None):
    if not query_str:
        return None, None, query_str
    q_low = query_str.lower().strip()

    # Instant landmark & city overrides
    if "kharar bus stand" in q_low or "bus stand kharar" in q_low or "kharar bus stop" in q_low or "new bus stand kharar" in q_low:
        return 30.74981, 76.64122, "Kharar Bus Stand, NH 205, Kharar, Punjab"
    if q_low == "kharar" or q_low.startswith("kharar,"):
        return 30.74884, 76.64290, "Kharar, SAS Nagar, Punjab"
    if "thapar" in q_low and "patiala" in q_low:
        return 30.35453, 76.36580, "Thapar Institute of Engineering and Technology, Patiala, Punjab"
    if "thapar" in q_low:
        return 30.35453, 76.36580, "Thapar Institute of Engineering and Technology, Patiala, Punjab"
    if "sector 15" in q_low and "noida" in q_low:
        return 28.58488, 77.31161, "Sector 15, Noida, Uttar Pradesh"
    if "sector 62" in q_low and "noida" in q_low:
        return 28.6258, 77.3626, "Sector 62, Noida, Uttar Pradesh"
    if "elante" in q_low:
        return 30.7055, 76.8013, "Elante Mall, Industrial Area Phase 1, Chandigarh"

    # Check local database for exact matches
    for item in LOCAL_PLACES_DB:
        if item['name'].lower() == q_low or f"{item['name']}, {item['city']}".lower() == q_low:
            return float(item['lat']), float(item['lon']), f"{item['name']}, {item['city']}"

    # Determine coordinate biasing for search
    bias_lat = user_lat or 30.7046
    bias_lon = user_lon or 76.7179
    for city, coords in INDIA_CITY_COORDS.items():
        if city in q_low:
            bias_lat, bias_lon = coords
            break

    # Query Photon API with coordinate biasing & India bounds
    import urllib.request, urllib.parse, json
    url_photon = f"https://photon.komoot.io/api/?q={urllib.parse.quote(query_str)}&lat={bias_lat}&lon={bias_lon}&limit=10"
    try:
        req = urllib.request.Request(url_photon, headers={'User-Agent': 'CivicEye-Geocoder/2.0'})
        with urllib.request.urlopen(req, timeout=4.5) as resp:
            data = json.loads(resp.read().decode())
            features = data.get('features', [])
            for f in features:
                p = f.get('properties', {})
                coords = f.get('geometry', {}).get('coordinates', [])
                if len(coords) >= 2:
                    c_lon, c_lat = float(coords[0]), float(coords[1])
                    # Strict India geographic bounding box (Lat 6.0 to 37.5, Lon 68.0 to 98.0)
                    if 6.0 <= c_lat <= 37.5 and 68.0 <= c_lon <= 98.0:
                        name = p.get('name') or p.get('street') or query_str
                        city = p.get('city') or p.get('district') or p.get('county') or ''
                        state = p.get('state') or ''
                        full_name = f"{name}, {city}, {state}".strip(', ')
                        return c_lat, c_lon, full_name
    except Exception:
        pass

    # Query Nominatim with progressive fallback, restricted to India
    parts = [p.strip() for p in query_str.split(',') if p.strip()]
    queries = [query_str if "india" in query_str.lower() else f"{query_str}, India"]
    if len(parts) > 2:
        queries.append(f"{parts[0]}, {parts[-2]}, {parts[-1]}")
        queries.append(f"{parts[0]}, {parts[-1]}")
        queries.append(parts[0])

    for q in queries:
        url_nom = f"https://nominatim.openstreetmap.org/search?format=json&q={urllib.parse.quote(q)}&countrycodes=in&limit=1"
        try:
            req = urllib.request.Request(url_nom, headers={'User-Agent': 'CivicEye-Geocoder/2.0'})
            with urllib.request.urlopen(req, timeout=4.5) as resp:
                data = json.loads(resp.read().decode())
                if data:
                    return float(data[0]['lat']), float(data[0]['lon']), data[0].get('display_name', query_str)
        except Exception:
            pass

    return None, None, query_str

@app.route('/api/geocode', methods=['GET'])
def api_geocode():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'success': False, 'error': 'Missing query param q'}), 400
    user_lat = request.args.get('lat', type=float)
    user_lon = request.args.get('lon', type=float)
    lat, lon, name = resolve_location_coordinates(q, user_lat=user_lat, user_lon=user_lon)
    if lat is not None and lon is not None:
        return jsonify({'success': True, 'lat': lat, 'lon': lon, 'name': name})
    return jsonify({'success': False, 'error': 'Location not found'}), 404

@app.route('/api/search_places', methods=['GET'])
def search_places():
    import urllib.request, urllib.parse, concurrent.futures
    q_raw = request.args.get('q', '').strip()
    if not q_raw or len(q_raw) < 2:
        return jsonify([])

    user_lat = request.args.get('lat', type=float) or 30.7046
    user_lon = request.args.get('lon', type=float) or 76.7179
    limit = min(request.args.get('limit', 25, type=int), 35)

    q_low = q_raw.lower()
    lat, lon = user_lat, user_lon
    detected_city = None
    for city, coords in INDIA_CITY_COORDS.items():
        if city in q_low:
            lat, lon = coords
            detected_city = city
            break

    results = []
    seen = set()

    # 1. Local Database search
    for item in LOCAL_PLACES_DB:
        name_l = item['name'].lower()
        city_l = item['city'].lower()
        kw_l = item.get('keywords', '').lower()

        match = False
        if name_l.startswith(q_low) or q_low.startswith(name_l):
            match = True
        elif q_low in name_l or q_low in city_l or q_low in kw_l:
            match = True

        if match:
            full = f"{item['name']}, {item['city']}"
            k = full.lower()
            if k not in seen:
                seen.add(k)
                cat = item.get('type', 'sector')
                icon = CATEGORY_ICONS.get(cat, '📍')
                results.append({
                    'name': item['name'],
                    'sub': item['city'],
                    'full': full,
                    'lat': float(item.get('lat', lat)),
                    'lon': float(item.get('lon', lon)),
                    'category': cat,
                    'icon': icon,
                    'source': 'database'
                })

    # 2. Photon API with India coordinate biasing
    queries_to_try = [q_raw]
    if detected_city:
        rem = q_low.replace(detected_city, '').strip()
        if len(rem) >= 2:
            queries_to_try.append(rem)

    def fetch_photon_item(search_term):
        url = f"https://photon.komoot.io/api/?q={urllib.parse.quote(search_term)}&lat={lat}&lon={lon}&limit=15"
        req = urllib.request.Request(url, headers={'User-Agent': 'CivicEye-India/2.0'})
        try:
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode())
                return data.get('features', [])
        except:
            return []

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_map = {executor.submit(fetch_photon_item, t): t for t in queries_to_try}
            for fut in concurrent.futures.as_completed(future_map, timeout=4):
                features = fut.result()
                for f in features:
                    p = f.get('properties', {})
                    country = (p.get('country') or '').lower()
                    if country and 'india' not in country:
                        continue

                    coords = f.get('geometry', {}).get('coordinates', [lon, lat])
                    f_lon, f_lat = float(coords[0]), float(coords[1])

                    name = p.get('name') or p.get('street') or q_raw
                    sub_parts = [
                        p.get('street') if p.get('name') and p.get('street') != name else None,
                        p.get('district') or p.get('city'),
                        p.get('state'),
                        'India'
                    ]
                    sub = ', '.join([s for s in sub_parts if s])
                    full = f"{name}, {sub}" if sub else name
                    k = full.lower()

                    if k not in seen:
                        seen.add(k)
                        osm_val = p.get('osm_value') or p.get('osm_key') or 'place'
                        icon = CATEGORY_ICONS.get(osm_val, '📍')
                        results.append({
                            'name': name,
                            'sub': sub,
                            'full': full,
                            'lat': f_lat,
                            'lon': f_lon,
                            'category': osm_val,
                            'icon': icon,
                            'source': 'osm_photon'
                        })
    except Exception as e:
        pass

    return jsonify(results[:limit])

# ==================== DUAL ROUTING API (SHORTEST ACTUAL VS CORRECTED SAFE) ====================
import math
import route_engine

@app.route('/api/routes/calculate', methods=['POST'])
def calculate_route():
    data = request.get_json() or {}
    from_name = data.get('from_name', 'Origin').strip()
    to_name = data.get('to_name', 'Destination').strip()
    
    # Try parsing provided coordinates
    from_lat = None
    from_lon = None
    to_lat = None
    to_lon = None
    
    try:
        from_lat = float(data.get('from_lat')) if data.get('from_lat') is not None else None
        from_lon = float(data.get('from_lon')) if data.get('from_lon') is not None else None
        to_lat = float(data.get('to_lat')) if data.get('to_lat') is not None else None
        to_lon = float(data.get('to_lon')) if data.get('to_lon') is not None else None
    except (ValueError, TypeError):
        pass

    # Always verify provided coordinates against the requested location names
    if from_name and from_name != 'Origin':
        res_lat, res_lon, res_name = resolve_location_coordinates(from_name)
        if res_lat is not None and res_lon is not None:
            dist_diff = math.hypot(from_lat - res_lat, from_lon - res_lon) * 111 if (from_lat and from_lon) else 999
            if dist_diff > 10:  # Provided coords differed by >10km or were defaults
                from_lat, from_lon = res_lat, res_lon

    if to_name and to_name != 'Destination':
        res_lat, res_lon, res_name = resolve_location_coordinates(to_name)
        if res_lat is not None and res_lon is not None:
            dist_diff = math.hypot(to_lat - res_lat, to_lon - res_lon) * 111 if (to_lat and to_lon) else 999
            if dist_diff > 10:  # Provided coords differed by >10km or were defaults
                to_lat, to_lon = res_lat, res_lon

    # Final safe fallbacks if truly unresolved
    if from_lat is None or from_lon is None:
        from_lat, from_lon = 30.7046, 76.7179
    if to_lat is None or to_lon is None:
        to_lat, to_lon = 30.7333, 76.7794

    dataset_path = os.path.join(app.static_folder, 'dataset.json')
    incidents = []
    try:
        with open(dataset_path, 'r', encoding='utf-8') as f:
            incidents = json.load(f)
    except Exception as e:
        pass

    # Merge complaints from live SQLite database so any user-entered hazard is immediately scanned
    try:
        conn = database.get_db_connection()
        db_rows = conn.execute("SELECT * FROM complaints WHERE status != 'Resolved'").fetchall()
        conn.close()
        seen_places = {str(x.get('place', '')).lower() for x in incidents if x.get('place')}
        for r in db_rows:
            row_dict = dict(r)
            tracking = row_dict.get('tracking_id') or f"REP-{row_dict.get('id')}"
            addr = row_dict.get('address') or 'Reported Hazard Location'
            if addr.lower() not in seen_places:
                incidents.append({
                    'id': tracking,
                    'title': row_dict.get('title') or 'Reported Civic Hazard',
                    'place': addr,
                    'lat': float(row_dict.get('latitude', 0)),
                    'lon': float(row_dict.get('longitude', 0)),
                    'type': row_dict.get('category') or 'Civic Hazard',
                    'severity': row_dict.get('priority') or 'Severe',
                    'status': row_dict.get('status') or 'In Progress',
                    'desc': row_dict.get('description') or ''
                })
    except Exception as e:
        pass

    result = route_engine.calculate_both_routes(
        from_lat=from_lat, from_lon=from_lon,
        to_lat=to_lat, to_lon=to_lon,
        from_name=from_name, to_name=to_name,
        incidents=incidents
    )
    return jsonify(result)



@app.route('/api/wards/<ward_name>/stats', methods=['GET'])
def ward_stats(ward_name):
    conn = database.get_db_connection()
    cursor = conn.cursor()

    ward_info = cursor.execute("SELECT * FROM wards WHERE name = ?", (ward_name,)).fetchone()
    complaints = cursor.execute("SELECT * FROM complaints WHERE ward = ? ORDER BY priority_score DESC, created_at DESC", (ward_name,)).fetchall()
    conn.close()

    return jsonify({
        'ward': dict(ward_info) if ward_info else {},
        'complaints': [dict(c) for c in complaints],
        'count': len(complaints)
    })

# ==================== 3D ROTATING CITY & WATERLOGGING APIS ====================
@app.route('/api/3d/sectors', methods=['GET'])
def get_3d_sectors():
    conn = database.get_db_connection()
    rows = conn.execute("SELECT * FROM sectors").fetchall()
    conn.close()

    sectors = []
    total_water_loss = 0
    high_count = 0
    mod_count = 0
    low_count = 0

    for r in rows:
        d = dict(r)
        d['timeline'] = json.loads(d['timeline_json'])
        d['elevation_profile'] = json.loads(d['elevation_profile_json'])
        total_water_loss += d['avg_water_loss_liters']
        if d['risk_tier'] == 'Severe': high_count += 1
        elif d['risk_tier'] == 'Moderate': mod_count += 1
        else: low_count += 1
        sectors.append(d)

    total_s = len(sectors) or 1
    risk_distribution = {
        'high_pct': round((high_count / total_s) * 100),
        'moderate_pct': round((mod_count / total_s) * 100),
        'low_pct': round((low_count / total_s) * 100)
    }

    return jsonify({
        'sectors': sectors,
        'total_avg_water_loss_liters': total_water_loss,
        'expected_rainfall_mm': 56.0,
        'risk_distribution': risk_distribution,
        'ai_insights': {
            'alert': 'High risk of waterlogging in Sectors 18, 20, 22 (next 3 hrs)',
            'expected_rainfall': '56 mm',
            'risk_multiplier': '3x higher risk than average',
            'suggested_action': 'Deploy drainage teams in Sector 18'
        }
    })

@app.route('/api/3d/sector/<name>', methods=['GET'])
def get_single_sector(name):
    conn = database.get_db_connection()
    row = conn.execute("SELECT * FROM sectors WHERE name = ? OR code = ?", (name, name)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Sector not found'}), 404

    d = dict(row)
    d['timeline'] = json.loads(d['timeline_json'])
    d['elevation_profile'] = json.loads(d['elevation_profile_json'])
    return jsonify(d)

@app.route('/api/3d/simulate', methods=['POST'])
def simulate_water_dynamics():
    """
    Simulates waterlogging depth and average water loss across sectors
    as rainfall increases or decreases.
    """
    data = request.json or {}
    rainfall_mm = float(data.get('rainfall_mm', 56.0))
    drain_efficiency = float(data.get('drain_efficiency', 0.85))

    conn = database.get_db_connection()
    rows = conn.execute("SELECT * FROM sectors").fetchall()

    updated = []
    total_loss = 0
    for r in rows:
        d = dict(r)
        # Low lying sectors accumulate more water:
        # Water level = (Rainfall * Depression_Factor) * (1 - Drain_Efficiency)
        depression_factor = max(0.2, (30.0 - d['elevation_m']) / 10.0)
        simulated_water_level = max(0.0, round((rainfall_mm * depression_factor) * (1.0 - drain_efficiency * 0.5), 1))
        
        # Calculate water volume (m3) and water loss
        sim_volume = round(simulated_water_level * 2000.0, 0)
        sim_loss = round(sim_volume * 1.5, 0)
        total_loss += sim_loss

        # Risk tier
        if simulated_water_level > 30.0:
            tier = 'Severe'
        elif simulated_water_level >= 10.0:
            tier = 'Moderate'
        elif simulated_water_level > 2.0:
            tier = 'Low'
        else:
            tier = 'Clear'

        d['water_level_cm'] = simulated_water_level
        d['rainfall_mm'] = rainfall_mm
        d['risk_tier'] = tier
        d['water_volume_m3'] = sim_volume
        d['avg_water_loss_liters'] = sim_loss
        updated.append(d)

    conn.close()

    return jsonify({
        'rainfall_mm': rainfall_mm,
        'simulated_sectors': updated,
        'total_avg_water_loss_liters': total_loss,
        'message': f"Simulation updated for {rainfall_mm}mm rainfall."
    })

@app.route('/api/3d/cctv', methods=['GET'])
def get_cctv_feeds():
    curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    feeds = [
        {
            'camera_id': 'CAM-KB-01',
            'sector': 'Kharar Junction',
            'location': 'Kharar Bus Stand & NH-5 Flyover Corridor',
            'lat': 30.74981,
            'lon': 76.64122,
            'water_level': '38 cm (Severe)',
            'water_level_cm': 38,
            'severity': 'Severe',
            'fps': 60,
            'status': '🔴 LIVE STREAM • 1080p 60FPS',
            'timestamp': curr_time,
            'thumbnail': 'https://images.unsplash.com/photo-1547683905-f686c993aae5?auto=format&fit=crop&w=800&q=80'
        },
        {
            'camera_id': 'CAM-PT-04',
            'sector': 'Patiala Central',
            'location': 'Leela Bhawan Chowk, Patiala',
            'lat': 30.3425,
            'lon': 76.3880,
            'water_level': '24 cm (Moderate)',
            'water_level_cm': 24,
            'severity': 'Moderate',
            'fps': 60,
            'status': '🔴 LIVE STREAM • 1080p 60FPS',
            'timestamp': curr_time,
            'thumbnail': 'https://images.unsplash.com/photo-1515162816999-a0c47dc192f7?auto=format&fit=crop&w=800&q=80'
        },
        {
            'camera_id': 'CAM-S62-02',
            'sector': 'Phase 8 Mohali',
            'location': 'Sector 62 (Phase 8) Traffic Junction',
            'lat': 30.7046,
            'lon': 76.7179,
            'water_level': '45 cm (Critical Flood)',
            'water_level_cm': 45,
            'severity': 'Critical',
            'fps': 60,
            'status': '🔴 LIVE STREAM • 1080p 60FPS',
            'timestamp': curr_time,
            'thumbnail': 'https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=800&q=80'
        },
        {
            'camera_id': 'CAM-N15-01',
            'sector': 'Noida Transit',
            'location': 'Sector 15 Metro Underpass, Noida',
            'lat': 28.58488,
            'lon': 77.31161,
            'water_level': '16 cm (Moderate)',
            'water_level_cm': 16,
            'severity': 'Moderate',
            'fps': 60,
            'status': '🔴 LIVE STREAM • 1080p 60FPS',
            'timestamp': curr_time,
            'thumbnail': 'https://images.unsplash.com/photo-1509114397022-ed747cca3f65?auto=format&fit=crop&w=800&q=80'
        },
        {
            'camera_id': 'CAM-S18-MAIN',
            'sector': 'Central Corridor',
            'location': 'Metro Junction & Drainage Underpass',
            'lat': 30.7333,
            'lon': 76.7794,
            'water_level': '42 cm (Severe)',
            'water_level_cm': 42,
            'severity': 'Severe',
            'fps': 60,
            'status': '🔴 LIVE STREAM • 1080p 60FPS',
            'timestamp': curr_time,
            'thumbnail': 'https://images.unsplash.com/photo-1477959858617-67f30bc75b82?auto=format&fit=crop&w=800&q=80'
        },
        {
            'camera_id': 'CAM-S25-NORTH',
            'sector': 'Highland Bypass',
            'location': 'Highland Elevated Highway Corridor',
            'lat': 30.7510,
            'lon': 76.7900,
            'water_level': '0 cm (Clear Transit)',
            'water_level_cm': 0,
            'severity': 'Clear',
            'fps': 60,
            'status': '🟢 LIVE STREAM • 1080p 60FPS',
            'timestamp': curr_time,
            'thumbnail': 'https://images.unsplash.com/photo-1517457373958-b7bdd4587205?auto=format&fit=crop&w=800&q=80'
        }
    ]
    return jsonify({'cctv_feeds': feeds, 'count': len(feeds), 'server_time': curr_time})


# ==================== AUTH API ====================
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    phone = data.get('phone', '').strip()
    city = data.get('city', '').strip()
    role = data.get('role', 'citizen').strip().lower()
    department = data.get('department', 'Resident')

    # Strict rule: ONLY citizen can sign up. Employees/Admins CANNOT sign up!
    if role != 'citizen':
        return jsonify({'error': 'Registration is restricted to Citizens only. Municipal staff & employee accounts are provisioned directly by the Municipal Corporation Administration and can only log in.'}), 403

    if not name or not email or not password:
        return jsonify({'error': 'Full name, email/username, and password are required'}), 400

    if len(password) < 4:
        return jsonify({'error': 'Password must be at least 4 characters long'}), 400

    conn = database.get_db_connection()
    try:
        # Check if email/username already registered
        existing = conn.execute("SELECT id FROM users WHERE LOWER(email) = ?", (email,)).fetchone()
        if existing:
            return jsonify({'error': f'An account with email "{email}" already exists. Please log in.'}), 409

        pw_hash = database.hash_password(password)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (name, email, password_hash, role, department, phone, city, karma_score, badges)
            VALUES (?, ?, ?, 'citizen', 'Resident', ?, ?, 100, '["Active Citizen", "Water Scout"]')
        ''', (name, email, pw_hash, phone, city or 'Mohali, Punjab'))
        conn.commit()
        user_id = cursor.lastrowid
        session['user_id'] = user_id
        session['role'] = 'citizen'
        user = {
            'id': user_id, 'name': name, 'email': email,
            'role': 'citizen', 'department': 'Resident', 'phone': phone,
            'city': city or 'Mohali, Punjab', 'karma_score': 100, 'badges': ['Active Citizen', 'Water Scout']
        }
        return jsonify({'success': True, 'user': user, 'message': 'Account created successfully! Welcome to Jal-Drishti.'})
    except Exception as e:
        return jsonify({'error': f'Registration failed: {str(e)}'}), 500
    finally:
        conn.close()

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    req_role = data.get('role', '').strip().lower()

    if not email or not password:
        return jsonify({'error': 'Email / Employee ID and password are required'}), 400

    conn = database.get_db_connection()
    pw_hash = database.hash_password(password)
    user = conn.execute("""
        SELECT id, name, email, role, department, phone, city, karma_score, badges 
        FROM users 
        WHERE (LOWER(email) = ? OR phone = ?) AND password_hash = ?
    """, (email, email, pw_hash)).fetchone()
    conn.close()

    if user:
        u = dict(user)
        if req_role and req_role in ('admin', 'worker', 'employee') and u['role'] == 'citizen':
            return jsonify({'error': 'This is a Citizen account. Please switch to the Citizen Login tab.'}), 403

        session['user_id'] = u['id']
        session['role'] = u['role']
        try:
            u['badges'] = json.loads(u['badges']) if isinstance(u['badges'], str) else u['badges']
        except:
            u['badges'] = ["Civic Citizen"]
        return jsonify({'success': True, 'user': u})
    return jsonify({'error': 'Invalid credentials. Please verify your Email / ID and Password.'}), 401

@app.route('/api/auth/demo-login', methods=['POST'])
def demo_login():
    role = request.json.get('role', 'citizen') if request.json else 'citizen'
    conn = database.get_db_connection()
    if role == 'admin':
        user = conn.execute("SELECT id, name, email, role, department, karma_score, badges FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    elif role == 'worker':
        user = conn.execute("SELECT id, name, email, role, department, karma_score, badges FROM users WHERE role = 'worker' LIMIT 1").fetchone()
    else:
        user = conn.execute("SELECT id, name, email, role, department, karma_score, badges FROM users WHERE role = 'citizen' LIMIT 1").fetchone()
    conn.close()

    if user:
        session['user_id'] = user['id']
        session['role'] = user['role']
        u = dict(user)
        try: u['badges'] = json.loads(u['badges'])
        except: u['badges'] = ["Civic Citizen"]
        return jsonify({'success': True, 'user': u})
    return jsonify({'error': 'Demo user not found'}), 404

@app.route('/api/auth/current', methods=['GET'])
def current_user():
    user = get_current_user()
    if user:
        return jsonify({'authenticated': True, 'user': user})
    return jsonify({'authenticated': False})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

# ==================== AI VISION ANALYSIS API ====================
@app.route('/api/complaints/analyze-image', methods=['POST'])
def analyze_image():
    gemini_key = request.form.get('gemini_api_key') or os.environ.get('GEMINI_API_KEY')
    image_file = request.files.get('image')

    saved_path = None
    if image_file and image_file.filename != '':
        filename = secure_filename(f"img_{uuid.uuid4().hex[:8]}_{image_file.filename}")
        saved_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image_file.save(saved_path)
        image_url = f"/static/uploads/{filename}"
    else:
        image_url = request.form.get('image_url')
        if not image_url:
            return jsonify({'error': 'No image file uploaded'}), 400

    analysis = analyze_civic_image(saved_path, gemini_api_key=gemini_key)
    analysis['image_url'] = image_url
    return jsonify(analysis)

# ==================== COMPLAINTS & DUPLICACY ENGINE API ====================
@app.route('/api/complaints', methods=['GET'])
def list_complaints():
    category = request.args.get('category')
    status = request.args.get('status')
    ward = request.args.get('ward')
    search = request.args.get('search')
    sort_by = request.args.get('sort_by', 'priority')

    query = "SELECT * FROM complaints WHERE 1=1"
    params = []

    if category and category != 'All':
        query += " AND category = ?"
        params.append(category)

    if status and status != 'All':
        query += " AND status = ?"
        params.append(status)

    if ward and ward != 'All':
        query += " AND ward = ?"
        params.append(ward)

    if search:
        query += " AND (title LIKE ? OR description LIKE ? OR tracking_id LIKE ? OR address LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s, s])

    if sort_by == 'priority':
        query += " ORDER BY priority_score DESC, upvotes_count DESC"
    elif sort_by == 'water_loss':
        query += " ORDER BY estimated_water_loss_liters DESC"
    elif sort_by == 'upvotes':
        query += " ORDER BY upvotes_count DESC, created_at DESC"
    elif sort_by == 'oldest':
        query += " ORDER BY created_at ASC"
    else:
        query += " ORDER BY created_at DESC"

    conn = database.get_db_connection()
    rows = conn.execute(query, params).fetchall()
    complaints = [dict(row) for row in rows]
    conn.close()

    return jsonify({'complaints': complaints, 'count': len(complaints)})

@app.route('/api/complaints', methods=['POST'])
def create_complaint():
    user = get_current_user()
    data = request.form.to_dict() if request.form else (request.json or {})

    # Image upload
    image_url = data.get('image_url')
    if 'image' in request.files:
        file = request.files['image']
        if file.filename != '':
            filename = secure_filename(f"issue_{uuid.uuid4().hex[:8]}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            image_url = f"/static/uploads/{filename}"

    # Default fallback image if none uploaded
    if not image_url:
        image_url = "https://images.unsplash.com/photo-1541888946425-d0fbb186f5f7?auto=format&fit=crop&w=800&q=80"

    category = data.get('category', 'Water Leakage & Rupture')
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()

    if not title or not description:
        return jsonify({'error': 'Title and description are required'}), 400

    try:
        lat = float(data.get('latitude', 28.6139))
        lng = float(data.get('longitude', 77.2090))
    except ValueError:
        lat, lng = 28.6139, 77.2090

    ward = data.get('ward', 'Ward 4 - Central Zone')
    address = data.get('address', 'Central Area, Delhi')
    landmark = data.get('landmark', '')
    audio_lang = data.get('original_audio_lang', 'en')

    # Water & AI Metrics
    ai_severity = float(data.get('ai_severity_score', 7.5))
    water_loss = float(data.get('estimated_water_loss_liters', 0))
    flow_rate = float(data.get('water_flow_rate_lph', 0))
    people_affected = int(data.get('people_affected', 50))
    ai_notes = data.get('ai_analysis_notes', '')

    conn = database.get_db_connection()
    cursor = conn.cursor()

    # ==================== SMART DUPLICACY DETECTION ====================
    # Check if an unresolved issue exists within ~85 meters of the same category
    active_complaints = cursor.execute("SELECT id, tracking_id, title, category, latitude, longitude, status, upvotes_count, duplicate_reports_count FROM complaints WHERE status != 'Resolved'").fetchall()
    active_list = [dict(c) for c in active_complaints]

    dup_result = detect_duplicacy(lat, lng, category, active_list, threshold_meters=85)

    if dup_result['is_duplicate']:
        parent_id = dup_result['parent_id']
        parent_tracking_id = dup_result['parent_tracking_id']

        # Auto-upvote the existing parent complaint
        cursor.execute("UPDATE complaints SET upvotes_count = upvotes_count + 1, duplicate_reports_count = duplicate_reports_count + 1 WHERE id = ?", (parent_id,))

        # Recalculate priority score for parent
        p_row = cursor.execute("SELECT estimated_water_loss_liters, upvotes_count, ai_severity_score, people_affected, duplicate_reports_count FROM complaints WHERE id = ?", (parent_id,)).fetchone()
        new_priority = calculate_priority_score(
            p_row['estimated_water_loss_liters'],
            p_row['upvotes_count'],
            p_row['ai_severity_score'],
            p_row['people_affected'],
            p_row['duplicate_reports_count']
        )
        cursor.execute("UPDATE complaints SET priority_score = ?, priority = ?, sla_hours = ? WHERE id = ?", 
                       (new_priority['priority_score'], new_priority['priority'], new_priority['sla_hours'], parent_id))

        # Add community review / note on parent
        citizen_name = user['name'] if user else "Citizen Reporter (+1)"
        cursor.execute('''
            INSERT INTO reviews (complaint_id, user_name, user_role, rating, comment)
            VALUES (?, ?, 'citizen', 5, ?)
        ''', (parent_id, citizen_name, f"Identical issue reported at Lat: {lat:.4f}, Lng: {lng:.4f} (~{dup_result['distance_meters']}m away). Auto-merged to boost priority!"))

        # Log timeline event on parent
        cursor.execute('''
            INSERT INTO timeline_events (complaint_id, status, title, description, actor_name)
            VALUES (?, 'Verified', 'Duplicate Issue Merged & Priority Escalated', ?, 'AI Duplicacy Engine')
        ''', (parent_id, f"Resident reported identical issue within {dup_result['distance_meters']}m. Priority escalated to {new_priority['priority_score']}/100."))

        # Award user karma
        if user:
            cursor.execute("UPDATE users SET karma_score = karma_score + 50 WHERE id = ?", (user['id'],))

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'is_duplicate': True,
            'parent_tracking_id': parent_tracking_id,
            'parent_title': dup_result['parent_title'],
            'distance_meters': dup_result['distance_meters'],
            'message': f"A matching grievance (#{parent_tracking_id}) was already reported within {dup_result['distance_meters']}m. Your report has been auto-merged and upvoted to boost municipal urgency!"
        })

    # ==================== NEW COMPLAINT REGISTRATION ====================
    # Calculate Priority Score & SLA
    p_meta = calculate_priority_score(water_loss, upvotes=1, severity_score=ai_severity, people_affected=people_affected)
    priority_score = p_meta['priority_score']
    priority = p_meta['priority']
    sla_hours = p_meta['sla_hours']

    rand_code = random.randint(1000, 9999)
    tracking_id = f"CIVIC-2026-{rand_code}"
    now = datetime.now()
    sla_deadline = (now + timedelta(hours=sla_hours)).isoformat()

    # Department assignment
    dept_map = {
        'Water Leakage & Rupture': 'Water Supply & Sewerage Board',
        'Water-Logged Pothole & Road Hazard': 'Roads & Infrastructure',
        'Drainage Clogging & Sewage Backflow': 'Sanitation & Health',
        'Streetlight & Power': 'Electrical & Public Works'
    }
    assigned_dept = dept_map.get(category, 'Water Supply & Sewerage Board')

    user_id = user['id'] if user else None
    citizen_name = user['name'] if user else data.get('citizen_name', 'Citizen Reporter')
    citizen_contact = data.get('citizen_contact', '+91 99000 11223')

    cursor.execute('''
        INSERT INTO complaints (
            tracking_id, user_id, citizen_name, citizen_contact,
            category, title, description, original_audio_lang,
            image_url, latitude, longitude, address, landmark, ward,
            estimated_water_loss_liters, water_flow_rate_lph, people_affected,
            duplicate_reports_count, ai_detected_category, ai_severity_score,
            ai_confidence, ai_analysis_notes, priority_score, priority,
            status, assigned_department, sla_hours, sla_deadline,
            upvotes_count, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, 'Submitted', ?, ?, ?, 1, ?, ?)
    ''', (
        tracking_id, user_id, citizen_name, citizen_contact,
        category, title, description, audio_lang,
        image_url, lat, lng, address, landmark, ward,
        water_loss, flow_rate, people_affected,
        category, ai_severity, 0.94, ai_notes,
        priority_score, priority, assigned_dept,
        sla_hours, sla_deadline, now.isoformat(), now.isoformat()
    ))
    complaint_id = cursor.lastrowid

    # Update Ward stats
    cursor.execute("UPDATE wards SET active_issues_count = active_issues_count + 1, water_loss_liters = water_loss_liters + ? WHERE name = ?", (water_loss, ward))

    # Award user karma
    if user_id:
        cursor.execute("UPDATE users SET karma_score = karma_score + 100 WHERE id = ?", (user_id,))

    # Log initial timeline
    cursor.execute('''
        INSERT INTO timeline_events (complaint_id, status, title, description, actor_name)
        VALUES (?, 'Submitted', 'Grievance Registered', 'Telemetry logged. Water impact & priority score evaluated.', ?)
    ''', (complaint_id, citizen_name))

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'is_duplicate': False,
        'tracking_id': tracking_id,
        'complaint_id': complaint_id,
        'priority': priority,
        'priority_score': priority_score,
        'sla_hours': sla_hours,
        'estimated_water_loss': water_loss,
        'message': 'Grievance successfully registered on civic grid'
    })

@app.route('/api/complaints/<int:complaint_id>', methods=['GET'])
def get_complaint(complaint_id):
    conn = database.get_db_connection()
    row = conn.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Complaint not found'}), 404

    complaint = dict(row)
    timeline = conn.execute("SELECT * FROM timeline_events WHERE complaint_id = ? ORDER BY created_at ASC", (complaint_id,)).fetchall()
    reviews = conn.execute("SELECT * FROM reviews WHERE complaint_id = ? ORDER BY created_at DESC", (complaint_id,)).fetchall()
    conn.close()

    complaint['timeline'] = [dict(t) for t in timeline]
    complaint['reviews'] = [dict(r) for r in reviews]
    return jsonify(complaint)

@app.route('/api/track/<tracking_id>', methods=['GET'])
def track_complaint(tracking_id):
    tracking_id = tracking_id.strip().upper()
    conn = database.get_db_connection()
    row = conn.execute("SELECT * FROM complaints WHERE tracking_id = ?", (tracking_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': f'No grievance found with Tracking ID: {tracking_id}'}), 404

    complaint = dict(row)
    timeline = conn.execute("SELECT * FROM timeline_events WHERE complaint_id = ? ORDER BY created_at ASC", (complaint['id'],)).fetchall()
    reviews = conn.execute("SELECT * FROM reviews WHERE complaint_id = ? ORDER BY created_at DESC", (complaint['id'],)).fetchall()
    conn.close()

    complaint['timeline'] = [dict(t) for t in timeline]
    complaint['reviews'] = [dict(r) for r in reviews]
    return jsonify(complaint)

# ==================== UPVOTING API ====================
@app.route('/api/complaints/<int:complaint_id>/upvote', methods=['POST'])
def upvote_complaint(complaint_id):
    user = get_current_user()
    user_id = str(user['id']) if user else (request.remote_addr or 'anon_user')

    conn = database.get_db_connection()
    cursor = conn.cursor()

    existing = cursor.execute("SELECT id FROM upvotes WHERE complaint_id = ? AND user_identifier = ?", (complaint_id, user_id)).fetchone()
    if existing:
        cursor.execute("DELETE FROM upvotes WHERE id = ?", (existing['id'],))
        cursor.execute("UPDATE complaints SET upvotes_count = MAX(1, upvotes_count - 1) WHERE id = ?", (complaint_id,))
        upvoted = False
    else:
        cursor.execute("INSERT INTO upvotes (complaint_id, user_identifier) VALUES (?, ?)", (complaint_id, user_id))
        cursor.execute("UPDATE complaints SET upvotes_count = upvotes_count + 1 WHERE id = ?", (complaint_id,))
        upvoted = True

    # Recalculate priority
    c = cursor.execute("SELECT estimated_water_loss_liters, upvotes_count, ai_severity_score, people_affected, duplicate_reports_count FROM complaints WHERE id = ?", (complaint_id,)).fetchone()
    new_p = calculate_priority_score(c['estimated_water_loss_liters'], c['upvotes_count'], c['ai_severity_score'], c['people_affected'], c['duplicate_reports_count'])
    cursor.execute("UPDATE complaints SET priority_score = ?, priority = ?, sla_hours = ? WHERE id = ?", (new_p['priority_score'], new_p['priority'], new_p['sla_hours'], complaint_id))

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'upvoted': upvoted, 'upvotes_count': c['upvotes_count'], 'priority_score': new_p['priority_score']})

# ==================== REVIEWS & VERIFICATION API ====================
@app.route('/api/complaints/<int:complaint_id>/reviews', methods=['POST'])
def add_review(complaint_id):
    user = get_current_user()
    data = request.json or {}
    comment = data.get('comment', '').strip()
    rating = int(data.get('rating', 5))
    is_proof = int(data.get('is_verification_proof', 0))

    if not comment:
        return jsonify({'error': 'Comment cannot be empty'}), 400

    user_name = user['name'] if user else data.get('user_name', 'Citizen')
    user_role = user['role'] if user else 'citizen'

    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO reviews (complaint_id, user_name, user_role, rating, comment, is_verification_proof)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (complaint_id, user_name, user_role, rating, comment, is_proof))

    if user:
        cursor.execute("UPDATE users SET karma_score = karma_score + 50 WHERE id = ?", (user['id'],))

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Review published'})

# ==================== STATUS UPDATES (ADMIN & FIELD CREWS) ====================
@app.route('/api/complaints/<int:complaint_id>/status', methods=['POST'])
def update_status(complaint_id):
    user = get_current_user()
    if not user or user['role'] not in ('admin', 'worker'):
        return jsonify({'error': 'Unauthorized: Only Municipal Admin or Field Crew can update status'}), 403

    data = request.form.to_dict() if request.form else (request.json or {})
    new_status = data.get('status')
    notes = data.get('notes', '').strip()
    assigned_officer = data.get('assigned_officer')
    assigned_dept = data.get('assigned_department')

    resolution_image_url = data.get('resolution_image_url')
    if 'resolution_image' in request.files:
        file = request.files['resolution_image']
        if file.filename != '':
            filename = secure_filename(f"res_{uuid.uuid4().hex[:8]}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            resolution_image_url = f"/static/uploads/{filename}"

    conn = database.get_db_connection()
    cursor = conn.cursor()

    updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
    vals = [new_status]

    if assigned_officer:
        updates.append("assigned_officer = ?")
        vals.append(assigned_officer)
    if assigned_dept:
        updates.append("assigned_department = ?")
        vals.append(assigned_dept)
    if resolution_image_url:
        updates.append("resolution_image_url = ?")
        vals.append(resolution_image_url)

    vals.append(complaint_id)
    cursor.execute(f"UPDATE complaints SET {', '.join(updates)} WHERE id = ?", vals)

    # Timeline event with human readable status
    status_desc_map = {
        'Submitted': 'Grievance submitted by citizen.',
        'Verified': 'AI & Municipal verification completed.',
        'Team Sent': 'Field response squad dispatched with tools & heavy machinery.',
        'In Progress': 'Active on-ground repair & excavation underway.',
        'Resolved': 'Repair verified & water loss successfully halted.'
    }
    desc = notes if notes else status_desc_map.get(new_status, f'Status updated to {new_status}.')
    cursor.execute('''
        INSERT INTO timeline_events (complaint_id, status, title, description, actor_name)
        VALUES (?, ?, ?, ?, ?)
    ''', (complaint_id, new_status, f"Status: {new_status}", desc, user['name']))

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'new_status': new_status})

# ==================== MAP HOTSPOTS API ====================
@app.route('/api/map/hotspots', methods=['GET'])
def get_hotspots():
    conn = database.get_db_connection()
    rows = conn.execute('''
        SELECT id, tracking_id, category, title, latitude, longitude,
               ai_severity_score, priority_score, priority, status, upvotes_count,
               estimated_water_loss_liters, people_affected, address, image_url
        FROM complaints
    ''').fetchall()
    conn.close()

    points = []
    markers = []
    for r in rows:
        d = dict(r)
        # Heatmap intensity based on priority score (0 to 1.0)
        intensity = min(1.0, max(0.2, (d['priority_score'] or 50.0) / 100.0))
        points.append([d['latitude'], d['longitude'], round(intensity, 2)])
        markers.append(d)

    return jsonify({
        'heatmap_points': points,
        'markers': markers,
        'total': len(markers)
    })

# ==================== LEADERBOARD API ====================
@app.route('/api/leaderboard', methods=['GET'])
def leaderboard():
    conn = database.get_db_connection()
    users = conn.execute('''
        SELECT id, name, role, karma_score, badges
        FROM users ORDER BY karma_score DESC LIMIT 10
    ''').fetchall()
    conn.close()

    res = []
    for u in users:
        d = dict(u)
        try: d['badges'] = json.loads(d['badges'])
        except: d['badges'] = ['Active Citizen']
        res.append(d)
    return jsonify({'leaderboard': res})

# ==================== OPEN DATA FOR ALL API ====================
@app.route('/api/open-data/stats', methods=['GET'])
def open_data_stats():
    conn = database.get_db_connection()
    cursor = conn.cursor()

    total = cursor.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
    resolved = cursor.execute("SELECT COUNT(*) FROM complaints WHERE status = 'Resolved'").fetchone()[0]
    in_progress = cursor.execute("SELECT COUNT(*) FROM complaints WHERE status IN ('In Progress', 'Team Sent')").fetchone()[0]
    critical = cursor.execute("SELECT COUNT(*) FROM complaints WHERE priority = 'Critical' AND status != 'Resolved'").fetchone()[0]

    # Water metrics
    water_loss = cursor.execute("SELECT SUM(estimated_water_loss_liters) FROM complaints WHERE status != 'Resolved'").fetchone()[0] or 0
    water_saved = cursor.execute("SELECT SUM(water_saved_liters) FROM wards").fetchone()[0] or 0

    cat_counts = cursor.execute('''
        SELECT category, COUNT(*) as count, AVG(priority_score) as avg_priority, SUM(estimated_water_loss_liters) as total_water_loss
        FROM complaints GROUP BY category
    ''').fetchall()

    ward_counts = cursor.execute('''
        SELECT name as ward, active_issues_count, resolved_issues_count, water_loss_liters, water_saved_liters
        FROM wards
    ''').fetchall()

    total_upvotes = cursor.execute("SELECT SUM(upvotes_count) FROM complaints").fetchone()[0] or 0
    conn.close()

    rate = round((resolved / total * 100), 1) if total > 0 else 0

    return jsonify({
        'total_complaints': total,
        'resolved_complaints': resolved,
        'in_progress_complaints': in_progress,
        'critical_unresolved': critical,
        'resolution_rate_pct': rate,
        'total_water_loss_liters': water_loss,
        'total_water_saved_liters': water_saved,
        'total_community_upvotes': total_upvotes,
        'citizen_satisfaction_rating': 4.9,
        'category_breakdown': [dict(c) for c in cat_counts],
        'ward_breakdown': [dict(w) for w in ward_counts],
        'avg_resolution_sla_hours': 3.8
    })

@app.route('/api/open-data/export/csv', methods=['GET'])
def export_csv():
    conn = database.get_db_connection()
    rows = conn.execute("SELECT * FROM complaints ORDER BY priority_score DESC").fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    if rows:
        headers = list(rows[0].keys())
        writer.writerow(headers)
        for r in rows:
            writer.writerow(list(r))

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=aquacivic_open_data_{datetime.now().strftime('%Y%m%d')}.csv"}
    )

@app.route('/api/open-data/export/json', methods=['GET'])
def export_json():
    conn = database.get_db_connection()
    rows = conn.execute("SELECT * FROM complaints ORDER BY priority_score DESC").fetchall()
    conn.close()

    data = [dict(r) for r in rows]
    return jsonify({
        'portal': 'AquaCivic AI Open Data Portal',
        'license': 'Open Government Data License (OGDL)',
        'timestamp': datetime.now().isoformat(),
        'records_count': len(data),
        'records': data
    })

# ==================== WEATHER API (Open-Meteo — Free, No Key) ====================
@app.route('/api/weather', methods=['GET'])
def get_weather():
    """
    Returns current weather + 3-hour rain forecast using Open-Meteo (free, no API key).
    Falls back to simulated data if offline.
    Query params: lat (float), lon (float)
    """
    import requests as req_lib
    lat = request.args.get('lat', '28.6189')
    lon = request.args.get('lon', '77.2150')

    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current_weather=true"
            f"&hourly=precipitation,precipitation_probability,relativehumidity_2m"
            f"&forecast_days=1"
            f"&timezone=Asia%2FKolkata"
        )
        r = req_lib.get(url, timeout=5)
        raw = r.json()

        current = raw.get('current_weather', {})
        hourly = raw.get('hourly', {})

        # Pick the next 3 hours of precipitation
        prec_list = hourly.get('precipitation', [])
        prec_prob = hourly.get('precipitation_probability', [])
        humidity = hourly.get('relativehumidity_2m', [])
        hours = hourly.get('time', [])

        # Get current hour index
        from datetime import datetime as dt
        now_hour = dt.now().hour
        next3 = []
        for i, t in enumerate(hours):
            try:
                h = int(t.split('T')[1].split(':')[0])
                if h >= now_hour and len(next3) < 4:
                    next3.append({
                        'time': t.split('T')[1][:5],
                        'precipitation_mm': prec_list[i] if i < len(prec_list) else 0,
                        'probability_pct': prec_prob[i] if i < len(prec_prob) else 0,
                        'humidity_pct': humidity[i] if i < len(humidity) else 60,
                    })
            except:
                pass

        # WMO weather code mapping
        wmo_map = {
            0: ('Clear Sky', '☀️'), 1: ('Mainly Clear', '🌤️'), 2: ('Partly Cloudy', '⛅'),
            3: ('Overcast', '☁️'), 45: ('Foggy', '🌫️'), 48: ('Icy Fog', '🌫️'),
            51: ('Light Drizzle', '🌦️'), 53: ('Drizzle', '🌦️'), 55: ('Heavy Drizzle', '🌧️'),
            61: ('Light Rain', '🌧️'), 63: ('Rain', '🌧️'), 65: ('Heavy Rain', '🌧️'),
            71: ('Light Snow', '🌨️'), 73: ('Snow', '❄️'), 75: ('Heavy Snow', '❄️'),
            80: ('Rain Showers', '🌦️'), 81: ('Heavy Showers', '⛈️'), 82: ('Violent Showers', '⛈️'),
            95: ('Thunderstorm', '⛈️'), 96: ('Storm w/ Hail', '⛈️'), 99: ('Severe Storm', '⛈️'),
        }
        wmo_code = current.get('weathercode', 0)
        desc, icon = wmo_map.get(wmo_code, ('Unknown', '🌡️'))

        total_next3_rain = sum(x['precipitation_mm'] for x in next3)
        flood_risk = 'High' if total_next3_rain > 10 else ('Moderate' if total_next3_rain > 3 else 'Low')

        return jsonify({
            'lat': lat, 'lon': lon,
            'current': {
                'temperature_c': current.get('temperature', '--'),
                'windspeed_kmh': current.get('windspeed', 0),
                'wind_direction_deg': current.get('winddirection', 0),
                'description': desc,
                'icon': icon,
                'wmo_code': wmo_code,
            },
            'forecast_3hr': next3,
            'total_expected_rain_mm': round(total_next3_rain, 1),
            'flood_risk_level': flood_risk,
            'source': 'Open-Meteo (open-meteo.com)',
        })

    except Exception as ex:
        # Offline fallback with realistic-looking data
        return jsonify({
            'lat': lat, 'lon': lon,
            'current': {
                'temperature_c': 28,
                'windspeed_kmh': 14,
                'wind_direction_deg': 225,
                'description': 'Partly Cloudy',
                'icon': '⛅',
                'wmo_code': 2,
            },
            'forecast_3hr': [
                {'time': '15:00', 'precipitation_mm': 2.1, 'probability_pct': 45, 'humidity_pct': 72},
                {'time': '16:00', 'precipitation_mm': 5.4, 'probability_pct': 68, 'humidity_pct': 78},
                {'time': '17:00', 'precipitation_mm': 8.2, 'probability_pct': 80, 'humidity_pct': 82},
            ],
            'total_expected_rain_mm': 15.7,
            'flood_risk_level': 'Moderate',
            'source': 'Fallback (Offline)',
            'offline': True,
            'error': str(ex)
        })


# ==================== NEARBY COMPLAINTS API ====================
@app.route('/api/complaints/nearby', methods=['GET'])
def complaints_nearby():
    """
    Returns complaints within radius_km of given lat/lon using Haversine distance.
    """
    import math
    lat = float(request.args.get('lat', 28.6189))
    lon = float(request.args.get('lon', 77.2150))
    radius_km = float(request.args.get('radius_km', 3.0))

    conn = database.get_db_connection()
    rows = conn.execute("SELECT * FROM complaints ORDER BY priority_score DESC").fetchall()
    conn.close()

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
        return R * 2 * math.asin(math.sqrt(a))

    nearby = []
    for r in rows:
        d = dict(r)
        if d.get('latitude') and d.get('longitude'):
            dist = haversine(lat, lon, d['latitude'], d['longitude'])
            if dist <= radius_km:
                d['distance_km'] = round(dist, 2)
                nearby.append(d)

    return jsonify({'complaints': nearby, 'count': len(nearby), 'radius_km': radius_km})


# ==================== JAL-RAKSHAK CIVIC KARMA & REWARDS API ====================
@app.route('/api/karma', methods=['GET'])
def get_karma():
    user = get_current_user()
    points = 1400
    complaints_count = 14
    if user:
        conn = database.get_db_connection()
        u_row = conn.execute("SELECT karma_score FROM users WHERE id = ?", (user['id'],)).fetchone()
        c_count = conn.execute("SELECT COUNT(*) FROM complaints WHERE user_id = ?", (user['id'],)).fetchone()[0]
        conn.close()
        points = u_row['karma_score'] if u_row and u_row['karma_score'] else 100
        complaints_count = c_count or 1

    return jsonify({
        'success': True,
        'karma_score': points,
        'points_per_complaint': 100,
        'lifetime_complaints': complaints_count,
        'water_saved_liters': 85000,
        'history': [
            {'title': 'Registered Complaint: Submerged Road Crater at Phase 3B2', 'points': '+100', 'date': '2026-11-21', 'type': 'earn'},
            {'title': 'Registered Complaint: Ruptured Water Feeder at Sector 70', 'points': '+100', 'date': '2026-11-20', 'type': 'earn'},
            {'title': 'Registered Complaint: Choked Storm Drain at Kharar Stand', 'points': '+100', 'date': '2026-11-19', 'type': 'earn'},
            {'title': 'Community Verification Upvote Received', 'points': '+50', 'date': '2026-11-18', 'type': 'earn'}
        ]
    })

@app.route('/api/karma/redeem', methods=['POST'])
def redeem_karma():
    import random, string
    data = request.json or {}
    points = int(data.get('points', 1000))
    reward_type = data.get('type', 'bill_discount')
    provider = data.get('provider', 'Municipal Water Board')
    val = data.get('value', 50)

    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    if reward_type == 'bill_discount':
        code = f"MC-WATER-{val}-{suffix}"
        msg = f"Successfully redeemed ₹{val} discount on Municipal Water Bill! Code: {code}"
    else:
        prefix = 'AMZN' if 'amazon' in provider.lower() else 'FLIP' if 'flipkart' in provider.lower() else 'SWIG'
        code = f"{prefix}-CIVIC-{val}-{suffix}"
        msg = f"Successfully redeemed ₹{val} {provider} Gift Card! Code: {code}"

    user = get_current_user()
    if user:
        conn = database.get_db_connection()
        conn.execute("UPDATE users SET karma_score = MAX(0, karma_score - ?) WHERE id = ?", (points, user['id']))
        conn.commit()
        conn.close()

    return jsonify({
        'success': True,
        'voucher_code': code,
        'points_spent': points,
        'reward_type': reward_type,
        'provider': provider,
        'value': val,
        'message': msg
    })


if __name__ == '__main__':
    print("==================================================================")
    print("AquaCivic AI Hydro-Intelligence Engine Running at http://127.0.0.1:5000")
    print("==================================================================")
    app.run(debug=True, host='0.0.0.0', port=5000)


