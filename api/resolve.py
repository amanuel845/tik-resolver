from flask import Flask, request, jsonify, Response, stream_with_context
from urllib.parse import urlparse, quote
import yt_dlp
import requests
import os

app = Flask(__name__)


ALLOWED_HOSTS = (
    '.tiktokcdn.com',
    '.tiktokcdn-us.com',
    '.tiktok.com',
    '.tiktokv.com',
    '.byteoversea.com',
    '.ibytedtos.com',
)

BROWSER_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/120.0.0.0 Safari/537.36'),
    'Referer': 'https://www.tiktok.com/',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
}

# Module-level session so cookies persist across requests within the
# same warm serverless invocation.
_session = requests.Session()
_session.headers.update(BROWSER_HEADERS)

_cookies_warmed = False


def _warm_cookies(force=False):
    """Visit tiktok.com once to collect the CDN cookies (ttwid, msToken, …).

    Fastly checks the cookie chain in addition to the URL signature.
    Without these, /stream returns 403 even though the URL itself is valid.
    """
    global _cookies_warmed
    if _cookies_warmed and not force:
        return
    try:
        _session.get('https://www.tiktok.com/', timeout=10, allow_redirects=True)
        _cookies_warmed = True
    except requests.RequestException:
        pass


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

    formats = info.get('formats') or []
    no_watermark = _pick_no_watermark(formats, info)
    watermark = _pick_watermark(formats, info)

    base = request.host_url.rstrip('/')

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
                'noWatermark': _proxy_url(base, no_watermark),
                'watermark': _proxy_url(base, watermark),
                'hd': _proxy_url(base, no_watermark),
            },
            'music': {},
            'images': [],
        },
    })


@app.route('/stream')
def stream():
    """Proxy a TikTok CDN URL, adding cookies and Referer so Fastly accepts it.

    Only TikTok CDN hosts are allowed, so this can't be abused as an open
    proxy. Range requests are forwarded so <video> seeking works.
    """
    target = request.args.get('url')
    if not target:
        return jsonify({'ok': False, 'error': 'missing url'}), 400

    host = urlparse(target).netloc.lower()
    if not any(host.endswith(h) for h in ALLOWED_HOSTS):
        return jsonify({'ok': False, 'error': 'host not allowed'}), 403

    _warm_cookies()

    headers = dict(BROWSER_HEADERS)
    if 'Range' in request.headers:
        headers['Range'] = request.headers['Range']

    try:
        upstream = _session.get(target, headers=headers, stream=True, timeout=30)
    except requests.RequestException as e:
        return jsonify({'ok': False, 'error': 'upstream failed: ' + str(e)}), 502

    status = upstream.status_code

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    out_headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Range',
        'Access-Control-Expose-Headers': 'Content-Length, Content-Range, Accept-Ranges',
        'Accept-Ranges': upstream.headers.get('Accept-Ranges', 'bytes'),
    }
    for h in ('Content-Type', 'Content-Length', 'Content-Range'):
        if h in upstream.headers:
            out_headers[h] = upstream.headers[h]

    if 'Content-Type' not in out_headers:
        out_headers['Content-Type'] = 'video/mp4'

    return Response(
        stream_with_context(generate()),
        status=status,
        headers=out_headers,
    )


@app.route('/health')
def health():
    return jsonify({'ok': True, 'service': 'tik-resolver'})


def _proxy_url(base, cdn_url):
    """Wrap a TikTok CDN URL in our streaming proxy."""
    if not cdn_url:
        return ''
    return base + '/stream?url=' + quote(cdn_url, safe='')


def _pick_thumbnail(info):
    thumbs = info.get('thumbnails') or []
    if not thumbs:
        return ''
    return thumbs[-1].get('url', '')


def _pick_no_watermark(formats, info):
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
    for f in formats:
        fid = (f.get('format_id') or '').lower()
        if 'watermark' in fid and (f.get('ext') or '').lower() == 'mp4':
            return f.get('url') or ''
    return ''


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
