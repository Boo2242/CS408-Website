from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
from flask import render_template, redirect, url_for, request, flash
from flask_login import login_user, login_required, logout_user
import string
from decor_data import WIKI_DECOR_URLS, PIKMIN_POOLS

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

with app.app_context():
    db.create_all()
    if not Category.query.first():
        for cat_name, pool in PIKMIN_POOLS.items():
            db.session.add(Category(name=cat_name, is_official=True, allowed_pikmin=pool))
        db.session.commit()


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
        
        # Hash password and create new user
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        
        flash('Account created successfully! Please log in.')
        return redirect(url_for('login'))
        
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

# 5. Local run block 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)