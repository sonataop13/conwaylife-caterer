import discord
import asyncio
import re
import requests
from html import unescape
from collections import namedtuple

rbold = re.compile(r"'''")
ritalics = re.compile(r"''.+?''(\\n).+?")
rparens = re.compile(r" \(.+?\)")
rrefs = re.compile(r"<ref>.*?</ref>")
rlinks = re.compile(r"\[\[(.*?)(\|)?(?(2)(.*?))\]\]")
rformatting = re.compile(r"{.+?}}")
rqualifiers = re.compile(r'"[a-zA-Z]*?":.*?".*?"')
rctrlchars = re.compile(r"\\.")
#rfirstheader = re.compile(r"=.*")
rfirstpbreak = re.compile(r"\\n\\n.*")
rredirect = re.compile(r"\[\[(.+?)\]\]")
#rtitle = re.compile(r'"title":.+?"')
rfinal = re.compile(r'^.*?\S(?=(?:\*\*)?[A-Z])|[\[{}\]"]')

rtitle = re.compile(r'"title":"(.+?)",')
rgif = re.compile(r"File[^F]+?\.gif")
rimage = re.compile(r"File[^F]+?\.png")
rfileurl = re.compile(r'"url":"(.+?)"')

rdisamb = re.compile(r"(?<=\*\*).+(?=\*\*)")
rlinksb = re.compile(r"^\[\[(.*?)(\|)?(?(2)(.*?))\]\]", re.M)

numbers_ft = [':one:', ':two:', ':three:', ':four:', ':five:', ':six:', ':seven:', ':eight:', ':nine:']
numbers_fu = [u'\u0031\u20E3', u'\u0032\u20E3', u'\u0033\u20E3', u'\u0034\u20E3', u'\u0035\u20E3', u'\u0036\u20E3', u'\u0037\u20E3', u'\u0038\u20E3', u'\u0039\u20E3']
#numbers_rt = {':one:': 1, ':two:': 2, ':three:': 3, ':four:': 4, ':five:': 5, ':six:': 6, ':seven:': 7, ':eight:': 8, ':nine:': 9}
numbers_ru = {u'\u0031\u20E3': 0, u'\u0032\u20E3': 1, u'\u0033\u20E3': 2, u'\u0034\u20E3': 3, u'\u0035\u20E3': 4, u'\u0036\u20E3': 5, u'\u0037\u20E3': 6, u'\u0038\u20E3': 7, u'\u0039\u20E3': 8}

links = []

def parse(txt):
    txt = ritalics.sub('', txt, 1)
    txt = rfirstpbreak.sub('', txt) # exchange with rfirstheader.sub() below for entire first section to be preserved
    txt = rformatting.sub('', txt)
    txt = rbold.sub('**', txt)
    txt = rparens.sub('', txt)
    txt = rrefs.sub('', txt)
    txt = rlinks.sub(lambda m: m.group(3) if m.group(3) else m.group(1), txt)
    txt = rctrlchars.sub('', txt)
    txt = rqualifiers.sub('', txt)
    txt = rfinal.sub('', txt + ']')
#   txt = rfirstheader.sub('', txt)

    fixbold = txt.find('**')
    try:
        if txt[fixbold+2] == ' ' or txt[fixbold+2] == ',':
            txt = '**' + txt
    except IndexError:
        pass
    return txt

def regpage(data, query, rqst, em):
    images = rqst.get("http://conwaylife.com/w/api.php?action=query&prop=images&format=json&titles=" + query).text
    pgimg = rgif.search(images)
    find = rimage.findall(images)
    pgimg = (pgimg.group(0) if pgimg else (min(find, key = len) if find else ''))
    images = rqst.get("http://conwaylife.com/w/api.php?action=query&prop=imageinfo&iiprop=url&format=json&titles=" + pgimg).text
    pgimg = rfileurl.search(images)
    if pgimg:
        pgimg = pgimg.group(1)
        em.set_thumbnail(url=pgimg)

    pgtitle = rtitle.search(data).group(1)
    desc = unescape(parse(data))

    em.title = pgtitle
    em.url = "http://conwaylife.com/wiki/" + pgtitle.replace(" ", "_")
    em.description = desc
    em.color = 0x680000

def parsedisambig(txt):
    txt = rformatting.sub('', txt)
    txt = rrefs.sub('', txt)
    txt = txt.replace('* ', '')
    txt = rlinksb.sub(lambda m: '**' + (m.group(3) if m.group(3) else m.group(1)) + '**', txt)
    txt = rlinks.sub(lambda m: m.group(3) if m.group(3) else m.group(1), txt)
    txt = rfinal.sub('', txt)
    links = rdisamb.findall(txt)
    return (txt, links)

def disambig(data):
    pgtitle = rtitle.search(data).group(1)
    desc_links = parsedisambig(data)
    return (discord.Embed(title=pgtitle, url='http://conwaylife.com/wiki/' + pgtitle.replace(' ', '_'), description=desc_links[0], color=0x680000), desc_links[1])

client = discord.Client()

@client.event
async def on_ready():
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)
    print('------')

@client.event
async def on_message(message):
    if message.content.startswith("!wiki"):
        em = discord.Embed()
        edit = False
        query = message.content[6:]
        if query == "methusynthesae" or query == "Methusynthesae":
            gus = "Methusynthesae (singular Methusynthesis) are patterns/methuselah that basically/mildly are spaceship reactions, though it is a bit hard to explain the relation. It is way different from syntheses because they are patterns, and don't form other patterns."
            em = discord.Embed(title="Methusynthesae", description=gus, color=0x680000, url='http://conwaylife.com/forums/viewtopic.php?f=2&t=1600')
            em.set_thumbnail(url='https://i.imgur.com/CQefDXF.png')
            await client.send_message(message.channel, embed=em)
        else:
            with requests.Session() as rqst:
                data = rqst.get("http://conwaylife.com/w/api.php?action=query&prop=revisions&rvprop=content&format=json&titles=" + query).text
                
                if '#REDIRECT' in data:
                    em.set_footer(text='(redirected from "' + query + '")')
                    query = rredirect.search(data).group(1)
                    data = rqst.get("http://conwaylife.com/w/api.php?action=query&prop=revisions&rvprop=content&format=json&titles=" + query).text
                    
                if '"-1":{' in data:
                    await client.send_message(message.channel, 'Page `' + query + '` does not exist.')
                else:
                    templates = {}

                    from mediawiki_parser.preprocessor import make_parser
                    preprocessor = make_parser(templates)

                    from mediawiki_parser.text import make_parser
                    parser = make_parser()

                    data = preprocessor.parse(source)
                    output = parser.parse(data.leaves())
                    await client.send_message(message.channel, output)
                    if "(disambiguation)" in data:
                        edit = True
                        data = data.replace(r'\n', '\n')
                        emb = disambig(data)
                        links = emb[1]
                        emb = emb[0]
                        msg = await client.send_message(message.channel, embed=emb)
                        for i in range(len(links)):
                            await client.add_reaction(msg, numbers_fu[i])
                        react = await client.wait_for_reaction(numbers_fu, message=msg, user=message.author)
                        query = links[numbers_fu.index(react.reaction.emoji)]
                        data = rqst.get("http://conwaylife.com/w/api.php?action=query&prop=revisions&rvprop=content&format=json&titles=" + query).text
                    
                    regpage(data, query, rqst, em)
                    if edit:
                        await client.edit_message(msg, embed=em)
                        await client.clear_reactions(msg)
                    else:
                        await client.send_message(message.channel, embed=em)


client.run('MzU5MDY3NjM4MjE2Nzg1OTIw.DKBnUw.MJm4R_Zz6hCI3TPLT05wsdn6Mgs')

