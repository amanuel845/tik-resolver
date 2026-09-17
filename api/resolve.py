from flask import Flask, request, jsonify, Response, stream_with_context
from urllib.parse import quote
import yt_dlp
import tempfile
import os

app = Flask(__name__)


# ---------- Metadata ----------
@app.route('/')
@app.route('/api/resolve')
def resolve():
    url = request.args.get('url')
    if not url:
        return jsonify({'ok': False, 'error': 'missing url parameter'}), 400

    ydl_opts = {
        'quiet': True, 'no_warnings': True,
        'skip_download': True, 'format': 'best',
        'nocheckcertificate': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        return jsonify({'ok': False, 'error': 'extraction failed: ' + str(e)}), 502
    except Exception as e:
        return jsonify({'ok': False, 'error': 'unexpected error: ' + str(e)}), 500

    if not info:
        return jsonify({'ok': False, 'error': 'no info'}), 502

    return jsonify({
        'ok': True,
        'mode': 'video',
        'item': {
            'id': info.get('id', ''),
            'type': 'video',
            'title': info.get('title') or info.get('description') or '',
            'duration': info.get('duration') or 0,
            'author': {
                'handle': info.get('uploader') or info.get('uploader_id') or '',
                'name': info.get('uploader') or '',
                'avatar': _pick_thumbnail(info),
            },
            'stats': {
                'plays': info.get('view_count'),
                'likes': info.get('like_count'),
                'comments': info.get('comment_count'),
                'shares': info.get('repost_count'),
            },
            'cover': _pick_thumbnail(info),
            'video': {'noWatermark': '', 'watermark': '', 'hd': ''},
            'music': {},
            'images': [],
        },
    })


# ---------- Download (server-side) ----------
@app.route('/api/download')
def download():
    url = request.args.get('url')
    if not url:
        return jsonify({'ok': False, 'error': 'missing url parameter'}), 400

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
    tmp_path = tmp.name
    tmp.close()

    ydl_opts = {
        'quiet': True, 'no_warnings': True,
        'outtmpl': tmp_path,
        'format': 'best[ext=mp4]/best',
        'nocheckcertificate': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        try: os.unlink(tmp_path)
        except OSError: pass
        return jsonify({'ok': False, 'error': str(e)}), 502

    file_size = os.path.getsize(tmp_path)

    def generate():
        try:
            with open(tmp_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        finally:
            try: os.unlink(tmp_path)
            except OSError: pass

    return Response(
        stream_with_context(generate()),
        mimetype='video/mp4',
        headers={
            'Content-Disposition': 'attachment; filename="tiktok.mp4"',
            'Content-Length': str(file_size),
            'Access-Control-Allow-Origin': '*',
        },
    )


@app.route('/health')
def health():
    return jsonify({'ok': True, 'service': 'tik-resolver'})


def _pick_thumbnail(info):
    thumbs = info.get('thumbnails') or []
    if not thumbs:
        return ''
    return thumbs[-1].get('url', '')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
