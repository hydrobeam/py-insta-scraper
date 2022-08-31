import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from pprint import pprint

import aiofiles
import aiohttp
import toml
from aiohttp.client_exceptions import ContentTypeError
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
    followed_by_viewer: bool

    def __post_init__(self):
        self.can_view = (self.followed_by_viewer and self.is_private) or (
            not self.is_private
        )

    @classmethod
    def from_node(cls, node: dict):
        """Initialize a user from the json ouptput of Endpoints.account_json()."""

        try:
            user_json = node["graphql"]["user"]
        except:
            pprint(node)

        id = user_json["id"]
        username = user_json["username"]
        num_followers = user_json["edge_followed_by"]["count"]
        num_posts = user_json["edge_owner_to_timeline_media"]["count"]
        is_private = user_json["is_private"]
        followed_by_viewer = user_json["followed_by_viewer"]

        return cls(
            id=id,
            username=username,
            num_followers=num_followers,
            num_posts=num_posts,
            is_private=is_private,
            followed_by_viewer=followed_by_viewer,
        )


@dataclass
class Post:
    url: str
    id: str  # effectively the "id" of the post
    is_video: bool

    def __post_init__(self):
        self.extension = "mp4" if self.is_video else "jpg"
        self.tert_folder = "vid" if self.is_video else "img"

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

        return cls(
            url=url,
            id=node["id"],
            is_video=is_video,
        )


async def get_posts(
    session: aiohttp.ClientSession, user: User
) -> tuple[list[Post], int]:
    """Query endpoints to assemble a list of Posts to download.


    Returns
    -------
        A tuple consisting of the number of media files, and the number of posts
    actually queried. Done this way to verify if there are discrepancies between the number
    of reported posts, and the number of posts available to us.
    """

    total_post_list: list[Post] = []

    end_cursor: str = ""
    has_next_page: bool = True

    # counter for how many posts we hit
    counter = 0

    while has_next_page:
        # connection rodeo
        while True:
            resp = await session.get(
                Endpoints.account_medias(user_id=user.id, after=end_cursor)
            )
            if not resp.ok:
                if resp.status == 429:
                    print("Hit API Limit")
                    await asyncio.sleep(120) # wait for a minute and try again
                elif resp.status == 404:
                    print(f"HIT 404: {user.username} does not exist")
                    import ipdb; ipdb.set_trace(context=7)
                elif resp.status == 560:
                    # https://lightrun.com/answers/instaloader-instaloader-instagram-560-errors-when-trying-to-download-stories-from-lots-of-accounts
                    print("Insta is ??? + API limit (maybe?)")
                    await asyncio.sleep(120)
            elif not await resp.json():
                # no idea why this doesn't return a 404 when the user doesn't exist
                # but the spelling is close?
                print(f"EMPTY JSON: {user.username} does not exist")
                import ipdb; ipdb.set_trace(context=7)
            else:
                break

        json_result: dict = await resp.json()
        timeline_media = json_result["data"]["user"][
            "edge_owner_to_timeline_media"]


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

    return (total_post_list, counter)


async def write_content(post: Post, dest_folder: Path, session: aiohttp.ClientSession):
    """Actually writes the post url to file"""
    open_sesame = f"{dest_folder}/{post.tert_folder}/{post.id}.{post.extension}"
    if Path(open_sesame).exists():
        # don't rewrite existing files, id is always the same
        pass
    else:
        while True:
            try:
                stuff = await session.get(post.url)

                async with aiofiles.open(open_sesame, "wb") as file:
                    async for data in stuff.content.iter_chunked(1024):
                        await file.write(data)

                break
            except Exception as e:
                print(f"Error at: {post.id}\nException: {e}")


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
        login[7].click()  # cookie options on vpn in EU
        time.sleep(3)
    except IndexError:
        pass

    login[1].click()  # is the first button, (i assume logo is first)
    time.sleep(6)  # sleep for long enough so that the instagram page loads


async def core_func(session: aiohttp.ClientSession, user_profile: str):
    failed_api_count  = 1
    while True:
        resp = await session.get(Endpoints.account_json(user_profile))
        if not resp.ok:
            if resp.status == 429:
                print(f"Hit API Limit: {failed_api_count=}")
                failed_api_count+=1
                await asyncio.sleep(120) # wait for a minute and try again
            elif resp.status == 404:
                print(f"HIT 404: {user_profile} does not exist")
                return
            elif resp.status == 560:
                # https://lightrun.com/answers/instaloader-instaloader-instagram-560-errors-when-trying-to-download-stories-from-lots-of-accounts
                print("Insta is ??? + API limit (maybe?)")
                await asyncio.sleep(120)
        elif not await resp.json():
            # no idea why this doesn't return a 404 when the user doesn't exist
            # but the spelling is close?
            print(f"EMPTY JSON: {user_profile} does not exist")
            return
        else:
            break

    user = User.from_node(await resp.json())

    if not user.can_view:
        print(f"Do not have permission to view user: {user.username}")
        await session.post(Endpoints.follow(user.id))
        print(f"Requested to follow: {user.username}")
        return


    dest_folder = (
        Path(__file__).parent.parent
        / f"{config.data['file']['output_location']}/{user.username}"
    )
    dest_folder.mkdir(parents=True, exist_ok=True)
    (dest_folder / "img").mkdir(exist_ok=True)
    (dest_folder / "vid").mkdir(exist_ok=True)

    cache_file: Path = dest_folder / "cache.toml"

    # whether we should query
    queryp = True
    if cache_file.exists():
        cached_content = toml.load(cache_file)
        if cached_content["expected_post_count"] == user.num_posts:
            print(f"No action needed for {user.username}")
            queryp = False

    if queryp:
        print(f"Querying: {user.username}")
        media_list, post_number = await get_posts(session, user)
        await save_media(media_list, dest_folder, session)
        print(f"Wrote all content for {user.username}")

        async with aiofiles.open(cache_file, "w") as file:
            content = {
                "observed_post_count": post_number,
                "expected_post_count": user.num_posts,
                "media_item_count": len(media_list),
                "query_time": datetime.now(),
            }
            pprint(f"{user.username}: {content}")
            await file.write(toml.dumps(content))


async def main():
    driver_options = Options()
    # don't need to see the logging in happening
    # driver_options.headless = True
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
    session.cookie_jar.update_cookies(cookie_mapping)

    tasks = []
    for user_profile in config.data["insta"]["insta_user_list"]:
        tasks.append(core_func(session, user_profile))

    await asyncio.gather(*tasks)

    await session.close()


asyncio.run(main())
