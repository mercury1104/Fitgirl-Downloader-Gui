import os, re, sys, time, threading
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory
from curl_cffi import requests as curl_requests
import requests as std_requests
import webview


if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
    except:
        pass


def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


static_dir = get_resource_path('web')
app = Flask(__name__, static_folder=static_dir, static_url_path='')

is_downloading = False
stop_requested = False
global_bytes_downloaded = 0
last_bytes_count = 0
last_time = time.time()
current_speed_bps = 0

active_downloads = {}
completed_count = 0
total_count = 0
downloads_folder = ""
executor = None
file_lock = threading.Lock()
error_log = []

headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'accept-language': 'en-US,en;q=0.5',
    'referer': 'https://fitgirl-repacks.site/',
    'sec-ch-ua': '"Brave";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
}


def speed_monitor():
    global last_bytes_count, last_time, current_speed_bps, global_bytes_downloaded
    while True:
        time.sleep(1.0)
        now = time.time()
        dt = now - last_time
        current_bytes = global_bytes_downloaded
        if dt > 0:
            current_speed_bps = (current_bytes - last_bytes_count) / dt
        last_bytes_count = current_bytes
        last_time = now


threading.Thread(target=speed_monitor, daemon=True).start()


def remove_link_threadsafe(processed_link, input_file='input.txt'):
    with file_lock:
        if not os.path.exists(input_file):
            return
        with open(input_file, 'r') as file:
            links = file.readlines()
        with open(input_file, 'w') as file:
            for link in links:
                if link.strip() != processed_link:
                    file.write(link)


def download_file(download_url, output_path, link_id, referer=None, depth=0):
    global global_bytes_downloaded, active_downloads, error_log
    if depth > 3:
        error_log.append(f"Too many redirects for: {download_url[:60]}")
        return False
    file_name = os.path.basename(output_path)
    active_downloads[link_id] = {"name": file_name, "downloaded": 0, "total": 0, "percent": 0}

    download_headers = {
        'User-Agent': headers['user-agent'],
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    if referer:
        download_headers['Referer'] = referer

    try:
        response = std_requests.get(download_url, stream=True, headers=download_headers, allow_redirects=True, timeout=60)

        if response.status_code != 200:
            error_log.append(f"HTTP {response.status_code} for {download_url[:60]}")
            active_downloads.pop(link_id, None)
            return False

        content_type = response.headers.get('content-type', '')
        if 'text/html' in content_type:
            soup = BeautifulSoup(response.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                h = a['href']
                if h.startswith('http') and any(ext in h.lower() for ext in ['.zip', '.rar', '.7z', '.bin', '.part', '.exe', '.iso', '.001']):
                    return download_file(h, output_path, link_id, referer=referer, depth=depth+1)
            for iframe in soup.find_all('iframe', src=True):
                s = iframe['src']
                if s.startswith('http'):
                    return download_file(s, output_path, link_id, referer=referer, depth=depth+1)
            error_log.append(f"Got HTML page, no download link: {download_url[:60]}")
            active_downloads.pop(link_id, None)
            return False

        total_size = int(response.headers.get('content-length', 0)) or 0
        active_downloads[link_id]["total"] = total_size

        block_size = 1048576
        downloaded = 0

        with open(output_path, 'wb', buffering=1048576) as f:
            for data in response.iter_content(block_size):
                if stop_requested:
                    break
                f.write(data)
                downloaded += len(data)
                global_bytes_downloaded += len(data)
                percent = int((downloaded / total_size) * 100) if total_size > 0 else 0
                active_downloads[link_id]["downloaded"] = downloaded
                active_downloads[link_id]["percent"] = percent
                time.sleep(0.001)

        if stop_requested:
            try:
                if os.path.exists(output_path):
                    os.remove(output_path)
            except:
                pass
            active_downloads.pop(link_id, None)
            return False

        active_downloads.pop(link_id, None)
        return True
    except Exception as e:
        error_log.append(f"Download error: {str(e)[:100]}")
        active_downloads.pop(link_id, None)
        return False


def process_link(link, index):
    global completed_count, stop_requested, downloads_folder, error_log
    if stop_requested:
        return

    link_id = f"link_{index}"
    try:
        try:
            session = curl_requests.Session(js=True)
        except TypeError:
            session = curl_requests.Session()

        response = session.get(link, headers=headers, impersonate="chrome")
        if response.status_code != 200 or stop_requested:
            if response.status_code != 200:
                error_log.append(f"Link {index}: HTTP {response.status_code}")
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        meta_title = soup.find('meta', attrs={'name': 'title'})
        file_name = meta_title['content'] if meta_title else f"part_{index}.rar"

        download_link_tag = soup.find('a', attrs={'hx-post': True})
        if not download_link_tag:
            for a in soup.find_all('a', href=True):
                h = a['href']
                if h.startswith('http') and any(ext in h.lower() for ext in ['.zip', '.rar', '.7z', '.bin', '.part', '.exe', '.iso']):
                    download_link_tag = a
                    break

        if not download_link_tag or stop_requested:
            error_log.append(f"Link {index}: no download link found")
            return

        post_path = download_link_tag.get('hx-post') or download_link_tag.get('href')
        post_url = urljoin(link, post_path)

        output_path = os.path.join(downloads_folder, file_name)

        for attempt in range(3):
            if stop_requested:
                return
            try:
                resp = session.post(post_url, headers=headers, impersonate="chrome", allow_redirects=False, timeout=30)
                candidate_url = None
                is_html = False

                hx_redirect = resp.headers.get('hx-redirect')
                if hx_redirect:
                    candidate_url = hx_redirect
                elif resp.status_code in (301, 302, 303, 307, 308):
                    candidate_url = resp.headers.get('Location')
                elif resp.status_code == 200:
                    ctype = resp.headers.get('content-type', '')
                    if 'text/html' in ctype:
                        is_html = True
                        ad_soup = BeautifulSoup(resp.text, 'html.parser')
                        for a in ad_soup.find_all('a', href=True):
                            h = a['href']
                            if h.startswith('http'):
                                candidate_url = h
                                break
                        if not candidate_url:
                            for script in ad_soup.find_all('script'):
                                m = re.search(r'https?://[^\s"\'\)]+', script.text)
                                if m:
                                    candidate_url = m.group(0)
                                    break
                    else:
                        candidate_url = post_url
                elif resp.status_code == 403:
                    error_log.append(f"Link {index}: blocked (403) attempt {attempt+1}")
                    continue

                if candidate_url:
                    candidate_url = candidate_url.strip().strip('"').strip("'")
                    success = download_file(candidate_url, output_path, link_id, referer=link)
                    if success and not stop_requested:
                        remove_link_threadsafe(link)
                        completed_count += 1
                        return
                    if is_html and attempt < 2:
                        continue
                    elif is_html:
                        error_log.append(f"Link {index}: got HTML even after 3 attempts")
                        return
            except Exception as e:
                error_log.append(f"Link {index} POST attempt {attempt+1}: {str(e)[:60]}")

        error_log.append(f"Link {index}: could not resolve download after 3 attempts")
    except Exception as e:
        error_log.append(f"Link {index} error: {str(e)[:100]}")


def download_manager_thread(links, workers):
    global is_downloading, stop_requested, executor, total_count, completed_count, error_log
    error_log.clear()
    total_count = len(links)
    completed_count = 0
    stop_requested = False
    is_downloading = True

    try:
        with ThreadPoolExecutor(max_workers=workers) as exec_pool:
            executor = exec_pool
            futures = [executor.submit(process_link, link, idx) for idx, link in enumerate(links)]
            for future in futures:
                future.result()
    except Exception as e:
        error_log.append(f"Thread pool error: {str(e)[:100]}")

    is_downloading = False
    stop_requested = False


@app.route('/')
def serve_index():
    return send_from_directory(static_dir, 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory(static_dir, path)


@app.route('/api/extract', methods=['POST'])
def api_extract():
    data = request.json or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({"status": "error", "message": "Falta la URL"}), 400

    try:
        r = curl_requests.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        links = [
            a["href"]
            for dlinks_div in soup.find_all("div", class_="dlinks")
            for a in dlinks_div.find_all("a", href=True)
            if a["href"].startswith("https://fuckingfast.co/")
        ]

        if not links:
            return jsonify({"status": "error", "message": "No se encontraron enlaces de fuckingfast.co en esta pagina"}), 404

        with file_lock:
            with open('input.txt', 'w') as f:
                f.write("\n".join(links) + "\n")

        return jsonify({"status": "success", "links": links})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error: {str(e)}"}), 500


@app.route('/api/start', methods=['POST'])
def api_start():
    global is_downloading, downloads_folder
    if is_downloading:
        return jsonify({"status": "error", "message": "Ya hay una descarga en progreso"}), 400

    data = request.json or {}
    workers = int(data.get('workers', 4))

    with file_lock:
        if not os.path.exists('input.txt'):
            return jsonify({"status": "error", "message": "input.txt no existe. Extrae enlaces primero."}), 400
        with open('input.txt', 'r') as file:
            links = [line.strip() for line in file if line.strip()]

    if not links:
        return jsonify({"status": "error", "message": "No hay enlaces en input.txt"}), 400

    first_game_link = next((l for l in links if "fitgirl-repacks.site" in urlparse(l).fragment), None)
    game_name = urlparse(first_game_link).fragment.split("--")[0].strip("_") if first_game_link else "Downloaded_Game"

    downloads_folder = os.path.join("downloads", game_name)
    os.makedirs(downloads_folder, exist_ok=True)

    threading.Thread(target=download_manager_thread, args=(links, workers), daemon=True).start()
    return jsonify({"status": "success", "message": "Descarga iniciada", "folder": downloads_folder})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    global stop_requested, is_downloading
    if not is_downloading:
        return jsonify({"status": "error", "message": "No hay descargas activas"}), 400

    stop_requested = True
    return jsonify({"status": "success", "message": "Deteniendo descargas..."})


@app.route('/api/status', methods=['GET'])
def api_status():
    global is_downloading, completed_count, total_count, current_speed_bps, active_downloads, downloads_folder, error_log

    speed_mb = current_speed_bps / (1024 * 1024)
    speed_text = f"{speed_mb:.2f} MB/s" if speed_mb >= 0.1 else f"{current_speed_bps / 1024:.2f} KB/s"

    active_list = []
    for lid, item in list(active_downloads.items()):
        active_list.append({
            "name": item["name"],
            "downloaded": f"{item['downloaded'] / (1024*1024):.1f} MB",
            "total": f"{item['total'] / (1024*1024):.1f} MB" if item['total'] > 0 else "? MB",
            "percent": item["percent"]
        })

    remaining_count = 0
    try:
        with file_lock:
            if os.path.exists('input.txt'):
                with open('input.txt', 'r') as file:
                    remaining_count = len([line.strip() for line in file if line.strip()])
    except:
        pass

    errors = list(error_log)
    error_log.clear()

    return jsonify({
        "is_downloading": is_downloading,
        "completed_count": completed_count,
        "total_count": total_count,
        "remaining_count": remaining_count,
        "speed": speed_text,
        "folder": os.path.abspath(downloads_folder) if downloads_folder else "",
        "active_downloads": active_list,
        "errors": errors
    })


@app.route('/api/ping', methods=['GET'])
def api_ping():
    return jsonify({"ok": True})


def start_flask():
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)


def wait_for_flask(timeout=10):
    import urllib.request
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen('http://127.0.0.1:5000/api/ping', timeout=1)
            return True
        except:
            time.sleep(0.2)
    return False


if __name__ == '__main__':
    threading.Thread(target=start_flask, daemon=True).start()

    print("Esperando a que Flask inicie...")
    if not wait_for_flask():
        print("ERROR: Flask no pudo iniciarse en el tiempo esperado")
        sys.exit(1)
    print("Flask listo. Abriendo ventana...")

    try:
        webview.create_window('FitGirl Easy Downloader', 'http://127.0.0.1:5000', width=1280, height=800)
        webview.start()
    except Exception as e:
        print(f"Error con pywebview: {e}")
        print("Abriendo en navegador como fallback...")
        import webbrowser
        webbrowser.open('http://127.0.0.1:5000')
        start_flask()
