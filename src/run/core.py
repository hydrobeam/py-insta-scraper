import json
import concurrent.futures
import time
from dataclasses import dataclass
from pathlib import Path
from pprint import pprint
from typing import List, Set, Iterable
from src.config.config import config

import requests
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
import asyncio
import aiohttp
import aiofiles
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait


@dataclass
class Post:
    url: str
    url_id: str  # effectively the "id" of the post
    is_video: bool

    def __post_init__(self):
        self.set_extenstion()
        self.set_folder()

    @classmethod
    def from_node(cls, node: dict):
        """Accepts a node that represents a dictionary of a post,
        and returns a Post object."""

        if video_candidate_list := node.get("video_versions"):
            # get first candidate from list because that's the highest quality one
            target_post = video_candidate_list[0]
            url_id = target_post["id"]
            is_video = True
        else:
            target_post = node["image_versions2"]["candidates"][0]
            url_id = node["id"]
            is_video = False

        return cls(url=target_post["url"], url_id=url_id, is_video=is_video)

    def set_extenstion(self):
        if self.is_video:
            extension = "mp4"
        else:
            extension = "jpg"

        self.extension = extension

    def set_folder(self):
        if self.is_video:
            tert_folder = "vid"
        else:
            tert_folder = "img"

        self.tert_folder = tert_folder


def get_urls(driver, num_urls: int) -> Set[str]:
    """Scrolling and collecting links.

    num_urls refers to the amount of urls we know should exist

    """

    driver.execute_script("document.body.style.zoom = '40%'")
    posts = set()
    ignored_exceptions = (
        NoSuchElementException,
        StaleElementReferenceException,
    )

    while len(posts) < num_urls:
        # https://stackoverflow.com/questions/27003423/staleelementreferenceexception-on-python-selenium
        # basically: wait until the page loads before trying to collect links

        time.sleep(0.5)
        links = WebDriverWait(driver, 20, ignored_exceptions=ignored_exceptions).until(
            expected_conditions.presence_of_all_elements_located((By.TAG_NAME, "a"))
        )

        time.sleep(0.5)
        # --- end of copypasta --- #

        for link in links:
            post = link.get_attribute("href")
            if "/p/" in post:
                posts.add(post)

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")



    print(f"{posts=}")
    return posts


def create_text_post_file(url_list: Set[str], num_posts: int, text_post: Path):
    """Creates a text_post file to track which urls have been visisted.

    Made use of in case no new posts have been made, then don't bother with re-obtaining
    urls.
    """
    if len(url_list) == num_posts:
        with text_post.open(mode="w") as file:
            for url in url_list:
                file.write(f"{url}\n")
    else:
        print("INCOMPLETE url_list !!!")

async def get_post(url: str, session: aiohttp.ClientSession) -> list[Post]:
    # https://stackoverflow.com/questions/72467565/error-when-scraping-instagram-media-by-adding-at-the-end-of-url-a-1
    # no idea why this fucking works

    async with session.get(f"{url}?__a=1&__d=dis") as resp:
        post_list: list[Post] = []
        json_data: dict = await resp.json()
        if json_data.get("spam"):
            print("SPAM DETECTED")

        post_info: dict = json_data["items"][0]

        # present if there are multiple posts
        if carousel_media := post_info.get("carousel_media"):
            for subpost_info in carousel_media:
                post_list.append(Post.from_node(subpost_info))
        else:
            post_list.append(Post.from_node(post_info))

        return post_list

async def get_posts(url_list: Iterable[str], session: aiohttp.ClientSession) -> List[Post]:
    post_list: list[list[Post]]


    tasks = []
    for url in url_list:
        pprint(f"{url}")
        tasks.append(get_post(url, session))


    post_list =  await asyncio.gather(*tasks)
    return_list = [item for sublist in post_list for item in sublist]
    # import ipdb; ipdb.set_trace(context=7)



    pprint(f"{len(return_list)=}")
    return return_list


async def write_content(post: Post, dest_folder: Path, session: aiohttp.ClientSession):
    """Actually writes the post url to file"""
    open_sesame = f"{dest_folder}/{post.tert_folder}/{post.url_id}.{post.extension}"
    if Path(open_sesame).exists():
        # don't rewrite existing files, id is always the same
        pass
    else:
        print(f"Writing at {open_sesame}")
        stuff = await session.get(post.url)
        async with aiofiles.open(open_sesame, "wb") as file:
            async for chunk in stuff.content.iter_chunked(1024):
                await file.write(chunk)


async def save_media(post_list: List[Post], dest_folder: Path, session: aiohttp.ClientSession):
    """Asynchronously download multiple files at once from the post_list."""

    tasks = []

    for post in post_list:
        tasks.append(write_content(post, dest_folder, session))

    await asyncio.gather(*tasks)


def login(driver):
    driver.get("https://www.instagram.com")
    driver.implicitly_wait(10)

    username_pass = driver.find_elements(By.TAG_NAME, "input")
    user = config.data["auth"]["username"]
    password = config.data["auth"]["password"]

    username_pass[0].send_keys(user)
    username_pass[1].send_keys(password)

    login = driver.find_elements(By.CSS_SELECTOR, "button")

    # import ipdb; ipdb.set_trace(context=10)
    try:
        login[7].click()  # cookie options on vpn
        time.sleep(4)
    except IndexError:
        pass

    login[1].click()  # is the first button, (i assume logo is first)
    time.sleep(7)  # sleep for long enough so that the instagram page loads



async def main():
    driver = webdriver.Firefox()
    login(driver)

    cookies = driver.get_cookies()
    session = aiohttp.ClientSession()

    # generate: [key, value] par for cookie
    # inspired by
    # https://stackoverflow.com/questions/29563335/how-do-i-load-session-and-cookies-from-selenium-browser-to-requests-library-in-p

    cookie_mapping = [(cookie["name"],cookie["value"]) for cookie in cookies]
    session.cookie_jar.update_cookies(cookie_mapping)
    for user_profile in config.data["insta"]["insta_user_list"]:
        print(f"Querying: {user_profile}")

        dest_folder = (
            Path(__file__).parent.parent.parent
            / f"{config.data['file']['output_location']}/{user_profile}"
        )
        Path(dest_folder).mkdir(parents=True, exist_ok=True)
        Path(f"{dest_folder}/img").mkdir(exist_ok=True)
        Path(f"{dest_folder}/vid").mkdir(exist_ok=True)
        text_post = Path(f"{dest_folder}/post_list.txt")

        try:
            driver.get(f"https://www.instagram.com/{user_profile}")  # made it
            time.sleep(3)
        except:
            print(f"User {user_profile} not found.")
            continue

        # find number of posts

        num_posts: int = int(
            driver.find_element(By.XPATH, '//div[contains(text(), " posts")]').text.split(
                " "
            )[0]
        )

        pprint(f"{num_posts=}")

        if driver.page_source.find("This Account is Private") >= 0:
            print(f"User: {user_profile} is private")
            continue

        if text_post.exists():
            with text_post.open() as file:
                potential_url_list = file.read().splitlines()
                print(f"len_posts_url {potential_url_list.__len__()}")

            if len(potential_url_list) == num_posts:
                url_list = potential_url_list
            else:
                url_list = get_urls(driver, num_posts)
                create_text_post_file(url_list, num_posts, text_post)
        else:
            url_list = get_urls(driver, num_posts)
            create_text_post_file(url_list, num_posts, text_post)


        post_list = await get_posts(url_list, session)

        pprint(f"num_links = {len(url_list)}")

        await save_media(post_list, dest_folder, session)
        print(f"Wrote all content for {user_profile}")

    await session.close()

asyncio.run(main())
