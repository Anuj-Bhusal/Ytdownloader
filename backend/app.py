"""
YouTube Downloader API Backend
Flask API for fetching video info and downloading videos
"""

import os
import re
import time
import tempfile
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

# Config
TEMP_DIR = tempfile.gettempdir()
COOKIE_FILE = os.path.join(os.path.dirname(__file__), 'cookies.txt')

# Rate limiting (simple in-memory)
REQUEST_LOG = {}
RATE_LIMIT = 10  # requests per minute per IP


def check_rate_limit(ip):
    """Simple rate limiting"""
    now = time.time()
    if ip not in REQUEST_LOG:
        REQUEST_LOG[ip] = []
    
    # Clean old entries
    REQUEST_LOG[ip] = [t for t in REQUEST_LOG[ip] if now - t < 60]
    
    if len(REQUEST_LOG[ip]) >= RATE_LIMIT:
        return False
    
    REQUEST_LOG[ip].append(now)
    return True


def get_ydl_opts():
    """Base yt-dlp options with cookie authentication"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }
    
    # Use cookies if file exists
    if os.path.exists(COOKIE_FILE):
        opts['cookiefile'] = COOKIE_FILE
    
    return opts


def format_filesize(bytes_size):
    """Convert bytes to human readable format"""
    if not bytes_size:
        return None
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} TB"


@app.route('/api/info', methods=['POST'])
def get_video_info():
    """Fetch video information and available formats"""
    # Rate limit check
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if not check_rate_limit(client_ip):
        return jsonify({'error': 'Rate limit exceeded. Please wait.'}), 429
    
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        ydl_opts = get_ydl_opts()
        ydl_opts['extract_flat'] = False
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        if not info:
            return jsonify({'error': 'Could not fetch video info'}), 400
        
        # Process formats
        formats = []
        seen_qualities = set()
        
        for f in info.get('formats', []):
            format_id = f.get('format_id')
            ext = f.get('ext', 'mp4')
            height = f.get('height')
            width = f.get('width')
            filesize = f.get('filesize') or f.get('filesize_approx')
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')
            abr = f.get('abr')
            
            if vcodec != 'none' and height:
                quality_key = f"video_{height}"
                if quality_key not in seen_qualities:
                    seen_qualities.add(quality_key)
                    formats.append({
                        'format_id': format_id,
                        'type': 'video',
                        'quality': f'{height}p',
                        'height': height,
                        'width': width,
                        'ext': ext,
                        'filesize': format_filesize(filesize),
                        'has_audio': acodec != 'none',
                    })
            
            elif acodec != 'none' and vcodec == 'none' and abr:
                quality_key = f"audio_{int(abr)}"
                if quality_key not in seen_qualities:
                    seen_qualities.add(quality_key)
                    formats.append({
                        'format_id': format_id,
                        'type': 'audio',
                        'quality': f'{int(abr)} kbps',
                        'bitrate': int(abr),
                        'ext': ext,
                        'filesize': format_filesize(filesize),
                    })
        
        # Add combined format options
        formats.insert(0, {
            'format_id': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
            'type': 'video',
            'quality': 'Best Quality',
            'height': 9999,
            'ext': 'mp4',
            'filesize': 'Auto',
            'has_audio': True,
        })
        
        for res in [2160, 1440, 1080, 720, 480, 360]:
            format_str = f'bestvideo[height<={res}][ext=mp4]+bestaudio[ext=m4a]/best[height<={res}]'
            quality_key = f"combined_{res}"
            if quality_key not in seen_qualities:
                formats.append({
                    'format_id': format_str,
                    'type': 'video',
                    'quality': f'{res}p',
                    'height': res,
                    'ext': 'mp4',
                    'filesize': 'Auto',
                    'has_audio': True,
                })
        
        video_formats = sorted([f for f in formats if f['type'] == 'video'], 
                              key=lambda x: x.get('height', 0), reverse=True)
        audio_formats = sorted([f for f in formats if f['type'] == 'audio'], 
                              key=lambda x: x.get('bitrate', 0), reverse=True)
        
        audio_formats.insert(0, {
            'format_id': 'bestaudio/best',
            'type': 'audio',
            'quality': 'Best Audio (MP3)',
            'bitrate': 9999,
            'ext': 'mp3',
            'filesize': 'Auto',
        })
        
        return jsonify({
            'title': info.get('title', 'Unknown'),
            'duration': info.get('duration', 0),
            'channel': info.get('uploader', 'Unknown'),
            'thumbnail': info.get('thumbnail', ''),
            'formats': video_formats + audio_formats,
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download', methods=['POST'])
def download_video():
    """Download video with specified format"""
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if not check_rate_limit(client_ip):
        return jsonify({'error': 'Rate limit exceeded. Please wait.'}), 429
    
    try:
        data = request.get_json()
        url = data.get('url')
        format_id = data.get('format_id', 'best')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        is_audio = 'bestaudio' in format_id and 'bestvideo' not in format_id
        output_template = os.path.join(TEMP_DIR, '%(title)s.%(ext)s')
        
        ydl_opts = get_ydl_opts()
        ydl_opts.update({
            'format': format_id,
            'outtmpl': output_template,
            'merge_output_format': 'mp4' if not is_audio else None,
        })
        
        if is_audio:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }]
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if is_audio:
                filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'
            else:
                filename = ydl.prepare_filename(info)
                if not os.path.exists(filename):
                    filename = filename.rsplit('.', 1)[0] + '.mp4'
        
        if not os.path.exists(filename):
            return jsonify({'error': 'Download failed - file not found'}), 500
        
        safe_title = re.sub(r'[^\w\s-]', '', info.get('title', 'video'))[:100]
        ext = 'mp3' if is_audio else 'mp4'
        download_name = f"{safe_title}.{ext}"
        
        response = send_file(
            filename,
            as_attachment=True,
            download_name=download_name,
            mimetype='audio/mpeg' if is_audio else 'video/mp4'
        )
        
        @response.call_on_close
        def cleanup():
            try:
                if os.path.exists(filename):
                    os.remove(filename)
            except:
                pass
        
        return response
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    cookie_status = 'found' if os.path.exists(COOKIE_FILE) else 'missing'
    return jsonify({'status': 'ok', 'cookies': cookie_status})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
