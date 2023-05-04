"""Application endpoints"""
import os
import re
from uuid import uuid4
import jinja2
from dotenv import load_dotenv
from aiofauna import Api
from kubectl.config import env
from kubectl.client import client
from kubectl.models import User, Upload
from kubectl.utils import gen_port
from kubectl.handlers import (
    upload_handler,
    DOCKER_URL,
    GITHUB_URL,
    GITHUB_HEADERS,
    CLOUDFLARE_URL,
    CLOUDFLARE_HEADERS,
    docker_pull,
    get_latest_commit_sha,
    docker_build_from_github_tarball,
    create_dns_record,
    docker_start
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

@app.post("/api/github/deploy/{owner}/{repo}")
async def deploy_from_repo_endpoint(
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
        await docker_start(_id)
        res = await create_dns_record(name)
        jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader("templates"))
        template = jinja_env.get_template("nginx.conf")
        nginx_config = template.render(
            name=name, port=port
        )
        for path in ["/etc/nginx/conf.d", "/etc/nginx/sites-enabled", "/etc/nginx/sites-available"]:
            with open(f"{path}/{name}.conf", "w", encoding="utf-8") as file_:
                file_.write(nginx_config)
        os.system("nginx -t")
        os.system("nginx -s reload")
        os.system("systemctl restart nginx")
        os.system("systemctl enable nginx")
        os.system("systemctl status nginx")
        data = await client.fetch(f"{DOCKER_URL}/containers/{_id}/json")
        return {
            "url": f"{name}.smartpro.solutions",
            "port": host_port,
            "container": data,
            "dns": res,
        }
    except Exception as e:
        print(e)
        return container