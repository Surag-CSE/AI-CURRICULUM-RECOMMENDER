from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_mysqldb import MySQL
import bcrypt
import json

app = Flask(__name__)
# IMPORTANT: Use a long, random, and secret key in a real application
app.secret_key = 'your_very_long_and_random_secret_key' 

# Configure MySQL
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'Pokemonbw@2015'
app.config['MYSQL_DB'] = 'SmartLearnAI_New'
# Use DictCursor to get results as dictionaries, which is easier to work with
app.config['MYSQL_CURSORCLASS'] = 'DictCursor' 

mysql = MySQL(app)

# --------------------- ROUTES ---------------------

@app.route('/')
def home():
    return render_template('LandingPageUltimate.html')

@app.route('/login')
def login_page():
    # Pop the message from the session to display it on the login page
    message = session.pop('message', None)
    return render_template('LoginPage.html', message=message)

@app.route('/logout')
def logout():
    # Clear all session data
    session.clear()
    # Redirect user to the login page
    return redirect(url_for('login_page'))

@app.route('/signup')
def signup_page():
    return render_template('SignUpPage.html')

@app.route('/dashboard')
def dashboard_page():
    # Protect the dashboard route: if user is not logged in, redirect to login
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    username = session.get('username', 'User')
    # Use session.pop to get the message and remove it, so it only shows once
    message = session.pop('message', None)
    # Pop the landing prompt as well, so it's only used once upon loading the dashboard
    prefilled_prompt = session.pop('landing_prompt', None)
    
    return render_template('DashBoard.html', message=message, username=username, prefilled_prompt=prefilled_prompt)

# ---Handle Landing Page Prompt ---
@app.route('/handle_landing_prompt', methods=['POST'])
def handle_landing_prompt():
    # Capture the prompt from the form submission
    prompt = request.form.get('prompt')
    if prompt:
        # Store the prompt in the session to use after login
        session['landing_prompt'] = prompt
    
    # Set a message for the login page and redirect
    session['message'] = 'Please log-in first'
    return redirect(url_for('login_page'))

# ----------------- API: Email Check -----------------

@app.route('/check_email', methods=['POST'])
def check_email():
    email = request.json['email']
    cur = mysql.connection.cursor()
    cur.execute("SELECT email FROM users WHERE email = %s", (email,))
    user = cur.fetchone()
    cur.close()
    return jsonify({'exists': bool(user)})

# ----------------- API: Sign-Up -----------------

@app.route('/signup_user', methods=['POST'])
def signup_user():
    email = request.form['email']
    password = request.form['password']

    cur = mysql.connection.cursor()
    cur.execute("SELECT email FROM users WHERE email = %s", (email,))
    user = cur.fetchone()

    if user:
        return render_template('LoginPage.html', message='Email already exists. Please log in.')

    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    cur.execute("INSERT INTO users (email, password) VALUES (%s, %s)", (email, hashed_password))
    mysql.connection.commit()
    cur.close()

    return render_template('LoginPage.html', message='User registered successfully. Please log in.')

# ----------------- API: Login -----------------

@app.route('/login_user', methods=['POST'])
def login_user():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Request must be JSON'}), 400

        email = data.get('email')
        password = data.get('password')

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()

        if not user:
            return jsonify({'success': False, 'message': 'No account found. Please sign up.'})

        # Use the column name 'password' thanks to DictCursor
        hashed_pw = user['password'].encode('utf-8')
        if bcrypt.checkpw(password.encode('utf-8'), hashed_pw):
            # Store essential user info in the session
            session['user_id'] = user['id']
            session['username'] = email.split('@')[0].capitalize()
            session['message'] = 'Login successful!'
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Incorrect Password.'})

    except Exception as e:
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

# ----------------- API: Save Goal and Details -----------------
@app.route('/api/save_goal_and_details', methods=['POST'])
def save_goal_and_details():
    # Ensure user is logged in before proceeding
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'User not logged in'}), 401

    try:
        data = request.get_json()
        user_id = session['user_id']
        
        # Extract data from the payload
        main_prompt = data['mainPrompt']
        responses = data['questionnaireResponses']
        
        user_type = responses['general']
        education_level = responses['level']
        domains = responses['domain']
        subdomains = responses['subdomains']
        # Convert list of durations to a comma-separated string for DB storage
        duration = ", ".join(responses['duration'])
        reason = responses['reason']

        cur = mysql.connection.cursor()

        # 1. Update or Insert User Profile (UPSERT logic)
        cur.execute("SELECT id FROM user_profiles WHERE user_id = %s", (user_id,))
        profile = cur.fetchone()
        if profile:
            cur.execute("""
                UPDATE user_profiles 
                SET user_type = %s, education_level = %s 
                WHERE user_id = %s
            """, (user_type, education_level, user_id))
        else:
            cur.execute("""
                INSERT INTO user_profiles (user_id, user_type, education_level) 
                VALUES (%s, %s, %s)
            """, (user_id, user_type, education_level))

        # 2. Insert the new Goal
        cur.execute("INSERT INTO goals (user_id, goal_prompt) VALUES (%s, %s)", (user_id, main_prompt))
        goal_id = cur.lastrowid # Get the ID of the goal we just inserted

        # 3. Insert Goal Details
        cur.execute("""
            INSERT INTO goal_details (goal_id, preferred_duration, reason) 
            VALUES (%s, %s, %s)
        """, (goal_id, duration, reason))

        # 4. Insert Domains and associated Subdomains
        for domain in domains:
            cur.execute("INSERT INTO goal_domains (goal_id, domain_name) VALUES (%s, %s)", (goal_id, domain))
            if domain in subdomains and subdomains[domain]:
                for subdomain in subdomains[domain]:
                    cur.execute("""
                        INSERT INTO goal_subdomains (goal_id, domain_name, subdomain_name) 
                        VALUES (%s, %s, %s)
                    """, (goal_id, domain, subdomain))

        # Commit all changes to the database
        mysql.connection.commit()
        cur.close()

        return jsonify({'success': True, 'message': 'Goal and details saved successfully.', 'goal_id': goal_id})

    except Exception as e:
        # It's good practice to log the error for debugging
        print(f"Error saving goal: {str(e)}")
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500


# ------------------ MAIN ------------------

if __name__ == '__main__':
    app.run(debug=True)
