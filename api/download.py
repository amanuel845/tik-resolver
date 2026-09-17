from flask import Flask, request, jsonify, Response, stream_with_context
import yt_dlp
import tempfile
import os

app = Flask(__name__)


@app.route('/')
@app.route('/api/download')
def download():
    url = request.args.get('url')
    if not url:
        return jsonify({'ok': False, 'error': 'missing url parameter'}), 400

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
    tmp_path = tmp.name
    tmp.close()

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'outtmpl': tmp_path,
        'format': 'best[ext=mp4]/best',
        'nocheckcertificate': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
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
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return Response(
        stream_with_context(generate()),
        mimetype='video/mp4',
        headers={
            'Content-Disposition': 'attachment; filename="tiktok.mp4"',
            'Content-Length': str(file_size),
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': '*',
        },
    )


@app.route('/health')
def health():
    return jsonify({'ok': True, 'service': 'tik-resolver-download'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
