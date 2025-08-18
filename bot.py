import discord, time, urllib.request, random, logging, sys, string
import settings
from pyquery import PyQuery as pq
from io import BytesIO
from pyurbandict import UrbanDict

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.presences = True
intents.message_content = True

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

client = discord.Client(intents=intents)

cache = {}
last_spam = 0

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
    if not cache.get(f'{what}_data') or cache.get(f'{what}_age', 0) + duration < time.time():
        logger.info(f'{what} cache miss')
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
        except:
            logger.exception(f'fetching {url} {binurl}')
        cache[f'{what}_age'] = time.time()
        return newdata
    else:
        logger.info(f'{what} cache hit')
        val = cache.get(f'{what}_data')
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

@client.event
async def on_ready():
    logger.info(f'We have logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user: # don't ever reply to yourself
        return

    if 'spam' in message.content.lower() and valid_channel(message.channel.name):
        if time.time() - last_spam > settings.SPAM_LIMIT:
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
            await message.channel.send(file=discord.File(radar_gif, filename='radar.gif'))
        except Exception as e:
            logger.exception("radar")
            await message.channel.send('```' + str(e) + '```')

client.run(settings.TOKEN)
