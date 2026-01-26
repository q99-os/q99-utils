from http.client import HTTPException
from typing import List, Optional
import httpx

from q99_utils.environment import USER_MANAGER_URL
from q99_utils.models import OnboardingData, UMMessage

class UserManagerSDK:
    def __init__(self, access_token:str) -> None:
        self.access_token = access_token
        self._client = httpx.AsyncClient(timeout=30.0)
        
    async def _request(
        self,
        method: str,
        url: str,
        headers: dict = None,
        params: dict = None,
        json: dict = None,
        clean_output: bool = False
    ):
        headers = headers or {}
        headers["Authorization"] = self.access_token

        try:
            response = await self._client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"User Manager unavailable: {exc}"
            )# UM does not respond

        if response.status_code > 400:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.text
            ) # Internal SDK, we don't need raise for status traces.

        if clean_output:
            raw_string = response.content.decode('utf-8').strip('"')
            cleaned_config_data = raw_string.encode('utf-8').decode('unicode_escape')
            return cleaned_config_data
        return response.json()

    async def get_credential(self, source: str | None = None, integration_type: str | None = None):
        url = f"{USER_MANAGER_URL}/v1/credentials/"
        params = {}
        if source:
            params["source"] = source
        if integration_type:
            params["integration-type"] = integration_type
        
        return await self._request(method="GET", url=url, params=params)

    async def post_credentials(self, data: OnboardingData):
        url = f"{USER_MANAGER_URL}/v1/credentials/"
        
        return await self._request(method="POST", url=url, json=data.model_dump(exclude_none=True))

    async def update_credentials(self, data, credential_id: str):
        update_url = f"{USER_MANAGER_URL}/v1/credentials/{credential_id}/"

        return await self._request(method="PUT", url=update_url, json=data.model_dump())

    async def activate_credential(self, id:str):
        patch_url = f"{USER_MANAGER_URL}/v1/credentials/{id}/"
        
        return await self._request(method="PATCH", url=patch_url, json={"is_active": True})

    async def validate_token(self):
        auth_url = f"{USER_MANAGER_URL}/v1/validate/"

        return await self._request(method="GET", url=auth_url, clean_output=True)

    async def get_current_user_info(self):
        user_info_url = f"{USER_MANAGER_URL}/v1/user/info/"
        
        return await self._request(method="GET", url=user_info_url)
    
    async def get_conversation_history(self, conversation_id: str):
        conversation_url = f"{USER_MANAGER_URL}/v1/history/conversation/{conversation_id}/"
        
        return await self._request(method="GET", url=conversation_url)
        
    async def get_branch_history(self, interaction_id: str, normalize: bool=False, add_last_msg: bool=False):
        interaction_url = f"{USER_MANAGER_URL}/v1/history/conversation/{interaction_id}/branch/"

        branch_content = await self._request(method="GET", url=interaction_url)
            
        interactions = branch_content["chats"]
        
        if add_last_msg:
            last_msg_content = interactions[-1]["messages"][-1]
            if last_msg_content["type"] != "Interruption":
                raise ValueError(f"'{interaction_id}' does not correspond to an active interruption.")
            
            branch_content["last_msg"] = last_msg_content
            
        if interactions[-1]["status"] == "Stopped": # Removal of "stopped" questions. 
            interactions.pop()
        
        if normalize: # UM to ChatCompletions API Mapping
            messages = []
            for interaction in interactions: # chat = interaction
                for msg in interaction["messages"]:
                    # Skip error messages - they shouldn't be part of chat history
                    if msg["type"] == "Error":
                        continue
                    messages.append( 
                        {
                            "role":"assistant" if msg["type"] in {"Answer","Interruption"} else "user", 
                            "content":msg["content"]
                        }
                    )
            branch_content["messages"] = messages
            
        return branch_content  
    
    async def add_interaction_message(self, interaction_id: str, message: UMMessage):
        interaction_url = f"{USER_MANAGER_URL}/v1/history/conversation/add-message/"

        payload = {
            "interaction_id": interaction_id,
            "type": message.type,
            "content": message.content,
            "metadata": message.metadata
        }

        return await self._request(method="POST", url=interaction_url, json=payload)
        
    async def add_interaction(self,
                            message:UMMessage,
                            conversation_id:Optional[str] = None,
                            parent_interaction_id:Optional[str] = None,
                            title:Optional[str] = None,
                            ):
        chat_url = f"{USER_MANAGER_URL}/v1/history/conversation/"

        payload = {"messages":[message.model_dump()]}
        
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id
        if parent_interaction_id is not None:
            payload["parent_interaction"] = parent_interaction_id # que alguien me explique porq este no tiene id ._. // Porque no todos tienen ocd como vos'
        if title is not None:
            payload["title"] = title
        
        return await self._request(method="POST", url=chat_url, json=payload)
        
    async def patch_interaction(self, interaction_id:str, json:dict):
        interaction_url = f"{USER_MANAGER_URL}/v1/interaction/{interaction_id}/"
        
        return await self._request(method="PATCH", url=interaction_url, json=json)
        
    async def patch_conversation(self, conversation_id:str, json:dict):
        conversation_url = f"{USER_MANAGER_URL}/v1/history/conversation/{conversation_id}/"

        return await self._request(method="PATCH", url=conversation_url, json=json)
        
    async def patch_message(self, message_id:str, json:dict):
        message_url = f"{USER_MANAGER_URL}/v1/messages/{message_id}/"
        
        return await self._request(method="PUT", url=message_url, json=json)
        
    async def add_tag(self, tag: str):
        tag_url = f"{USER_MANAGER_URL}/v1/tags/"
        
        return await self._request(method="POST", url=tag_url, params={"tag":tag})
        
    async def get_tags(self):
        tag_url = f"{USER_MANAGER_URL}/v1/tags/"
        
        return await self._request(method="GET", url=tag_url)
        
    async def set_tags(self, conversation_id:str, tags_ids:List[str]):
        url = f"{USER_MANAGER_URL}/v1/history/conversation/{conversation_id}/set-tags/"

        return await self._request(method="POST", url=url, params={"tags":tags_ids})