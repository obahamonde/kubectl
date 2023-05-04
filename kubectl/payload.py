"""

Request Payloads

"""

from typing import List as L, Optional as O # pylint: disable=unused-import
from pydantic import BaseModel, Field # pylint: disable=no-name-in-module
from kubectl.utils import gen_port

class RepoBuildPayload(BaseModel):
    """
    
    Repository build payload

    """
    owner: str = Field(..., description="Repository owner")
    repo: str = Field(..., description="Repository name")
    port:O[int] = Field(default_factory=gen_port, description="Port to expose")
    env_vars:L[str] = Field([], description="Environment variables")
    cmd:L[str] = Field([], description="Command to run") 
        
        
    
    
  
    

    