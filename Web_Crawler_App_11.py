import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import deque
import csv
import datetime
import re
import time
from io import StringIO

# Enhanced subdomain validation
def is_subdomain_of(url_netloc, main_domain):
    main_domain = main_domain.replace("www.", "").lower()
    url_netloc = url_netloc.replace("www.", "").lower()
    return url_netloc.endswith("." + main_domain) or url_netloc == main_domain

# Optimized keyword detection
def contains_keyword(text, keywords):
    if not text:
        return False
    text = str(text).lower().strip()
    patterns = [re.compile(rf'\b{re.escape(kw.lower())}\b|^{re.escape(kw.lower())}$') for kw in keywords]
    return any(pattern.search(text) for pattern in patterns)

# Extract categories from a website
def extract_categories(soup, base_url):
    categories = []
    category_names = ["travel", "blog", "resources"]
    other_categories = set()
    
    for link in soup.find_all('a', href=True):
        href = link.get('href', '').strip().lower()
        text = link.get_text().strip().lower()
        
        # Skip empty, javascript, and anchor links
        if not href or href.startswith(('javascript:', '#', 'mailto:', 'tel:')):
            continue
            
        # Look for category patterns in URLs and text
        for category in category_names:
            if (category in href or category in text) and '/category/' in href:
                full_url = urljoin(base_url, href)
                if full_url not in categories:
                    categories.append((category, full_url))
            elif (category in href or category in text) and (f'/{category}/' in href or href.endswith(f'/{category}')):
                full_url = urljoin(base_url, href)
                if full_url not in categories:
                    categories.append((category, full_url))
        
        # Collect other potential categories
        if '/category/' in href and all(cat not in href for cat in category_names):
            category_match = re.search(r'/category/([^/]+)', href)
            if category_match:
                cat_name = category_match.group(1).lower()
                if cat_name not in [c[0] for c in categories]:
                    other_categories.add((cat_name, urljoin(base_url, href)))
    
    # Add main categories first
    result = []
    for cat_name in category_names:
        matched = [url for name, url in categories if name == cat_name]
        if matched:
            result.append((cat_name, matched[0]))
    
    # Add other categories
    for cat_name, url in other_categories:
        result.append((cat_name, url))
        
    return result

# Speed-optimized processing with connection reuse
session = requests.Session()
def process_url(url, main_domain, visited, results, status_messages):
    if url in visited:
        return []
    visited.add(url)
    
    try:
        start_time = time.time()
        response = session.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        response.raise_for_status()
        load_time = time.time() - start_time
        status_messages.append(("✅", f"Crawled: {url} ({load_time:.2f}s)"))
    except Exception as e:
        status_messages.append(("❌", f"Error fetching {url}: {str(e)}"))
        return []

    if 'text/html' not in response.headers.get('Content-Type', ''):
        return []

    final_url = response.url
    parsed_url = urlparse(final_url)
    
    if not is_subdomain_of(parsed_url.netloc, main_domain):
        status_messages.append(("⚠️", f"Skipping non-subdomain: {final_url}"))
        return []

    # Use lxml parser for faster parsing
    soup = BeautifulSoup(response.text, 'lxml')
    keywords = ["gowithguide", "go with guide", "go-with-guide", "87121"]

    # Batch element processing
    elements_to_check = [
        *soup.find_all(['a', 'div', 'section', 'title', 'main', 'article']),
        *[soup.find('meta', {'name': 'description'})]
    ]
    
    for element in elements_to_check:
        if not element:
            continue
            
        # Check hrefs
        href = element.get('href', '')
        if href and contains_keyword(href, keywords):
            results.append((final_url, "Keyword in URL", href))
            status_messages.append(("🔗", f"Match in URL: {href}"))
        
        # Check text content
        text = element.get_text(separator=' ', strip=True)
        if text and contains_keyword(text, keywords):
            context = text[:200] if len(text) > 50 else text
            results.append((final_url, "Keyword in content", context))
            status_messages.append(("📄", f"Match in content: {context}"))
            
        # Check meta content
        content = element.get('content', '')
        if content and contains_keyword(content, keywords):
            context = content[:200] if len(content) > 50 else content
            results.append((final_url, "Keyword in meta content", context))
            status_messages.append(("📄", f"Match in meta content: {context}"))

    # Fast link extraction
    extracted_links = []
    for link in soup.find_all('a', href=True):
        absolute_url = urljoin(final_url, link['href'])
        parsed_link = urlparse(absolute_url)
        if is_subdomain_of(parsed_link.netloc, main_domain) and absolute_url not in visited:
            extracted_links.append(absolute_url)

    return extracted_links, soup

def main():
    st.set_page_config(page_title="Smart Web Inspector", page_icon="🌐", layout="wide")
    
    # Initialize session state with reset capability
    if 'crawl_data' not in st.session_state:
        st.session_state.crawl_data = {
            'running': False,
            'queue': deque(),
            'visited': set(),
            'results': [],
            'status': [],
            'main_domain': '',
            'start_time': 0,
            'categories': [],
            'current_category': None,
            'pages_crawled': 0,
            'max_pages': 6  # Set to 6 per requirements
        }

    # Control panel with reset option
    with st.container():
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            url_input = st.text_input("Enter website URL:", "https://example.com")
        with col2:
            st.write("<div style='height:28px'></div>", unsafe_allow_html=True)
            start_btn = st.button("▶️ Start" if not st.session_state.crawl_data['running'] else "⏸️ Pause")
        with col3:
            if st.button("⏹️ Stop & Reset"):
                st.session_state.crawl_data = {
                    'running': False,
                    'queue': deque(),
                    'visited': set(),
                    'results': [],
                    'status': [],
                    'main_domain': '',
                    'start_time': 0,
                    'categories': [],
                    'current_category': None,
                    'pages_crawled': 0,
                    'max_pages': 6  # Set to 6
                }

    # Status Display
    with st.container():
        st.subheader("Live Activity Feed")
        status_window = st.empty()
        
    # Results Display
    results_container = st.container()
    
    # Crawling logic
    if start_btn:
        st.session_state.crawl_data['running'] = not st.session_state.crawl_data['running']
        
        if st.session_state.crawl_data['running'] and not st.session_state.crawl_data['queue']:
            # Initialize new crawl
            initial_url = url_input.strip()
            if not initial_url.startswith(('http://', 'https://')):
                initial_url = f'https://{initial_url}'
            
            parsed_initial = urlparse(initial_url)
            st.session_state.crawl_data = {
                'running': True,
                'queue': deque([initial_url]),
                'visited': set(),
                'results': [],
                'status': [("🚀", f"Starting crawl of {initial_url}")],
                'main_domain': parsed_initial.netloc,
                'start_time': time.time(),
                'categories': [],
                'current_category': None,
                'pages_crawled': 0,
                'max_pages': 6  # Set to 6
            }

    if st.session_state.crawl_data['running']:
        progress_bar = st.progress(0)
        stats_display = st.empty()
        
        # Main domain crawl logic
        if not st.session_state.crawl_data['current_category']:
            max_pages = st.session_state.crawl_data['max_pages']
            
            while st.session_state.crawl_data['running'] and st.session_state.crawl_data['pages_crawled'] < max_pages:
                if not st.session_state.crawl_data['queue']:
                    st.session_state.crawl_data['status'].append(("ℹ️", f"No more pages to crawl in main domain after {st.session_state.crawl_data['pages_crawled']} pages."))
                    break
                    
                url = st.session_state.crawl_data['queue'].popleft()
                if url in st.session_state.crawl_data['visited']:
                    continue
                    
                new_links, soup = process_url(
                    url,
                    st.session_state.crawl_data['main_domain'],
                    st.session_state.crawl_data['visited'],
                    st.session_state.crawl_data['results'],
                    st.session_state.crawl_data['status']
                )
                
                # Increment page counter
                st.session_state.crawl_data['pages_crawled'] += 1
                
                # Store homepage soup to extract categories later if needed
                if st.session_state.crawl_data['pages_crawled'] == 1:
                    try:
                        homepage_categories = extract_categories(soup, url)
                        st.session_state.crawl_data['categories'] = homepage_categories
                        if homepage_categories:
                            cat_names = [cat[0] for cat in homepage_categories]
                            st.session_state.crawl_data['status'].append(("🗂️", f"Found categories: {', '.join(cat_names)}"))
                    except Exception as e:
                        st.session_state.crawl_data['status'].append(("⚠️", f"Error extracting categories: {str(e)}"))
                
                # Add new links to queue
                for link in new_links or []:
                    if link not in st.session_state.crawl_data['visited']:
                        st.session_state.crawl_data['queue'].append(link)
                
                # If we found matches, stop crawling
                if st.session_state.crawl_data['results']:
                    st.session_state.crawl_data['status'].append(("🎯", f"Found {len(st.session_state.crawl_data['results'])} matches! Stopping main crawl."))
                    st.session_state.crawl_data['running'] = False
                    break
                
                # Update progress
                progress = min(st.session_state.crawl_data['pages_crawled'] / max_pages, 1.0)
                progress_bar.progress(progress)
                
                # Check if we've reached the max pages limit
                if st.session_state.crawl_data['pages_crawled'] >= max_pages:
                    st.session_state.crawl_data['status'].append(("🛑", f"Reached max pages limit ({max_pages}) for main domain."))
                    
                    # If no results found, move to first category
                    if not st.session_state.crawl_data['results'] and st.session_state.crawl_data['categories']:
                        first_category = st.session_state.crawl_data['categories'][0]
                        st.session_state.crawl_data['current_category'] = first_category
                        st.session_state.crawl_data['status'].append(("🔄", f"No matches found in main domain. Moving to '{first_category[0]}' category."))
                        st.session_state.crawl_data['queue'] = deque([first_category[1]])
                        st.session_state.crawl_data['pages_crawled'] = 0
                    elif not st.session_state.crawl_data['results'] and not st.session_state.crawl_data['categories']:
                        st.session_state.crawl_data['status'].append(("ℹ️", "No categories found. Crawl completed with no matches."))
                        st.session_state.crawl_data['running'] = False
            
        # Category crawl logic
        else:
            max_pages = st.session_state.crawl_data['max_pages']
            category_name, category_url = st.session_state.crawl_data['current_category']
            
            # Reset stats for this category
            if st.session_state.crawl_data['pages_crawled'] == 0:
                st.session_state.crawl_data['status'].append(("🔍", f"Starting crawl of '{category_name}' category"))
                st.session_state.crawl_data['queue'] = deque([category_url])
            
            while st.session_state.crawl_data['running'] and st.session_state.crawl_data['pages_crawled'] < max_pages:
                if not st.session_state.crawl_data['queue']:
                    st.session_state.crawl_data['status'].append(("ℹ️", f"No more pages to crawl in '{category_name}' category after {st.session_state.crawl_data['pages_crawled']} pages."))
                    break
                    
                url = st.session_state.crawl_data['queue'].popleft()
                if url in st.session_state.crawl_data['visited']:
                    continue
                    
                new_links, _ = process_url(
                    url,
                    st.session_state.crawl_data['main_domain'],
                    st.session_state.crawl_data['visited'],
                    st.session_state.crawl_data['results'],
                    st.session_state.crawl_data['status']
                )
                
                # Increment page counter
                st.session_state.crawl_data['pages_crawled'] += 1
                
                # Add new links to queue
                for link in new_links or []:
                    if link not in st.session_state.crawl_data['visited']:
                        st.session_state.crawl_data['queue'].append(link)
                
                # If we found matches, stop crawling
                if st.session_state.crawl_data['results']:
                    st.session_state.crawl_data['status'].append(("🎯", f"Found {len(st.session_state.crawl_data['results'])} matches in '{category_name}' category! Stopping crawl."))
                    st.session_state.crawl_data['running'] = False
                    break
                
                # Update progress
                progress = min(st.session_state.crawl_data['pages_crawled'] / max_pages, 1.0)
                progress_bar.progress(progress)
                
                # Check if we've reached the max pages limit
                if st.session_state.crawl_data['pages_crawled'] >= max_pages:
                    st.session_state.crawl_data['status'].append(("🛑", f"Reached max pages limit ({max_pages}) for '{category_name}' category."))
                    
                    # Move to next category if available
                    categories = st.session_state.crawl_data['categories']
                    current_idx = next((i for i, cat in enumerate(categories) if cat[0] == category_name), -1)
                    
                    if current_idx < len(categories) - 1:
                        next_category = categories[current_idx + 1]
                        st.session_state.crawl_data['current_category'] = next_category
                        st.session_state.crawl_data['status'].append(("🔄", f"No matches found. Moving to '{next_category[0]}' category."))
                        st.session_state.crawl_data['queue'] = deque([next_category[1]])
                        st.session_state.crawl_data['pages_crawled'] = 0
                    else:
                        st.session_state.crawl_data['status'].append(("ℹ️", "No more categories to crawl. Crawl completed with no matches."))
                        st.session_state.crawl_data['running'] = False
            
        # Update stats
        elapsed_time = time.time() - st.session_state.crawl_data['start_time']
        stats_display.markdown(f"""
        **Crawling Stats**  
        ⏱️ Elapsed Time: {elapsed_time:.1f}s  
        📊 Processed: {len(st.session_state.crawl_data['visited'])} pages  
        🗂️ Queued: {len(st.session_state.crawl_data['queue'])} pages  
        🔍 Matches Found: {len(st.session_state.crawl_data['results'])}
        """)

    # Display status messages (newest first)
    with status_window.container():
        for icon, msg in reversed(st.session_state.crawl_data['status'][-15:]):
            st.markdown(f"{icon} `{msg}`")

    # Display results and controls
    with results_container:
        if st.session_state.crawl_data['results']:
            st.subheader(f"Matches Found ({len(st.session_state.crawl_data['results'])})")
            
            # Show last 10 matches
            for result in reversed(st.session_state.crawl_data['results'][-10:]):
                st.markdown(f"""
                **URL:** {result[0]}  
                **Type:** {result[1]}  
                **Context:** `{result[2] if result[2] else 'N/A'}`
                """)
            
            # CSV generation
            csv_file = StringIO()
            writer = csv.writer(csv_file)
            writer.writerow(["Source URL", "Match Type", "Match Context", "Timestamp"])
            
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for row in st.session_state.crawl_data['results']:
                writer.writerow([*row, timestamp])
            
            # Download controls
            cols = st.columns(3)
            with cols[0]:
                st.download_button(
                    "💾 Save Results as CSV",
                    data=csv_file.getvalue(),
                    file_name=f"crawler_results_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
            with cols[1]:
                if st.button("▶️ Continue Crawling"):
                    st.session_state.crawl_data['running'] = True
            with cols[2]:
                if st.button("🔄 New Crawl"):
                    st.session_state.crawl_data = {
                        'running': False,
                        'queue': deque(),
                        'visited': set(),
                        'results': [],
                        'status': [],
                        'main_domain': '',
                        'start_time': 0,
                        'categories': [],
                        'current_category': None,
                        'pages_crawled': 0,
                        'max_pages': 6  # Set to 6
                    }

if __name__ == "__main__":
    main()
