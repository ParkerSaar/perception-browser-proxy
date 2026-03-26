from flask import Flask, jsonify, request
import requests
from bs4 import BeautifulSoup
import os
import time
import re

app = Flask(__name__)

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

PERCEPTION_USERNAME = os.environ.get('PERCEPTION_USERNAME', '')
PERCEPTION_PASSWORD = os.environ.get('PERCEPTION_PASSWORD', '')
API_KEY = os.environ.get('API_KEY', 'change_this_key')
PERCEPTION_BASE = 'https://perception.cx'

session_data = {
    'cookies': {},
    'last_login': 0,
    'debug_info': {},
    'needs_2fa': False
}

cache = {}
CACHE_TTL = 300

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def check_api_key():
    key = request.args.get('key', '')
    return key == API_KEY

def get_cached(key):
    if key in cache:
        data, timestamp = cache[key]
        if time.time() - timestamp < CACHE_TTL:
            return data
    return None

def set_cached(key, data):
    cache[key] = (data, time.time())

def do_login(twofa_code=None):
    """Login to perception.cx"""
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': PERCEPTION_BASE,
    })
    
    debug = {}
    
    try:
        # Step 1: Get the login/account page
        login_page = session.get(f"{PERCEPTION_BASE}/account/", timeout=15)
        debug['step1_status'] = login_page.status_code
        debug['step1_url'] = login_page.url
        
        # Also try /login if /account redirects
        if '/login' in login_page.url:
            debug['redirected_to'] = login_page.url
        
        soup = BeautifulSoup(login_page.text, 'html.parser')
        
        # Check for Cloudflare
        if 'cloudflare' in login_page.text.lower():
            debug['error'] = 'Cloudflare protection detected'
            session_data['debug_info'] = debug
            return False
        
        # Find CSRF token - try multiple patterns
        csrf_token = ''
        
        # Pattern 1: input field
        token_input = soup.select_one('input[name="_xfToken"]')
        if token_input:
            csrf_token = token_input.get('value', '')
        
        # Pattern 2: data attribute
        if not csrf_token:
            csrf_el = soup.select_one('[data-xf-token]')
            if csrf_el:
                csrf_token = csrf_el.get('data-xf-token', '')
        
        # Pattern 3: JavaScript
        if not csrf_token:
            token_match = re.search(r'csrf["\s:]+["\']([^"\']+)["\']', login_page.text, re.IGNORECASE)
            if token_match:
                csrf_token = token_match.group(1)
        
        debug['csrf_found'] = bool(csrf_token)
        debug['csrf_preview'] = csrf_token[:20] + '...' if csrf_token else 'none'
        
        # Find login form
        form = soup.select_one('form[action*="login"], form[action*="account"], form.login')
        if form:
            form_action = form.get('action', '')
            debug['form_found'] = True
            debug['form_action'] = form_action
        else:
            debug['form_found'] = False
            # Try common XenForo login endpoints
            form_action = '/login/login'
        
        # Make form_action absolute
        if form_action and not form_action.startswith('http'):
            if form_action.startswith('/'):
                form_action = PERCEPTION_BASE + form_action
            else:
                form_action = PERCEPTION_BASE + '/' + form_action
        
        # Step 2: Submit login
        login_data = {
            'login': PERCEPTION_USERNAME,
            'password': PERCEPTION_PASSWORD,
            '_xfToken': csrf_token,
            'remember': '1',
        }
        
        # If we have a 2FA code, add it
        if twofa_code:
            login_data['code'] = twofa_code
            login_data['two_step_code'] = twofa_code
        
        debug['posting_to'] = form_action if form_action else f"{PERCEPTION_BASE}/login/login"
        
        login_response = session.post(
            form_action if form_action else f"{PERCEPTION_BASE}/login/login",
            data=login_data,
            timeout=15,
            allow_redirects=True
        )
        
        debug['step2_status'] = login_response.status_code
        debug['step2_url'] = login_response.url
        debug['cookies_received'] = list(session.cookies.keys())
        
        response_text = login_response.text.lower()
        
        # Check for 2FA prompt
        if any(x in response_text for x in ['two-step', 'two_step', '2fa', 'verification code', 'authenticator']):
            debug['needs_2fa'] = True
            session_data['needs_2fa'] = True
            session_data['cookies'] = dict(session.cookies)  # Keep cookies for 2FA step
            session_data['debug_info'] = debug
            return False
        
        # Check for success
        if any(x in response_text for x in ['logout', 'sign out', 'log out', 'my account', 'avatar']):
            session_data['cookies'] = dict(session.cookies)
            session_data['last_login'] = time.time()
            session_data['needs_2fa'] = False
            debug['success'] = True
            session_data['debug_info'] = debug
            return True
        
        # Check for errors
        soup2 = BeautifulSoup(login_response.text, 'html.parser')
        error_el = soup2.select_one('.blockMessage--error, .error, [class*="error"]')
        if error_el:
            debug['login_error'] = error_el.get_text(strip=True)[:300]
        
        # Still on login page?
        if any(x in login_response.url for x in ['/login', '/account']):
            debug['error'] = 'Still on login page after submit'
        
        session_data['debug_info'] = debug
        return False
        
    except Exception as e:
        debug['exception'] = str(e)
        session_data['debug_info'] = debug
        return False

def ensure_logged_in():
    if not session_data['cookies'] or (time.time() - session_data['last_login']) > 1800:
        return do_login()
    return True

def fetch_perception(path):
    if not ensure_logged_in():
        return None
    
    try:
        resp = requests.get(
            f"{PERCEPTION_BASE}{path}",
            cookies=session_data['cookies'],
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'},
            timeout=10
        )
        return resp.text if resp.status_code == 200 else None
    except:
        return None

# ═══════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return jsonify({
        'status': 'online',
        'service': 'Perception Browser Proxy',
        'version': '2.2.0'
    })

@app.route('/api/test')
def test_connection():
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    login_success = do_login()
    
    return jsonify({
        'success': login_success,
        'needs_2fa': session_data.get('needs_2fa', False),
        'has_credentials': bool(PERCEPTION_USERNAME and PERCEPTION_PASSWORD),
        'debug': session_data['debug_info']
    })

@app.route('/api/submit2fa')
def submit_2fa():
    """Submit 2FA code"""
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    code = request.args.get('code', '')
    if not code:
        return jsonify({'error': 'No 2FA code provided'}), 400
    
    login_success = do_login(twofa_code=code)
    
    return jsonify({
        'success': login_success,
        'debug': session_data['debug_info']
    })

@app.route('/api/forums')
def get_forums():
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    html = fetch_perception('/forums/')
    if not html:
        return jsonify({'error': 'Failed to fetch', 'needs_2fa': session_data.get('needs_2fa'), 'debug': session_data['debug_info']}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    forums = []
    
    for node in soup.select('.node--forum, .node, [class*="node"]'):
        title_el = node.select_one('.node-title a, .nodeTitle a, h3 a')
        desc_el = node.select_one('.node-description, .nodeDescription')
        if title_el:
            forums.append({
                'title': title_el.get_text(strip=True),
                'url': title_el.get('href', ''),
                'description': desc_el.get_text(strip=True)[:200] if desc_el else ''
            })
    
    return jsonify({'forums': forums, 'count': len(forums)})

@app.route('/api/forum/<path:forum_id>')
def get_forum_threads(forum_id):
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    html = fetch_perception(f'/forums/{forum_id}/')
    if not html:
        return jsonify({'error': 'Failed to fetch forum'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    threads = []
    
    for item in soup.select('.structItem--thread, .discussionListItem, [class*="thread"]'):
        title_el = item.select_one('.structItem-title a, .title a')
        author_el = item.select_one('.username, .structItem-minor a')
        if title_el:
            threads.append({
                'title': title_el.get_text(strip=True),
                'url': title_el.get('href', ''),
                'author': author_el.get_text(strip=True) if author_el else 'Unknown'
            })
    
    return jsonify({'threads': threads, 'count': len(threads)})

@app.route('/api/thread/<path:thread_id>')
def get_thread(thread_id):
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    html = fetch_perception(f'/threads/{thread_id}/')
    if not html:
        return jsonify({'error': 'Failed to fetch thread'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    title_el = soup.select_one('.p-title-value, h1')
    title = title_el.get_text(strip=True) if title_el else 'Unknown'
    
    posts = []
    for post in soup.select('.message, [class*="message--post"]'):
        author_el = post.select_one('.username')
        content_el = post.select_one('.bbWrapper, .messageContent')
        if content_el:
            posts.append({
                'author': author_el.get_text(strip=True) if author_el else 'Unknown',
                'content': content_el.get_text(strip=True)[:3000]
            })
    
    return jsonify({'title': title, 'posts': posts, 'count': len(posts)})

@app.route('/api/scripts')
def get_scripts():
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    html = fetch_perception('/resources/')
    if not html:
        return jsonify({'error': 'Failed to fetch scripts'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    scripts = []
    
    for item in soup.select('.resourceListItem, [class*="resource"]'):
        title_el = item.select_one('.resourceTitle a, .title a')
        if title_el:
            scripts.append({
                'title': title_el.get_text(strip=True),
                'url': title_el.get('href', '')
            })
    
    return jsonify({'scripts': scripts, 'count': len(scripts)})

@app.route('/api/news')
def get_news():
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    html = fetch_perception('/')
    if not html:
        return jsonify({'error': 'Failed to fetch news'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    news = []
    
    for item in soup.select('.structItem, [class*="announcement"]'):
        title_el = item.select_one('.structItem-title a, .title a')
        if title_el:
            news.append({'title': title_el.get_text(strip=True)})
    
    return jsonify({'news': news[:10], 'count': len(news[:10])})

app = app
