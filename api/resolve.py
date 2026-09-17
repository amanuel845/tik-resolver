from flask import Flask, request, jsonify
import yt_dlp
import re
import os

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Shared classifier
# ---------------------------------------------------------------------------
def _classify_one(url):
    """Classify a single TikTok URL. Returns a dict, never raises."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'format': 'best',
        'nocheckcertificate': True,
    }

    info = None
    extract_error = None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        extract_error = str(e)
    except Exception as e:
        extract_error = str(e)

    kind = 'unknown'
    resolved_url = ''
    live_broadcast = None
    live_username = ''
    reason = ''

    if info:
        resolved_url = info.get('webpage_url') or info.get('url') or ''
        live_broadcast = info.get('is_live')

        if live_broadcast is True:
            kind = 'live'
            reason = 'yt-dlp reports is_live=true'
        elif resolved_url and '/live' in resolved_url:
            kind = 'live'
            reason = 'resolved URL contains /live'
        elif info.get('_type') == 'playlist':
            kind = 'live'
            reason = 'yt-dlp returned a playlist (live streams often do)'
        elif resolved_url and '/photo/' in resolved_url:
            kind = 'photo'
            reason = 'resolved URL contains /photo/'
        elif resolved_url and '/video/' in resolved_url:
            kind = 'video'
            reason = 'resolved URL contains /video/'
        elif info.get('ext') in ('mp4', 'webm'):
            kind = 'video'
            reason = 'yt-dlp returned an mp4/webm format'
        else:
            kind = 'video'
            reason = 'yt-dlp extracted a single-item result without /live'

    if extract_error:
        err_lower = extract_error.lower()

        m = re.search(r'\[tiktok:live\]\s+([^:]+):', extract_error)
        if m:
            live_username = m.group(1).strip()

        if kind == 'unknown' and (
            'not currently live' in err_lower or
            '[tiktok:live]' in err_lower or
            'tiktok:live' in err_lower
        ):
            kind = 'live'
            reason = 'extractor reported a live channel that is offline'

    if kind == 'unknown':
        if re.search(r'/(live|share/live)/', url, re.I):
            kind = 'live'
            reason = 'input URL matches live pattern'
        elif re.search(r'/(video|photo)/\d+', url, re.I):
            kind = 'video'
            reason = 'input URL matches video/photo pattern'

    return {
        'input': url,
        'kind': kind,
        'reason': reason,
        'resolved_url': resolved_url,
        'is_live': live_broadcast,
        'live_username': live_username,
        'error': extract_error,
    }


# ---------------------------------------------------------------------------
# Single-URL endpoint
# ---------------------------------------------------------------------------
@app.route('/')
@app.route('/api/classify')
def classify():
    url = request.args.get('url')
    if not url:
        return jsonify({
            'ok': False,
            'error': 'missing url parameter. Usage: /api/classify?url=<tiktok_url>'
        }), 400

    result = _classify_one(url)
    result['ok'] = True
    return jsonify(result)


# ---------------------------------------------------------------------------
# Batch endpoint
# ---------------------------------------------------------------------------
# Vercel Hobby has a 10-second execution limit. Each yt-dlp call takes
# ~1-2 s. Cap the batch so we finish comfortably inside the limit.
BATCH_MAX = 5


@app.route('/api/classify-batch', methods=['POST', 'OPTIONS'])
def classify_batch():
    # CORS preflight for browser clients.
    if request.method == 'OPTIONS':
        return ('', 204, {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
        })

    payload = request.get_json(silent=True) or {}
    urls = payload.get('urls') or []
    if not isinstance(urls, list) or not urls:
        return jsonify({
            'ok': False,
            'error': 'expected JSON body {"urls": ["...", "..."]}'
        }), 400

    truncated = False
    if len(urls) > BATCH_MAX:
        urls = urls[:BATCH_MAX]
        truncated = True

    results = []
    for u in urls:
        if not isinstance(u, str) or not u.strip():
            results.append({
                'input': u,
                'kind': 'unknown',
                'reason': 'empty url',
                'resolved_url': '',
                'is_live': None,
                'live_username': '',
                'error': 'empty url',
            })
            continue
        results.append(_classify_one(u.strip()))

    response = jsonify({
        'ok': True,
        'count': len(results),
        'truncated': truncated,
        'batch_max': BATCH_MAX,
        'results': results,
    })
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


# ---------------------------------------------------------------------------
# Metadata endpoint (unchanged)
# ---------------------------------------------------------------------------
@app.route('/api/resolve')
def resolve_metadata():
    """Return metadata for a TikTok URL. No video bytes are fetched."""
    url = request.args.get('url')
    if not url:
        return jsonify({'ok': False, 'error': 'missing url parameter'}), 400

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
            'video': {'noWatermark': '', 'watermark': '', 'hd': ''},
            'music': {},
            'images': [],
        },
    })


@app.route('/health')
def health():
    return jsonify({'ok': True, 'service': 'tik-classifier'})


def _pick_thumbnail(info):
    thumbs = info.get('thumbnails') or []
    if not thumbs:
        return ''
    return thumbs[-1].get('url', '')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
