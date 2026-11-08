from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
from flask import render_template, redirect, url_for, request, flash
from flask_login import login_user, login_required, logout_user
import string
from decor_data import WIKI_DECOR_URLS, PIKMIN_POOLS
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
import math
from decor_mapping import DECOR_MAPPING
import requests
import time

SCALE_MAP = {
    ('Regular', 'Small'): 0.03,
    ('Regular', 'Normal'): 0.23,
    ('Regular', 'Large'): 1.00,
    ('Regular', 'Giant'): 1.20,
    ('Special', 'Normal'): 0.31,
    ('Special', 'Large'): 1.10
}

TYPE_MAP = {
    'Red': 4,
    'Yellow': 3,
    'Blue': 3,
    'Purple': 6,
    'White': 2,
    'Pink': 2,
    'Gray': 5,
    'Ice Blue': 2,
    'Fire': 92,
    'Water': 91,
    'Crystal': 93,
    'Electric': 91,
    'Poisonous': 90
}

database_url = os.getenv("DATABASE_URL")
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-fallback-key-for-local-testing-only')
if database_url:
    # Render / Heroku / PostgreSQL fix for older SQLAlchemy URI schemes if needed
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://", "postgresql://", 1
        )
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///local.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

def get_base_color(p_type):
    colors = ["red", "yellow", "blue", "purple", "white", "rock", "winged", "ice"]
    for color in colors:
        if p_type.startswith(color):
            return color
    return "default_pikmin"

app.jinja_env.globals.update(get_base_color=get_base_color)


def get_custom_image_url(category_id, p_type):
    cat = Category.query.get(category_id)
    if cat and cat.custom_images:
        # Expected format in custom_images text: item_key:url,item_key2:url
        pairs = cat.custom_images.split(',')
        for pair in pairs:
            if ':' in pair:
                key, url = pair.split(':', 1)
                if key.strip() == p_type:
                    return url.strip()
    return None

def get_pikmin_image_url(p_type, status, category_id=None):
    color = get_base_color(p_type)
    
    if status == 'missing':
        return url_for('static', filename='images/pikmin/question.png')
    elif status == 'seedling':
        return url_for('static', filename='images/pikmin/' + color + '_seedling.png')
    elif status == 'plucked':
        return url_for('static', filename='images/pikmin/' + color + '.png')
    else:
        # Check if it has a custom user-provided URL first (if category_id is provided)
        if category_id:
            custom_url = get_custom_image_url(category_id, p_type)
            if custom_url and status == 'decor':
                return custom_url

        # Fallback to wiki dictionary or base color sprite
        lookup_key = f"{p_type}_rare" if status == 'rare' else p_type
        if lookup_key in WIKI_DECOR_URLS:
            return WIKI_DECOR_URLS[lookup_key]
        elif p_type in WIKI_DECOR_URLS:
            return WIKI_DECOR_URLS[p_type]
        else:
            return url_for('static', filename='images/pikmin/' + color + '.png')

app.jinja_env.globals['get_pikmin_image_url'] = get_pikmin_image_url

def get_wiki_decor_name(p_type, status):
    # We will build out this dictionary so you only type the name once!
    # Example generator logic:
    # If it's a rare status, append %28Rare%29.png
    pass

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    is_official = db.Column(db.Boolean, default=True)
    allowed_pikmin = db.Column(db.Text, nullable=False, default="red,yellow,blue,purple,white,rock,winged,ice")
    has_rare = db.Column(db.Boolean, default=False)
    custom_images = db.Column(db.Text, nullable=True)

class UserDecorProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    pikmin_type = db.Column(db.String(50), nullable=False)  # e.g., "Red", "Yellow", "Blue"
    status = db.Column(db.String(20), default='missing')     # missing, seedling, plucked, decor

class Expedition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)

with app.app_context():
    db.create_all()
    if not Category.query.first():
        for cat_name, pool in PIKMIN_POOLS.items():
            db.session.add(Category(name=cat_name, is_official=True, allowed_pikmin=pool))
        db.session.commit()

class CachedPOI(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    osm_id = db.Column(db.BigInteger, unique=True, nullable=True) # Tracks unique OSM element ID
    name = db.Column(db.String(150), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

def get_decor_info(tags):
    # Priority keys that dictate specific decor types (like cuisine or specific shop types)
    priority_keys = ['cuisine', 'shop', 'amenity', 'leisure', 'tourism', 'natural', 'landuse', 'waterway', 'aeroway', 'railway', 'building', 'highway', 'bridge']
    
    # Check priority keys first
    for key in priority_keys:
        if key in tags:
            val = tags[key].lower()
            if (key, val) in DECOR_MAPPING:
                mapping = DECOR_MAPPING[(key, val)]
                return mapping['decor'], mapping['category']
                
    # Fallback to general iteration over all tags
    for key, val in tags.items():
        val_lower = val.lower()
        if (key, val_lower) in DECOR_MAPPING:
            mapping = DECOR_MAPPING[(key, val_lower)]
            return mapping['decor'], mapping['category']
        elif (key, '*') in DECOR_MAPPING:
            mapping = DECOR_MAPPING[(key, '*')]
            return mapping['decor'], mapping['category']
            
    # Ultimate fallback if no tags match the mapping
    return "Roadside", "Default"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if len(password) < 15:
            flash('Password must be at least 15 characters long.')
            return redirect(url_for('register'))

        if " " in password:
            flash("Password cannot contain spaces.")
            return redirect(url_for("register"))

        if not any(char.isupper() for char in password):
            flash("Password must contain at least one uppercase letter.")
            return redirect(url_for("register"))

        if not any(char.islower() for char in password):
            flash("Password must contain at least one lowercase letter.")
            return redirect(url_for("register"))

        if not any(char.isdigit() for char in password):
            flash("Password must contain at least one number.")
            return redirect(url_for("register"))

        if not any(char in string.punctuation for char in password):
            flash("Password must contain at least one special character (e.g., !@#$%^&*).")
            return redirect(url_for("register"))
        
        if password != confirm_password:
            flash('Passwords do not match.')
            return redirect(url_for('register'))
        
        # Check if user already exists
        existing_user = User.query.filter(
            db.func.lower(User.username) == username.lower()
        ).first()
        
        if existing_user:
            flash('That username is already taken. Please choose another.', 'danger')
            return redirect(url_for('register'))
        
        try:
            hashed_password = generate_password_hash(password)
            new_user = User(username=username, password_hash=hashed_password)
            db.session.add(new_user)
            db.session.commit()
            
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('login'))
            
        except IntegrityError:
            db.session.rollback() # Fallback safety net for race conditions
            flash('That username is already taken. Please choose another.', 'danger')
            return redirect(url_for('register'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter(
            db.func.lower(User.username) == username.lower()
        ).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('account'))
        else:
            flash('Invalid username or password.')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/account')
@login_required
def account():
  return render_template('account.html', username=current_user.username)

@app.route('/delete-account', methods=['POST'])
@login_required
def delete_account():
    user = current_user

    UserDecorProgress.query.filter_by(user_id=user.id).delete()

    db.session.delete(user)
    db.session.commit()

    logout_user()

    flash('Your account has been permanently deleted.', 'info')
    return redirect(url_for('index'))

@app.route('/tracker')
@login_required
def tracker():
    categories = Category.query.all()
    user_progress = {
        (p.category_id, p.pikmin_type): p.status 
        for p in UserDecorProgress.query.filter_by(user_id=current_user.id).all()
    }
    
    processed_categories = []
    for cat in categories:
        groups = {}
        for entry in cat.allowed_pikmin.split(','):
            if not entry.strip():
                continue
            parts = entry.split(':')
            p_type = parts[0].strip()
            # Extract true/false for rare availability (default to False if missing)
            has_rare = parts[1].strip().lower() == 'true' if len(parts) > 1 else False
            
            color = get_base_color(p_type)
            
            if "_" in p_type:
                subgroup = p_type[len(color)+1:]
            else:
                subgroup = "Standard"
                
            if subgroup not in groups:
                groups[subgroup] = []
            
            # Store both properties for the template
            groups[subgroup].append({'p_type': p_type, 'has_rare': has_rare})
            
        processed_categories.append({
            'id': cat.id,
            'name': cat.name,
            'is_official': cat.is_official,
            'groups': groups
        })

    return render_template('tracker.html', categories=processed_categories, user_progress=user_progress)

@app.route('/tracker/update', methods=['POST'])
@login_required
def update_tracker():
    category_id = request.form.get('category_id')
    pikmin_type = request.form.get('pikmin_type')
    status = request.form.get('status') # 'missing', 'seedling', 'plucked', 'decor'

    # Check if a record already exists for this user, category, and pikmin type
    progress = UserDecorProgress.query.filter_by(
        user_id=current_user.id,
        category_id=category_id,
        pikmin_type=pikmin_type
    ).first()

    if progress:
        progress.status = status
    else:
        progress = UserDecorProgress(
            user_id=current_user.id,
            category_id=category_id,
            pikmin_type=pikmin_type,
            status=status
        )
        db.session.add(progress)
    
    db.session.commit()
    return redirect(url_for('tracker'))

@app.route('/category/add', methods=['POST'])
@login_required
def add_category():
    name = request.form.get('name')
    # Default to all standard types for custom categories, user can customize later if wanted
    default_pool = "red,yellow,blue,purple,white,rock,winged,ice"
    
    if name and not Category.query.filter_by(name=name).first():
        new_cat = Category(name=name, is_official=False, allowed_pikmin=default_pool)
        db.session.add(new_cat)
        db.session.commit()
        flash(f'Category "{name}" added successfully!')
    else:
        flash('Category name is invalid or already exists.')
        
    return redirect(url_for('tracker'))

@app.route('/category/edit/<int:cat_id>', methods=['GET', 'POST'])
@login_required
def edit_category(cat_id):
    category = Category.query.get_or_404(cat_id)
    
    # Prevent editing official categories
    if category.is_official:
        flash('Official categories cannot be edited.')
        return redirect(url_for('tracker'))
        
    if request.method == 'POST':
        category.name = request.form.get('name')
        category.allowed_pikmin = request.form.get('allowed_pikmin')
        category.custom_images = request.form.get('custom_images')
        db.session.commit()
        flash(f'Category "{category.name}" updated successfully!')
        return redirect(url_for('tracker'))
        
    return render_template('edit_category.html', category=category)

@app.route('/category/delete/<int:cat_id>', methods=['POST'])
@login_required
def delete_category(cat_id):
    category = Category.query.get_or_404(cat_id)
    
    if category.is_official:
        flash('Official categories cannot be deleted.')
        return redirect(url_for('tracker'))
        
    # Clean up associated user progress records first
    UserDecorProgress.query.filter_by(category_id=category.id).delete()
    
    db.session.delete(category)
    db.session.commit()
    flash(f'Category "{category.name}" has been deleted.', 'info')
    return redirect(url_for('tracker'))

@app.route('/timers', methods=['GET', 'POST'])
@login_required
def timers_page():
    active_expeditions = Expedition.query.filter_by(user_id=current_user.id).all()
    return render_template('timers.html', expeditions=active_expeditions)

@app.route('/calculators', methods=['GET', 'POST'])
@login_required
def calculators_page():
    mushroom_result = None
    star_rating = "☆☆☆"
    health_display = None
    duration_str = "0m 0s"
    estimated_duration_minutes = 15
    
    selected_type = request.form.get('mushroom_type', 'Purple')
    selected_size = request.form.get('mushroom_size', 'Small')
    squad_strength = request.form.get('squad_strength', '')
    
    # Elemental / Special types that use the Special scale
    special_types = ['Fire', 'Water', 'Crystal', 'Electric', 'Poisonous']
    
    if request.method == 'POST' and 'calc_mushroom' in request.form:
        try:
            strength_val = float(squad_strength)
            
            # Automatically detect if it's special or regular
            if selected_type in special_types:
                scale = SCALE_MAP.get(('Special', selected_size), 0.31)
            else:
                scale = SCALE_MAP.get(('Regular', selected_size), 0.23)
                
            t_val = TYPE_MAP.get(selected_type, 6)
            health = 100 * math.floor(1080 * scale * (23 + t_val))
            health_display = health
            
            t2 = health / 163.3
            t3 = health / 80.9
            t4 = health / 39.4
            
            score = int(strength_val * 1.15)
            mushroom_result = score
            
            if score >= t4:
                star_rating = "★★★★"
            elif score >= t3:
                star_rating = "★★★☆"
            elif score >= t2:
                star_rating = "★★☆☆"
            else:
                star_rating = "★☆☆☆"
                
            total_seconds = int((health / max(strength_val, 1)) * 100)
            estimated_duration_minutes = max(1, round(total_seconds / 60))
            
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            
            if days > 0:
                duration_str = f"{days}d {hours}h {minutes}m {seconds}s"
            elif hours > 0:
                duration_str = f"{hours}h {minutes}m {seconds}s"
            else:
                duration_str = f"{minutes}m {seconds}s"
                
        except (ValueError, ZeroDivisionError):
            mushroom_result = 0

    return render_template('calculators.html', 
                           mushroom_result=mushroom_result, 
                           star_rating=star_rating, 
                           health_display=health_display,
                           duration_str=duration_str,
                           estimated_duration_minutes=estimated_duration_minutes,
                           types=TYPE_MAP.keys(),
                           sizes=['Small', 'Normal', 'Large', 'Giant'],
                           selected_type=selected_type,
                           selected_size=selected_size,
                           squad_strength=squad_strength)

@app.route('/calculator/quick-timer', methods=['POST'])
@login_required
def quick_timer_from_calc():
    m_type = request.form.get('mushroom_type')
    m_size = request.form.get('mushroom_size')
    minutes = int(request.form.get('minutes', 15))
    
    title = f"{m_size} {m_type} Mushroom"
    end_time = datetime.utcnow() + timedelta(minutes=minutes)
    
    new_exp = Expedition(user_id=current_user.id, title=title, duration_minutes=minutes, end_time=end_time)
    db.session.add(new_exp)
    db.session.commit()
    flash('Timer successfully created from calculation!', 'success')
    return redirect(url_for('timers_page'))

    return render_template('calculators.html', 
                           mushroom_result=mushroom_result, 
                           star_rating=star_rating, 
                           health_display=health_display,
                           types=TYPE_MAP.keys(),
                           sizes=['Small', 'Normal', 'Large', 'Giant'])

@app.route('/expedition/add', methods=['POST'])
@login_required
def add_expedition():
    title = request.form.get('title', 'Mushroom')
    category = request.form.get('category', 'Regular')
    minutes = int(request.form.get('minutes', 15))
    end_time = datetime.utcnow() + timedelta(minutes=minutes)
    
    # Store category/type info in title or separate field if needed
    full_title = f"{category} - {title}"
    new_exp = Expedition(user_id=current_user.id, title=full_title, duration_minutes=minutes, end_time=end_time)
    db.session.add(new_exp)
    db.session.commit()
    return redirect(url_for('timers_page'))

@app.route('/expedition/delete/<int:exp_id>', methods=['POST'])
@login_required
def delete_expedition(exp_id):
    exp = Expedition.query.get_or_404(exp_id)
    if exp.user_id == current_user.id:
        db.session.delete(exp)
        db.session.commit()
    return redirect(url_for('timers_page'))

@app.route('/map')
@login_required
def map_page():
    lat = request.args.get('lat', 43.695, type=float) # Settlers Park / Eagle area default
    lon = request.args.get('lon', -116.353, type=float)
    zoom = request.args.get('zoom', 14, type=int)
    
    pois = CachedPOI.query.all()
    poi_list = [{'name': p.name, 'lat': p.lat, 'lon': p.lon, 'category': p.category} for p in pois]
    return render_template('map.html', pois=poi_list, current_lat=lat, current_lon=lon, current_zoom=zoom)

@app.route('/api/fetch-overpass', methods=['POST'])
@login_required
def fetch_overpass():
    lat = request.form.get('lat', 43.695, type=float)
    lon = request.form.get('lon', -116.353, type=float)
    zoom = request.form.get('zoom', 14, type=int)
    
    radius = 1600 
    
    overpass_url = "https://overpass.openstreetmap.fr/api/interpreter"
    overpass_query = f"""
    [out:json][timeout:25];
    (
      nwr["shop"](around:{radius},{lat},{lon});
      nwr["amenity"](around:{radius},{lat},{lon});
      nwr["leisure"](around:{radius},{lat},{lon});
      nwr["tourism"](around:{radius},{lat},{lon});
      nwr["natural"](around:{radius},{lat},{lon});
      nwr["landuse"](around:{radius},{lat},{lon});
      nwr["waterway"](around:{radius},{lat},{lon});
      nwr["aeroway"](around:{radius},{lat},{lon});
      nwr["railway"](around:{radius},{lat},{lon});
      nwr["building"](around:{radius},{lat},{lon});
      nwr["highway"](around:{radius},{lat},{lon});
      nwr["bridge"](around:{radius},{lat},{lon});
      nwr["cuisine"](around:{radius},{lat},{lon});
      
      relation["amenity"="university"](around:{radius},{lat},{lon});
      relation["amenity"="college"](around:{radius},{lat},{lon});
    );
    
    (._; >;);
    out center;
    """
    
    headers = {'User-Agent': 'PikminBloomCompanionApp/1.0'}
    
    try:
        response = requests.post(overpass_url, data={'data': overpass_query}, headers=headers, timeout=25)
        response.raise_for_status()
        data = response.json()
        elements = data.get('elements', [])
        
        count = 0
        updated_count = 0
        
        for element in elements:
            tags = element.get('tags', {})
            # Fallback name if tag doesn't have 'name' but has 'official_name' or similar
            name = tags.get('name') or tags.get('alt_name')
            if not name:
                continue
                
            osm_id = element.get('id')
            lat_elem = element.get('lat') or (element.get('center') and element['center'].get('lat'))
            lon_elem = element.get('lon') or (element.get('center') and element['center'].get('lon'))
            
            if not lat_elem or not lon_elem or not osm_id:
                continue
            
            matched_decor, matched_cat = get_decor_info(tags)
            
            # If it's ExtraMile Arena or BSU, let's force-correct their categories if tags were ambiguous
            if "ExtraMile Arena" in name:
                matched_decor, matched_cat = "Ball Keychain", "Stadium"
            elif "Boise State University" in name:
                matched_decor, matched_cat = "College Crest Patch", "University"
                
            category_str = f"{matched_cat} ({matched_decor})"
            
            existing_poi = CachedPOI.query.filter_by(osm_id=osm_id).first()
            if existing_poi:
                existing_poi.name = name
                existing_poi.lat = lat_elem
                existing_poi.lon = lon_elem
                existing_poi.category = category_str
                existing_poi.updated_at = datetime.utcnow()
                updated_count += 1
            else:
                new_poi = CachedPOI(
                    osm_id=osm_id,
                    name=name,
                    lat=lat_elem,
                    lon=lon_elem,
                    category=category_str
                )
                db.session.add(new_poi)
                count += 1
                
        db.session.commit()
        flash(f'Synced! Added {count} new POIs and updated {updated_count} existing cached locations.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error fetching Overpass data: {str(e)}', 'danger')
        
    return redirect(url_for('map_page', lat=lat, lon=lon, zoom=zoom))

# 5. Local run block 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)