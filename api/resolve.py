from flask import Flask, request, jsonify
import yt_dlp

app = Flask(__name__)

@app.route('/api/resolve')
def resolve():
    url = request.args.get('url')
    if not url:
        return jsonify({'ok': False, 'error': 'missing url'}), 400

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'format': 'best',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # yt-dlp normalizes TikTok's data
        return jsonify({
            'ok': True,
            'item': {
                'id': info.get('id', ''),
                'title': info.get('title', ''),
                'duration': info.get('duration', 0),
                'author': {
                    'handle': info.get('uploader_id', ''),
                    'name': info.get('uploader', ''),
                },
                'video': {
                    'noWatermark': _pick_best(info.get('formats', [])),
                },
                'stats': {},
            }
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


def _pick_best(formats):
    """Prefer a no-watermark MP4 if yt-dlp exposes one."""
    for f in formats:
        if f.get('ext') == 'mp4' and 'watermark' not in f.get('format_id', '').lower():
            return f.get('url')
    return formats[-1].get('url') if formats else ''


# Vercel's Python runtime looks for an 'app' instance
# This file works as both a local Flask app and a Vercel function
