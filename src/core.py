import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from pprint import pprint

import aiofiles
import aiohttp
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from config.config import config
from utils.endpoints import Endpoints


@dataclass
class User:
    id: str
    username: str
    num_followers: int
    num_posts: int
    is_private: bool
    can_view: bool

    @classmethod
    def from_node(cls, node: dict):
        """Initialize a user from the json ouptput of Endpoints.account_json()."""

        try:
            user_json = node["graphql"]["user"]
        except KeyError:
            raise (
                Exception(f"Failed with: {node['message']}, status: {node['status']}")
            )

        id = user_json["id"]
        username = user_json["username"]
        num_followers = user_json["edge_followed_by"]["count"]
        num_posts = user_json["edge_owner_to_timeline_media"]["count"]

        is_private = user_json["is_private"]
        if not user_json["followed_by_viewer"] and is_private:
            can_view = False
        else:
            can_view = True

        return cls(
            id=id,
            username=username,
            num_followers=num_followers,
            num_posts=num_posts,
            is_private=is_private,
            can_view=can_view,
        )


@dataclass
class Post:
    url: str
    id: str  # effectively the "id" of the post
    is_video: bool
    extension: str
    tert_folder: str

    @classmethod
    def from_node(cls, node: dict):
        """Accepts a node that represents a dictionary of a post,
        and returns a Post object."""

        if node["is_video"]:
            url = node["video_url"]
            is_video = True
        else:
            url = node["display_url"]
            is_video = False

        extension = "mp4" if is_video else "jpg"
        tert_folder = "vid" if is_video else "img"

        return cls(
            url=url,
            id=node["id"],
            is_video=is_video,
            extension=extension,
            tert_folder=tert_folder,
        )


async def get_posts(session: aiohttp.ClientSession, user: User) -> list[Post]:
    """Query endpoints to assemble a list of Posts to download."""

    total_post_list: list[Post] = []

    end_cursor: str = ""
    has_next_page: bool = True

    # counter for how many posts we hit
    counter = 0

    while has_next_page:
        async with session.get(
            Endpoints.account_medias(user_id=user.id, after=end_cursor)
        ) as resp:
            json_result: dict = await resp.json()

            try:
                timeline_media = json_result["data"]["user"][
                    "edge_owner_to_timeline_media"
                ]
            except KeyError:
                raise (
                    Exception(
                        f"Failed with: {json_result['message']}, status: {json_result['status']}"
                    )
                )

            has_next_page = timeline_media["page_info"]["has_next_page"]
            end_cursor = timeline_media["page_info"]["end_cursor"]

            # list of up to``count`` posts of the user
            media_list = timeline_media["edges"]

            for post in media_list:
                post_list: list[Post] = []

                node = post["node"]
                # if there are multiple media items in this singular post
                if (sidecar := node.get("edge_sidecar_to_children")) is not None:
                    for subnode in sidecar["edges"]:
                        post_list.append(Post.from_node(subnode["node"]))
                else:
                    post_list.append(Post.from_node(node))

                counter += 1
                total_post_list += post_list

    print(f"Observed {counter} posts out of {user.num_posts} for {user.username}")

    return total_post_list


async def write_content(post: Post, dest_folder: Path, session: aiohttp.ClientSession) -> Post | None:
    """Actually writes the post url to file"""
    open_sesame = f"{dest_folder}/{post.tert_folder}/{post.id}.{post.extension}"
    if Path(open_sesame).exists():
        # don't rewrite existing files, id is always the same
        pass
    else:
        succeeded = False
        while not succeeded:
            try:
                stuff = await session.get(post.url)
                succeeded = True
            except TimeoutError:
                print(f"TimeoutError at: {post.url}")


        async with aiofiles.open(open_sesame, "wb") as file:
            async for data in stuff.content.iter_any():
                await file.write(data)


async def save_media(
    post_list: list[Post], dest_folder: Path, session: aiohttp.ClientSession
):
    """Asynchronously download multiple files at once from the post_list."""

    tasks = []

    for post in post_list:
        tasks.append(write_content(post, dest_folder, session))

    return await asyncio.gather(*tasks)


def login(driver):
    driver.get(Endpoints.BASE_URL)
    driver.implicitly_wait(10)

    username_pass = driver.find_elements(By.TAG_NAME, "input")
    user = config.data["auth"]["username"]
    password = config.data["auth"]["password"]

    username_pass[0].send_keys(user)
    username_pass[1].send_keys(password)

    login = driver.find_elements(By.CSS_SELECTOR, "button")

    try:
        login[7].click()  # cookie options on vpn
        time.sleep(3)
    except IndexError:
        pass

    login[1].click()  # is the first button, (i assume logo is first)
    time.sleep(4)  # sleep for long enough so that the instagram page loads


async def core_func(session: aiohttp.ClientSession, user_profile: str):
    json_user: dict = await (
        await session.get(Endpoints.account_json(user_profile))
    ).json()

    # if unempty
    if json_user:
        user = User.from_node(json_user)
    else:
        print(f"User: {user_profile} does not exist")
        return

    if not user.can_view:
        print(f"Do not have permission to view user: {user.username}")
        return

    print(f"Querying: {user_profile}")

    dest_folder = (
        Path(__file__).parent.parent
        / f"{config.data['file']['output_location']}/{user_profile}"
    )
    Path(dest_folder).mkdir(parents=True, exist_ok=True)
    Path(f"{dest_folder}/img").mkdir(exist_ok=True)
    Path(f"{dest_folder}/vid").mkdir(exist_ok=True)

    post_list = await get_posts(session, user)

    print(f"{len(post_list)} posts detected for {user.username}")

    await save_media(post_list, dest_folder, session)

    print(f"Wrote all content for {user_profile}")


async def main():
    driver_options = Options()
    # don't need to see the logging in happening
    driver_options.headless = True
    # might improve performance? source:
    # https://stackoverflow.com/a/53657649
    driver_options.add_argument("--disable-extensions")

    driver = webdriver.Chrome(options=driver_options)
    login(driver)

    # limit the number of requests since we run into OSErrors
    # default is 100
    # did some testing to get at this value, anything over 25
    # is gg for large requests
    connector = aiohttp.TCPConnector(limit=5)
    cookies = driver.get_cookies()
    session = aiohttp.ClientSession(connector=connector)

    # generate: [key, value] par for cookie
    # inspired by
    # https://stackoverflow.com/questions/29563335/how-do-i-load-session-and-cookies-from-selenium-browser-to-requests-library-in-p

    cookie_mapping = [(cookie["name"], cookie["value"]) for cookie in cookies]
    pprint(cookies)
    pprint(cookie_mapping)
    session.cookie_jar.update_cookies(cookie_mapping)

    tasks = []
    for user_profile in config.data["insta"]["insta_user_list"]:
        tasks.append(core_func(session, user_profile))

    await asyncio.gather(*tasks)

    await session.close()


asyncio.run(main())
