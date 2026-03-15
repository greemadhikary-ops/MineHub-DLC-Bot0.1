# app.py (THE REAL, FINAL, CLEAN, EASY-TO-READ FULL CODE)

import os
import asyncio
import secrets
import traceback
import uvicorn
import re
import logging
from contextlib import asynccontextmanager

from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from pyrogram.errors import FloodWait, UserNotParticipant
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pyrogram.file_id import FileId
from pyrogram import raw
from pyrogram.session import Session, Auth
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import math

# Import required modules and configurations
from config import Config
from database import db

# =====================================================================================
# --- SETUP: BOT, WEB SERVER, AND LOGGING ---
# =====================================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    This function manages the bot lifecycle with the web server.
    """
    print("--- Lifespan: Server is starting up... ---")
    
    await db.connect()
    
    try:
        print("Starting main Pyrogram bot...")
        await bot.start()
        
        me = await bot.get_me()
        Config.BOT_USERNAME = me.username
        print(f"✅ Main Bot [@{Config.BOT_USERNAME}] started successfully.")

        # --- MULTI-CLIENT STARTUP ---
        multi_clients[0] = bot
        work_loads[0] = 0
        await initialize_clients()
        
        print(f"Verifying storage channel ({Config.STORAGE_CHANNEL})...")
        await bot.get_chat(Config.STORAGE_CHANNEL)
        print("✅ Storage channel is accessible.")

        if Config.FORCE_SUB_CHANNEL:
            try:
                print(f"Verifying force sub channel ({Config.FORCE_SUB_CHANNEL})...")
                await bot.get_chat(Config.FORCE_SUB_CHANNEL)
                print("✅ Force Sub channel is accessible.")
            except Exception as e:
                print(f"!!! WARNING: Bot is not admin in Force Sub channel. Error: {e}")
        
        try:
            await cleanup_channel(bot)
        except Exception as e:
            print(f"Warning: Channel cleanup failed. Error: {e}")

        print("--- Lifespan: Startup completed successfully. ---")
    
    except Exception as e:
        print(f"!!! FATAL ERROR: Bot startup failed: {traceback.format_exc()}")
    
    yield
    
    print("--- Lifespan: Server is shutting down... ---")
    if bot.is_initialized:
        await bot.stop()
    print("--- Lifespan: Shutdown complete. ---")

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- LOG FILTER: HIDE /dl/ ENDPOINT LOGS ---
class HideDLFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Hide logs containing "GET /dl/"
        return "GET /dl/" not in record.getMessage()

# Apply filter to uvicorn access logger
logging.getLogger("uvicorn.access").addFilter(HideDLFilter())
# --- LOG FILTER END ---

bot = Client("SimpleStreamBot", api_id=Config.API_ID, api_hash=Config.API_HASH, bot_token=Config.BOT_TOKEN, in_memory=True)
multi_clients = {}; work_loads = {}; class_cache = {}

# =====================================================================================
# --- MULTI-CLIENT LOGIC ---
# =====================================================================================

class TokenParser:
    """ Parse MULTI_TOKENs from environment variables. """
    @staticmethod
    def parse_from_env():
        return {
            c + 1: t
            for c, (_, t) in enumerate(
                filter(lambda n: n[0].startswith("MULTI_TOKEN"), sorted(os.environ.items()))
            )
        }

async def start_client(client_id, bot_token):
    """ Start a new client bot. """
    try:
        print(f"Attempting to start Client: {client_id}")
        client = await Client(
            name=str(client_id), 
            api_id=Config.API_ID, 
            api_hash=Config.API_HASH,
            bot_token=bot_token, 
            no_updates=True, 
            in_memory=True
        ).start()
        work_loads[client_id] = 0
        multi_clients[client_id] = client
        print(f"✅ Client {client_id} started successfully.")
    except Exception as e:
        print(f"!!! CRITICAL ERROR: Failed to start Client {client_id} - Error: {e}")

async def initialize_clients():
    """ Initialize all additional clients. """
    all_tokens = TokenParser.parse_from_env()
    if not all_tokens:
        print("No additional clients found. Using default bot only.")
        return
    
    print(f"Found {len(all_tokens)} extra clients. Starting them...")
    tasks = [start_client(i, token) for i, token in all_tokens.items()]
    await asyncio.gather(*tasks)

    if len(multi_clients) > 1:
        print(f"✅ Multi-Client Mode Enabled. Total Clients: {len(multi_clients)}")

# =====================================================================================
# --- HELPER FUNCTIONS ---
# =====================================================================================

def get_readable_file_size(size_in_bytes):
    """ Convert bytes to human readable format. """
    if not size_in_bytes:
        return '0B'
    power = 1024
    n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB'}
    while size_in_bytes >= power and n < len(power_labels) - 1:
        size_in_bytes /= power
        n += 1
    return f"{size_in_bytes:.2f} {power_labels[n]}"

def is_mcaddon_file(filename: str) -> bool:
    """ Check if file is MCaddon. """
    return filename.lower().endswith('.mcaddon')

def mask_filename(name: str):
    """ Mask filename to protect privacy while preserving MCaddon extension. """
    if not name:
        return "Protected File"
    
    # Special handling for MCaddon files
    if is_mcaddon_file(name):
        base = name[:-8]  # Remove .mcaddon
        # Mask the base name but keep recognizable
        masked_base = ''.join(c if (i % 3 == 0 and c.isalnum()) else ('*' if c.isalnum() else c) 
                            for i, c in enumerate(base))
        return f"{masked_base}.mcaddon"
    
    # Original masking for other files
    base, ext = os.path.splitext(name)
    metadata_pattern = re.compile(
        r'((19|20)\d{2}|4k|2160p|1080p|720p|480p|360p|HEVC|x265|BluRay|WEB-DL|HDRip)',
        re.IGNORECASE
    )
    match = metadata_pattern.search(base)
    if match:
        title_part = base[:match.start()].strip(' .-_')
        metadata_part = base[match.start():]
    else:
        title_part = base
        metadata_part = ""
    masked_title = ''.join(c if (i % 3 == 0 and c.isalnum()) else ('*' if c.isalnum() else c) 
                          for i, c in enumerate(title_part))
    return f"{masked_title} {metadata_part}{ext}".strip()

# =====================================================================================
# --- PYROGRAM BOT HANDLERS ---
# =====================================================================================

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    if len(message.command) > 1 and message.command[1].startswith("verify_"):
        unique_id = message.command[1].split("_", 1)[1]
        
        if Config.FORCE_SUB_CHANNEL:
            try:
                await client.get_chat_member(Config.FORCE_SUB_CHANNEL, user_id)
            except UserNotParticipant:
                channel_username = str(Config.FORCE_SUB_CHANNEL).replace('@', '')
                channel_link = f"https://t.me/{channel_username}"
                join_button = InlineKeyboardButton("📢 Join Channel", url=channel_link)
                retry_button = InlineKeyboardButton("✅ Joined", url=f"https://t.me/{Config.BOT_USERNAME}?start={message.command[1]}")
                keyboard = InlineKeyboardMarkup([[join_button], [retry_button]])
                await message.reply_text(
                    "**You Must Join Our Channel To Get The Link!**\n\n"
                    "__Join Channel & Click '✅ Joined'.__",
                    reply_markup=keyboard, quote=True
                )
                return

        final_link = f"{Config.BASE_URL}/show/{unique_id}"
        reply_text = f"__✅ Verification Successful!\n\nCopy Link:__ `{final_link}`"
        button = InlineKeyboardMarkup([[InlineKeyboardButton("Open Link", url=final_link)]])
        await message.reply_text(reply_text, reply_markup=button, quote=True, disable_web_page_preview=True)

    else:
        reply_text = f"""
👋 **Hello, {user_name}!**

__Welcome To Sharing Box Bot. I Can Help You Create Permanent, Shareable Links For Your Files.__

**How To Use Me:**

__Just Send Or Forward Any File To Me And I will instantly give you a special link that you can share with anyone!__
"""
        await message.reply_text(reply_text)

async def handle_file_upload(message: Message, user_id: int):
    """ Handle file upload and generate unique link. """
    try:
        # Check if it's MCaddon file
        if message.document and is_mcaddon_file(message.document.file_name):
            print(f"📦 MCaddon file detected: {message.document.file_name}")
        
        sent_message = await message.copy(chat_id=Config.STORAGE_CHANNEL)
        unique_id = secrets.token_urlsafe(8)
        await db.save_link(unique_id, sent_message.id)
        
        verify_link = f"https://t.me/{Config.BOT_USERNAME}?start=verify_{unique_id}"
        
        # Custom button text for MCaddon
        button_text = "Get MCaddon Link" if (message.document and is_mcaddon_file(message.document.file_name)) else "Get Link Now"
        button = InlineKeyboardMarkup([[InlineKeyboardButton(button_text, url=verify_link)]])
        
        await message.reply_text("__✅ File Uploaded!__", reply_markup=button, quote=True)
    except Exception as e:
        print(f"!!! ERROR: {traceback.format_exc()}")
        await message.reply_text("Sorry, something went wrong.")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def file_handler(_, message: Message):
    await handle_file_upload(message, message.from_user.id)

@bot.on_chat_member_updated(filters.chat(Config.STORAGE_CHANNEL))
async def simple_gatekeeper(c: Client, m_update: ChatMemberUpdated):
    """ Auto-kick users who join storage channel. """
    try:
        if(m_update.new_chat_member and m_update.new_chat_member.status==enums.ChatMemberStatus.MEMBER):
            u=m_update.new_chat_member.user
            if u.id==Config.OWNER_ID or u.is_self: return
            print(f"Gatekeeper: Kicking {u.id}")
            await c.ban_chat_member(Config.STORAGE_CHANNEL,u.id)
            await c.unban_chat_member(Config.STORAGE_CHANNEL,u.id)
    except Exception as e:
        print(f"Gatekeeper Error: {e}")

async def cleanup_channel(c: Client):
    """ Cleanup storage channel - remove unauthorized users. """
    print("Gatekeeper: Running cleanup...")
    allowed={Config.OWNER_ID,c.me.id}
    try:
        async for m in c.get_chat_members(Config.STORAGE_CHANNEL):
            if m.user.id in allowed: continue
            if m.status in [enums.ChatMemberStatus.ADMINISTRATOR,enums.ChatMemberStatus.OWNER]: continue
            try:
                print(f"Cleanup: Kicking {m.user.id}")
                await c.ban_chat_member(Config.STORAGE_CHANNEL,m.user.id)
                await asyncio.sleep(1)
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception as e:
                print(f"Cleanup Error: {e}")
    except Exception as e:
        print(f"Cleanup Error: {e}")

# =====================================================================================
# --- FASTAPI WEB SERVER ---
# =====================================================================================
 
@app.get("/")
async def health_check():
    """
    This route provides a 200 OK response for uptime monitors.
    """
    return {"status": "ok", "message": "Server is healthy and running!"}

@app.get("/show/{unique_id}", response_class=HTMLResponse)
async def show_page(request: Request, unique_id: str):
    return templates.TemplateResponse(
        "show.html",
        {"request": request}
    )

@app.get("/api/file/{unique_id}", response_class=JSONResponse)
async def get_file_details_api(request: Request, unique_id: str):
    """ Get file details for the show page. """
    message_id = await db.get_link(unique_id)
    if not message_id:
        raise HTTPException(status_code=404, detail="Link expired or invalid.")
    
    main_bot = multi_clients.get(0)
    if not main_bot:
        raise HTTPException(status_code=503, detail="Bot is not ready.")
    
    try:
        message = await main_bot.get_messages(Config.STORAGE_CHANNEL, message_id)
    except Exception:
        raise HTTPException(status_code=404, detail="File not found on Telegram.")
    
    media = message.document or message.video or message.audio
    if not media:
        raise HTTPException(status_code=404, detail="Media not found in the message.")
    
    file_name = media.file_name or "file"
    safe_file_name = "".join(c for c in file_name if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
    mime_type = media.mime_type or "application/octet-stream"
    
    # Check if it's MCaddon file
    is_mcaddon = is_mcaddon_file(file_name)
    
    response_data = {
        "file_name": mask_filename(file_name),
        "file_size": get_readable_file_size(media.file_size),
        # MCaddon files should NOT be treated as media
        "is_media": mime_type.startswith(("video", "audio")) and not is_mcaddon,
        "is_mcaddon": is_mcaddon,  # New field for frontend
        "direct_dl_link": f"{Config.BASE_URL}/dl/{message_id}/{safe_file_name}",
        "mx_player_link": f"intent:{Config.BASE_URL}/dl/{message_id}/{safe_file_name}#Intent;action=android.intent.action.VIEW;type={mime_type};end",
        "vlc_player_link": f"intent:{Config.BASE_URL}/dl/{message_id}/{safe_file_name}#Intent;action=android.intent.action.VIEW;type={mime_type};package=org.videolan.vlc;end"
    }
    return response_data

class ByteStreamer:
    """ Handles streaming of files from Telegram. """
    def __init__(self,c:Client):
        self.client=c
    
    @staticmethod
    async def get_location(f:FileId):
        return raw.types.InputDocumentFileLocation(
            id=f.media_id,
            access_hash=f.access_hash,
            file_reference=f.file_reference,
            thumb_size=f.thumbnail_size
        )
    
    async def yield_file(self,f:FileId,i:int,o:int,fc:int,lc:int,pc:int,cs:int):
        c=self.client
        work_loads[i]+=1
        ms=c.media_sessions.get(f.dc_id)
        
        if ms is None:
            if f.dc_id!=await c.storage.dc_id():
                ak=await Auth(c,f.dc_id,await c.storage.test_mode()).create()
                ms=Session(c,f.dc_id,ak,await c.storage.test_mode(),is_media=True)
                await ms.start()
                ea=await c.invoke(raw.functions.auth.ExportAuthorization(dc_id=f.dc_id))
                await ms.invoke(raw.functions.auth.ImportAuthorization(id=ea.id,bytes=ea.bytes))
            else:
                ms=c.session
            c.media_sessions[f.dc_id]=ms
        
        loc=await self.get_location(f)
        cp=1
        try:
            while cp<=pc:
                r=await ms.invoke(
                    raw.functions.upload.GetFile(location=loc,offset=o,limit=cs),
                    retries=0
                )
                if isinstance(r,raw.types.upload.File):
                    chk=r.bytes
                    if not chk:break
                    if pc==1:
                        yield chk[fc:lc]
                    elif cp==1:
                        yield chk[fc:]
                    elif cp==pc:
                        yield chk[:lc]
                    else:
                        yield chk
                    cp+=1
                    o+=cs
                else:break
        finally:
            work_loads[i]-=1

@app.get("/dl/{mid}/{fname}")
async def stream_media(r:Request,mid:int,fname:str):
    """ Stream media/file with range support. """
    if not work_loads:
        raise HTTPException(503)
    
    client_id = min(work_loads, key=work_loads.get)
    c = multi_clients.get(client_id)
    if not c:
        raise HTTPException(503)
    
    tc=class_cache.get(c) or ByteStreamer(c)
    class_cache[c]=tc
    
    try:
        msg=await c.get_messages(Config.STORAGE_CHANNEL,mid)
        m=msg.document or msg.video or msg.audio
        if not m or msg.empty:
            raise FileNotFoundError
        
        fid=FileId.decode(m.file_id)
        fsize=m.file_size
        rh=r.headers.get("Range","")
        fb,ub=0,fsize-1
        
        if rh:
            rps=rh.replace("bytes=","").split("-")
            fb=int(rps[0])
            if len(rps)>1 and rps[1]:
                ub=int(rps[1])
        
        if(ub>=fsize)or(fb<0):
            raise HTTPException(416)
        
        rl=ub-fb+1
        cs=1024*1024
        off=(fb//cs)*cs
        fc=fb-off
        lc=(ub%cs)+1
        pc=math.ceil(rl/cs)
        
        body=tc.yield_file(fid,client_id,off,fc,lc,pc,cs)
        sc=206 if rh else 200
        
        hdrs={
            "Content-Type":m.mime_type or "application/octet-stream",
            "Accept-Ranges":"bytes",
            "Content-Disposition":f'inline; filename="{m.file_name}"',
            "Content-Length":str(rl)
        }
        if rh:
            hdrs["Content-Range"]=f"bytes {fb}-{ub}/{fsize}"
        
        return StreamingResponse(body,status_code=sc,headers=hdrs)
    
    except FileNotFoundError:
        raise HTTPException(404)
    except Exception:
        print(traceback.format_exc())
        raise HTTPException(500)

# =====================================================================================
# --- MAIN EXECUTION BLOCK ---
# =====================================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    # Keep log level "info" for our filter to work
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
