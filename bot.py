import discord, time, urllib.request, random, logging, sys, string
import settings
from pyquery import PyQuery as pq
from io import BytesIO
from pyurbandict import UrbanDict
from flask import Flask, render_template_string, request, redirect, url_for, flash
import threading
import asyncio

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.presences = True
intents.message_content = True

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

client = discord.Client(intents=intents)

# Flask app
app = Flask(__name__)
app.secret_key = settings.FLASK_SECRET_KEY

cache = {}
last_spam = 0

# Queue for messages to be sent to Discord (will be created in Discord event loop)
message_queue = None

def l2u(s):
    if type(s) == str:
        #return str(bytes(s, 'latin1'), 'utf-8')
        return s
    if type(s) == bytes:
        return str(s, 'utf-8')
    if s: # if s has value, complain
        logger.warning(f"can't handle {s} of type {type(s)}")
    return '' # but don't make a mess

def valid_channel(name):
    for c in settings.VALID_CHANNELS:
        if c in name:
            return True
    return False

def cached(what, url=None, binurl=None, duration=600):
    global cache
    cached_data = cache.get(f'{what}_data')
    cache_age = cache.get(f'{what}_age', 0)
    
    if (cached_data is None and (cache_age == 0 or cache_age + 30 < time.time())) or \
        (cached_data is not None and cache_age + duration < time.time()):
        logger.info(f'{what} cache miss')
        
        for attempt in range(settings.REQUEST_RETRIES):
            try:
                if url:
                    r = urllib.request.urlopen(url)
                    s = r.read()
                    t = s.decode('utf-8')
                    newdata = pq(t)
                elif binurl:
                    newdata = BytesIO(urllib.request.urlopen(binurl).read())
                else:
                    raise ValueError("pass url or binurl")
                cache[f'{what}_data'] = newdata
                cache[f'{what}_age'] = time.time()
                return newdata
            except Exception as e:
                if attempt < settings.REQUEST_RETRIES - 1:
                    logger.warning(f'fetching {url} {binurl} attempt {attempt + 1}/{settings.REQUEST_RETRIES} failed: {e}')
                    time.sleep(1)
                else:
                    logger.exception(f'fetching {url} {binurl} - all {settings.REQUEST_RETRIES} attempts failed')
        
        # All retries failed, set cache data to None and update age to avoid immediate retry
        cache[f'{what}_data'] = None
        cache[f'{what}_age'] = time.time()
        return None
    else:
        logger.info(f'{what} cache hit')
        val = cached_data
        if type(val) == BytesIO:
            val.seek(0)
        return val

def getvreme(what='long'): # or long or full
    napoved = cached('napoved',
        'https://meteo.arso.gov.si/uploads/probase/www/fproduct/text/sl/fcast_si_text.html')
    podatki = cached('podatki',
        'https://meteo.arso.gov.si/uploads/probase/www/observ/surface/text/sl/observation_si_latest.html')
    text_podatki = '\n'
    for location in settings.LOCATIONS:
        line = podatki('td').filter(lambda i, this: location == l2u(pq(this).text()))
        vreme_text = l2u(line.next().next()[0].text)
        if not vreme_text: vreme_text = 'neznano'
        stopinje_text = l2u(line.next().next().next()[0].text)
        if not stopinje_text: stopinje_text = '??'
        text_podatki += location.split()[-1] + ', ' + vreme_text + ', ' + stopinje_text + '°C\n'
    text_vreme = ''
    if what == 'long':
        p = napoved("h2").next().next().next()
        while True:
            el = p[0]
            if el.tag != 'p':
                break
            text_vreme += '\n' + l2u(el.text)
            p = p.next()
    elif what == 'full':
        text_vreme = ''
        p = napoved("h2:first")
        while True:
            el = p[0]
            if el.tag not in ('h2', 'p'):
                break
            text_vreme += '\n' + l2u(el.text)
            p = p.next()
    elif what == 'short':
        text_vreme = l2u(napoved("p:first")[0].text)
    else:
        return 'ne vem kaj je to ' + what + ', lahko je short, long, full'
    return text_podatki + text_vreme

def getdefinition(what, how_many):
    word = UrbanDict(what)
    results = word.search()
    return results[:how_many]

async def process_message_queue():
    """Background task to process messages from the queue and send them to Discord"""
    while True:
        try:
            # Wait for a message in the queue (async, non-blocking)
            message = await asyncio.wait_for(message_queue.get(), timeout=1.0)
            
            guild = client.get_guild(settings.DISCORD_SERVER_ID)
            if guild:
                channel = guild.get_channel(settings.DISCORD_CHANNEL_ID)
                if channel:
                    await channel.send(f"**Anonimno sporočilo:**\n```{message}```")
                    logger.info("Anonymous message sent to Discord")
                else:
                    logger.error("Discord channel not found")
            else:
                logger.error("Discord server not found")
                
            message_queue.task_done()
        except asyncio.TimeoutError:
            # No message in queue, continue waiting
            continue
        except Exception as e:
            logger.exception("Error processing message queue")
            await asyncio.sleep(1)  # Wait a bit before retrying

# HTML template for the form
FORM_TEMPLATE = '''
<!DOCTYPE html>
<html lang="sl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Anonimno sporočilo</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 600px;
            margin: 50px auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background-color: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
            color: #555;
        }
        textarea {
            width: 100%;
            height: 200px;
            padding: 10px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
            resize: vertical;
            box-sizing: border-box;
        }
        textarea:focus {
            outline: none;
            border-color: #4CAF50;
        }
        .char-counter {
            text-align: right;
            margin-top: 5px;
            font-size: 12px;
            color: #666;
        }
        .char-counter.warning {
            color: #ff9800;
        }
        .char-counter.error {
            color: #f44336;
        }
        .submit-btn {
            background-color: #4CAF50;
            color: white;
            padding: 12px 30px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
            width: 100%;
            margin-top: 10px;
        }
        .submit-btn:hover {
            background-color: #45a049;
        }
        .submit-btn:disabled {
            background-color: #cccccc;
            cursor: not-allowed;
        }
        .success-message {
            background-color: #d4edda;
            color: #155724;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            border: 1px solid #c3e6cb;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Anonimno sporočilo</h1>
        
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                <div class="success-message">
                    {{ messages[0] }}
                </div>
            {% endif %}
        {% endwith %}
        
        <form method="POST" action="/">
            <div class="form-group">
                <label for="message">Vaše sporočilo:</label>
                <textarea id="message" name="message" maxlength="1900" placeholder="Vnesite vaše anonimno sporočilo..." required>{{ request.form.message if request.form.message else '' }}</textarea>
                <div id="char-counter" class="char-counter">0 / 1900 znakov</div>
            </div>
            <button type="submit" class="submit-btn" id="submit-btn">Pošlji anonimno sporočilo</button>
        </form>
    </div>

    <script>
        const textarea = document.getElementById('message');
        const counter = document.getElementById('char-counter');
        const submitBtn = document.getElementById('submit-btn');
        
        function updateCounter() {
            const length = textarea.value.length;
            const remaining = 1900 - length;
            
            counter.textContent = length + ' / 1900 znakov';
            
            if (remaining < 100) {
                counter.className = 'char-counter warning';
                if (remaining < 0) {
                    counter.className = 'char-counter error';
                    submitBtn.disabled = true;
                } else {
                    submitBtn.disabled = false;
                }
            } else {
                counter.className = 'char-counter';
                submitBtn.disabled = false;
            }
        }
        
        textarea.addEventListener('input', updateCounter);
        updateCounter(); // Initial call
    </script>
</body>
</html>
'''

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        message = request.form.get('message', '').strip()
        
        if not message:
            flash('Prosimo vnesite sporočilo.')
            return redirect(url_for('index'))
        
        if len(message) > 1900:
            flash('Sporočilo je predolgo. Maksimalno 1900 znakov.')
            return redirect(url_for('index'))
        
        # Queue message for Discord
        try:
            # Schedule the put operation on the Discord event loop
            if message_queue is not None and client.loop is not None:
                client.loop.call_soon_threadsafe(message_queue.put_nowait, message)
                flash('Sporočilo je bilo uspešno poslano!')
            else:
                flash('Napaka: Discord bot ni pripravljen. Prosimo poskusite kasneje.')
        except Exception as e:
            logger.exception("Error queuing anonymous message")
            flash('Napaka pri pošiljanju sporočila. Prosimo poskusite kasneje.')
        
        return redirect(url_for('index'))
    
    return render_template_string(FORM_TEMPLATE)

@client.event
async def on_ready():
    global message_queue
    logger.info(f'We have logged in as {client.user}')
    
    # Create the queue in the Discord event loop
    message_queue = asyncio.Queue()
    
    # Start background task to process message queue
    client.loop.create_task(process_message_queue())

@client.event
async def on_message(message):
    global last_spam

    if message.author == client.user: # don't ever reply to yourself
        return

    if 'spam' in message.content.lower() and valid_channel(message.channel.name):
        if time.time() - last_spam > settings.SPAM_LIMIT:
            last_spam = time.time()
            await message.channel.send(
                    file=discord.File(BytesIO(open('spam.mp4', 'rb').read()),
                    filename=f'''{"".join([random.choice(string.ascii_lowercase + string.digits)
                                      for x in range(32)])}.mp4'''))

    if (message.content.lower().startswith('vreme')
            and len(message.content.split()) < 3
            and valid_channel(message.channel.name)):
        try:
            what = message.content.split()[1]
        except IndexError:
            what = 'long'
        try:
            vreme = getvreme(what)
            if len(vreme) < settings.MAX_MSG_LEN:
                await message.channel.send('```' + vreme + '```')
            else:
                bodysofar = ''
                for chunk in vreme.split('\n\n'):
                    if len(bodysofar) + len(chunk) > settings.MAX_MSG_LEN:
                        await message.channel.send('```' + bodysofar + '```')
                        bodysofar = ''
                    bodysofar += chunk + '\n\n'
                if bodysofar:
                    await message.channel.send('```' + bodysofar + '```')
        except Exception as e:
            logger.exception("vreme")
            await message.channel.send('```' + str(e) + '```')

    if (message.content.lower().startswith('!definicija')
            and valid_channel(message.channel.name)):
        what = message.content.split(maxsplit=1)[1]
        how_many = 1
        if what.split()[-1].isdigit():
            what, how_many = what.rsplit(maxsplit=1)
        try:
            results = getdefinition(what, int(how_many))
            for result in results:
                await message.channel.send(f'```Beseda: {result.word}\nDefinicija: {result.definition}\nPrimer: {result.example}\nAvtor: {result.author}\nŠtevilo :thumbs_up:: {result.thumbs_up}\nŠtevilo :thumbs_down::{result.thumbs_down}\nVpisano ob: {result.written_on}```')
            if not results:
                await message.channel.send(f'```{what} ne najdem na urbandictionary.```')
        except Exception as e:
            logger.exception("definicija")
            await message.channel.send('```' + str(e) + '```')

    if (message.content.lower().startswith('radar')
            and valid_channel(message.channel.name)):
        try:
            what = message.content.split()[1]
        except IndexError:
            what = 'si'
        try:
            if what == 'si':
                radar_gif = cached('radar-si',
                    binurl='https://meteo.arso.gov.si/uploads/probase/www/observ/radar/si0-rm-anim.gif')
            elif what == 'hr' or what == 'ba':
                radar_gif = cached('radar-hr',
                    binurl='https://vrijeme.hr/anim_kompozit.gif')
            elif what == 'at':
                radar_gif = cached('radar-at',
                    binurl='https://www.austrocontrol.at/jart/met/radar/loop.gif')
            else:
                await message.channel.send('```ne vem kaj je to ' + what + ', lahko je si, hr, ba, at```')
                return
            if radar_gif is None:
                await message.channel.send('```Napaka pri nalaganju radarskega posnetka. Prosim poskusite čez minuto.```')
                return
            await message.channel.send(file=discord.File(radar_gif, filename='radar.gif'))
        except Exception as e:
            logger.exception("radar")
            await message.channel.send('```' + str(e) + '```')

def run_flask():
    app.run(host=settings.FLASK_HOST, port=settings.FLASK_PORT, debug=settings.FLASK_DEBUG)

def run_discord():
    client.run(settings.TOKEN)

if __name__ == '__main__':
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start Discord bot in main thread
    run_discord()
