from flask import Flask, request, jsonify
import yt_dlp
import os

app = Flask(__name__)


@app.route('/')
@app.route('/api/resolve')
def resolve():
    url = request.args.get('url')
    if not url:
        return jsonify({
            'ok': False,
            'error': 'missing url parameter. Usage: /api/resolve?url=<tiktok_url>'
        }), 400

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'format': 'best',
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
        return jsonify({'ok': False, 'error': 'no info returned'}), 502

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
            'video': {
                'noWatermark': '',
                'watermark': '',
                'hd': '',
            },
            'music': {},
            'images': [],
        },
    })


@app.route('/health')
def health():
    return jsonify({'ok': True, 'service': 'tik-resolver'})


def _pick_thumbnail(info):
    thumbs = info.get('thumbnails') or []
    if not thumbs:
        return ''
    return thumbs[-1].get('url', '')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
