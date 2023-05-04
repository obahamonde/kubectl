"""Non decorated API Request Handlers"""
import botocore
from aiofauna import Request, Response, json_response
from aiohttp_sse import sse_response
from aiohttp.web_request import FileField
from aioboto3 import Session
from kubectl.config import env, CLOUDFLARE_HEADERS, CLOUDFLARE_URL, DOCKER_URL, GITHUB_HEADERS, GITHUB_URL # pylint: disable=unused-import, line-too-long
from kubectl.models import Upload
from kubectl.client import client

session = Session()

# Upload Component
async def upload_handler(request:Request)->Response:
    """
    Upload Endpoint
    """
    data = await request.post()
    params = dict(request.query)
    key = params.get("key")
    size = params.get("size")
    user = params.get("user")
    if key and size and user:
        size = int(size)
        file = data["file"]
        if isinstance(file, FileField):
            async with session.client(service_name="s3", 
            aws_access_key_id=env.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=env.AWS_SECRET_ACCESS_KEY,
            endpoint_url=env.AWS_S3_ENDPOINT,
            config=botocore.config.Config(signature_version="s3v4")) as s3client: # type: ignore
                key_ = f"{key}/{file.filename}" # type: ignore
                await s3client.put_object(Bucket=env.AWS_S3_BUCKET, Key=key_, Body=file.file.read(), ContentType=file.content_type, ACL="public-read")
                url = await s3client.generate_presigned_url("get_object", Params={"Bucket": env.AWS_S3_BUCKET, "Key": key_}, ExpiresIn=3600*7*24)
                upload = await Upload(user=user,key=key_, name=file.filename, size=size, type=file.content_type, url=url).save()
                return json_response(upload.dict())
    return json_response({"message": "Invalid request", "status": "error"}, status=400)

# Docker Pull
async def docker_pull(request:Request)->Response:
    """
    Docker Pull
    """
    params = dict(request.query)
    image = params.get("image")
    
    async with sse_response(request) as resp:
        async for event in client.stream(f"{DOCKER_URL}/images/create?fromImage={image}", "POST"):
            await resp.send(event)
            if "Pull complete" in event:
                await resp.send(event)
                break
        return resp

# Latest Commit SHA
async def get_latest_commit_sha(owner: str, repo: str) -> str:
    """


    Gets the SHA of the latest commit in the repository.


    """

    url = f"https://api.github.com/repos/{owner}/{repo}/commits"

    payload = await client.fetch(url, headers=GITHUB_HEADERS)
    
    return payload[0]["sha"] 
