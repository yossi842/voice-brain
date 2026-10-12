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
    def clean(t):
        t = re.sub(r'<[^>]+>', '', t)
        return _h.unescape(t).strip()
    for pat in (r'<title[^>]*>(.*?)</title>',
                r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
                r'<h1[^>]*>(.*?)</h1>', r'<h2[^>]*>(.*?)</h2>',
                r'<a[^>]*>(.*?)</a>'):
        for m in re.finditer(pat, html, re.S | re.I):
            t = clean(m.group(1))
            if len(t) > 20 and len(t) < 200 and t not in heads and any('\u0590' <= c <= '\u05ea' for c in t):
                heads.append(t)
            if len(heads) >= 15:
                return heads
    return heads

def oracle_text(url):
    r = requests.get(f'{ORACLE_URL}/fetch', params={'key': BROWSE_KEY, 'url': url, 'text': '1'}, timeout=90)
    r.raise_for_status()
    return r.json()

def clean_lines(lines, skip_title=True):
    heb = [l for l in lines if any('\u0590' <= c <= '\u05ea' for c in l)]
    if skip_title:
        heb = [l for l in heb if '|' not in l and 'אתר החדשות' not in l and 'כל הזכויות' not in l]
    return heb[:12]

def maybe_browse(prompt):
    try:
        # 1. explicit URL -> fetch full text
        if 'http' in prompt:
            url = 'http' + prompt.split('http', 1)[1].split()[0]
            d = oracle_text(url)
            lines = clean_lines(d.get('lines', []), skip_title=False)[:25]
            return ('\n[טקסט חי מ-' + url + '. סכם/ענה לפיו, אסור לומר שאין גישה]:\n'
                    + '\n'.join(lines)[:4000])
        # 2. summarize first article from a site
        if any(w in prompt for w in ['סכם', 'תמצת', 'צטט', 'קרא', 'תמצית', 'סיכום']) and any(w in prompt for w in ['כתבה', 'מאמר', 'ידיעה']):
            site = next((u for n, u in SITE_MAP.items() if n in prompt), 'https://www.ynet.co.il')
            d = oracle_text(site)
            art = next((l['u'] for l in d.get('links', []) if '/video' not in l['u'] and l['u'] != site and not l['u'].endswith('.ico')), None)
            if art:
                a = oracle_text(art)
                lines = clean_lines(a.get('lines', []), skip_title=False)[:40]
                return ('\n[כתבה מלאה מ-' + art + '. סכם את כולה בעברית]:\n' + '\n'.join(lines)[:5000])
            return '\n[לא נמצאה כתבה באתר]'
        # 3. site headlines
        for name, url in SITE_MAP.items():
            if name in prompt:
                d = oracle_text(url)
                use = clean_lines(d.get('lines', []))[:12]
                if use:
                    return ('\n[מידע חי מ-' + url + '. חובה לענות לפיו. השורה הראשונה היא הכתבה הראשונה. '
                            'אסור לומר שאין גישה עדכנית]:\n' + '\n'.join(f'{i+1}. {h}' for i, h in enumerate(use)))
                return '\n[הגלישה לא החזירה כותרות]'
        # 4. deep research: cloud search (residential IP) + Wikipedia
        if any(w in prompt for w in ['חפש', 'מחקר', 'תחקור', 'בדוק באינטרנט', 'מה קורה', 'עדכני', 'מעמיק', 'תחקיר']):
            q = prompt
            for w in ['חפש', 'מחקר', 'מעמיק', 'תחקור', 'תחקיר', 'בדוק באינטרנט', 'בבקשה', 'לי', 'את', 'על', 'תעשה']:
                q = q.replace(w, ' ').strip(' :')
            txt = ''
            try:
                r = requests.get(f'{ORACLE_URL}/cloudsearch', params={'key': BROWSE_KEY, 'q': q[:150]}, timeout=120)
                res = [f"{x['t']} ({x['u']})" for x in r.json().get('results', [])[:8]]
                if res:
                    txt += 'תוצאות חיפוש חיות:\n' + '\n'.join(res) + '\n\n'
            except Exception:
                pass
            try:
                r = requests.get(f'{ORACLE_URL}/research', params={'key': BROWSE_KEY, 'q': q[:150]}, timeout=90)
                j = r.json()
                if j.get('sources', 0) > 0:
                    txt += 'מקורות רקע:\n' + j['text'][:4000]
            except Exception:
                pass
            if txt:
                return ('\n[מחקר מעמיק ממקורות חיים. תן תשובה מסודרת ומפורטת בעברית: רקע, נקודות עיקריות, וסיכום. '
                        'אסור לומר שאין מידע]:\n' + txt[:6000])
            return '\n[המחקר לא החזיר מקורות]'
        # 5. song/podcast download -> MEDIAQ command for bridge (Oracle resolves: rss/mp3/youtube)
        if any(w in prompt for w in ['שיר', 'מוזיקה', 'פודקאס', 'פודקסט', 'שיעור', 'הרצאה', 'סרטון', 'mp3']) and any(w in prompt for w in ['הורד', 'תוריד', 'תורי', 'יוריד', 'מוריד', 'להוריד', 'להשמיע', 'תשמיע', 'שים', 'תשים', 'נגן', 'תנגן', 'שלח', 'תשלח', 'השמע', 'העלה', 'תעלה']):
            try:
                qmsgs = [{'role': 'system', 'content': 'Extract a short web search query (2-6 words) for the requested song/podcast/lecture. Fix obvious speech-to-text errors. Reply with ONLY the query, nothing else.'},
                         {'role': 'user', 'content': prompt}]
                clean_q, _ = smart_chat(qmsgs)
                clean_q = clean_q.strip().strip('"')[:120]
            except Exception:
                clean_q = prompt[:120]
            return 'MEDIAQ:' + clean_q
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
    msgs = [{'role': 'system', 'content': 'אתה עוזר קולי בעברית. תשובות קצרות וברורות. אם מצורפות כותרות חיות מהדפדפן, ענה תמיד לפיהן ולא מהזיכרון. יש לך גישה לאינטרנט דרך המערכת - לעולם אל תאמר שאין לך גישה לאינטרנט.'},
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
    if extra.startswith('MEDIA:') or extra.startswith('MEDIAQ:') or extra.startswith('AGENT:'):
        return jsonify({'reply': extra})
    msgs = [{'role': 'system', 'content': 'אתה עוזר קולי בעברית. תשובות קצרות. יש לך גישה לאינטרנט דרך המערכת - לעולם אל תאמר שאין לך גישה לאינטרנט.'},
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
