from flask import Flask, jsonify, request
import requests
from bs4 import BeautifulSoup
import os
import time

app = Flask(__name__)

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION - Set these in Vercel environment variables!
# ═══════════════════════════════════════════════════════════════

PERCEPTION_SESSION = os.environ.get('PERCEPTION_SESSION', '')
API_KEY = os.environ.get('API_KEY', 'change_this_key')
PERCEPTION_BASE = 'https://perception.cx'

# Simple in-memory cache (resets on cold start, but helps during warm periods)
cache = {}
CACHE_TTL = 300  # 5 minutes

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
    cookies = {'session': PERCEPTION_SESSION}
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
        'version': '1.0.0',
        'endpoints': [
            'GET /api/forums',
            'GET /api/forum/<id>',
            'GET /api/thread/<id>',
            'GET /api/scripts',
            'GET /api/news'
        ]
    })

@app.route('/api/forums')
def get_forums():
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    cached = get_cached('forums')
    if cached:
        cached['cached'] = True
        return jsonify(cached)
    
    html = fetch_perception('/forums/')
    if not html:
        return jsonify({'error': 'Failed to fetch forums'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    
    forums = []
    
    # Try multiple selectors (adjust based on actual site)
    selectors = [
        '.forum-item',
        '.category',
        '.node',
        '.forumRow',
        '[class*="forum"]'
    ]
    
    for selector in selectors:
        elements = soup.select(selector)
        if elements:
            for forum in elements:
                title_el = forum.select_one('.title, .forum-title, h3, a, .nodeTitle')
                link_el = forum.select_one('a[href]')
                desc_el = forum.select_one('.description, .nodeDescription, p')
                
                if title_el:
                    forums.append({
                        'title': title_el.get_text(strip=True),
                        'url': link_el.get('href', '') if link_el else '',
                        'description': desc_el.get_text(strip=True)[:200] if desc_el else ''
                    })
            break
    
    result = {'forums': forums, 'cached': False, 'count': len(forums)}
    set_cached('forums', result)
    
    return jsonify(result)

@app.route('/api/forum/<path:forum_id>')
def get_forum_threads(forum_id):
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    cache_key = f'forum_{forum_id}'
    cached = get_cached(cache_key)
    if cached:
        cached['cached'] = True
        return jsonify(cached)
    
    html = fetch_perception(f'/forums/{forum_id}/')
    if not html:
        return jsonify({'error': 'Failed to fetch forum'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    
    threads = []
    
    selectors = [
        '.thread-item',
        '.discussionListItem',
        '.structItem',
        '.threadRow',
        '[class*="thread"]'
    ]
    
    for selector in selectors:
        elements = soup.select(selector)
        if elements:
            for thread in elements:
                title_el = thread.select_one('.title a, .thread-title, h3 a, .structItem-title a')
                author_el = thread.select_one('.author, .username, .starter, .structItem-minor a')
                date_el = thread.select_one('.date, .DateTime, time, .structItem-latestDate')
                replies_el = thread.select_one('.replies, .stats, .pairs--justified dd')
                
                if title_el:
                    threads.append({
                        'title': title_el.get_text(strip=True),
                        'url': title_el.get('href', ''),
                        'author': author_el.get_text(strip=True) if author_el else 'Unknown',
                        'date': date_el.get_text(strip=True) if date_el else '',
                        'replies': replies_el.get_text(strip=True) if replies_el else '0'
                    })
            break
    
    result = {'threads': threads, 'forum_id': forum_id, 'cached': False, 'count': len(threads)}
    set_cached(cache_key, result)
    
    return jsonify(result)

@app.route('/api/thread/<path:thread_id>')
def get_thread(thread_id):
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    cache_key = f'thread_{thread_id}'
    cached = get_cached(cache_key)
    if cached:
        cached['cached'] = True
        return jsonify(cached)
    
    html = fetch_perception(f'/threads/{thread_id}/')
    if not html:
        return jsonify({'error': 'Failed to fetch thread'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    
    title_el = soup.select_one('.thread-title, h1, .p-title-value, .titleBar h1')
    title = title_el.get_text(strip=True) if title_el else 'Unknown Thread'
    
    posts = []
    
    selectors = [
        '.post',
        '.message',
        '.messageSimple',
        '[class*="post"]'
    ]
    
    for selector in selectors:
        elements = soup.select(selector)
        if elements:
            for post in elements:
                author_el = post.select_one('.author, .username, .message-name, .userText a')
                content_el = post.select_one('.content, .messageContent, .bbWrapper, .messageText')
                date_el = post.select_one('.date, .DateTime, time, .message-attribution-main time')
                avatar_el = post.select_one('.avatar img, .message-avatar img')
                
                if content_el:
                    content_text = content_el.get_text(strip=True)
                    
                    posts.append({
                        'author': author_el.get_text(strip=True) if author_el else 'Unknown',
                        'content': content_text[:3000],
                        'date': date_el.get_text(strip=True) if date_el else '',
                        'avatar': avatar_el.get('src', '') if avatar_el else ''
                    })
            break
    
    result = {
        'title': title,
        'posts': posts,
        'thread_id': thread_id,
        'cached': False,
        'post_count': len(posts)
    }
    set_cached(cache_key, result)
    
    return jsonify(result)

@app.route('/api/scripts')
def get_scripts():
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    cached = get_cached('scripts')
    if cached:
        cached['cached'] = True
        return jsonify(cached)
    
    html = fetch_perception('/resources/')
    if not html:
        html = fetch_perception('/scripts/')
    if not html:
        return jsonify({'error': 'Failed to fetch scripts'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    
    scripts = []
    
    selectors = [
        '.script-item',
        '.resource',
        '.resourceListItem',
        '.product',
        '[class*="resource"]'
    ]
    
    for selector in selectors:
        elements = soup.select(selector)
        if elements:
            for script in elements:
                title_el = script.select_one('.title, h3, a, .resourceTitle')
                desc_el = script.select_one('.description, .tagLine, p, .resourceTagLine')
                author_el = script.select_one('.author, .username, .resourceDetails a')
                downloads_el = script.select_one('.downloads, .resourceDownloads dd')
                rating_el = script.select_one('.rating, .ratingStars')
                
                if title_el:
                    scripts.append({
                        'title': title_el.get_text(strip=True),
                        'url': title_el.get('href', '') if title_el.name == 'a' else '',
                        'description': desc_el.get_text(strip=True)[:300] if desc_el else '',
                        'author': author_el.get_text(strip=True) if author_el else 'Unknown',
                        'downloads': downloads_el.get_text(strip=True) if downloads_el else '0'
                    })
            break
    
    result = {'scripts': scripts, 'cached': False, 'count': len(scripts)}
    set_cached('scripts', result)
    
    return jsonify(result)

@app.route('/api/news')
def get_news():
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    cached = get_cached('news')
    if cached:
        cached['cached'] = True
        return jsonify(cached)
    
    html = fetch_perception('/announcements/')
    if not html:
        html = fetch_perception('/news/')
    if not html:
        html = fetch_perception('/')
    if not html:
        return jsonify({'error': 'Failed to fetch news'}), 500
    
    soup = BeautifulSoup(html, 'html.parser')
    
    news = []
    
    selectors = [
        '.news-item',
        '.announcement',
        'article',
        '.structItem--announcement',
        '[class*="announcement"]'
    ]
    
    for selector in selectors:
        elements = soup.select(selector)
        if elements:
            for item in elements:
                title_el = item.select_one('.title, h2, h3, a')
                content_el = item.select_one('.content, .body, p, .structItem-title')
                date_el = item.select_one('.date, time, .DateTime')
                
                if title_el:
                    news.append({
                        'title': title_el.get_text(strip=True),
                        'content': content_el.get_text(strip=True)[:500] if content_el else '',
                        'date': date_el.get_text(strip=True) if date_el else ''
                    })
            break
    
    result = {'news': news, 'cached': False, 'count': len(news)}
    set_cached('news', result)
    
    return jsonify(result)

@app.route('/api/test')
def test_connection():
    """Test if we can connect to perception.cx"""
    if not check_api_key():
        return jsonify({'error': 'Invalid API key'}), 401
    
    html = fetch_perception('/')
    
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.select_one('title')
        
        logged_in = False
        user_indicators = soup.select('.username, .accountUsername, [class*="user"], .p-navgroup--member')
        if user_indicators:
            logged_in = True
        
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
#═══════════════════════════════════════════════════════════════
# VERCEL HANDLER
# ═══════════════════════════════════════════════════════════════

# This is required for Vercel
def handler(request):
    return app(request)

if __name__ == '__main__':
    app.run(debug=True)
