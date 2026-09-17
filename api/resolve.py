from flask import Flask, request, jsonify
import yt_dlp
import os

app = Flask(__name__)


@app.route('/')
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
        'extractor_args': {
            'tiktok': {
                'api_hostname': ['api22-normal-c-useast2a.tiktokv.com'],
            },
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        return jsonify({
            'ok': False,
            'error': 'extraction failed: ' + str(e)
        }), 502
    except Exception as e:
        return jsonify({
            'ok': False,
            'error': 'unexpected error: ' + str(e)
        }), 500

    if not info:
        return jsonify({'ok': False, 'error': 'no info returned'}), 502

    formats = info.get('formats') or []
    no_watermark = _pick_no_watermark(formats, info)
    watermark = _pick_watermark(formats, info)

    return jsonify({
        'ok': True,
        'mode': info.get('extractor_key', 'TikTok').lower().replace('tiktok', 'video') or 'video',
        'item': {
            'id': info.get('id', ''),
            'type': 'video',
            'title': info.get('title') or info.get('description') or '',
            'duration': info.get('duration') or 0,
            'author': {
                'handle': info.get('uploader_id') or info.get('uploader') or '',
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
                'noWatermark': no_watermark,
                'watermark': watermark,
                'hd': no_watermark,
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


def _pick_no_watermark(formats, info):
    """
    yt-dlp for TikTok exposes several format IDs. The ones without
    'watermark' in their id are the clean copies. Prefer MP4, prefer
    the highest resolution.
    """
    candidates = []
    for f in formats:
        fid = (f.get('format_id') or '').lower()
        ext = (f.get('ext') or '').lower()
        if ext != 'mp4':
            continue
        if 'watermark' in fid or 'watermarked' in fid:
            continue
        candidates.append(f)

    if not candidates:
        candidates = [f for f in formats if (f.get('ext') or '').lower() == 'mp4']

    if not candidates:
        return info.get('url') or ''

    candidates.sort(key=lambda f: (f.get('height') or 0, f.get('tbr') or 0), reverse=True)
    return candidates[0].get('url') or ''


def _pick_watermark(formats, info):
    """Find the watermarked variant, if yt-dlp exposes one."""
    for f in formats:
        fid = (f.get('format_id') or '').lower()
        if 'watermark' in fid and (f.get('ext') or '').lower() == 'mp4':
            return f.get('url') or ''
    return ''


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
