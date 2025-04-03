import socket
import argparse
import sys
import time
import re
import ipaddress
import threading
import concurrent.futures
from flask import Flask, request, jsonify
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

app = Flask(__name__)
Base = declarative_base()
engine = create_engine('sqlite:///sites.db', echo=False)
Session = sessionmaker(bind=engine)
db_lock = threading.Lock()

# Конфигурация
MAX_WORKERS = 120
MAX_CONTENT_LENGTH = 100000
CRAWL_DEPTH = 2
REQUEST_DELAY = 0.5

class Site(Base):
    __tablename__ = 'sites'
    id = Column(Integer, primary_key=True)
    ip = Column(String(15), nullable=False)
    domain = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

class Page(Base):
    __tablename__ = 'pages'
    id = Column(Integer, primary_key=True)
    site_id = Column(Integer, ForeignKey('sites.id'), nullable=False)
    url = Column(String(1024), unique=True, nullable=False)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)

def parse_ip_input(ip_input):
    ips = []
    for item in ip_input:
        try:
            if '-' in item:
                start_ip, end_ip = item.split('-')
                start = ipaddress.IPv4Address(start_ip.strip())
                end = ipaddress.IPv4Address(end_ip.strip())
                
                current_ip = start
                while current_ip <= end:
                    ips.append(str(current_ip))
                    current_ip += 1
                
            elif '/' in item:
                network = ipaddress.IPv4Network(item.strip(), strict=False)
                ips.extend(str(host) for host in network.hosts())
            else:
                ips.append(str(ipaddress.IPv4Address(item.strip())))
        except ValueError as e:
            print(f"Invalid IP format: {item} - {str(e)}")
    return list(set(ips))

def resolve_dns(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror):
        return None

class WebsiteCrawler:
    def __init__(self, base_url):
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        self.visited = set()
        self.lock = threading.Lock()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; SearchBot/1.0)',
            'Accept-Language': 'en-US,en;q=0.5'
        })

    def is_valid_url(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        if parsed.netloc != self.domain:
            return False
        if re.search(r'\.(pdf|jpg|png|zip|exe)$', parsed.path, re.I):
            return False
        return True

    def extract_links(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        links = set()
        for tag in soup.find_all(['a', 'link'], href=True):
            url = urljoin(self.base_url, tag['href'])
            clean_url = url.split('#')[0].split('?')[0]
            if self.is_valid_url(clean_url):
                links.add(clean_url)
        return links

    def crawl(self, url, depth=0):
        with self.lock:
            if depth > CRAWL_DEPTH or url in self.visited:
                return []
            self.visited.add(url)

        try:
            time.sleep(REQUEST_DELAY)
            response = self.session.get(url, timeout=10)
            if response.status_code != 200:
                return []

            content_type = response.headers.get('Content-Type', '')
            if 'text/html' not in content_type:
                return []

            content = response.text[:MAX_CONTENT_LENGTH]
            pages = [{'url': url, 'content': content}]
            
            for link in self.extract_links(content):
                pages.extend(self.crawl(link, depth + 1))
            
            return pages
        except Exception as e:
            print(f"Error crawling {url}: {str(e)}")
            return []

def scan_ip(ip):
    domain = resolve_dns(ip)
    pages = []
    
    for protocol in ['https://', 'http://']:
        base_url = f"{protocol}{domain or ip}"
        try:
            response = requests.get(base_url, timeout=5)
            if response.ok:
                crawler = WebsiteCrawler(base_url)
                pages = crawler.crawl(base_url)
                if pages:
                    break
        except Exception:
            print(f"- {ip}")
            continue
    
    return ip, domain, pages

def save_results(ip, domain, pages):
    with db_lock:
        session = Session()
        try:
            site = session.query(Site).filter_by(ip=ip).first()
            if not site:
                site = Site(ip=ip, domain=domain)
                session.add(site)
                session.commit()

            existing_urls = {url for (url,) in session.query(Page.url)}
            new_pages = [
                Page(
                    site_id=site.id,
                    url=page['url'],
                    content=page['content']
                ) for page in pages if page['url'] not in existing_urls
            ]
            
            session.bulk_save_objects(new_pages)
            session.commit()
            return len(new_pages)
        except Exception as e:
            session.rollback()
            print(f"Database error: {str(e)}")
            return 0
        finally:
            session.close()

def run_scan(ip_input):
    print("\n=== Starting network scan ===")
    ips = parse_ip_input(ip_input)
    print(f"Target IPs: {len(ips)}")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(scan_ip, ip): ip for ip in ips}
        
        for future in concurrent.futures.as_completed(futures):
            ip = futures[future]
            try:
                ip, domain, pages = future.result()
                if pages:
                    count = save_results(ip, domain, pages)
                    print(f"Found {len(pages)} pages @ {ip} ({domain})")
            except Exception as e:
                print(f"Error scanning {ip}: {str(e)}")

@app.route('/search', methods=['GET'])
def handle_search():
    query = request.args.get('q', '')
    if not query:
        return jsonify({'results': [], 'error': 'Missing search query'}), 400
    
    session = Session()
    try:
        search_term = f"%{query}%"
        results = session.query(Site.domain, Page.url, Page.content)\
            .join(Page)\
            .filter(Page.content.ilike(search_term))\
            .order_by(Page.created_at.desc())\
            .limit(100)\
            .all()
        
        return jsonify({
            'results': [{
                'domain': row.domain or urlparse(row.url).netloc,
                'url': row.url,
                'snippet': row.content[:200] + '...' if len(row.content) > 200 else row.content
            } for row in results],
            'error': None
        })
    except Exception as e:
        return jsonify({'results': [], 'error': str(e)}), 500
    finally:
        session.close()

@app.route('/all-words', methods=['GET'])
def get_all_words():
    session = Session()
    try:
        contents = session.query(Page.content).all()
        
        words = set()
        for content in contents:
            if content[0]:
                words.update(
                    word.strip(".,!?():;\"'").lower()
                    for word in re.findall(r'\b\w+\b', content[0])
                    if len(word) > 2
                )
        
        return jsonify({
            'words': sorted(list(words)),
            'count': len(words)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--scan', nargs='+', 
                       help='IP ranges (e.g. "192.168.1.0/24 10.0.0.1-10.0.0.5")')
    parser.add_argument('--run', action='store_true', 
                       help='Start web server')
    
    args = parser.parse_args()
    
    if args.scan:
        run_scan(args.scan)
    elif args.run:
        print("Starting search server on http://localhost:5000")
        app.run(host='0.0.0.0', port=5000)
    else:
        parser.print_help()
