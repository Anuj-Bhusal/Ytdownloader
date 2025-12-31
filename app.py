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
        
        # Process formats - include both merged formats and audio-only
        formats = []
        seen_qualities = set()
        available_video_heights = set()  # Track all available video resolutions
        
        for f in info.get('formats', []):
            format_id = f.get('format_id')
            ext = f.get('ext', 'mp4')
            height = f.get('height')
            width = f.get('width')
            filesize = f.get('filesize') or f.get('filesize_approx')
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')
            abr = f.get('abr')
            vbr = f.get('vbr') or f.get('tbr')
            
            # Track all available video resolutions (including video-only streams)
            if vcodec != 'none' and height:
                available_video_heights.add(int(height))
            
            # Video formats with audio (merged/progressive)
            if vcodec != 'none' and acodec != 'none' and height:
                quality_key = f"video_{height}"
                if quality_key not in seen_qualities:
                    seen_qualities.add(quality_key)
                    # Estimate size if missing
                    estimated_size = filesize
                    if not estimated_size and vbr and info.get('duration'):
                        estimated_size = int((vbr * 1000 / 8) * info.get('duration'))
                    
                    formats.append({
                        'format_id': str(format_id),
                        'type': 'video',
                        'quality': f'{int(height)}p',
                        'height': int(height),
                        'width': int(width) if width else 0,
                        'ext': str(ext),
                        'filesize': int(estimated_size) if estimated_size else None,
                        'has_audio': True,
                    })
            
            # Audio-only formats
            elif acodec != 'none' and vcodec == 'none' and abr:
                quality_key = f"audio_{int(abr)}"
                if quality_key not in seen_qualities:
                    seen_qualities.add(quality_key)
                    # Estimate audio size
                    estimated_size = filesize
                    if not estimated_size and abr and info.get('duration'):
                        estimated_size = int((abr * 1000 / 8) * info.get('duration'))
                    
                    formats.append({
                        'format_id': str(format_id),
                        'type': 'audio',
                        'quality': f'{int(abr)} kbps',
                        'bitrate': int(abr),
                        'ext': str(ext),
                        'filesize': int(estimated_size) if estimated_size else None,
                    })
        
        # Add smart combined formats for video (for high-res that need merging)
        # Get existing merged video heights to avoid duplicates
        existing_heights = set(f.get('height', 0) for f in formats if f['type'] == 'video')
        
        # Always add "Best Quality" option for video
        formats.insert(0, {
            'format_id': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
            'type': 'video',
            'quality': 'Best Quality',
            'height': 9999,
            'ext': 'mp4',
            'filesize': None,
            'has_audio': True,
        })
        
        # Add combined formats ONLY for resolutions that actually exist
        # (where we have video-only streams but no merged format)
        for res in [2160, 1440, 1080, 720, 480, 360]:
            # Skip if we already have a merged format at this resolution
            if res in existing_heights:
                continue
            
            # Only add if yt-dlp has video streams at this resolution
            if res in available_video_heights:
                formats.append({
                    'format_id': f'bestvideo[height<={res}][ext=mp4]+bestaudio[ext=m4a]/best[height<={res}]',
                    'type': 'video',
                    'quality': f'{res}p',
                    'height': res,
                    'ext': 'mp4',
                    'filesize': None,  # Can't know size until merge
                    'has_audio': True,
                })
        
        # Sort formats
        video_formats = sorted([f for f in formats if f['type'] == 'video'], 
                              key=lambda x: x.get('height', 0), reverse=True)
        audio_formats = sorted([f for f in formats if f['type'] == 'audio'], 
                              key=lambda x: x.get('bitrate', 0), reverse=True)
        
        # Always add "Best Audio" option at the top
        audio_formats.insert(0, {
            'format_id': 'bestaudio/best',
            'type': 'audio',
            'quality': 'Best Audio (MP3)',
            'bitrate': 9999,
            'ext': 'mp3',
            'filesize': None,
        })
        
        return jsonify({
            'title': str(info.get('title', 'Unknown')),
            'duration': int(info.get('duration') or 0),
            'channel': str(info.get('uploader', 'Unknown')),
            'thumbnail': str(info.get('thumbnail') or ''),
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
        
        # Create unique temp filename
        import uuid
        temp_id = str(uuid.uuid4())[:8]
        output_template = os.path.join(TEMP_DIR, f'yt_dl_{temp_id}_%(title)s.%(ext)s')
        
        ydl_opts = get_ydl_opts()
        ydl_opts.update({
            'format': format_id,
            'outtmpl': output_template,
            'merge_output_format': 'mp4' if not is_audio else None,
            'progress_hooks': [],  # Disable progress for speed
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
