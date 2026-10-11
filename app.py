from flask import Flask, request, jsonify, send_file
import os, requests, io, time

app = Flask(__name__)

GROQ_KEY = os.environ.get('GROQ_API_KEY', '')
OR_KEY = os.environ.get('OPENROUTER_API_KEY', '')
ORACLE_URL = os.environ.get('ORACLE_BROWSE_URL', 'http://129.159.159.222:8080')
BROWSE_KEY = os.environ.get('BROWSE_KEY', 'tzvi-free-1234')

GROQ_MODELS = ['openai/gpt-oss-120b', 'openai/gpt-oss-20b']
OR_MODELS = ['google/gemma-4-31b-it:free', 'nvidia/nemotron-3-super-120b-a12b:free', 'google/gemma-4-26b-a4b-it:free']

def groq_chat(messages, model):
    r = requests.post('https://api.groq.com/openai/v1/chat/completions',
        headers={'Authorization': f'Bearer {GROQ_KEY}', 'Content-Type': 'application/json'},
        json={'model': model, 'messages': messages, 'temperature': 0.7}, timeout=60)
    if r.status_code in (429, 401, 403, 500, 502, 503):
        raise RuntimeError(f'groq {r.status_code}: {r.text[:200]}')
    r.raise_for_status()
    return r.json()['choices'][0]['message']['content']

def or_chat(messages, model):
    r = requests.post('https://openrouter.ai/api/v1/chat/completions',
        headers={'Authorization': f'Bearer {OR_KEY}', 'Content-Type': 'application/json',
                 'HTTP-Referer': 'https://render.com', 'X-Title': 'voice-brain'},
        json={'model': model, 'messages': messages, 'temperature': 0.7}, timeout=60)
    if r.status_code in (429, 401, 402, 403, 500, 502, 503):
        raise RuntimeError(f'openrouter {r.status_code}: {r.text[:200]}')
    r.raise_for_status()
    return r.json()['choices'][0]['message']['content']

def smart_chat(messages):
    errors = []
    for m in GROQ_MODELS:
        if not GROQ_KEY: break
        try:
            return groq_chat(messages, m), f'groq/{m}'
        except Exception as e:
            errors.append(str(e)); time.sleep(1)
    for m in OR_MODELS:
        if not OR_KEY: break
        try:
            return or_chat(messages, m), f'openrouter/{m}'
        except Exception as e:
            errors.append(str(e)); time.sleep(1)
    raise RuntimeError('all models failed: ' + ' | '.join(errors))

SITE_MAP = {
    'כיכר השבת': 'https://www.kikar.co.il', 'כיכר': 'https://www.kikar.co.il',
    'ynet': 'https://www.ynet.co.il', 'וויינט': 'https://www.ynet.co.il',
    'וואלה': 'https://www.walla.co.il', 'walla': 'https://www.walla.co.il',
    'חדשות 12': 'https://www.mako.co.il', 'מאקו': 'https://www.mako.co.il', 'mako': 'https://www.mako.co.il',
    'ישראל היום': 'https://www.israelhayom.co.il',
    'הארץ': 'https://www.haaretz.co.il', 'ynet ספורט': 'https://www.ynet.co.il/sport',
    'בחדרי חרדים': 'https://www.bhol.co.il', 'בחדרי': 'https://www.bhol.co.il',
    'JDN': 'https://www.jdn.co.il',
    'הידברות': 'https://www.hidabroot.org',
}
NEWS_WORDS = ['כתבה ראשונה', 'כותרת ראשית', 'מה חדש', 'מה קורה', 'חדשות', 'כותרות', 'הכתבה', 'הכותרת', 'עדכני', 'היום']

def extract_headlines(html):
    import re, html as _h
    heads = []
    for pat in (r'<title[^>]*>(.*?)</title>', r'<h1[^>]*>(.*?)</h1>', r'<h2[^>]*>(.*?)</h2>'):
        for m in re.finditer(pat, html, re.S | re.I):
            t = re.sub(r'<[^>]+>', '', m.group(1))
            t = _h.unescape(t).strip()
            if len(t) > 15 and t not in heads:
                heads.append(t)
            if len(heads) >= 15:
                break
    return heads

def maybe_browse(prompt):
    target = None
    if 'http' in prompt:
        target = 'http' + prompt.split('http', 1)[1].split()[0]
    else:
        for name, url in SITE_MAP.items():
            if name in prompt:
                target = url
                break
        if not target and any(w in prompt for w in NEWS_WORDS):
            target = 'https://www.ynet.co.il'
    if not target:
        return ''
    try:
        r = requests.get(f'{ORACLE_URL}/fetch', params={'key': BROWSE_KEY, 'url': target}, timeout=60)
        if r.ok:
            heads = extract_headlines(r.json().get('html', ''))
            if heads:
                return '\n[כותרות חיות מ-' + target + ' דרך הדפדפן, ענה לפיהן]:\n' + '\n'.join(f'{i+1}. {h}' for i, h in enumerate(heads))
            return '\n[הגלישה לא החזירה כותרות]'
    except Exception as e:
        return f'\n[גלישה נכשלה: {e}]'
    return ''

@app.route('/health')
def health():
    return 'ok'

@app.route('/chat', methods=['POST'])
def chat():
    d = request.get_json(force=True)
    prompt = d.get('text', '')
    extra = maybe_browse(prompt)
    msgs = [{'role': 'system', 'content': 'אתה עוזר קולי בעברית. תשובות קצרות וברורות. אם מצורפות כותרות חיות מהדפדפן, ענה תמיד לפיהן ולא מהזיכרון.'},
            {'role': 'user', 'content': prompt + extra}]
    try:
        ans, via = smart_chat(msgs)
        return jsonify({'reply': ans, 'via': via})
    except Exception as e:
        return jsonify({'error': str(e)}), 503

@app.route('/voice', methods=['POST'])
def voice():
    if 'audio' not in request.files:
        return jsonify({'error': 'no audio file'}), 400
    af = request.files['audio']
    # STT via Groq Whisper (free tier)
    try:
        r = requests.post('https://api.groq.com/openai/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {GROQ_KEY}'},
            files={'file': (af.filename or 'a.wav', af.read(), 'audio/wav')},
            data={'model': 'whisper-large-v3-turbo', 'language': 'he'}, timeout=90)
        r.raise_for_status()
        text = r.json().get('text', '')
    except Exception as e:
        return jsonify({'error': f'stt failed: {e}'}), 503
    extra = maybe_browse(text)
    msgs = [{'role': 'system', 'content': 'אתה עוזר קולי בעברית. תשובות קצרות.'},
            {'role': 'user', 'content': text + extra}]
    try:
        ans, via = smart_chat(msgs)
    except Exception as e:
        return jsonify({'error': str(e), 'transcript': text}), 503
    # TTS via gTTS (free, no key)
    try:
        from gtts import gTTS
        buf = io.BytesIO()
        gTTS(ans[:500], lang='iw').write_to_fp(buf)
        buf.seek(0)
        return send_file(buf, mimetype='audio/mpeg', download_name='reply.mp3')
    except Exception as e:
        return jsonify({'reply': ans, 'via': via, 'tts_error': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
