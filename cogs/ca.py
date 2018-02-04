import asyncio
import concurrent
import math
import os
import random
import re
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import discord
import imageio
import png
from discord.ext import commands
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

from cogs.resources import utils

# matches LtL rulestring
rLtL = re.compile(r'R\d{1,3},C\d{1,3},M[01],S\d+\.\.\d+,B\d+\.\.\d+,N[NM]', re.I)

# matches B/S and if no B then either 2-state single-slash rulestring or generations rulestring
rrulestring = re.compile(r'(B)?[0-8cekainyqjrtwz-]+(?(1)/?(S)?[0-8cekainyqjrtwz\-]*|/(S)?[0-8cekainyqjrtwz\-]*(?(2)|(?(3)|/[\d]{1,3})?))', re.I)

# matches multiline XRLE; currently cannot, however, match headerless patterns (my attempts thus far have forced re to take much too many steps)
rxrle = re.compile(r'x ?= ?\d+, ?y ?= ?\d+(?:, ?rule ?= ?([^ \n]+))?\n([\dob$]*[ob$][\dob$\n]*!?)')

# splits RLE into its runs
rruns = re.compile(r'([0-9]*)([ob])')
# [rruns.sub(lambda m:''.join(['0' if m.group(2) == 'b' else '1' for x in range(int(m.group(1)) if m.group(1) else 1)]), pattern) for pattern in patlist[i]]

# unrolls $ signs
rdollarsigns = re.compile(r'(\d+)\$')

# determines 80% of available RAM to allow bgolly to use
maxmem = int(os.popen('free -m').read().split()[7]) // 1.25

# ---- #

def parse(current):
    with open(f'{current}_out.rle', 'r') as pat:
        patlist = [line.rstrip('\n') for line in pat]

    os.remove(f'{current}_out.rle')
    # `positions` needs to be a list, not a generator
    # because it's returned from this function, so
    # it gets pickled by run_in_executor -- and
    # generators can't be pickled
    positions = [eval(i) for i in patlist[::3]]
    bboxes = (eval(i) for i in patlist[1::3])
    
    # Determine the bounding box to make gifs from
    # The rectangle: xmin <= x <= xmax, ymin <= y <= ymax
    # where (x|y)(min|max) is the min/max coordinate across all gens.
    xmins, ymins = zip(*positions)
    widths, heights = zip(*bboxes)
    xmaxs = (xm+w for xm, w in zip(xmins, widths))
    ymaxs = (ym+h for ym, h in zip(ymins, heights))
    xmin, ymin, xmax, ymax = min(xmins), min(ymins), max(xmaxs), max(ymaxs)
    # Bounding box: top-left x and y, width and height
    bbox = xmin, ymin, xmax-xmin, ymax-ymin
    
    patlist = patlist[2::3] # just RLE
    # ['4b3$o', '3o2b'] -> ['4b$$$o', '3o2b']
    patlist = (rdollarsigns.sub(lambda m: ''.join(['$' for i in range(int(m.group(1)))]), j).replace('!', '') for j in patlist) # unroll newlines
    # ['4b$$$o', '3o2b'] -> [['4b', '', '', '', 'o'], ['3o', '2b']]
    patlist = [i.split('$') for i in patlist]
    return patlist, positions, bbox

def makeframes(current, patlist, positions, bbox, pad):
    
    assert len(patlist) == len(positions), (patlist, positions)
    xmin, ymin, width, height = bbox
    
    # Used in doubling the frame size
    def scale_list(li, mult):
        """(li=[a, b, c], mult=2) => [a, a, b, b, c, c]
        Changes in one copy(ex. c) will affect the other (c)."""
        return [i for i in li for _ in range(mult)]
    
    for index in range(len(patlist)):
        pat = patlist[index]
        xpos, ypos = positions[index]
        dx, dy = (xpos - xmin) + 1, (ypos - ymin) + 1 #+1 for one-cell padding
        
        # Create a blank frame of off cells
        # Colors: on=0, off=1
        frame = [[1] * (width+2) for _ in range(height+2)] #+2 for one-cell padding
        
        # unroll RLE and convert to list of ints, 1=off and 0=on
        int_pattern = []
        for row in pat:
            int_row = []
            for runs, chars in rruns.findall(row):
                runs = int(runs) if runs else 1
                state = 1 if chars == 'b' else 0
                int_row.extend([state] * runs)
            int_pattern.append(int_row)
        
        # Draw the pattern onto the frame
        for i, int_row in enumerate(int_pattern):
            # replace this row of frame with int_row
            frame[dy+i][dx:dx+len(int_row)] = int_row
        
        anchor = min(height, width)
        mult = -(-75 // anchor) if anchor <= 75 else 1
        frame = scale_list([scale_list(row, mult) for row in frame], mult)
        
        with open(f'{current}_frames/{index:0{pad}}.png', 'wb') as out:
            w = png.Writer(len(frame[0]), len(frame), greyscale=True, bitdepth=1)
            w.write(out, frame)    

def savegif(current, gen, step):
    # finally, pass all created pics to imageio for conversion to gif
    # then either upload to gfycat or send directly to discord depending on presence of "g" flag
    png_dir = f'{current}_frames/'
    duration = min(1/6, max(1/60, 5/gen/step) if gen else 1)
    for subdir, dirs, files in os.walk(png_dir):
        files.sort()
        with imageio.get_writer(f'{current}.gif', mode='I', duration=str(duration)) as writer:
            for file in files:
                file_path = os.path.join(subdir, file)
                writer.append_data(imageio.imread(file_path))

class CA:
    def __init__(self, bot):
        self.bot = bot
        self.dir = os.path.dirname(os.path.abspath(__file__))
        self.ppe = ProcessPoolExecutor()
        self.tpe = ThreadPoolExecutor() # or just None
        self.loop = bot.loop
        
        self.defaults = *[[self.ppe, 'ProcessPoolExecutor']]*2, [self.tpe, 'ThreadPoolExecutor']
        self.opts = {'tpe': [self.tpe, 'ThreadPoolExecutor'], 'ppe': [self.ppe, 'ProcessPoolExecutor']}
    
    @staticmethod
    def genconvert(gen: int):
        if int(gen) > 0:
            return int(gen) - 1
        raise Exception # bad step (less than or equal to zero)

    @staticmethod
    def parse_args(args: [str], regex: [re.compile], defaults: []) -> ([str], [str]):
        """
        Sorts `args` according to order in `regexes`.
        
        If no matches for a given regex are found in `args`, the item
        in `defaults` with the same index is dropped in to replace it.
        
        Extraneous arguments in `args` are left untouched, and the
        second item in this func's return tuple will consist of these
        extraneous args, if there are any.
        """
        assert len(regex) == len(defaults)
        args = list(args)
        new, regex = [], [i if isinstance(i, (list, tuple)) else [i] for i in regex]
        for ri, rgx in enumerate(regex): 
            for ai, arg in enumerate(args):
                if any(k.match(arg) for k in rgx):
                    new.append(arg)
                    args.pop(ai)
                    break
            else: 
                 new.append(defaults[ri])
        return new, args
    
    @staticmethod
    def parse_flags(flags: [str]) -> {str: str}:
        new = {}
        for i, v in enumerate(flags):
            flag, opts = (v+':'[':' in v:]).split(':', 1)
            new[flag.lstrip('-')] = opts
        return new
    
    @staticmethod
    def makesoup(rulestring: str, x: int, y: int) -> str:
        """generates random soup as RLE with specified dimensions"""

        rle = f'x = {x}, y = {y}, rule = {rulestring}\n' # not really needed but it looks prettier :shrug:
                                                         # also prevents the length stuff below from erroring
        for row in range(y):
            pos = x
            while pos > 0:
                # below could also just be random.randint(1,x) but something likes this gives natural-ish-looking results
                runlength = math.ceil(-math.log(1-random.random()))
                if runlength > pos:
                    runlength = pos # or just `break`, no big difference qualitatively
                # switches o/b from last occurrence of the letter
                rle += (str(runlength) if runlength > 1 else '') + 'ob'['o' in rle[-3 if rle[-1] == '\n' else -1]]
                pos -= runlength
            rle += '$\n' if y > row + 1 else '!\n'
        return rle
    
    def cancellation_check(self, ctx, msg):
        if msg.channel != ctx.channel or msg.author != ctx.message.author:
            return False
        if any(msg.content.startswith(i) for i in self.bot.command_prefix(self.bot, ctx.message)):
            return msg.content.lower().endswith('cancel') and len(msg.content) < 10 # good enough

    async def do_gif(self, execs, current, gen, step):
        start = time.perf_counter()
        patlist, positions, bbox = await self.loop.run_in_executor(execs[0][0], parse, current)
        end_parse = time.perf_counter()
        await self.loop.run_in_executor(execs[1][0], makeframes, current, patlist, positions, bbox, len(str(gen)))
        end_makeframes = time.perf_counter()
        await self.loop.run_in_executor(execs[2][0], savegif, current, gen, step)
        end_savegif = time.perf_counter()
        return start, end_parse, end_makeframes, end_savegif
    
    async def run_bgolly(self, current, algo, gen, step, rule):
        # run bgolly with parameters
        preface = f'{self.dir}/resources/bgolly'
        return os.popen(f'{preface} -a "{algo}" -m {gen} -i {step} -r {rule} -o {current}_out.rle {current}_in.rle').read()
    
    def moreinfo(self, ctx):
        return f"'{ctx.prefix}help sim' for more info"
    
    @utils.group(name='sim', invoke_without_command=True)
    async def sim(self, ctx, *args, **kwargs):
        """
        # Simulates PAT with output to animated gif. #
        <[FLAGS]>
        -h: Use HashLife instead of the default QuickLife.
        -time: Include time taken to create gif (in seconds w/hundredths) alongside GIF.
          all: Provide verbose output, showing time taken for each step alongside the type of executor used.
        -tag: When finished, tag requester. Useful for time-intensive simulations.
        -id: Has no function besides appearing above the final output, but can be used to tell apart simultaneously-created gifs.
        
        <[ARGS]>
        GEN: Generation to simulate up to.
        STEP: Step size. Affects simulation speed. If omitted, defaults to 1.
        RULE: Rulestring to simulate PAT under. If omitted, defaults to B3/S23 or rule specified in PAT.
        PAT: One-line rle or .lif file to simulate. If omitted, uses last-sent Golly-compatible pattern (which should be enclosed in a code block and therefore can be a multiliner).
        #TODO: streamline GIF generation process, implement proper LZW compression, implement flags & gfycat upload
        """
        _ = re.compile(r'^\d+$')
        rand = kwargs.pop('randpat', None)
        dims = kwargs.pop('soup_dims', None)
        (gen, step, rule, pat), flags = self.parse_args(
          args,
          [_, _, (rrulestring, rLtL), re.compile(r'[\dob$]*[ob$][\dob$\n]*!?')],
          ['', '1', '', '']
          )
        flags = self.parse_flags(flags)
        if 'execs' in flags:
            flags['execs'] = flags['execs'].split(',')
            execs = [self.opts.get(v, self.defaults[i]) for i, v in enumerate(flags['execs'])]
        else:
            execs = self.defaults
        algo = 'HashLife' if 'h' in flags else 'QuickLife'
        try:
            step, gen = sorted([int(step), int(gen)])
        except ValueError:
            return await ctx.send(f"`Error: No GEN given. {self.moreinfo(ctx)}`")
        if gen / step > 2500:
            return await ctx.send(f"`Error: Cannot simulate more than 2500 frames. {self.moreinfo(ctx)}`")
        if rand:
            pat = rand
        if not pat:
            async for msg in ctx.channel.history(limit=50):
                rmatch = rxrle.search(msg.content)
                if rmatch:
                    pat = rmatch.group(2)
                    if rmatch.group(1):
                        rule = rmatch.group(1)
                    break
            if not pat:
                return await ctx.send(f"`Error: No PAT given and none found in last 50 messages. {self.moreinfo(ctx)}`")
        else:
            pat = pat.strip('`')
        
        if not rule:
            async for msg in ctx.channel.history(limit=50):
                rmatch = rLtL.search(msg.content) or rrulestring.search(msg.content)
                if rmatch:
                    rule = rmatch.group()
                    break
            else:
                rule = ''
        
        current = f'{self.dir}/{ctx.message.id}'
        os.mkdir(f'{current}_frames')
        rule = ''.join(rule.split()) or 'B3/S23'
        algo = 'Larger than Life' if rLtL.match(rule) else algo
        details = (
          (f'Running `{dims}` soup' if rand else f'Running supplied pattern')
          + f' in rule `{rule}` with step `{step}` for `{gen+bool(rand)}` generation(s)'
          + (f' using `{algo}`.' if algo != 'QuickLife' else '.')
          )
        announcement = await ctx.send(details)
        with open(f'{current}_in.rle', 'w') as infile:
            infile.write(pat)
        bg_err = await self.run_bgolly(current, algo, gen, step, rule)
        if bg_err:
            return await ctx.send(f'`{bg_err}`')
        resp = await utils.await_event_or_coro(
                  self.bot,
                  event = 'message',
                  coro = self.do_gif(execs, current, gen, step),
                  ret_check = lambda obj: isinstance(obj, discord.Message),
                  event_check = lambda msg: self.cancellation_check(ctx, msg)
                  )
        try:
            start, end_parse, end_makeframes, end_savegif = resp['coro']
        except KeyError:
            return await resp['event'].add_reaction('👍')
        content = (
            (ctx.message.author.mention if 'tag' in flags else '')
          + (f' **{flags["id"]}** \n' if 'id' in flags else '')
          + '{time}'
          )
        try:
            gif = await ctx.send(
              content.format(
                time = str(
                  {
                    'Times': '',
                    '**Parsing frames**': f'{round(end_parse-start, 2)}s ({execs[0][1]})',
                    '**Saving frames**': f'{round(end_makeframes-end_parse, 2)}s ({execs[1][1]})',
                    '**Stitching frames to GIF**': f'{round(end_savegif-end_makeframes, 2)}s ({execs[2][1]})'
                  }
                ).replace("'", '').replace(',', '\n').replace('{', '\n').replace('}', '\n')
                if flags.get('time') == 'all'
                  else f'{round(end_savegif-start, 2)}s'
                  if 'time' in flags
                    else ''
                ),
              file=discord.File(f'{current}.gif')
              )
        except discord.errors.HTTPException as e:
            return await ctx.send(f'{ctx.message.author.mention}\n`HTTP 413: GIF too large. Try a higher STEP or lower GEN!`')
        try:
            while True:
                await gif.add_reaction('➕')
                rxn = await self.bot.wait_for('reaction_add', timeout=30.0, check=lambda rxn, usr: rxn.emoji == '➕' and rxn.message.id == gif.id and usr is ctx.message.author)
                await gif.delete()
                os.system(f'rm -r {current}_frames/'); os.mkdir(f'{current}_frames')
                gen += int(50*math.log1p(gen)) # gives a nice increasing-at-a-decreasing-rate curve
                details = (
                  (f'Running `{dims}` soup' if rand else f'Running supplied pattern')
                  + f' in rule `{rule}` with step `{step}` for `{gen+bool(rand)}` generation(s)'
                  + (f' using `{algo}`.' if algo != 'QuickLife' else '.')
                  )
                await announcement.edit(content=details)
                bg_err = await self.run_bgolly(current, algo, gen, step, rule)
                if bg_err:
                    return await ctx.send(f'`{bg_err}`')
                resp = await utils.await_event_or_coro(
                  self.bot,
                  event = 'message',
                  coro = self.do_gif(execs, current, gen, step),
                  ret_check = lambda obj: isinstance(obj, discord.Message),
                  event_check = lambda msg: self.cancellation_check(ctx, msg)
                  )
                try:
                    start, end_parse, end_makeframes, end_savegif = resp['coro']
                except KeyError:
                    return await resp['event'].add_reaction('👍')
                try:
                    gif = await ctx.send(
                      content.format(
                        str(
                          {
                            'Times': '',
                            '**Parsing frames**': f'{round(end_parse-start, 2)}s ({execs[0][1]})',
                            '**Saving frames**': f'{round(end_makeframes-end_parse, 2)}s ({execs[1][1]})',
                            '**Stitching frames to GIF**': f'{round(end_savegif-end_makeframes, 2)}s ({execs[2][1]})'
                          }
                        ).replace("'", '').replace(',', '\n').replace('{', '\n').replace('}', '\n')
                        if flags.get('time') == 'all'
                          else f'{round(end_savegif-start, 2)}s'
                          if 'time' in flags
                            else ''
                        ),
                      file=discord.File(f'{current}.gif')
                      )
                except discord.errors.HTTPException as e:
                    return await ctx.send(f'`HTTP 413: GIF too large. Try a higher STEP or lower GEN!`')
        except asyncio.TimeoutError:
            # will occur in the "forces-error" unpacking line above
            pass
        finally:
            await gif.clear_reactions()
            os.remove(f'{current}.gif')
            os.remove(f'{current}_in.rle')
            os.system(f'rm -r {current}_frames/')
        
    @sim.command(name='rand')
    async def rand(self, ctx, *args):
        """
        # Simulates a random soup in given rule with output to GIF. Dims default to 16x16. #
        <[FLAGS]>
        (None)
        {inherits}
        
        <[ARGS]>
        DIMS: "AxB" (sans quotes), where A and B are the desired soup's width and height separated by the literal character "x".
        {inherits}
        """
        # dims, rule, gen, step
        _ = re.compile(r'^\d+$')
        (dims, rule, *nums), flags = self.parse_args(
          args,
          [re.compile(r'^\d+x\d+$'), (rrulestring, rLtL), _, _],
          ['16x16', None, '300', None]
          )
        try:
            step, gen = sorted(int(i) for i in nums)
        except TypeError:
            try:
                step, gen = 1, list(filter(None, nums))[0]
            except IndexError:
                return await ctx.send(f'`Error: No GEN given. {self.moreinfo(ctx)}`')
        if not rule:
            async for msg in ctx.channel.history(limit=50):
                rmatch = rLtL.search(msg.content) or rrulestring.search(msg.content)
                if rmatch:
                    rule = rmatch.group()
                    break
        x, y = dims.split('x')
        await ctx.invoke(
          self.sim,
          str(self.genconvert(gen)),
          str(step),
          rule or 'B3/S23',
          *flags,
          randpat = self.makesoup(rule, int(x), int(y)),
          soup_dims = '×'.join(dims.split('x'))
          )
    
    @sim.error
    async def sim_error(self, ctx, error):
        # In case of missing GEN:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f'`Error: No {error.param.name.upper()} given. {self.moreinfo(ctx)}`')
        # Bad argument:
        elif isinstance(error, (commands.BadArgument, ZeroDivisionError)): # BadArgument on failure to convert to int, ZDE on gen=0
            badarg = str(error).split('"')[3].split('"')[0]
            await ctx.send(f'`Error: Invalid {badarg.upper()}. {self.moreinfo(ctx)}`')
        # Something went wrong in the command itself:
        elif isinstance(error, commands.CommandInvokeError):
            exc = traceback.format_exception(type(error), error, error.__traceback__)
            
            # extract relevant traceback only (not whatever led up to CommandInvokeError)
            end = '\nThe above exception was the direct cause of the following exception:\n\n'
            end = len(exc) - next(i for i, j in enumerate(reversed(exc), 1) if j == end)
            
            try:
                print('Ignoring exception in on_message', exc[0].split('"""')[1], *exc[1:end])
            except Exception as e:
                print(f'{e.__class__.__name__}: {e}\n--------\n')
                raise error
        else:
            raise error
        
        

def setup(bot):
    bot.add_cog(CA(bot))
