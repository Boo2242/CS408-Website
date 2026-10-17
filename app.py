from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
from flask import render_template, redirect, url_for, request, flash
from flask_login import login_user, login_required, logout_user
import string

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

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    
with app.app_context():
    db.create_all()


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
  # Grab the currently logged-in user
  user = current_user

  # Delete from database and commit
  db.session.delete(user)
  db.session.commit()

  # Log them out of the session
  logout_user()

  flash('Your account has been permanently deleted.', 'info')
  return redirect(url_for('index'))

# 5. Local run block 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)