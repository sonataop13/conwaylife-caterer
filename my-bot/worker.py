import discord
import asyncio
import re
import requests
from html import unescape
from collections import namedtuple

rbold = re.compile(r"'''")
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
rfinal = re.compile(r"^.*?\S(?=(?:\*\*)?[A-Z])|[\[{}\]]")

rtitle = re.compile(r'"title":"(.+?)",')
rgif = re.compile(r"File[^F]+?\.gif")
rimage = re.compile(r"File[^F]+?\.png")
rfileurl = re.compile(r'"url":"(.+?)"')

rdisamb = re.compile(r"(?<=\*\*).+(?=\*\*)")

numbers_ft = [':one:', ':two:', ':three:', ':four:', ':five:', ':six:', ':seven:', ':eight:', ':nine:']
numbers_fu = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
#numbers_rt = {':one:': 1, ':two:': 2, ':three:': 3, ':four:': 4, ':five:': 5, ':six:': 6, ':seven:': 7, ':eight:': 8, ':nine:': 9}
numbers_ru = {'1️⃣': 1, '2️⃣': 2, '3️⃣': 3, '4️⃣': 4, '5️⃣': 5, '6️⃣': 6, '7️⃣': 7, '8️⃣': 8, '9️⃣': 9}

links = []

def regex(txt):
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
    if txt[fixbold+2] == ' ' or txt[fixbold+2] == ',':
        txt = '**' + txt
    return txt

def disambigregex(txt):
    txt = rformatting.sub('', txt)
    txt = rrefs.sub('', txt)
    txt = txt.replace('* ', '')
    txt = rlinksb.sub(lambda m: '**' + (m.group(3) if m.group(3) else m.group(1)) + '**', txt)
    txt = rlinks.sub(lambda m: m.group(3) if m.group(3) else m.group(1), txt)
    txt = rfinal.sub('', txt)
    links = rdisamb.findall(txt)
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
    desc = unescape(regex(data))

    em.title = pgtitle
    em.url = "http://conwaylife.com/wiki/" + pgtitle.replace(" ", "_")
    em.description = desc
    em.color = 0x680000

def disambig(data):
    pgtitle = rtitle.search(data).group(1)
    desc = disambigregex(data)
    return discord.Embed(title=pgtitle, url='http://conwaylife.com/wiki/' + pgtitle.replace(' ', '_'), description=desc, color=0x680000)

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
        with requests.Session() as rqst:
            data = rqst.get("http://conwaylife.com/w/api.php?action=query&prop=revisions&rvprop=content&format=json&titles=" + query).text
            
            if '#REDIRECT' in data:
                em.set_footer(text='(redirected from "' + query + '")')
                query = rredirect.search(data).group(1)
                data = rqst.get("http://conwaylife.com/w/api.php?action=query&prop=revisions&rvprop=content&format=json&titles=" + query).text
                
            if '"-1":{' in data:
                await client.send_message(message.channel, 'Page `' + query + '` does not exist.')
            else:
                print("(disambiguation)" in data)
                if "(disambiguation)" in data:
                    edit = True
                    emb = disambig(data)
                    msg = await client.send_message(message.channel, embed=emb)
                    for i in range(len(links)):
                        add_reaction(msg, numbers_ft[i])
                    react = await client.wait_for_reaction(numbers_fu, message=msg)
                    query = links[numbers_ru[react.reaction.emoji]]
                    data = rqst.get("http://conwaylife.com/w/api.php?action=query&prop=revisions&rvprop=content&format=json&titles=" + query).text
                
                regpage(data, query, rqst, em)            
                eval('await client.' + ('edit_message(msg' if edit else 'send_message(message.channel') + ', embed=em)')


client.run('MzU5MDY3NjM4MjE2Nzg1OTIw.DKBnUw.MJm4R_Zz6hCI3TPLT05wsdn6Mgs')
