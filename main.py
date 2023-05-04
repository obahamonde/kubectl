"""Application endpoints"""
import os
import re
from uuid import uuid4
import json
import asyncio
import jinja2
from dotenv import load_dotenv
from aiofauna import Api
from aiohttp import ClientSession
from kubectl.config import env
from kubectl.client import client
from kubectl.models import User, Upload
from kubectl.utils import gen_port
from kubectl.payload import RepoBuildPayload
from kubectl.handlers import (
    upload_handler,
    DOCKER_URL,
    GITHUB_URL,
    GITHUB_HEADERS,
    CLOUDFLARE_URL,
    CLOUDFLARE_HEADERS,
    docker_pull,
    get_latest_commit_sha,
)  # pylint: disable=unused-import, line-too-long

load_dotenv()

app = Api()

#### Healthcheck Endpoint ####


@app.get("/")
async def healthcheck():
    """Healthcheck Endpoint"""
    return {"message": "Accepted", "status": "success"}


#### Authorizer ####


@app.get("/api/auth")
async def authorize(token: str):
    """Authorization Endpoint"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://{env.AUTH0_DOMAIN}/userinfo"
    user_dict = await client.fetch(url, headers=headers)
    return await User(**user_dict).save()


#### Bucket obj Endpoints ####


@app.delete("/api/upload")
async def delete_upload(ref: str):
    """Delete an uploaded file given it's document reference"""
    await Upload.delete(ref)
    return {"message": "Asset deleted successfully", "status": "success"}


@app.get("/api/upload")
async def get_upload(user: str):
    """Fetch Uploaded files for a given user"""
    return await Upload.find_many("user", user)


app.router.add_post("/api/upload", upload_handler)  # type: ignore
app.openapi["paths"].setdefault(
    "/api/upload",
    {
        "post": {
            "summary": "Upload a file",
            "parameters": [
                {
                    "name": "key",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                },
                {
                    "name": "size",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "integer"},
                },
            ],
            "requestBody": {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "file": {"type": "string", "format": "binary"}
                            },
                        }
                    }
                }
            },
            "responses": {"200": {"description": "File uploaded successfully"}},
        }
    },
)

##### Pipeline Endpoints #####

app.router.add_get("/api/docker/pull", docker_pull)  # type: ignore


async def docker_build_from_github_tarball(owner: str, repo: str):
    """
    Builds a Docker image from the latest code for the given GitHub repository.
    :param owner: The owner of the repository.
    :param repo: The name of the repository.
    :return: The output of the Docker build.
    """
    sha = await get_latest_commit_sha(owner, repo)
    tarball_url = f"https://api.github.com/repos/{owner}/{repo}/tarball/{sha}"
    local_path = f"{owner}-{repo}-{sha[:7]}"
    build_args = json.dumps({"LOCAL_PATH": local_path})
    async with ClientSession() as session:
        async with session.post(
            f"{DOCKER_URL}/build?remote={tarball_url}&dockerfile={local_path}/Dockerfile&buildargs={build_args}"
        ) as response:
            streamed_data = await response.text()
            id_ = streamed_data.split("Successfully built ")[1].split("\\n")[0]
            return id_
    
async def create_dns_record(name: str):
    """
    Create a record.
    """
    payload =  {"type": "A", "name": name, "content": env.IP_ADDR, "ttl": 1, "proxied": True}
    
    return await client.fetch(
        f"https://api.cloudflare.com/client/v4/zones/{env.CF_ZONE_ID}/dns_records",
        "POST",
        headers=CLOUDFLARE_HEADERS,
        data=payload,
    )
    
async def start_container(container: str):
    return await client.text(f"{DOCKER_URL}/containers/{container}/start", "POST")



@app.post("/api/github/deploy/{owner}/{repo}")
async def deploy_container_from_repo(
    owner:str, repo:str, port: int = 8080, env_vars: str = "DOCKER=1"
):
    name = f"{owner}-{repo}-{str(uuid4())[:8]}"
    image = await docker_build_from_github_tarball(owner, repo)
    if "error" in image:
        return image
    host_port = str(gen_port())
    payload = {
        "Image": image,
        "Env": env_vars.split(","),
        "ExposedPorts": {f"{str(port)}/tcp": {"HostPort": host_port}},
        "HostConfig": {"PortBindings": {f"{str(port)}/tcp": [{"HostPort": host_port}]}},
    }
    container = await client.fetch(
        f"{DOCKER_URL}/containers/create?name={name}",
        "POST",
        headers={"Content-Type": "application/json"},
        data=payload,
    )
    try:
        _id = container["Id"]
        await start_container(_id)
        res = await create_dns_record(name)
        jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader("templates"))
        template = jinja_env.get_template("nginx.conf")
        nginx_config = template.render(
            name=name, port=port, host_port=host_port, ip=env.IP_ADDR
        )
        for path in ["/etc/nginx/conf.d","/etc/nginx/sites-enabled",
    "/etc/nginx/sites-available"]:
            try:
                os.remove(f"{path}/{name}.conf")
            except:
                pass
            with open(f"{path}/{name}.conf", "w") as f:
                f.write(nginx_config)
        os.system("nginx -s reload")
        data = await client.fetch(f"{DOCKER_URL}/containers/{_id}/json")
        return {
            "url": f"{name}.smartpro.solutions",
            "port": host_port,
            "container": data,
            "dns": res,
        }
    except KeyError:
        return container