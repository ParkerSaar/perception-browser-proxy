from flask import Flask, jsonify, request
import requests
from bs4 import BeautifulSoup
import os
import time

app = Flask(__name__)

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

PERCEPTION_SESSION = os.environ.get('PERCEPTION_SESSION', '')
API_KEY = os.environ.get('API_KEY', 'change_this_key')
PERCEPTION_BASE = 'https://perception.cx'

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

def fetch_perception(path):
    cookies = {'xf_session': PERCEPTION_SESSION}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        resp = requests.get(
            f"{PERCEPTION_BASE}{path}",
            cookies=cookies,
            headers=headers,
            timeout=10
        )
        return resp.text if resp.status_code == 200 else None
    except Exception as e:
        print(f"Fetch error: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return jsonify({
        'status': 'online',
        'service': 'Perception Browser Proxy',
        'version': '1.0.0'
    })

@app.route('/api/test')
def test_connection():
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    html = fetch_perception('/')
    
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.select_one('title')
        logged_in = len(soup.select('.p-navgroup--member, .username, [class*="avatar"]')) > 0
        
        return jsonify({
            'success': True,
            'page_title': title.get_text(strip=True) if title else 'Unknown',
            'logged_in': logged_in,
            'html_length': len(html)
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Could not fetch perception.cx'
        })

@app.route('/api/forums')
def get_forums():
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    cached = get_cached('forums')
    if cached:
        return jsonify(cached)
    
    html = fetch_perception('/forums/')
    if not html:
        return jsonify({'error': 'Failed to fetch forums'}), 500
    
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
    
    result = {'forums': forums, 'count': len(forums)}
    set_cached('forums', result)
    return jsonify(result)

@app.route('/api/forum/<path:forum_id>')
def get_forum_threads(forum_id):
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    cache_key = f'forum_{forum_id}'
    cached = get_cached(cache_key)
    if cached:
        return jsonify(cached)
    
    html = fetch_perception(f'/forums/{forum_id}/')
    if not html:
        return jsonify({'error': 'Failed to fetch forum'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    threads = []
    
    for item in soup.select('.structItem--thread, .discussionListItem, [class*="thread"]'):
        title_el = item.select_one('.structItem-title a, .title a')
        author_el = item.select_one('.username, .structItem-minor a')
        date_el = item.select_one('time, .DateTime')
        
        if title_el:
            threads.append({
                'title': title_el.get_text(strip=True),
                'url': title_el.get('href', ''),
                'author': author_el.get_text(strip=True) if author_el else 'Unknown',
                'date': date_el.get_text(strip=True) if date_el else ''
            })
    
    result = {'threads': threads, 'forum_id': forum_id, 'count': len(threads)}
    set_cached(cache_key, result)
    return jsonify(result)

@app.route('/api/thread/<path:thread_id>')
def get_thread(thread_id):
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    cache_key = f'thread_{thread_id}'
    cached = get_cached(cache_key)
    if cached:
        return jsonify(cached)
    
    html = fetch_perception(f'/threads/{thread_id}/')
    if not html:
        return jsonify({'error': 'Failed to fetch thread'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    
    title_el = soup.select_one('.p-title-value, h1, .thread-title')
    title = title_el.get_text(strip=True) if title_el else 'Unknown Thread'
    
    posts = []
    for post in soup.select('.message, .post, [class*="message--post"]'):
        author_el = post.select_one('.username, .message-name')
        content_el = post.select_one('.bbWrapper, .messageContent, .message-body')
        date_el = post.select_one('time, .DateTime')
        
        if content_el:
            posts.append({
                'author': author_el.get_text(strip=True) if author_el else 'Unknown',
                'content': content_el.get_text(strip=True)[:3000],
                'date': date_el.get_text(strip=True) if date_el else ''
            })
    
    result = {'title': title, 'posts': posts, 'thread_id': thread_id, 'post_count': len(posts)}
    set_cached(cache_key, result)
    return jsonify(result)

@app.route('/api/scripts')
def get_scripts():
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    cached = get_cached('scripts')
    if cached:
        return jsonify(cached)
    
    html = fetch_perception('/resources/')
    if not html:
        return jsonify({'error': 'Failed to fetch scripts'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    scripts = []
    
    for item in soup.select('.resourceListItem, [class*="resource"]'):
        title_el = item.select_one('.resourceTitle a, .title a, h3 a')
        desc_el = item.select_one('.resourceTagLine, .tagLine')
        author_el = item.select_one('.username')
        
        if title_el:
            scripts.append({
                'title': title_el.get_text(strip=True),
                'url': title_el.get('href', ''),
                'description': desc_el.get_text(strip=True)[:300] if desc_el else '',
                'author': author_el.get_text(strip=True) if author_el else 'Unknown'
            })
    
    result = {'scripts': scripts, 'count': len(scripts)}
    set_cached('scripts', result)
    return jsonify(result)

@app.route('/api/news')
def get_news():
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    cached = get_cached('news')
    if cached:
        return jsonify(cached)
    
    html = fetch_perception('/')
    if not html:
        return jsonify({'error': 'Failed to fetch news'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    news = []
    
    for item in soup.select('.announcement, [class*="announcement"], .structItem'):
        title_el = item.select_one('.structItem-title a, .title a, h3')
        date_el = item.select_one('time, .DateTime')
        
        if title_el:
            news.append({
                'title': title_el.get_text(strip=True),
                'date': date_el.get_text(strip=True) if date_el else ''
            })
    
    result = {'news': news[:10], 'count': len(news[:10])}
    set_cached('news', result)
    return jsonify(result)

# ═══════════════════════════════════════════════════════════════
# VERCEL ENTRY POINT - This is the key part!
# ═══════════════════════════════════════════════════════════════

app = app
