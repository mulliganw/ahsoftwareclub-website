import json

from .models import GroupMessage
from .models import ChatGroup

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import Group


class ChatConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(args, kwargs)
        self.user_name = None
        self.room_group_name = None
        self.room_name = None

    async def connect(self):
        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
        self.room_group_name = f"chat_{self.room_name}"
        self.user_name = await self.get_name()

        # Join room group
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.create_chat_group()

        await self.accept()

        # send a message saying someone connected (and tell the person who connected who's here)
        active_users, active_user_ids= [], []
        users = await self.get_group_users_sync(self.room_name)
        for user in users:
            active_users.append(user.username)
            active_user_ids.append(user.id)
        await self.channel_layer.group_send(self.room_group_name, {
            "type": "chat.connect",
            "username": self.scope["user"].username,
            "active_users": active_users,
            "active_user_ids": active_user_ids
        })
        if(len(active_users) > 1):
            await self.channel_layer.send(self.room_group_name, {
                "type": "chat.load",
                "messages": await self.get_group_messages_sync(await self.get_user_chat_group)
            })

    async def disconnect(self, close_code):
        # tell everyone they left so it removes them from the activeUsers list
        await self.channel_layer.group_send(self.room_group_name, {
            "type": "chat.disconnect",
            "userID": self.scope["user"].id
        })

        # Leave room group
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    # Receive message from WebSocket
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        print(text_data_json)
        if text_data_json["type"] == "message":
            message = text_data_json["message"]
            # Send message to room group
            await self.channel_layer.group_send(
                self.room_group_name, {"type": "chat.message", "message": message, "username": self.user_name}
            )
            
            group = self.get_user_group()
            GroupMessage.objects.create(group=group, author=self.scope["user"], body=message)

        elif text_data_json["type"] == "file":
            data_url = text_data_json["dataURL"]
            await self.channel_layer.group_send(
                self.room_group_name, {"type": "chat.file", "dataURL": data_url, "username": self.user_name}
            )

    # Receive message from room group
    async def chat_message(self, event):
        message = event["message"]
        username = event["username"]

        # Send message to WebSocket
        await self.send(text_data=json.dumps({"type": "chat_message", "message": message, "username":username}))

    async def chat_connect(self, event):
        username = event["username"]
        active_users = event["active_users"]
        active_user_ids = event["active_user_ids"]

        await self.send(text_data=json.dumps({"type": "chat_connect", "username": username, "activeUsers": active_users, "activeUserIDs": active_user_ids}))

    async def chat_load(self, event):
        messages = event["messages"]
        messages_list = []
        for message in messages:
            messages_list.append({"author": message.author.username, "body": message.body})
        await self.send(text_data=json.dumps({"type": "chat_load", "messages": messages_list}))
        
    async def chat_disconnect(self, event):
        userID = event["userID"]
        await self.send(text_data=json.dumps({"type": "chat_disconnect", "userID": userID}))

    async def chat_file(self, event):
        username = event["username"]
        data_url = event["dataURL"]
        await self.send(text_data=json.dumps({"type": "chat_file", "dataURL": data_url, "username": username}))

    @database_sync_to_async
    def get_name(self):
        user = self.scope["user"]
        return user.get_username()

    @sync_to_async
    def get_group_users_sync(self, group_name):
        group = Group.objects.get(name=group_name)
        users_list = list(group.user_set.all())
        return users_list
    
    @sync_to_async
    def get_group_messages_sync(self, chat_group):
        messages = GroupMessage.objects.filter(group=chat_group)
        messages_list = list(messages)
        return messages_list
    
    @sync_to_async
    def get_user_chat_group(self):
        return ChatGroup.objects.filter(group_name=self.room_group_name).all()[0]
    
    @sync_to_async
    def create_chat_group(self):
        ChatGroup.objects.create(group_name=self.room_group_name)