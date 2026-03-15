# webserver.py - FastAPI Web Server for Telegram File Streaming
# Handles file display pages and streaming/download endpoints

import math
import traceback
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pyrogram.file_id import FileId
from pyrogram import raw, Client
from pyrogram.session import Session, Auth

# Local imports from your project
from config import Config
from bot import multi_clients, work_loads, get_readable_file_size
from database import db

# FastAPI app instance, started by main.py
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Cache for ByteStreamer instances to avoid re-creating them
class_cache = {}

# =====================================================================================
# --- HELPER FUNCTIONS ---
# =====================================================================================

@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    """Health check endpoint for uptime monitors."""
    return {"status": "ok", "message": "Web server is healthy!"}

def is_mcaddon_file(filename: str) -> bool:
    """Check if the file is a Minecraft addon."""
    return filename.lower().endswith('.mcaddon')

def mask_filename(name: str) -> str:
    """
    Obfuscate filename to protect privacy while preserving important metadata.
    Special handling for MCaddon files.
    """
    if not name: 
        return "Protected File"
    
    # Special handling for MCaddon files
    if is_mcaddon_file(name):
        base = name[:-8]  # Remove .mcaddon
        # Mask the base name but keep it recognizable
        masked_base = ''.join(c if (i % 3 == 0 and c.isalnum()) else '*' 
                            for i, c in enumerate(base))
        return f"{masked_base}.mcaddon"
    
    # Original masking for video files (keep resolution info)
    resolutions = ["216p", "480p", "720p", "1080p", "2160p", "4k"]
    res_part = ""
    for res in resolutions:
        if res in name:
            res_part = f" {res}"
            name = name.replace(res, "")
            break
    
    base, ext = os.path.splitext(name)
    masked_base = ''.join(c if (i % 3 == 0 and c.isalnum()) else '*' 
                         for i, c in enumerate(base))
    return f"{masked_base}{res_part}{ext}"

# =====================================================================================
# --- BYTE STREAMER CLASS ---
# =====================================================================================

class ByteStreamer:
    """
    Handles low-level fetching of file parts from Telegram servers.
    Implements chunked streaming with load balancing.
    """
    
    def __init__(self, client: Client):
        self.client = client

    @staticmethod
    async def get_location(file_id: FileId):
        """Convert FileId to Telegram InputDocumentFileLocation."""
        return raw.types.InputDocumentFileLocation(
            id=file_id.media_id,
            access_hash=file_id.access_hash,
            file_reference=file_id.file_reference,
            thumb_size=file_id.thumbnail_size
        )

    async def yield_file(self, file_id: FileId, index: int, offset: int, 
                        first_part_cut: int, last_part_cut: int, 
                        part_count: int, chunk_size: int):
        """
        Yield file chunks asynchronously with proper byte range support.
        
        Args:
            file_id: Telegram file identifier
            index: Client index for load balancing
            offset: Starting byte offset
            first_part_cut: Bytes to cut from first chunk
            last_part_cut: Bytes to keep in last chunk
            part_count: Total number of chunks
            chunk_size: Size of each chunk (1MB default)
        """
        client = self.client
        work_loads[index] += 1
        
        # Get or create media session for the DC
        media_session = client.media_sessions.get(file_id.dc_id)
        if media_session is None:
            if file_id.dc_id != await client.storage.dc_id():
                # Different DC - need to authenticate
                auth_key = await Auth(client, file_id.dc_id, await client.storage.test_mode()).create()
                media_session = Session(client, file_id.dc_id, auth_key, 
                                      await client.storage.test_mode(), is_media=True)
                await media_session.start()
                exported_auth = await client.invoke(
                    raw.functions.auth.ExportAuthorization(dc_id=file_id.dc_id)
                )
                await media_session.invoke(
                    raw.functions.auth.ImportAuthorization(
                        id=exported_auth.id, 
                        bytes=exported_auth.bytes
                    )
                )
            else:
                media_session = client.session
            client.media_sessions[file_id.dc_id] = media_session
        
        location = await self.get_location(file_id)
        current_part = 1
        
        try:
            while current_part <= part_count:
                # Fetch chunk from Telegram
                r = await media_session.invoke(
                    raw.functions.upload.GetFile(
                        location=location, 
                        offset=offset, 
                        limit=chunk_size
                    ),
                    retries=0
                )
                
                if isinstance(r, raw.types.upload.File):
                    chunk = r.bytes
                    if not chunk: 
                        break
                    
                    # Handle partial chunks for range requests
                    if part_count == 1:
                        yield chunk[first_part_cut:last_part_cut]
                    elif current_part == 1:
                        yield chunk[first_part_cut:]
                    elif current_part == part_count:
                        yield chunk[:last_part_cut]
                    else:
                        yield chunk
                    
                    current_part += 1
                    offset += chunk_size
                else:
                    break
        finally:
            work_loads[index] -= 1

# =====================================================================================
# --- WEB ROUTES ---
# =====================================================================================

@app.get("/show/{unique_id}", response_class=HTMLResponse)
async def show_file_page(request: Request, unique_id: str):
    """
    Display the file download page with file information.
    Supports MCaddon files with special handling.
    """
    try:
        # Get message ID from database
        storage_msg_id = await db.get_link(unique_id)
        if not storage_msg_id:
            raise HTTPException(status_code=404, detail="Link expired or invalid.")
        
        # Use main bot to get file details
        main_bot = multi_clients.get(0)
        if not main_bot:
            raise HTTPException(
                status_code=503, 
                detail="Bot is not ready yet. Please try again in a moment."
            )
        
        # Fetch message from storage channel
        file_msg = await main_bot.get_messages(Config.STORAGE_CHANNEL, storage_msg_id)
        media = file_msg.document or file_msg.video or file_msg.audio
        if not media:
            raise HTTPException(status_code=404, detail="File not found in the message.")
        
        original_file_name = media.file_name or "file"
        safe_file_name = "".join(c for c in original_file_name 
                                if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
        
        # Check if it's MCaddon
        is_mcaddon = is_mcaddon_file(original_file_name)
        is_media = (media.mime_type or "").startswith(("video/", "audio/")) and not is_mcaddon
        
        # Prepare template context
        context = {
            "request": request,
            "file_name": mask_filename(original_file_name),
            "file_size": get_readable_file_size(media.file_size),
            "is_media": is_media,
            "is_mcaddon": is_mcaddon,  # Pass to template
            "direct_dl_link": f"{Config.BASE_URL}/dl/{storage_msg_id}/{safe_file_name}",
            "mx_player_link": f"intent:{Config.BASE_URL}/dl/{storage_msg_id}/{safe_file_name}#Intent;action=android.intent.action.VIEW;type={media.mime_type};end",
            "vlc_player_link": f"vlc://{Config.BASE_URL}/dl/{storage_msg_id}/{safe_file_name}"
        }
        
        return templates.TemplateResponse("show.html", context)

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in /show route: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error.")

@app.get("/dl/{msg_id}/{file_name}")
async def stream_handler(request: Request, msg_id: int, file_name: str):
    """
    Stream file with support for partial content (range requests).
    Enables video seeking and efficient downloads.
    """
    try:
        # Load balancing: choose client with least workload
        index = min(work_loads, key=work_loads.get, default=0)
        client = multi_clients.get(index)
        if not client:
            raise HTTPException(
                status_code=503, 
                detail="No available clients to handle the request."
            )
        
        # Get or create ByteStreamer for this client
        tg_connect = class_cache.get(client)
        if not tg_connect:
            tg_connect = ByteStreamer(client)
            class_cache[client] = tg_connect
            
        # Fetch message from storage channel
        message = await client.get_messages(Config.STORAGE_CHANNEL, msg_id)
        media = message.document or message.video or message.audio
        if not media or message.empty:
            raise FileNotFoundError

        # Decode file ID and get file info
        file_id = FileId.decode(media.file_id)
        file_size = media.file_size
        
        # Parse range header for partial content
        range_header = request.headers.get("Range", 0)
        from_bytes, until_bytes = 0, file_size - 1
        
        if range_header:
            # Parse bytes=start-end
            from_bytes_str, until_bytes_str = range_header.replace("bytes=", "").split("-")
            from_bytes = int(from_bytes_str)
            if until_bytes_str:
                until_bytes = int(until_bytes_str)
        
        # Validate range
        if (until_bytes >= file_size) or (from_bytes < 0):
            raise HTTPException(
                status_code=416, 
                detail="Requested range not satisfiable"
            )
        
        # Calculate chunk parameters
        req_length = until_bytes - from_bytes + 1
        chunk_size = 1024 * 1024  # 1 MB chunks
        
        offset = (from_bytes // chunk_size) * chunk_size
        first_part_cut = from_bytes - offset
        last_part_cut = (until_bytes % chunk_size) + 1
        part_count = math.ceil(req_length / chunk_size)
        
        # Generate stream
        body = tg_connect.yield_file(
            file_id, index, offset, 
            first_part_cut, last_part_cut, 
            part_count, chunk_size
        )
        
        # Prepare response headers
        status_code = 206 if range_header else 200
        headers = {
            "Content-Type": media.mime_type or "application/octet-stream",
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{media.file_name}"',
            "Content-Length": str(req_length)
        }
        
        if range_header:
            headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
        
        return StreamingResponse(
            content=body, 
            status_code=status_code, 
            headers=headers
        )
        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found on Telegram.")
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in /dl route: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal streaming error.")
