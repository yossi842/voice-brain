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

def maybe_browse(prompt):
    if any(k in prompt for k in ['גלוש', 'browse:', 'חפש באינטרנט', 'fetch:']):
        url = prompt.split('http', 1)
        if len(url) == 2:
            full = 'http' + url[1].split()[0]
            try:
                r = requests.get(f'{ORACLE_URL}/fetch', params={'key': BROWSE_KEY, 'url': full}, timeout=45)
                if r.ok:
                    html = r.json().get('html', '')[:4000]
                    return f'\n[תוכן מהדפדפן Oracle]:\n{html}'
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
    msgs = [{'role': 'system', 'content': 'אתה עוזר קולי בעברית. תשובות קצרות וברורות.'},
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
