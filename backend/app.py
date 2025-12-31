"""
YouTube Downloader API Backend
Flask API for fetching video info and downloading videos
"""

import os
import re
import tempfile
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Temp directory for downloads
TEMP_DIR = tempfile.gettempdir()


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
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # yt-dlp options for fetching info only
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'noplaylist': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        }
        
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
            abr = f.get('abr')  # Audio bitrate
            
            # Video formats (must have video codec)
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
            
            # Audio-only formats
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
        
        # Add combined format options (best video + best audio)
        formats.insert(0, {
            'format_id': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
            'type': 'video',
            'quality': 'Best Quality',
            'height': 9999,
            'ext': 'mp4',
            'filesize': 'Auto',
            'has_audio': True,
        })
        
        # Add common resolutions
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
        
        # Sort formats
        video_formats = sorted([f for f in formats if f['type'] == 'video'], 
                              key=lambda x: x.get('height', 0), reverse=True)
        audio_formats = sorted([f for f in formats if f['type'] == 'audio'], 
                              key=lambda x: x.get('bitrate', 0), reverse=True)
        
        # Add best audio option
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
    try:
        data = request.get_json()
        url = data.get('url')
        format_id = data.get('format_id', 'best')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Determine if audio-only
        is_audio = 'bestaudio' in format_id and 'bestvideo' not in format_id
        
        # Create temp file path
        output_template = os.path.join(TEMP_DIR, '%(title)s.%(ext)s')
        
        ydl_opts = {
            'format': format_id,
            'outtmpl': output_template,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4' if not is_audio else None,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        }
        
        # Add audio postprocessor if audio only
        if is_audio:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }]
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Get the actual filename
            if is_audio:
                filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'
            else:
                filename = ydl.prepare_filename(info)
                # Handle merged files
                if not os.path.exists(filename):
                    filename = filename.rsplit('.', 1)[0] + '.mp4'
        
        if not os.path.exists(filename):
            return jsonify({'error': 'Download failed - file not found'}), 500
        
        # Get safe filename for download
        safe_title = re.sub(r'[^\w\s-]', '', info.get('title', 'video'))[:100]
        ext = 'mp3' if is_audio else 'mp4'
        download_name = f"{safe_title}.{ext}"
        
        # Send file and cleanup
        response = send_file(
            filename,
            as_attachment=True,
            download_name=download_name,
            mimetype='audio/mpeg' if is_audio else 'video/mp4'
        )
        
        # Schedule file cleanup (in production, use a proper cleanup mechanism)
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
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
