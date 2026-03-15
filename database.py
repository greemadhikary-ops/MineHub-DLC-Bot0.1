# database.py - MongoDB Database Handler for Telegram Stream Bot

import motor.motor_asyncio
from config import Config

class Database:
    """
    MongoDB database handler for storing file links.
    Supports both persistent (MongoDB) and non-persistent modes.
    """
    
    def __init__(self):
        self._client = None
        self.db = None
        self.collection = None
        self.links_cache = {}  # In-memory cache for non-persistent mode
        
        if not Config.DATABASE_URL:
            print("⚠️ WARNING: DATABASE_URL not configured. Links will be stored in memory only and will not persist after restart!")

    async def connect(self):
        """
        Establish database connection.
        Falls back to in-memory storage if no database URL provided.
        """
        if Config.DATABASE_URL:
            print("📡 Connecting to MongoDB database...")
            try:
                self._client = motor.motor_asyncio.AsyncIOMotorClient(Config.DATABASE_URL)
                self.db = self._client["StreamLinksDB"]
                self.collection = self.db["links"]
                
                # Create index for better performance
                await self.collection.create_index('_id', unique=True)
                
                print("✅ Database connection established successfully.")
            except Exception as e:
                print(f"❌ Database connection failed: {e}")
                print("⚠️ Falling back to in-memory storage!")
                self.db = None
                self.collection = None
        else:
            print("📝 Using in-memory storage (links will be temporary)")
            self.db = None
            self.collection = None

    async def disconnect(self):
        """
        Close database connection gracefully.
        """
        if self._client:
            self._client.close()
            print("🔌 Database connection closed.")

    async def save_link(self, unique_id: str, message_id: int) -> bool:
        """
        Save a file link mapping to database.
        
        Args:
            unique_id: Unique identifier for the link
            message_id: Telegram message ID in storage channel
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            if self.collection is not None:
                # Save to MongoDB
                await self.collection.insert_one({
                    '_id': unique_id, 
                    'message_id': message_id,
                    'created_at': self._get_timestamp()
                })
                print(f"💾 Link saved to database: {unique_id}")
            else:
                # Save to in-memory cache
                self.links_cache[unique_id] = {
                    'message_id': message_id,
                    'created_at': self._get_timestamp()
                }
                print(f"💾 Link saved to memory: {unique_id}")
            
            return True
            
        except Exception as e:
            print(f"❌ Error saving link: {e}")
            return False

    async def get_link(self, unique_id: str) -> int | None:
        """
        Retrieve message_id for a given unique_id.
        
        Args:
            unique_id: Unique identifier for the link
            
        Returns:
            int | None: Message ID if found, None otherwise
        """
        try:
            if self.collection is not None:
                # Get from MongoDB
                doc = await self.collection.find_one({'_id': unique_id})
                if doc:
                    print(f"📖 Link retrieved from database: {unique_id}")
                    return doc.get('message_id')
            else:
                # Get from in-memory cache
                if unique_id in self.links_cache:
                    print(f"📖 Link retrieved from memory: {unique_id}")
                    return self.links_cache[unique_id]['message_id']
            
            print(f"❌ Link not found: {unique_id}")
            return None
            
        except Exception as e:
            print(f"❌ Error retrieving link: {e}")
            return None

    async def delete_link(self, unique_id: str) -> bool:
        """
        Delete a link from database.
        
        Args:
            unique_id: Unique identifier for the link
            
        Returns:
            bool: True if deleted successfully, False otherwise
        """
        try:
            if self.collection is not None:
                # Delete from MongoDB
                result = await self.collection.delete_one({'_id': unique_id})
                if result.deleted_count > 0:
                    print(f"🗑️ Link deleted from database: {unique_id}")
                    return True
            else:
                # Delete from in-memory cache
                if unique_id in self.links_cache:
                    del self.links_cache[unique_id]
                    print(f"🗑️ Link deleted from memory: {unique_id}")
                    return True
            
            return False
            
        except Exception as e:
            print(f"❌ Error deleting link: {e}")
            return False

    async def link_exists(self, unique_id: str) -> bool:
        """
        Check if a link exists.
        
        Args:
            unique_id: Unique identifier for the link
            
        Returns:
            bool: True if exists, False otherwise
        """
        if self.collection is not None:
            doc = await self.collection.find_one({'_id': unique_id})
            return doc is not None
        else:
            return unique_id in self.links_cache

    async def get_all_links(self) -> list:
        """
        Get all stored links (for debugging/admin purposes).
        
        Returns:
            list: List of all links
        """
        links = []
        try:
            if self.collection is not None:
                cursor = self.collection.find({})
                async for doc in cursor:
                    links.append({
                        'unique_id': doc['_id'],
                        'message_id': doc['message_id'],
                        'created_at': doc.get('created_at')
                    })
            else:
                for unique_id, data in self.links_cache.items():
                    links.append({
                        'unique_id': unique_id,
                        'message_id': data['message_id'],
                        'created_at': data.get('created_at')
                    })
            
            return links
            
        except Exception as e:
            print(f"❌ Error getting all links: {e}")
            return []

    def _get_timestamp(self):
        """
        Get current timestamp for record keeping.
        """
        from datetime import datetime
        return datetime.utcnow().isoformat()

    @property
    def is_connected(self) -> bool:
        """
        Check if database is connected.
        
        Returns:
            bool: True if connected to MongoDB, False for in-memory
        """
        return self._client is not None and self.collection is not None

# Global database instance
db = Database()
