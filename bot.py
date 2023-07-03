import discord, time, urllib.request, random, logging, sys
import settings
from pyquery import PyQuery as pq
from io import BytesIO

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.presences = True
intents.message_content = True

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

client = discord.Client(intents=intents)

cache = {}

def l2u(s):
    if type(s) == str:
        return str(bytes(s, 'latin1'), 'utf-8')
    if type(s) == bytes:
        return str(s, 'utf-8')

def valid_channel(name):
    for c in settings.VALID_CHANNELS:
        if c in name:
            return True
    return False

def cached(what, url=None, binurl=None, duration=600):
    global cache
    if not cache.get(f'{what}_data') or cache.get(f'{what}_age', 0) + duration < time.time():
        logger.info(f'{what} cache miss')
        try:
            if url:
                newdata = pq(str(urlopen(url).read(), 'utf-8'))
            elif binurl:
                newdata = BytesIO(urllib.request.urlopen(binurl).read())
            else:
                raise ValueError("pass url or binurl")
            cache[f'{what}_data'] = newdata
        except:
            logging.exception(f'fetching {url} {binurl}')
        cache[f'{what}_age'] = time.time()
    else:
        logger.info(f'{what} cache hit')
    val = cache.get(f'{what}_data')
    age = time.time() - cache.get(f'{what}_age')
    logger.info(f'{what} returned at age {age}, {len(val)} bytes')
    return val

def getvreme(what='long'): # or long or full
    napoved = cached('napoved', 'https://meteo.arso.gov.si/uploads/probase/www/fproduct/text/sl/fcast_si_text.html')
    podatki = cached('podatki', 'https://meteo.arso.gov.si/uploads/probase/www/observ/surface/text/sl/observation_si_latest.html')
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

@client.event
async def on_ready():
    logger.info(f'We have logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.lower().startswith('vreme') and len(message.content.split()) < 3 and valid_channel(message.channel.name):
        try:
            what = message.content.split()[1]
        except IndexError:
            what = 'long'
        try:
            await message.channel.send('```' + getvreme(what) + '```')
        except Exception as e:
            await message.channel.send('```' + str(e) + '```')

    if message.content.lower().startswith('radar') and valid_channel(message.channel.name):
        try:
            radar_gif = cached('radar', binurl='https://meteo.arso.gov.si/uploads/probase/www/observ/radar/si0-rm-anim.gif')
            await message.channel.send(file=discord.File(radar_gif, filename='radar.gif'))
        except Exception as e:
            await message.channel.send('```' + str(e) + '```')

client.run(settings.TOKEN)

