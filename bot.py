# SiftNodes Official Discord Bot | discord.py 2.x | Python 3.10+
# Set DISCORD_TOKEN in the environment. Enable Server Members, Message Content, and Presence intents as needed.
# Backups cover role/channel structure and selected metadata, not messages, members, or all server settings.
import os, re, json, sqlite3, asyncio, random, time
from pathlib import Path
from datetime import timedelta, datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands, tasks

TOKEN = os.getenv('DISCORD_TOKEN', '').strip()
DB_FILE = os.getenv('SIFTNODES_DB', 'siftnodes.sqlite3')
BACKUP_DIR = Path(os.getenv('SIFTNODES_BACKUP_DIR', 'backups')); BACKUP_DIR.mkdir(exist_ok=True)
TWITCH = 'https://www.twitch.tv/siftnodes'
YT_LINKS = ['https://youtube.com/@notryxyt95?si=ZiC-g35hjwWE1FN8', 'https://youtube.com/@ryxenextra?si=_bEYn-MKUzHfuWWn']
STATUSES = ['SiftNodes Official Bot', 'SiftNodes Protection', 'SiftNodes Raid Protection']
PURPLE = 0x71368A
intents = discord.Intents.default(); intents.guilds = True; intents.members = True; intents.message_content = True; intents.invites = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
db = sqlite3.connect(DB_FILE); db.row_factory = sqlite3.Row

def init_db():
    db.executescript('''
    CREATE TABLE IF NOT EXISTS settings(guild INTEGER,key TEXT,value TEXT,PRIMARY KEY(guild,key));
    CREATE TABLE IF NOT EXISTS invite_uses(guild INTEGER,code TEXT,uses INTEGER,PRIMARY KEY(guild,code));
    CREATE TABLE IF NOT EXISTS invite_members(guild INTEGER,member INTEGER,inviter INTEGER,PRIMARY KEY(guild,member));
    CREATE TABLE IF NOT EXISTS triggers(guild INTEGER,word TEXT,reply TEXT,PRIMARY KEY(guild,word));
    CREATE TABLE IF NOT EXISTS giveaways(guild INTEGER,message INTEGER,channel INTEGER,prize TEXT,winners INTEGER,ends REAL,ended INTEGER DEFAULT 0,PRIMARY KEY(guild,message));
    CREATE TABLE IF NOT EXISTS tickets(guild INTEGER,channel INTEGER,owner INTEGER,support_role INTEGER,claimed INTEGER DEFAULT 0,PRIMARY KEY(guild,channel));
    CREATE TABLE IF NOT EXISTS timed_words(guild INTEGER,word TEXT,seconds INTEGER,PRIMARY KEY(guild,word));
    '''); db.commit()
def setting(g,k,default=None):
    r=db.execute('SELECT value FROM settings WHERE guild=? AND key=?',(g,k)).fetchone()
    if not r:return default
    try:return json.loads(r['value'])
    except:return r['value']
def put(g,k,v):
    db.execute('INSERT INTO settings VALUES(?,?,?) ON CONFLICT(guild,key) DO UPDATE SET value=excluded.value',(g,k,json.dumps(v)));db.commit()
def embed(title,desc='',colour=PURPLE): return discord.Embed(title=title[:256],description=desc[:4000],colour=colour)
def admin(i): return bool(i.guild and i.user.guild_permissions.manage_guild)
async def admin_check(i):
    if not admin(i): await i.response.send_message('❌ This command requires **Manage Server** permission.',ephemeral=True);return False
    return True
async def reply(i,*args,**kwargs):
    if i.response.is_done(): await i.followup.send(*args,**kwargs)
    else: await i.response.send_message(*args,**kwargs)
def duration(s):
    m=re.fullmatch(r'\s*(\d+)\s*([smhdw])\s*',s.lower())
    if not m: raise ValueError('Use `10m`, `2h`, `1d`, or `30s`.')
    n=int(m.group(1)); unit={'s':'seconds','m':'minutes','h':'hours','d':'days','w':'weeks'}[m.group(2)]
    d=timedelta(**{unit:n})
    if d.total_seconds()<1 or d>timedelta(days=28): raise ValueError('Duration must be between 1 second and 28 days.')
    return d
def parse_colour(s):
    s=s.strip().lstrip('#')
    try:return int(s,16) if len(s)==6 else PURPLE
    except:return PURPLE
def templ(s,member,inviter=None):
    return s.replace('%user%',member.mention).replace('%user',member.mention).replace('%server%',member.guild.name).replace('%server',member.guild.name).replace('%invited%',inviter.mention if inviter else 'Unknown').replace('%invited',inviter.mention if inviter else 'Unknown')
async def current_invites(guild):
    try:return {x.code:x.uses or 0 for x in await guild.invites()}
    except (discord.Forbidden,discord.HTTPException):return {}

# ---- verification ----
class VerifyStart(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label='Verify',style=discord.ButtonStyle.success,emoji='✅',custom_id='sn_verify_start')
    async def start(self,i,b):
        e=embed('SiftNodes Verification','1. Visit both YouTube links and subscribe if you choose to.\n\n[NotRyxenYT95]('+YT_LINKS[0]+')\n[Ryxen Extra]('+YT_LINKS[1]+')\n\n2. Submit a screenshot to the configured proof channel. A moderator will review it. Discord bots cannot independently confirm YouTube subscriptions or validate screenshots.')
        await i.response.send_message(embed=e,view=VerifySubmit(),ephemeral=True)
class VerifySubmit(discord.ui.View):
    def __init__(self):super().__init__(timeout=900)
    @discord.ui.button(label='I have proof',style=discord.ButtonStyle.primary,emoji='📸')
    async def submit(self,i,b):
        cid=setting(i.guild_id,'verify_proof_channel') if i.guild else None;ch=i.guild.get_channel(cid) if cid else None
        if not ch:return await i.response.send_message('Proof review channel is not configured. Ask a moderator.',ephemeral=True)
        await i.response.send_message(f'Please upload your screenshot in {ch.mention} and mention yourself. Staff will review it.',ephemeral=True)
        try:await ch.send(f'📨 Verification proof from {i.user.mention} (`{i.user.id}`). Review manually, then use `/verify approve` or `/verify reject`.')
        except discord.HTTPException:pass
class VerifyGroup(app_commands.Group):
    def __init__(self):super().__init__(name='verify',description='Set up verification and review proofs')
    @app_commands.command(name='setup',description='Post verification panel and configure visibility preference')
    @app_commands.describe(channel='Verification panel channel',verified_role='Role granted after proof review',without_verify_showchannels='Show other channels before verification?')
    @app_commands.choices(without_verify_showchannels=[app_commands.Choice(name='Yes — show channels',value='yes'),app_commands.Choice(name='No — only verification channel',value='no')])
    async def setup(self,i,channel:discord.TextChannel,verified_role:discord.Role,without_verify_showchannels:app_commands.Choice[str]):
        if not await admin_check(i):return
        put(i.guild_id,'verify_role',verified_role.id);put(i.guild_id,'verify_show',without_verify_showchannels.value=='yes')
        await channel.send(embed=embed('SiftNodes • Verification','Click Verify to begin. Submit proof for staff review.'),view=VerifyStart())
        await i.response.send_message(f'✅ Panel posted in {channel.mention}. Role: {verified_role.mention}. Show other channels before verification: **{without_verify_showchannels.name}**.\n\nDiscord channel visibility is controlled by permissions: to hide channels, deny View Channel to `@everyone` and allow it for the verified role. This setting cannot safely rewrite all existing channel permissions automatically.',ephemeral=True)
    @app_commands.command(name='proofchannel',description='Set the channel where users submit verification proof')
    async def proofchannel(self,i,channel:discord.TextChannel):
        if not await admin_check(i):return
        put(i.guild_id,'verify_proof_channel',channel.id);await i.response.send_message(f'Proof channel set to {channel.mention}.',ephemeral=True)
    @app_commands.command(name='approve',description='Approve reviewed proof and give verified role')
    async def approve(self,i,member:discord.Member):
        if not i.user.guild_permissions.manage_roles:return await i.response.send_message('Requires Manage Roles.',ephemeral=True)
        rid=setting(i.guild_id,'verify_role');r=i.guild.get_role(rid) if rid else None
        if not r:return await i.response.send_message('Run `/verify setup` first.',ephemeral=True)
        try:await member.add_roles(r,reason=f'Proof approved by {i.user}');await i.response.send_message(f'✅ {member.mention} verified.')
        except discord.Forbidden:await i.response.send_message('I need Manage Roles and my highest role must be above the verified role.',ephemeral=True)
    @app_commands.command(name='reject',description='Reject verification proof')
    async def reject(self,i,member:discord.Member,reason:str='Proof not accepted'):
        if not i.user.guild_permissions.manage_roles:return await i.response.send_message('Requires Manage Roles.',ephemeral=True)
        try:await member.send(f'Your verification in {i.guild.name} was rejected: {reason}')
        except discord.HTTPException:pass
        await i.response.send_message(f'Rejected proof from {member.mention}.')

# ---- tickets ----
class TicketCategoryModal(discord.ui.Modal,title='Add ticket category'):
    name=discord.ui.TextInput(label='Category name',max_length=70);emoji=discord.ui.TextInput(label='Emoji',default='🎫',required=False,max_length=20);role_id=discord.ui.TextInput(label='Support role ID',max_length=24)
    def __init__(self,gid,panel):super().__init__();self.gid=gid;self.panel=panel
    async def on_submit(self,i):
        try:rid=int(str(self.role_id.value).strip())
        except ValueError:return await i.response.send_message('Support role ID must be numeric.',ephemeral=True)
        role=i.guild.get_role(rid);cats=setting(self.gid,f'ticket_cats_{self.panel}',[])
        if not role:return await i.response.send_message('Role not found. Copy its ID with Developer Mode enabled.',ephemeral=True)
        if len(cats)>=25:return await i.response.send_message('Maximum 25 categories reached.',ephemeral=True)
        cats.append({'name':str(self.name.value),'emoji':str(self.emoji.value or '🎫'),'role':rid});put(self.gid,f'ticket_cats_{self.panel}',cats)
        await i.response.send_message(f'Added **{self.name.value}**. Run `/ticket refresh` to update the panel.',ephemeral=True)
class TicketCreateSelect(discord.ui.Select):
    def __init__(self,gid,panel,cats):
        self.gid=gid;self.panel=panel
        super().__init__(placeholder='Choose ticket category…',options=[discord.SelectOption(label=x['name'][:100],value=str(n),emoji=x.get('emoji') or None) for n,x in enumerate(cats[:25])],custom_id=f'sn_ticket_select_{panel}')
    async def callback(self,i):
        cats=setting(self.gid,f'ticket_cats_{self.panel}',[]);n=int(self.values[0])
        if n>=len(cats):return await i.response.send_message('Category removed; ask staff to refresh.',ephemeral=True)
        await create_ticket(i,cats[n])
class TicketPanel(discord.ui.View):
    def __init__(self,gid,panel,cats,kind):
        super().__init__(timeout=None);self.gid=gid;self.panel=panel
        if kind=='selectmenu':self.add_item(TicketCreateSelect(gid,panel,cats))
        else:
            for n,c in enumerate(cats[:5]):
                b=discord.ui.Button(label=c['name'][:80],emoji=c.get('emoji') or None,style=discord.ButtonStyle.primary,custom_id=f'sn_ticket_button_{panel}_{n}')
                async def cb(i,index=n):
                    cs=setting(self.gid,f'ticket_cats_{self.panel}',[])
                    if index>=len(cs):return await i.response.send_message('Category removed; refresh the panel.',ephemeral=True)
                    await create_ticket(i,cs[index])
                b.callback=cb;self.add_item(b)
class TicketControls(discord.ui.View):
    def __init__(self):super().__init__(timeout=None)
    @discord.ui.button(label='Claim',style=discord.ButtonStyle.success,emoji='✅',custom_id='sn_ticket_claim')
    async def claim(self,i,b):
        if not isinstance(i.channel,discord.TextChannel):return
        row=db.execute('SELECT * FROM tickets WHERE guild=? AND channel=?',(i.guild_id,i.channel_id)).fetchone()
        if not row:return await i.response.send_message('This ticket is not registered.',ephemeral=True)
        role=i.guild.get_role(row['support_role']) if row['support_role'] else None
        if not (i.user.guild_permissions.manage_channels or (role and role in getattr(i.user,'roles',[]))):return await i.response.send_message('Only support staff can claim this ticket.',ephemeral=True)
        db.execute('UPDATE tickets SET claimed=1 WHERE guild=? AND channel=?',(i.guild_id,i.channel_id));db.commit()
        b.disabled=True;b.label=f'Claimed by {i.user.display_name}'[:80];await i.response.edit_message(view=self);await i.channel.send(f'✅ Ticket claimed by {i.user.mention}.')
    @discord.ui.button(label='Close',style=discord.ButtonStyle.danger,emoji='🔒',custom_id='sn_ticket_close')
    async def close(self,i,b):
        row=db.execute('SELECT * FROM tickets WHERE guild=? AND channel=?',(i.guild_id,i.channel_id)).fetchone()
        if not row:return await i.response.send_message('This ticket is not registered.',ephemeral=True)
        role=i.guild.get_role(row['support_role']) if row['support_role'] else None
        if i.user.id!=row['owner'] and not i.user.guild_permissions.manage_channels and not (role and role in getattr(i.user,'roles',[])):return await i.response.send_message('Only the ticket owner or support staff can close this ticket.',ephemeral=True)
        # Delete record BEFORE channel deletion, so deleted tickets cannot remain in the database.
        db.execute('DELETE FROM tickets WHERE guild=? AND channel=?',(i.guild_id,i.channel_id));db.commit()
        await i.response.send_message('🔒 Ticket will be deleted in 3 seconds.');await asyncio.sleep(3)
        try:await i.channel.delete(reason=f'Ticket closed by {i.user}')
        except discord.HTTPException:pass
async def create_ticket(i,cat):
    g=i.guild
    row=db.execute('SELECT channel FROM tickets WHERE guild=? AND owner=?',(g.id,i.user.id)).fetchone()
    if row:
        ch=g.get_channel(row['channel'])
        if ch:return await i.response.send_message(f'You already have an open ticket: {ch.mention}',ephemeral=True)
        db.execute('DELETE FROM tickets WHERE guild=? AND channel=?',(g.id,row['channel']));db.commit()
    role=g.get_role(cat['role']) if cat.get('role') else None;cid=setting(g.id,'ticket_category')
    category=g.get_channel(cid) if cid else None
    if not isinstance(category,discord.CategoryChannel):
        try:category=await g.create_category('SiftNodes Tickets');put(g.id,'ticket_category',category.id)
        except discord.Forbidden:return await i.response.send_message('I need Manage Channels permission.',ephemeral=True)
    overwrites={g.default_role:discord.PermissionOverwrite(view_channel=False),i.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True)}
    if g.me:overwrites[g.me]=discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True,read_message_history=True)
    if role:overwrites[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
    tid=random.randint(1000,999999)
    try:
        ch=await g.create_text_channel(f'ticket-{tid}',category=category,overwrites=overwrites,topic=f'Ticket owner: {i.user.id}')
        db.execute('INSERT INTO tickets(guild,channel,owner,support_role,claimed) VALUES(?,?,?,?,0)',(g.id,ch.id,i.user.id,role.id if role else 0));db.commit()
        await ch.send(f'{i.user.mention} {role.mention if role else ""}',embed=embed(f'{cat.get("emoji","🎫")} {cat["name"]}', 'Describe your issue here. Support staff can claim this ticket.'),view=TicketControls())
        await i.response.send_message(f'✅ Ticket created: {ch.mention}',ephemeral=True)
    except discord.Forbidden:await i.response.send_message('I need Manage Channels, View Channel and Send Messages permissions.',ephemeral=True)
class TicketGroup(app_commands.Group):
    def __init__(self):super().__init__(name='ticket',description='Ticket setup and tools')
    @app_commands.command(name='setup',description='Create ticket panel')
    @app_commands.choices(ticket_type=[app_commands.Choice(name='Select menu',value='selectmenu'),app_commands.Choice(name='Buttons',value='button')])
    async def setup(self,i,channel:discord.TextChannel,ticket_type:app_commands.Choice[str],title:str='SiftNodes Support',description:str='Choose a category to open a private ticket.',colour:str='71368A',image:str='',thumbnail:str=''):
        if not await admin_check(i):return
        cats=setting(i.guild_id,f'ticket_cats_{channel.id}',[])
        if not cats:cats=[{'name':'General Support','emoji':'🎫','role':0}];put(i.guild_id,f'ticket_cats_{channel.id}',cats)
        put(i.guild_id,f'ticket_panel_{channel.id}',{'type':ticket_type.value,'title':title,'description':description,'colour':parse_colour(colour),'image':image,'thumbnail':thumbnail})
        e=embed(title,description,parse_colour(colour))
        if image.startswith('https://'):e.set_image(url=image)
        if thumbnail.startswith('https://'):e.set_thumbnail(url=thumbnail)
        await channel.send(embed=e,view=TicketPanel(i.guild_id,channel.id,cats,ticket_type.value));await i.response.send_message(f'Panel posted in {channel.mention}. Use `/ticket addcategory` to add categories.',ephemeral=True)
    @app_commands.command(name='addcategory',description='Add a ticket category, emoji and support role')
    async def addcategory(self,i,channel:discord.TextChannel):
        if not await admin_check(i):return
        await i.response.send_modal(TicketCategoryModal(i.guild_id,channel.id))
    @app_commands.command(name='refresh',description='Refresh a ticket panel after category changes')
    async def refresh(self,i,channel:discord.TextChannel):
        if not await admin_check(i):return
        cfg=setting(i.guild_id,f'ticket_panel_{channel.id}');cats=setting(i.guild_id,f'ticket_cats_{channel.id}',[])
        if not cfg:return await i.response.send_message('No panel config found; run `/ticket setup`.',ephemeral=True)
        e=embed(cfg['title'],cfg['description'],cfg['colour'])
        if cfg.get('image','').startswith('https://'):e.set_image(url=cfg['image'])
        if cfg.get('thumbnail','').startswith('https://'):e.set_thumbnail(url=cfg['thumbnail'])
        await channel.send(embed=e,view=TicketPanel(i.guild_id,channel.id,cats,cfg['type']));await i.response.send_message('Refreshed panel.',ephemeral=True)
    @app_commands.command(name='deletecategory',description='Delete a saved ticket category by its list number')
    async def deletecategory(self,i,channel:discord.TextChannel,number:app_commands.Range[int,1,25]):
        if not await admin_check(i):return
        cats=setting(i.guild_id,f'ticket_cats_{channel.id}',[])
        if number>len(cats):return await i.response.send_message('That category number does not exist.',ephemeral=True)
        removed=cats.pop(number-1);put(i.guild_id,f'ticket_cats_{channel.id}',cats);await i.response.send_message(f'Deleted category **{removed["name"]}**. Run `/ticket refresh`.',ephemeral=True)
    @app_commands.command(name='deletecategorychannel',description='Delete the automatically-created ticket category channel')
    async def deletecategorychannel(self,i):
        if not await admin_check(i):return
        cid=setting(i.guild_id,'ticket_category');ch=i.guild.get_channel(cid) if cid else None
        if not isinstance(ch,discord.CategoryChannel):return await i.response.send_message('Ticket category not found.',ephemeral=True)
        if ch.channels:return await i.response.send_message('Category is not empty. Close/delete its ticket channels first.',ephemeral=True)
        await ch.delete(reason=f'Requested by {i.user}');put(i.guild_id,'ticket_category',None);await i.response.send_message('Deleted ticket category channel.')

# ---- help menu ----
HELP_SECTIONS={
 'Setup':'/verify setup, /verify proofchannel, /ticket setup, /ticket addcategory, /welcome setup, /invite setup, /autorole add',
 'Moderation':'/ban, /unban, /kick, /timeout, /autotimeout add, /autotimeout remove, /clear',
 'Giveaways':'/gstart, /gend',
 'Backup':'/backup create, /backup list, /backup load',
 'Community':'/serverinfo, /userinfo, /avatar, /ping, /trigger add, /trigger remove, /trigger list',
}
class HelpSelect(discord.ui.Select):
    def __init__(self):super().__init__(placeholder='Choose a command section…',options=[discord.SelectOption(label=k,value=k,emoji=e) for k,e in [('Setup','⚙️'),('Moderation','🛡️'),('Giveaways','🎉'),('Backup','💾'),('Community','🌐')]])
    async def callback(self,i):await i.response.edit_message(embed=embed(f'SiftNodes Help • {self.values[0]}',HELP_SECTIONS[self.values[0]]),view=self.view)
class HelpView(discord.ui.View):
    def __init__(self):super().__init__(timeout=180);self.add_item(HelpSelect())

# ---- groups ----
class WelcomeGroup(app_commands.Group):
    def __init__(self):super().__init__(name='welcome',description='Welcome message setup')
    @app_commands.command(name='setup',description='Set welcome channel, title, image and thumbnail')
    async def setup(self,i,channel:discord.TextChannel,title:str='Welcome to %server%',image:str='',thumbnail:str='',description:str='Hey %user% Welcome To %server%'):
        if not await admin_check(i):return
        put(i.guild_id,'welcome_cfg',{'channel':channel.id,'title':title,'image':image,'thumbnail':thumbnail,'description':description})
        await i.response.send_message(f'Welcome messages configured in {channel.mention}. Placeholders: `%user%`, `%server%`.',ephemeral=True)
class InviteGroup(app_commands.Group):
    def __init__(self):super().__init__(name='invite',description='Invite tracking and welcome setup')
    @app_commands.command(name='setup',description='Set invite welcome channel and embed')
    async def setup(self,i,channel:discord.TextChannel,title:str='Welcome To %server%',description:str='%user% Welcome\nInvited By %invited%',image:str='',thumbnail:str=''):
        if not await admin_check(i):return
        put(i.guild_id,'invite_cfg',{'channel':channel.id,'title':title,'description':description,'image':image,'thumbnail':thumbnail})
        try:
            inv=await i.guild.invites()
            for x in inv:db.execute('INSERT OR REPLACE INTO invite_uses VALUES(?,?,?)',(i.guild_id,x.code,x.uses or 0))
            db.commit()
        except discord.Forbidden:pass
        await i.response.send_message(f'Invite tracking welcome configured in {channel.mention}. Bot needs Manage Server to read invites.',ephemeral=True)
class AutoRoleGroup(app_commands.Group):
    def __init__(self):super().__init__(name='autorole',description='Automatic role on member join')
    @app_commands.command(name='add',description='Set role for new members')
    async def add(self,i,role:discord.Role):
        if not await admin_check(i):return
        put(i.guild_id,'autorole',role.id);await i.response.send_message(f'New members will receive {role.mention} if bot role hierarchy permits.',ephemeral=True)
    @app_commands.command(name='remove',description='Disable automatic role')
    async def remove(self,i):
        if not await admin_check(i):return
        put(i.guild_id,'autorole',None);await i.response.send_message('Auto role disabled.',ephemeral=True)
class BackupGroup(app_commands.Group):
    def __init__(self):super().__init__(name='backup',description='Save and restore server structure')
    @app_commands.command(name='create',description='Save roles and channels under a name')
    async def create(self,i,name:str):
        if not i.user.guild_permissions.manage_guild:return await i.response.send_message('Requires Manage Server.',ephemeral=True)
        await i.response.defer(ephemeral=True,thinking=True)
        g=i.guild;data={'guild_name':g.name,'created_at':datetime.now(timezone.utc).isoformat(),'roles':[],'categories':[],'channels':[]}
        for r in g.roles:
            if r.is_default() or r.managed:continue
            data['roles'].append({'name':r.name,'colour':r.colour.value,'hoist':r.hoist,'mentionable':r.mentionable,'permissions':r.permissions.value,'position':r.position})
        for c in g.categories:data['categories'].append({'name':c.name,'position':c.position,'overwrites':serialize_overwrites(c.overwrites)})
        for c in g.channels:
            if isinstance(c,discord.CategoryChannel):continue
            data['channels'].append({'name':c.name,'type':'text' if isinstance(c,discord.TextChannel) else 'voice' if isinstance(c,discord.VoiceChannel) else 'forum' if isinstance(c,discord.ForumChannel) else 'other','category':c.category.name if c.category else None,'topic':getattr(c,'topic',None),'nsfw':getattr(c,'nsfw',False),'slowmode':getattr(c,'slowmode_delay',0),'position':c.position,'overwrites':serialize_overwrites(c.overwrites)})
        safe=re.sub(r'[^a-zA-Z0-9_-]','_',name)[:60]
        path=BACKUP_DIR/f'{g.id}_{safe}.json';path.write_text(json.dumps(data,indent=2),encoding='utf-8')
        await i.followup.send(f'✅ Saved structure backup as **{safe}**. This does not save messages, members, or every server setting.',ephemeral=True)
    @app_commands.command(name='list',description='List saved backups')
    async def listbackups(self,i):
        files=list(BACKUP_DIR.glob(f'{i.guild_id}_*.json'))
        names=[f.stem.split('_',1)[1] for f in files]
        await i.response.send_message('**Backups:**\n'+('\n'.join(f'• {x}' for x in names) if names else 'No backups found.'),ephemeral=True)
    @app_commands.command(name='load',description='Restore missing roles and channels from a backup')
    async def load(self,i,name:str):
        if not i.user.guild_permissions.manage_guild:return await i.response.send_message('Requires Manage Server.',ephemeral=True)
        safe=re.sub(r'[^a-zA-Z0-9_-]','_',name)[:60];path=BACKUP_DIR/f'{i.guild_id}_{safe}.json'
        if not path.exists():return await i.response.send_message('Backup not found. Use `/backup list`.',ephemeral=True)
        await i.response.defer(ephemeral=True,thinking=True);data=json.loads(path.read_text(encoding='utf-8'));g=i.guild;made_roles=made_channels=0;role_map={r.name:r for r in g.roles};cat_map={c.name:c for c in g.categories}
        for r in data.get('roles',[]):
            if r['name'] not in role_map:
                try:
                    role_map[r['name']]=await g.create_role(name=r['name'],colour=discord.Colour(r.get('colour',0)),hoist=r.get('hoist',False),mentionable=r.get('mentionable',False),permissions=discord.Permissions(r.get('permissions',0)),reason=f'Restore backup {safe}');made_roles+=1
                except discord.Forbidden:pass
        for c in data.get('categories',[]):
            if c['name'] not in cat_map:
                try:cat_map[c['name']]=await g.create_category(c['name']);made_channels+=1
                except discord.Forbidden:pass
        for c in data.get('channels',[]):
            if discord.utils.get(g.channels,name=c['name']):continue
            cat=cat_map.get(c.get('category'));overwrites={}
            # Apply @everyone permission only; role overwrites are skipped because role names/IDs may have changed.
            try:
                if c['type']=='text':await g.create_text_channel(c['name'],category=cat,topic=c.get('topic'),nsfw=c.get('nsfw',False),slowmode_delay=c.get('slowmode',0),overwrites=overwrites)
                elif c['type']=='voice':await g.create_voice_channel(c['name'],category=cat)
                else:continue
                made_channels+=1
            except (discord.Forbidden,discord.HTTPException):pass
        await i.followup.send(f'✅ Restore attempt finished. Roles created: {made_roles}; channels/categories created: {made_channels}. Review permissions and role hierarchy manually.',ephemeral=True)
def serialize_overwrites(overwrites):
    out=[]
    for target,ow in overwrites.items():
        if isinstance(target,discord.Role):out.append({'target':'role','name':target.name,'allow':ow.pair()[0].value,'deny':ow.pair()[1].value})
        else:out.append({'target':'member','name':getattr(target,'name','unknown')})
    return out

# ---- slash commands ----
@bot.tree.command(name='help',description='Open the interactive SiftNodes command menu')
async def help_cmd(i):await i.response.send_message(embed=embed('SiftNodes Bot Help','Choose a section from the menu below.'),view=HelpView(),ephemeral=True)
@bot.tree.command(name='ping',description='Show bot latency')
async def ping(i):await i.response.send_message(f'🏓 Pong! {round(bot.latency*1000)} ms',ephemeral=True)
@bot.tree.command(name='serverinfo',description='Show server details')
async def serverinfo(i):
    g=i.guild;e=embed(g.name,f'Members: {g.member_count}\nRoles: {len(g.roles)}\nChannels: {len(g.channels)}\nCreated: <t:{int(g.created_at.timestamp())}:D>')
    if g.icon:e.set_thumbnail(url=g.icon.url)
    await i.response.send_message(embed=e)
@bot.tree.command(name='userinfo',description='Show a member profile')
async def userinfo(i,member:discord.Member=None):
    m=member or i.user;e=embed(str(m),f'ID: `{m.id}`\nJoined: {discord.utils.format_dt(m.joined_at,style="R") if m.joined_at else "Unknown"}\nCreated: {discord.utils.format_dt(m.created_at,style="R")}\nRoles: {len(getattr(m,"roles",[]))-1}')
    e.set_thumbnail(url=m.display_avatar.url);await i.response.send_message(embed=e)
@bot.tree.command(name='avatar',description='Show a member avatar')
async def avatar(i,member:discord.Member=None):
    m=member or i.user;e=embed(f'{m.display_name} avatar');e.set_image(url=m.display_avatar.url);await i.response.send_message(embed=e)
@bot.tree.command(name='ban',description='Ban a member')
async def ban(i,member:discord.Member,reason:str='No reason provided'):
    if not i.user.guild_permissions.ban_members:return await i.response.send_message('Requires Ban Members.',ephemeral=True)
    try:await member.ban(reason=f'{reason} | By {i.user}');await i.response.send_message(f'🔨 Banned {member.mention}. Reason: {reason}')
    except discord.Forbidden:await i.response.send_message('I cannot ban this member; check my role hierarchy.',ephemeral=True)
@bot.tree.command(name='unban',description='Show ban list or unban by user ID')
@app_commands.describe(user_id='Optional user ID to unban; leave blank to show ban list')
async def unban(i,user_id:str=''):
    if not i.user.guild_permissions.ban_members:return await i.response.send_message('Requires Ban Members.',ephemeral=True)
    try:bans=[entry async for entry in i.guild.bans(limit=100)]
    except discord.Forbidden:return await i.response.send_message('I need Ban Members permission.',ephemeral=True)
    if not user_id:return await i.response.send_message('**Banned users (first 100):**\n'+('\n'.join(f'`{x.user.id}` — {x.user} | {x.reason or "No reason"}' for x in bans[:30]) or 'No bans found.'),ephemeral=True)
    try:uid=int(user_id)
    except ValueError:return await i.response.send_message('Enter a numeric user ID.',ephemeral=True)
    entry=next((x for x in bans if x.user.id==uid),None)
    if not entry:return await i.response.send_message('User not found in ban list.',ephemeral=True)
    await i.guild.unban(entry.user,reason=f'Unbanned by {i.user}');await i.response.send_message(f'✅ Unbanned {entry.user}.')
@bot.tree.command(name='kick',description='Kick a member')
async def kick(i,member:discord.Member,reason:str='No reason provided'):
    if not i.user.guild_permissions.kick_members:return await i.response.send_message('Requires Kick Members.',ephemeral=True)
    try:await member.kick(reason=f'{reason} | By {i.user}');await i.response.send_message(f'👢 Kicked {member.mention}. Reason: {reason}')
    except discord.Forbidden:await i.response.send_message('I cannot kick this member; check my role hierarchy.',ephemeral=True)
@bot.tree.command(name='timeout',description='Timeout a member for a duration')
async def timeout(i,member:discord.Member,duration_text:str,reason:str='No reason provided'):
    if not i.user.guild_permissions.moderate_members:return await i.response.send_message('Requires Moderate Members.',ephemeral=True)
    try:d=duration(duration_text);await member.timeout(d,reason=f'{reason} | By {i.user}');await i.response.send_message(f'⏳ Timed out {member.mention} for {duration_text}. Reason: {reason}')
    except ValueError as e:await i.response.send_message(str(e),ephemeral=True)
    except discord.Forbidden:await i.response.send_message('I cannot timeout this member; check role hierarchy.',ephemeral=True)
@bot.tree.command(name='clear',description='Delete recent messages')
async def clear(i,amount:app_commands.Range[int,1,100]):
    if not i.user.guild_permissions.manage_messages:return await i.response.send_message('Requires Manage Messages.',ephemeral=True)
    await i.response.defer(ephemeral=True)
    try:n=await i.channel.purge(limit=amount);await i.followup.send(f'🧹 Deleted {len(n)} messages.',ephemeral=True)
    except discord.Forbidden:await i.followup.send('I need Manage Messages.',ephemeral=True)
@bot.tree.command(name='announce',description='Send an announcement embed')
async def announce(i,channel:discord.TextChannel,title:str,description:str,colour_hex:str='71368A'):
    if not i.user.guild_permissions.manage_messages:return await i.response.send_message('Requires Manage Messages.',ephemeral=True)
    await channel.send(embed=embed(title,description,colour(colour_hex)));await i.response.send_message(f'Announcement sent to {channel.mention}.',ephemeral=True)
@bot.tree.command(name='gstart',description='Start a giveaway (duration examples: 1d, 2h, 30m)')
async def gstart(i,prize:str,winners:app_commands.Range[int,1,20],duration_text:str):
    if not i.user.guild_permissions.manage_guild:return await i.response.send_message('Requires Manage Server.',ephemeral=True)
    try:d=duration(duration_text)
    except ValueError as e:return await i.response.send_message(str(e),ephemeral=True)
    end=time.time()+d.total_seconds();e=embed('🎉 Giveaway!',f'Prize: **{prize}**\nWinners: **{winners}**\nEnds: <t:{int(end)}:R>\nReact with 🎉 to enter!')
    msg=await i.channel.send(embed=e);await msg.add_reaction('🎉');db.execute('INSERT OR REPLACE INTO giveaways VALUES(?,?,?,?,?,?,0)',(i.guild_id,msg.id,i.channel_id,prize,winners,end));db.commit();await i.response.send_message(f'Giveaway started: {msg.jump_url}',ephemeral=True)
@bot.tree.command(name='gend',description='End a giveaway by its exact prize name')
async def gend(i,prize_name:str):
    if not i.user.guild_permissions.manage_guild:return await i.response.send_message('Requires Manage Server.',ephemeral=True)
    rows=db.execute('SELECT * FROM giveaways WHERE guild=? AND prize=? AND ended=0',(i.guild_id,prize_name)).fetchall()
    if not rows:return await i.response.send_message('No active giveaway with that exact prize name.',ephemeral=True)
    for r in rows:await finish_giveaway(r,force=True)
    await i.response.send_message(f'Ended {len(rows)} giveaway(s).')
@bot.tree.command(name='autotimeout',description='Add/remove/list words that automatically timeout matching messages')
@app_commands.choices(action=[app_commands.Choice(name='Add',value='add'),app_commands.Choice(name='Remove',value='remove'),app_commands.Choice(name='List',value='list')])
async def autotimeout(i,action:app_commands.Choice[str],word:str='',duration_text:str='10m'):
    if not i.user.guild_permissions.moderate_members:return await i.response.send_message('Requires Moderate Members.',ephemeral=True)
    if action.value=='list':
        rows=db.execute('SELECT word,seconds FROM timed_words WHERE guild=?',(i.guild_id,)).fetchall();return await i.response.send_message('**Auto-timeout words:**\n'+('\n'.join(f'`{r["word"]}` — {r["seconds"]//60}m' for r in rows) or 'None'),ephemeral=True)
    if not word:return await i.response.send_message('Provide a word.',ephemeral=True)
    if action.value=='remove':db.execute('DELETE FROM timed_words WHERE guild=? AND word=?',(i.guild_id,word.lower()));db.commit();return await i.response.send_message(f'Removed `{word}`.',ephemeral=True)
    try:secs=int(duration(duration_text).total_seconds())
    except ValueError as e:return await i.response.send_message(str(e),ephemeral=True)
    db.execute('INSERT OR REPLACE INTO timed_words VALUES(?,?,?)',(i.guild_id,word.lower(),secs));db.commit();await i.response.send_message(f'Auto-timeout added for `{word}` ({duration_text}).',ephemeral=True)
@bot.tree.command(name='trigger',description='Manage custom automatic keyword replies')
@app_commands.choices(action=[app_commands.Choice(name='Add',value='add'),app_commands.Choice(name='Remove',value='remove'),app_commands.Choice(name='List',value='list')])
async def trigger(i,action:app_commands.Choice[str],word:str='',reply_text:str=''):
    if not i.user.guild_permissions.manage_guild:return await i.response.send_message('Requires Manage Server.',ephemeral=True)
    if action.value=='list':
        rows=db.execute('SELECT word,reply FROM triggers WHERE guild=?',(i.guild_id,)).fetchall();return await i.response.send_message('**Triggers:**\n'+('\n'.join(f'`{r["word"]}` → {r["reply"]}' for r in rows) or 'None'),ephemeral=True)
    if not word:return await i.response.send_message('Provide a word.',ephemeral=True)
    if action.value=='remove':db.execute('DELETE FROM triggers WHERE guild=? AND word=?',(i.guild_id,word.lower()));db.commit();return await i.response.send_message('Trigger removed.',ephemeral=True)
    if not reply_text:return await i.response.send_message('Provide a reply.',ephemeral=True)
    db.execute('INSERT OR REPLACE INTO triggers VALUES(?,?,?)',(i.guild_id,word.lower(),reply_text[:1500]));db.commit();await i.response.send_message('Trigger saved.',ephemeral=True)

bot.tree.add_command(VerifyGroup());bot.tree.add_command(TicketGroup());bot.tree.add_command(WelcomeGroup());bot.tree.add_command(InviteGroup());bot.tree.add_command(AutoRoleGroup());bot.tree.add_command(BackupGroup())

async def finish_giveaway(row,force=False):
    if row['ended']:return
    if not force and row['ends']>time.time():return
    guild=bot.get_guild(row['guild']);channel=guild.get_channel(row['channel']) if guild else None
    try:msg=await channel.fetch_message(row['message']) if channel else None
    except discord.HTTPException:msg=None
    entrants=[]
    if msg:
        for reaction in msg.reactions:
            if str(reaction.emoji)=='🎉':
                async for u in reaction.users():
                    if not u.bot:entrants.append(u)
    winners=random.sample(list({u.id:u for u in entrants}.values()),min(row['winners'],len({u.id:u for u in entrants}.values()))) if entrants else []
    db.execute('UPDATE giveaways SET ended=1 WHERE guild=? AND message=?',(row['guild'],row['message']));db.commit()
    if channel:
        await channel.send(f'🎉 Giveaway **{row["prize"]}** ended! '+('Winner(s): '+', '.join(x.mention for x in winners) if winners else 'No valid entrants; no winner.'))

@bot.event
async def on_ready():
    init_db()
    bot.add_view(VerifyStart());bot.add_view(TicketControls())
    # Re-register persistent ticket panel views after restarts.
    for row in db.execute('SELECT guild,key,value FROM settings WHERE key LIKE \'ticket_panel_%\'').fetchall():
        try:
            panel_id=int(row['key'].split('_')[-1]); cfg=json.loads(row['value']); gid=row['guild']
            cats=json.loads(db.execute('SELECT value FROM settings WHERE guild=? AND key=?',(gid,f'ticket_cats_{panel_id}')).fetchone()['value'])
            bot.add_view(TicketPanel(gid,panel_id,cats,cfg['type']))
        except Exception as exc: print('Ticket panel restore skipped:',repr(exc))
    try:
        synced=await bot.tree.sync();print(f'Synced {len(synced)} slash commands.')
    except Exception as e:print('Command sync error:',repr(e))
    if not status_loop.is_running():status_loop.start()
    if not giveaway_loop.is_running():giveaway_loop.start()
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
@tasks.loop(minutes=5)
async def status_loop():
    status=random.choice(STATUSES);await bot.change_presence(activity=discord.Streaming(name=status,url=TWITCH),status=discord.Status.online)
@tasks.loop(seconds=20)
async def giveaway_loop():
    rows=db.execute('SELECT * FROM giveaways WHERE ended=0 AND ends<=?',(time.time(),)).fetchall()
    for r in rows:
        try:await finish_giveaway(r)
        except Exception as e:print('Giveaway finish error:',repr(e))
@bot.event
async def on_member_join(member):
    # Autorole
    rid=setting(member.guild.id,'autorole');role=member.guild.get_role(rid) if rid else None
    if role:
        try:await member.add_roles(role,reason='Configured SiftNodes autorole')
        except discord.HTTPException:pass
    # Track inviter by comparing cached invite uses
    inviter=None
    try:
        now=await member.guild.invites()
        for inv in now:
            old=db.execute('SELECT uses FROM invite_uses WHERE guild=? AND code=?',(member.guild.id,inv.code)).fetchone()
            if old and (inv.uses or 0)>old['uses']:
                inviter=inv.inviter;break
            db.execute('INSERT OR REPLACE INTO invite_uses VALUES(?,?,?)',(member.guild.id,inv.code,inv.uses or 0))
        db.commit()
    except discord.Forbidden:pass
    if inviter:db.execute('INSERT OR REPLACE INTO invite_members VALUES(?,?,?)',(member.guild.id,member.id,inviter.id));db.commit()
    cfg=setting(member.guild.id,'welcome_cfg')
    if cfg:
        ch=member.guild.get_channel(cfg['channel'])
        if ch:
            e=embed(templ(cfg['title'],member),templ(cfg['description'],member))
            if cfg.get('image','').startswith('https://'):e.set_image(url=cfg['image'])
            if cfg.get('thumbnail','').startswith('https://'):e.set_thumbnail(url=cfg['thumbnail'])
            try:await ch.send(embed=e)
            except discord.HTTPException:pass
    icfg=setting(member.guild.id,'invite_cfg')
    if icfg:
        ch=member.guild.get_channel(icfg['channel'])
        if ch:
            e=embed(templ(icfg['title'],member,inviter),templ(icfg['description'],member,inviter))
            if icfg.get('image','').startswith('https://'):e.set_image(url=icfg['image'])
            if icfg.get('thumbnail','').startswith('https://'):e.set_thumbnail(url=icfg['thumbnail'])
            try:await ch.send(embed=e)
            except discord.HTTPException:pass
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:return
    text=message.content.lower()
    words=db.execute('SELECT word,seconds FROM timed_words WHERE guild=?',(message.guild.id,)).fetchall()
    for row in words:
        if row['word'].lower() in text and isinstance(message.author,discord.Member):
            if message.author.guild_permissions.moderate_members:break
            try:
                await message.author.timeout(timedelta(seconds=row['seconds']),reason=f'Auto-timeout keyword: {row["word"]}')
                await message.channel.send(f'{message.author.mention} was timed out for a configured keyword.',delete_after=8)
            except discord.HTTPException:pass
            break
    triggers=db.execute('SELECT word,reply FROM triggers WHERE guild=?',(message.guild.id,)).fetchall()
    for row in triggers:
        if row['word'].lower() in text:
            try:await message.channel.send(row['reply'][:1800])
            except discord.HTTPException:pass
            break
    await bot.process_commands(message)
@bot.event
async def on_invite_create(invite):
    db.execute('INSERT OR REPLACE INTO invite_uses VALUES(?,?,?)',(invite.guild.id,invite.code,invite.uses or 0));db.commit()
@bot.event
async def on_invite_delete(invite):
    db.execute('DELETE FROM invite_uses WHERE guild=? AND code=?',(invite.guild.id,invite.code));db.commit()

if __name__=='__main__':
    init_db()
    if not TOKEN:raise SystemExit('Missing DISCORD_TOKEN. Set it as an environment variable before starting the bot.')
    bot.run(TOKEN,log_handler=None)
