"""
YouTube Downloader API Backend
Flask API with real-time progress tracking via Server-Sent Events (SSE)
"""

import os
import re
import time
import tempfile
import uuid
import json
import threading
import traceback
from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app, expose_headers=['Content-Disposition'], supports_credentials=True)

# Add CORS headers to all responses including errors
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

# Config
TEMP_DIR = tempfile.gettempdir()
COOKIE_FILE = os.path.join(os.path.dirname(__file__), 'cookies.txt')

# Rate limiting (simple in-memory)
REQUEST_LOG = {}
RATE_LIMIT = 10  # requests per minute per IP

# Download jobs storage (in-memory, for production use Redis)
DOWNLOAD_JOBS = {}


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


def create_progress_hook(job_id):
    """Create a progress hook for yt-dlp that updates job status"""
    def hook(d):
        if job_id not in DOWNLOAD_JOBS:
            return
        
        job = DOWNLOAD_JOBS[job_id]
        
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            speed = d.get('speed', 0)
            eta = d.get('eta', 0)
            
            # Track if this is video or audio stream
            filename = d.get('filename', '')
            is_audio_stream = '.m4a' in filename or '.webm' in filename and 'audio' in str(d.get('info_dict', {}).get('format', ''))
            
            # Keep track of cumulative downloaded for multi-stream downloads
            if not job.get('_video_done'):
                job['_current_stream'] = 'video'
                if d['status'] == 'finished' or downloaded >= total > 0:
                    job['_video_done'] = True
                    job['_video_size'] = total
            else:
                job['_current_stream'] = 'audio'
            
            job['phase'] = 'downloading'
            job['downloaded_bytes'] = downloaded
            job['total_bytes'] = total
            job['speed'] = speed or 0
            job['eta'] = eta or 0
            job['stream'] = job.get('_current_stream', 'video')
            
            if total > 0:
                job['progress'] = min(int((downloaded / total) * 100), 99)
            
            # Show which stream is downloading
            stream_label = 'audio' if job.get('_video_done') else 'video'
            job['message'] = f'Downloading {stream_label}...'
            
        elif d['status'] == 'finished':
            job['phase'] = 'processing'
            job['progress'] = 95
            job['message'] = 'Merging video and audio...'
            
        elif d['status'] == 'error':
            job['phase'] = 'error'
            job['error'] = str(d.get('error', 'Download failed'))
    
    return hook


def download_worker(job_id, url, format_id):
    """Background worker that downloads the video"""
    job = DOWNLOAD_JOBS[job_id]
    
    try:
        job['phase'] = 'starting'
        job['message'] = 'Connecting to YouTube...'
        
        is_audio = 'bestaudio' in format_id and 'bestvideo' not in format_id
        job['is_audio'] = is_audio  # Set early so frontend knows
        
        output_template = os.path.join(TEMP_DIR, f'yt_dl_{job_id}_%(title)s.%(ext)s')
        
        ydl_opts = get_ydl_opts()
        ydl_opts.update({
            'format': format_id,
            'outtmpl': output_template,
            'merge_output_format': 'mp4' if not is_audio else None,
            'progress_hooks': [create_progress_hook(job_id)],
        })
        
        if is_audio:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }]
        
        job['phase'] = 'downloading'
        job['message'] = 'Downloading from YouTube...'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if is_audio:
                filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'
            else:
                filename = ydl.prepare_filename(info)
                if not os.path.exists(filename):
                    filename = filename.rsplit('.', 1)[0] + '.mp4'
        
        if not os.path.exists(filename):
            raise Exception('Download failed - file not found')
        
        # Create clean filename
        safe_title = re.sub(r'[^\w\s-]', '', info.get('title', 'video'))[:100].strip()
        if not safe_title:
            safe_title = 'video'
        ext = 'mp3' if is_audio else 'mp4'
        download_name = f"{safe_title}.{ext}"
        
        # Get actual file size
        actual_size = os.path.getsize(filename)
        
        job['phase'] = 'ready'
        job['progress'] = 100
        job['filepath'] = filename
        job['filename'] = download_name
        job['filesize'] = actual_size
        job['message'] = 'Ready to download!'
        job['is_audio'] = is_audio
        
    except Exception as e:
        job['phase'] = 'error'
        job['error'] = str(e)
        job['message'] = f'Error: {str(e)}'


@app.route('/api/info', methods=['POST'])
def get_video_info():
    """Fetch video information and available formats"""
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
        
        formats = []
        seen_qualities = set()
        available_video_heights = set()
        
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
            
            if vcodec != 'none' and height:
                available_video_heights.add(int(height))
            
            if vcodec != 'none' and acodec != 'none' and height:
                quality_key = f"video_{height}"
                if quality_key not in seen_qualities:
                    seen_qualities.add(quality_key)
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
            
            elif acodec != 'none' and vcodec == 'none' and abr:
                quality_key = f"audio_{int(abr)}"
                if quality_key not in seen_qualities:
                    seen_qualities.add(quality_key)
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
        
        existing_heights = set(f.get('height', 0) for f in formats if f['type'] == 'video')
        
        for res in [2160, 1440, 1080, 720, 480, 360]:
            if res in existing_heights:
                continue
            if res in available_video_heights:
                formats.append({
                    'format_id': f'bestvideo[height<={res}][ext=mp4]+bestaudio[ext=m4a]/best[height<={res}]',
                    'type': 'video',
                    'quality': f'{res}p',
                    'height': res,
                    'ext': 'mp4',
                    'filesize': None,
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


@app.route('/api/download/start', methods=['POST'])
def start_download():
    """Start a download job and return job ID"""
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if not check_rate_limit(client_ip):
        return jsonify({'error': 'Rate limit exceeded. Please wait.'}), 429
    
    try:
        data = request.get_json()
        url = data.get('url')
        format_id = data.get('format_id', 'best')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Create job
        job_id = str(uuid.uuid4())[:12]
        DOWNLOAD_JOBS[job_id] = {
            'id': job_id,
            'phase': 'queued',
            'progress': 0,
            'downloaded_bytes': 0,
            'total_bytes': 0,
            'speed': 0,
            'eta': 0,
            'message': 'Starting download...',
            'error': None,
            'filepath': None,
            'filename': None,
            'filesize': 0,
            'created_at': time.time(),
        }
        
        # Start download in background thread
        thread = threading.Thread(target=download_worker, args=(job_id, url, format_id))
        thread.daemon = True
        thread.start()
        
        return jsonify({'job_id': job_id})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download/progress/<job_id>')
def download_progress(job_id):
    """SSE endpoint for real-time progress updates"""
    def generate():
        # Wait a bit for job to be created (race condition fix)
        max_wait = 10  # Wait up to 10 seconds for job
        waited = 0
        while job_id not in DOWNLOAD_JOBS and waited < max_wait:
            time.sleep(0.5)
            waited += 0.5
        
        if job_id not in DOWNLOAD_JOBS:
            yield f"data: {json.dumps({'phase': 'error', 'error': 'Job not found or expired'})}\n\n"
            return
        
        while True:
            if job_id not in DOWNLOAD_JOBS:
                yield f"data: {json.dumps({'phase': 'error', 'error': 'Job expired'})}\n\n"
                break
            
            job = DOWNLOAD_JOBS[job_id]
            
            # Send current status
            yield f"data: {json.dumps(job)}\n\n"
            
            # Stop if completed or errored
            if job['phase'] in ['ready', 'error']:
                break
            
            # Clean up old jobs (older than 30 minutes)
            if time.time() - job.get('created_at', 0) > 1800:
                del DOWNLOAD_JOBS[job_id]
                break
            
            time.sleep(0.5)  # Update every 500ms
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',  # Disable nginx buffering
        }
    )


@app.route('/api/download/file/<job_id>')
def download_file(job_id):
    """Download the completed file"""
    try:
        if job_id not in DOWNLOAD_JOBS:
            return jsonify({'error': f'Job {job_id} not found. Available: {list(DOWNLOAD_JOBS.keys())}'}), 404
        
        job = DOWNLOAD_JOBS[job_id]
        
        if job['phase'] != 'ready':
            return jsonify({'error': f'Download not ready. Phase: {job["phase"]}'}), 400
        
        filepath = job.get('filepath')
        filename = job.get('filename', 'video.mp4')
        is_audio = job.get('is_audio', False)
        
        if not filepath:
            return jsonify({'error': 'No filepath in job'}), 500
            
        if not os.path.exists(filepath):
            return jsonify({'error': f'File not found at {filepath}'}), 404
        
        response = send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype='audio/mpeg' if is_audio else 'video/mp4'
        )
        
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        @response.call_on_close
        def cleanup():
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                if job_id in DOWNLOAD_JOBS:
                    del DOWNLOAD_JOBS[job_id]
            except:
                pass
        
        return response
        
    except Exception as e:
        print(f"Error in download_file: {traceback.format_exc()}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500


# Keep old endpoint for backward compatibility
@app.route('/api/download', methods=['POST'])
def download_video():
    """Legacy download endpoint (blocking)"""
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
        
        temp_id = str(uuid.uuid4())[:8]
        output_template = os.path.join(TEMP_DIR, f'yt_dl_{temp_id}_%(title)s.%(ext)s')
        
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
        
        safe_title = re.sub(r'[^\w\s-]', '', info.get('title', 'video'))[:100].strip()
        if not safe_title:
            safe_title = 'video'
        ext = 'mp3' if is_audio else 'mp4'
        download_name = f"{safe_title}.{ext}"
        
        response = send_file(
            filename,
            as_attachment=True,
            download_name=download_name,
            mimetype='audio/mpeg' if is_audio else 'video/mp4'
        )
        
        response.headers['Content-Disposition'] = f'attachment; filename="{download_name}"'
        
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
    return jsonify({
        'status': 'ok',
        'cookies': cookie_status,
        'active_jobs': len(DOWNLOAD_JOBS)
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
