from pathlib import Path
from urllib.parse import urlparse, quote
import json
import shutil
import os

import httpx
from playwright.sync_api import sync_playwright


def get_note_id(url: str) -> str:
    """
    从小红书笔记 URL 中提取 note_id
    """
    path = urlparse(url).path
    return path.rstrip("/").split("/")[-1]


def normalize_image_url(url: str) -> str:
    """
    用 URL path 作为去重键
    """
    parsed = urlparse(url)
    return parsed.path


def download_image(url: str, save_path: Path):
    """
    下载单张图片
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.xiaohongshu.com/",
    }

    response = httpx.get(
        url,
        headers=headers,
        timeout=30,
        follow_redirects=True,
    )

    response.raise_for_status()
    save_path.write_bytes(response.content)


def extract_note_images(page):
    """
    从当前小红书笔记页面中提取正文图片 URL
    """
    images = page.locator("img")
    count = images.count()

    unique_images = {}

    for i in range(count):
        img = images.nth(i)

        src = img.get_attribute("src")

        if not src:
            continue

        if "sns-webpic" not in src:
            continue

        if "/comment/" in src:
            continue

        try:
            box = img.bounding_box()
        except Exception:
            box = None

        if not box:
            continue

        width = box["width"]
        height = box["height"]

        if width < 300 or height < 300:
            continue

        key = normalize_image_url(src)

        if key not in unique_images:
            unique_images[key] = src

    return list(unique_images.values())


def save_metadata(
    note_dir: Path,
    note_id: str,
    title: str,
    source_url: str,
    image_files: list[str],
):
    """
    保存笔记 metadata.json
    """
    metadata = {
        "note_id": note_id,
        "title": title,
        "source_url": source_url,
        "image_count": len(image_files),
        "images": image_files,
    }

    metadata_path = note_dir / "metadata.json"

    with open(
        metadata_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            metadata,
            f,
            ensure_ascii=False,
            indent=2,
        )

    return metadata_path


def download_note(url: str):
    """
    下载一篇小红书笔记中的正文图片
    并保存 metadata.json
    """
    note_id = get_note_id(url)

    print("\n笔记 ID:", note_id)

    user_data_dir = Path("browser_data_v2").resolve()

    note_dir = Path("output") / note_id
    note_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("输出目录:", note_dir.resolve())

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
        )

        page = (
            context.pages[0]
            if context.pages
            else context.new_page()
        )

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(3000)

        page_title = page.title()

        title = page_title.replace(
            " - 小红书",
            "",
        )

        print("\n页面标题:", title)

        if "你访问的页面不见了" in title:
            print("\n当前笔记页面无效，停止下载。")
            input("\n按 Enter 关闭浏览器...")
            context.close()
            return

        image_urls = extract_note_images(page)

        print(
            "\n去重后正文图片数量:",
            len(image_urls),
        )

        image_files = []

        for index, image_url in enumerate(
            image_urls,
            start=1,
        ):
            filename = f"{index:02d}.webp"

            save_path = note_dir / filename

            download_image(
                image_url,
                save_path,
            )

            image_files.append(filename)

            print(
                "已保存:",
                save_path,
            )

        metadata_path = save_metadata(
            note_dir=note_dir,
            note_id=note_id,
            title=title,
            source_url=url,
            image_files=image_files,
        )

        print(
            "\nmetadata 已保存:",
            metadata_path,
        )

        input(
            "\n完成。按 Enter 关闭浏览器..."
        )

        context.close()


def open_page_with_retry(
    context,
    url: str,
    retries: int = 2,
):
    """
    尝试打开页面。

    特点：
    1. 始终复用同一个标签页
    2. 不再关闭页面 / 创建新标签页
    3. page.goto 失败后尝试用浏览器自身跳转
    """

    if context.pages:
        page = context.pages[0]
    else:
        page = context.new_page()

    for attempt in range(1, retries + 1):
        print(f"\n第 {attempt} 次尝试打开页面...")

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            print("页面打开成功。")
            return page

        except Exception as e:
            print("\npage.goto 打开失败:")
            print(e)

            print("\n当前浏览器 URL:")
            print(page.url)

            # 有些网页虽然 Playwright 报 timeout，
            # 实际浏览器已经开始进入页面
            if page.url != "about:blank":
                print(
                    "\n虽然发生超时，"
                    "但浏览器已经离开 about:blank。"
                )

                page.wait_for_timeout(5000)

                return page

            if attempt < retries:
                print(
                    "\n尝试使用浏览器自身进行跳转..."
                )

                try:
                    page.evaluate(
                        """
                        url => {
                            window.location.href = url;
                        }
                        """,
                        url,
                    )
                except Exception:
                    # 页面开始导航时，
                    # evaluate 本身可能被中断，这是正常的
                    pass

                page.wait_for_timeout(10000)

                print("\n浏览器跳转后的 URL:")
                print(page.url)

                if page.url != "about:blank":
                    print(
                        "\n浏览器自身跳转成功。"
                    )

                    return page

    print(
        "\n所有导航方式都失败，"
        "页面仍然没有正常打开。"
    )

    return None


def search_notes(
    keyword: str,
    max_results: int = 20,
):
    """
    根据关键词打开小红书搜索页面，
    收集搜索结果中的笔记链接。
    """
    user_data_dir = Path("browser_data_v2").resolve()

    search_url = (
        "https://www.xiaohongshu.com/search_result"
        f"?keyword={quote(keyword)}"
        "&source=web_search_result_notes"
    )

    print("\n搜索地址:")
    print(search_url)

    note_urls = {}

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
        )

        page = open_page_with_retry(
            context,
            search_url,
            retries=2,
        )

        if page is None:
            print("\n连续两次都无法打开搜索页面。")
            input("\n按 Enter 关闭浏览器...")
            context.close()
            return []

        page.wait_for_timeout(5000)

        print("\n搜索页面标题:")
        print(page.title())

        print("\n搜索页面 URL:")
        print(page.url)

        links = page.locator(
            'a[href*="/explore/"]'
        )

        count = links.count()

        print("\n找到候选笔记链接数量:", count)

        for i in range(count):
            href = links.nth(i).get_attribute("href")

            if not href:
                continue

            if href.startswith("/"):
                href = (
                    "https://www.xiaohongshu.com"
                    + href
                )

            note_id = get_note_id(href)

            if note_id not in note_urls:
                note_urls[note_id] = href

            if len(note_urls) >= max_results:
                break

        print(
            "\n当前找到笔记数量:",
            len(note_urls),
        )

        for index, note_url in enumerate(
            note_urls.values(),
            start=1,
        ):
            print(
                f"{index:02d}. {note_url}"
            )

        input(
            "\n检查完成，按 Enter 关闭浏览器..."
        )

        context.close()

    return list(note_urls.values())


def test_search_click(keyword: str):
    """
    测试：
    1. 使用 browser_data_v2 登录状态
    2. 先打开小红书首页
    3. 再进入搜索结果页
    4. 找到第一篇笔记对应的可见卡片
    5. 模拟真实鼠标点击
    6. 查看点击后的页面状态
    """

    user_data_dir = Path("browser_data_v2").resolve()

    search_url = (
        "https://www.xiaohongshu.com/search_result"
        f"?keyword={quote(keyword)}"
        "&source=web_search_result_notes"
    )

    print("\n搜索地址:")
    print(search_url)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
        )

        if context.pages:
            page = context.pages[0]
        else:
            page = context.new_page()

        # -------------------------------------------------
        # 第一步：先打开小红书首页
        # -------------------------------------------------

        print("\n步骤 1：打开小红书首页...")

        try:
            page.goto(
                "https://www.xiaohongshu.com",
                wait_until="domcontentloaded",
                timeout=60000,
            )
        except Exception as e:
            print("\n首页打开失败:")
            print(e)

            input("\n按 Enter 关闭浏览器...")
            context.close()
            return

        page.wait_for_timeout(3000)

        print("首页标题:", page.title())
        print("首页 URL:", page.url)

        # -------------------------------------------------
        # 第二步：进入搜索页
        # -------------------------------------------------

        print("\n步骤 2：进入搜索页面...")

        try:
            page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
        except Exception as e:
            print("\n搜索页打开失败:")
            print(e)
            print("\n当前 URL:", page.url)

            input("\n按 Enter 关闭浏览器...")
            context.close()
            return

        page.wait_for_timeout(5000)

        print("\n搜索页面标题:")
        print(page.title())

        print("\n搜索页面 URL:")
        print(page.url)

        # -------------------------------------------------
        # 第三步：找笔记链接
        # -------------------------------------------------

        note_links = page.locator(
            'a[href*="/explore/"]'
        )

        count = note_links.count()

        print("\n找到笔记链接数量:", count)

        if count == 0:
            print("\n没有找到笔记链接。")

            input("\n按 Enter 关闭浏览器...")
            context.close()
            return

        print("\n前 5 个搜索结果:")

        for i in range(min(count, 5)):
            href = note_links.nth(i).get_attribute("href")
            print(f"{i + 1:02d}. {href}")

        # -------------------------------------------------
        # 第四步：第一篇笔记
        # -------------------------------------------------

        first_link = note_links.first

        href = first_link.get_attribute("href")

        print("\n第一篇笔记原始 href:")
        print(href)

        # -------------------------------------------------
        # 第五步：从隐藏 a 向上寻找可见卡片
        # -------------------------------------------------

        print("\n开始寻找第一篇笔记的可见卡片...")

        target = first_link
        target_box = None

        for level in range(12):
            try:
                box = target.bounding_box()
            except Exception:
                box = None

            try:
                tag_name = target.evaluate(
                    "el => el.tagName"
                )
            except Exception:
                tag_name = "?"

            try:
                class_name = target.get_attribute("class")
            except Exception:
                class_name = None

            print(
                f"层级 {level}: "
                f"tag={tag_name}, "
                f"class={class_name}, "
                f"box={box}"
            )

            if box:
                width = box["width"]
                height = box["height"]

                if width >= 150 and height >= 150:
                    target_box = box
                    break

            target = target.locator("..")

        if target_box is None:
            print("\n没有找到尺寸足够大的可见卡片。")

            input("\n按 Enter 关闭浏览器...")
            context.close()
            return

        print(
            "\n找到卡片尺寸:",
            round(target_box["width"]),
            "x",
            round(target_box["height"]),
        )

        # -------------------------------------------------
        # 第六步：模拟鼠标点击
        # -------------------------------------------------

        x = (
            target_box["x"]
            + target_box["width"] / 2
        )

        y = (
            target_box["y"]
            + target_box["height"] / 2
        )

        print("\n准备点击:")
        print("x =", round(x))
        print("y =", round(y))

        old_page_count = len(context.pages)

        page.mouse.click(x, y)

        print("鼠标点击已执行。")

        page.wait_for_timeout(5000)

        # -------------------------------------------------
        # 第七步：判断详情页在哪里
        # -------------------------------------------------

        if len(context.pages) > old_page_count:
            detail_page = context.pages[-1]
        else:
            detail_page = page

        print(
            "\n========== 点击后的状态 =========="
        )

        print("\n标题:")
        print(detail_page.title())

        print("\nURL:")
        print(detail_page.url)

        print("\n当前共有页面:", len(context.pages))

        for index, browser_page in enumerate(
            context.pages,
            start=1,
        ):
            print(
                f"{index}. {browser_page.url}"
            )

        input(
            "\n检查完成，按 Enter 关闭浏览器..."
        )

        context.close()


def search_and_download_first(keyword: str):
    """
    搜索关键词，并下载第一个搜索结果中的图片。
    搜索和详情页使用同一个浏览器会话。
    """

    user_data_dir = Path("browser_data_v2").resolve()

    search_url = (
        "https://www.xiaohongshu.com/search_result"
        f"?keyword={quote(keyword)}"
        "&source=web_search_result_notes"
    )

    print("\n搜索地址:")
    print(search_url)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
        )

        page = (
            context.pages[0]
            if context.pages
            else context.new_page()
        )

        # 1. 先打开首页
        print("\n步骤 1：打开小红书首页...")

        page.goto(
            "https://www.xiaohongshu.com",
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(2000)

        # 2. 打开搜索页面
        print("\n步骤 2：打开搜索页面...")

        page.goto(
            search_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(5000)

        print("搜索页面标题:", page.title())

        # 3. 找搜索结果
        note_links = page.locator(
            'a[href*="/explore/"]'
        )

        count = note_links.count()

        print("搜索结果数量:", count)

        if count == 0:
            print("没有找到搜索结果。")
            context.close()
            return

        first_link = note_links.first

        # 4. 找第一篇对应的可见卡片
        target = first_link
        target_box = None

        for _ in range(12):
            try:
                box = target.bounding_box()
            except Exception:
                box = None

            if box:
                if (
                    box["width"] >= 150
                    and box["height"] >= 150
                ):
                    target_box = box
                    break

            target = target.locator("..")

        if target_box is None:
            print("没有找到可点击的笔记卡片。")
            context.close()
            return

        # 5. 模拟鼠标点击
        x = (
            target_box["x"]
            + target_box["width"] / 2
        )

        y = (
            target_box["y"]
            + target_box["height"] / 2
        )

        print("\n步骤 3：点击第一篇笔记...")

        page.mouse.click(x, y)

        page.wait_for_timeout(5000)

        # 6. 此时 page 已经是真正详情页
        detail_url = page.url

        print("\n详情页标题:")
        print(page.title())

        print("\n详情页 URL:")
        print(detail_url)

        if "/404" in detail_url:
            print("\n详情页无效，跳过。")
            context.close()
            return

        # 7. 获取 note_id
        note_id = get_note_id(detail_url)

        note_dir = Path("output") / note_id

        note_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        title = page.title().replace(
            " - 小红书",
            "",
        )

        # 8. 提取正文图片
        print("\n步骤 4：提取正文图片...")

        image_urls = extract_note_images(page)

        print(
            "正文图片数量:",
            len(image_urls),
        )

        if not image_urls:
            print(
                "\n这篇没有检测到正文图片，"
                "可能是视频笔记，暂时跳过。"
            )

            input(
                "\n按 Enter 关闭浏览器..."
            )

            context.close()
            return

        # 9. 下载图片
        image_files = []

        print("\n步骤 5：开始下载...")

        for index, image_url in enumerate(
            image_urls,
            start=1,
        ):
            filename = f"{index:02d}.webp"

            save_path = note_dir / filename

            download_image(
                image_url,
                save_path,
            )

            image_files.append(filename)

            print(
                f"已保存: {save_path}"
            )

        # 10. 保存 metadata
        metadata_path = save_metadata(
            note_dir=note_dir,
            note_id=note_id,
            title=title,
            source_url=detail_url,
            image_files=image_files,
        )

        print(
            "\nmetadata 已保存:",
            metadata_path,
        )

        print(
            "\n本篇下载完成。"
        )

        input(
            "\n按 Enter 关闭浏览器..."
        )

        context.close()


def click_note_card(page, note_link, expected_note_id: str) -> bool:
    """
    点击搜索结果中的某篇笔记。

    优先点击卡片中的可见图片，
    如果没有找到图片，再点击可见父容器。

    点击后验证是否真正进入对应的详情页。
    """

    print("正在定位可点击区域...")

    # 先从隐藏的 <a> 往上找可见卡片
    target = note_link
    card = None

    for _ in range(12):
        try:
            box = target.bounding_box()
        except Exception:
            box = None

        if box:
            if (
                box["width"] >= 150
                and box["height"] >= 150
            ):
                card = target
                break

        target = target.locator("..")

    if card is None:
        print("没有找到可见卡片。")
        return False

    # 确保卡片滚动到可见区域
    try:
        card.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
    except Exception:
        pass

    # ---------------------------------
    # 第一优先：点击卡片里的可见图片
    # ---------------------------------

    images = card.locator("img")
    image_count = images.count()

    for i in range(image_count):
        img = images.nth(i)

        try:
            box = img.bounding_box()
        except Exception:
            box = None

        if not box:
            continue

        if (
            box["width"] < 100
            or box["height"] < 100
        ):
            continue

        print(
            "点击封面图片:",
            round(box["width"]),
            "x",
            round(box["height"]),
        )

        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2

        page.mouse.click(x, y)

        page.wait_for_timeout(4000)

        # 检查是否进入正确笔记
        if (
            "/explore/" in page.url
            and expected_note_id in page.url
        ):
            print("已成功进入详情页。")
            return True

        print("点击图片后没有进入详情页。")

    # ---------------------------------
    # 第二优先：点击卡片偏上位置
    # 避开底部标题/互动区域
    # ---------------------------------

    try:
        box = card.bounding_box()
    except Exception:
        box = None

    if box:
        print("尝试点击卡片上半部分...")

        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] * 0.35

        page.mouse.click(x, y)

        page.wait_for_timeout(4000)

        if (
            "/explore/" in page.url
            and expected_note_id in page.url
        ):
            print("已成功进入详情页。")
            return True

    print("本次没有成功进入详情页。")
    return False


def collect_search_results(
    page,
    max_results: int,
    max_idle_rounds: int = 4,
):
    """
    在当前小红书搜索页持续向下滚动，
    收集去重后的 note_id。

    停止条件：
    1. 已达到 max_results
    2. 连续 max_idle_rounds 次滚动都没有新增结果
    """

    results = []
    seen_note_ids = set()

    idle_rounds = 0
    round_index = 0

    while len(results) < max_results:
        round_index += 1

        print(
            f"\n收集搜索结果，第 {round_index} 轮..."
        )

        note_links = page.locator(
            'a[href*="/explore/"]'
        )

        count = note_links.count()

        before_count = len(results)

        for i in range(count):
            href = note_links.nth(i).get_attribute(
                "href"
            )

            if not href:
                continue

            note_id = get_note_id(href)

            if note_id in seen_note_ids:
                continue

            seen_note_ids.add(note_id)

            results.append(
                {
                    "note_id": note_id,
                    "href": href,
                }
            )

            if len(results) >= max_results:
                break

        new_count = len(results) - before_count

        print(
            "本轮新增:",
            new_count,
        )

        print(
            "当前累计:",
            len(results),
        )

        if len(results) >= max_results:
            break

        if new_count == 0:
            idle_rounds += 1

            print(
                "本轮没有新增结果，"
                f"连续空闲轮数: {idle_rounds}"
            )
        else:
            idle_rounds = 0

        if idle_rounds >= max_idle_rounds:
            print(
                "\n连续多次滚动没有新结果，"
                "停止继续加载。"
            )
            break

        # 向页面底部滚动
        page.evaluate(
            """
            window.scrollTo(
                0,
                document.body.scrollHeight
            )
            """
        )

        # 等待新内容加载
        page.wait_for_timeout(2500)

    return results


def find_note_link(
    page,
    note_id: str,
    max_scroll_rounds: int = 40,
):
    """
    在搜索结果页中寻找指定 note_id。

    小红书搜索页存在懒加载/虚拟列表：
    某些已经收集到的笔记，在当前 DOM 中可能已经不存在。

    处理方式：
    1. 先检查当前 DOM
    2. 找不到则滚回顶部
    3. 从顶部逐屏向下滚动
    4. 每次滚动后重新检查目标笔记
    """

    selector = (
        f'a[href*="/explore/{note_id}"]'
    )

    # 先直接找一次
    note_link = page.locator(selector).first

    if note_link.count() > 0:
        return note_link

    print(
        "当前 DOM 中没有目标笔记，"
        "从搜索页顶部重新寻找..."
    )

    # 回到顶部
    page.evaluate(
        """
        window.scrollTo(0, 0)
        """
    )

    page.wait_for_timeout(1200)

    # 回顶部后再检查一次
    note_link = page.locator(selector).first

    if note_link.count() > 0:
        print("在搜索页顶部找到目标笔记。")
        return note_link

    last_scroll_y = -1

    for scroll_round in range(
        1,
        max_scroll_rounds + 1,
    ):
        current_scroll_y = page.evaluate(
            "window.scrollY"
        )

        print(
            f"寻找目标笔记："
            f"第 {scroll_round} 次向下滚动，"
            f"scrollY={round(current_scroll_y)}"
        )

        # 向下滚一屏左右
        page.evaluate(
            """
            window.scrollBy(
                0,
                window.innerHeight * 0.85
            )
            """
        )

        page.wait_for_timeout(900)

        note_link = page.locator(
            selector
        ).first

        if note_link.count() > 0:
            print(
                "已重新找到目标笔记。"
            )

            try:
                note_link.scroll_into_view_if_needed()
            except Exception:
                pass

            page.wait_for_timeout(300)

            return note_link

        new_scroll_y = page.evaluate(
            "window.scrollY"
        )

        # 页面已经滚不动了
        if new_scroll_y == last_scroll_y:
            print(
                "页面已经无法继续向下滚动。"
            )
            break

        last_scroll_y = new_scroll_y

    print(
        "从顶部滚动到底部后，"
        "仍然没有找到目标笔记。"
    )

    return None


def build_summary_folder(output_root: Path):
    """
    将所有笔记子目录中的图片再复制一份到“汇总”目录。

    汇总文件名格式：
        <note_id>_<原文件名>

    例如：
        6a34874800000000220196e8_01.webp

    这样不同笔记里的 01.webp 不会互相覆盖。
    metadata.json 不复制到汇总目录。
    """

    summary_dir = output_root / "汇总"
    summary_dir.mkdir(parents=True, exist_ok=True)

    image_extensions = {
        ".webp",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
    }

    copied_count = 0

    for note_dir in output_root.iterdir():
        if not note_dir.is_dir():
            continue

        if note_dir == summary_dir:
            continue

        note_id = note_dir.name

        for source_file in note_dir.iterdir():
            if not source_file.is_file():
                continue

            if source_file.suffix.lower() not in image_extensions:
                continue

            target_name = f"{note_id}_{source_file.name}"
            target_file = summary_dir / target_name

            shutil.copy2(
                source_file,
                target_file,
            )

            copied_count += 1

    print(
        "\n汇总文件夹已更新:\n"
        f"{summary_dir}"
    )

    print(
        "汇总图片数量:",
        copied_count,
    )

    return summary_dir


def search_and_download_batch(
    keyword: str,
    max_results: int = 20,
    output_dir="output",
):
    """
    搜索一次关键词。

    先滚动收集并固定 note_id，
    然后按照固定顺序逐篇处理。

    特点：
    - 不重复搜索关键词
    - 搜索结果先固定
    - 已处理笔记自动跳过
    - 视频笔记也保存 metadata
    - 搜索页虚拟列表导致卡片消失时，
      会从顶部重新滚动寻找
    """

    output_root = Path(output_dir)
    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    app_data = Path(
        os.getenv(
            "LOCALAPPDATA",
            str(Path.home()),
        )
    )

    user_data_dir = (
        app_data
        / "MediaDownloader"
        / "browser_data"
    )

    user_data_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    search_url = (
        "https://www.xiaohongshu.com/search_result"
        f"?keyword={quote(keyword)}"
        "&source=web_search_result_notes"
    )

    print("\n搜索地址:")
    print(search_url)

    with sync_playwright() as p:
        context = (
            p.chromium.launch_persistent_context(
                user_data_dir=str(
                    user_data_dir
                ),
                headless=False,
                channel="msedge",
            )
        )

        page = (
            context.pages[0]
            if context.pages
            else context.new_page()
        )

        # ==========================================
        # 1. 打开小红书首页
        # ==========================================

        print("\n打开小红书首页...")

        page.goto(
            "https://www.xiaohongshu.com",
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(2000)

        # ==========================================
        # 2. 搜索一次
        # ==========================================

        print(
            "\n搜索关键词（只执行一次）..."
        )

        page.goto(
            search_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(5000)

        print(
            "搜索页面标题:",
            page.title(),
        )

        # ==========================================
        # 3. 自动滚动收集结果
        # ==========================================

        print(
            f"\n开始收集最多 "
            f"{max_results} 篇笔记..."
        )

        initial_results = (
            collect_search_results(
                page=page,
                max_results=max_results,
            )
        )

        print(
            "\n最终固定搜索结果数量:",
            len(initial_results),
        )

        print(
            "\n本次将按照以下固定顺序处理:"
        )

        for index, item in enumerate(
            initial_results,
            start=1,
        ):
            print(
                f"{index:02d}. "
                f"{item['note_id']}"
            )

        # ==========================================
        # 4. 收集完成以后主动回顶部
        # ==========================================

        print(
            "\n搜索结果收集完成，"
            "返回搜索页顶部..."
        )

        page.evaluate(
            "window.scrollTo(0, 0)"
        )

        page.wait_for_timeout(1500)

        # ==========================================
        # 5. 统计
        # ==========================================

        success_count = 0
        video_count = 0
        already_downloaded_count = 0
        fail_count = 0

        # ==========================================
        # 6. 按固定顺序处理
        # ==========================================

        for index, item in enumerate(
            initial_results,
            start=1,
        ):

            note_id = item["note_id"]

            print("\n" + "=" * 60)

            print(
                f"正在处理第 "
                f"{index}/"
                f"{len(initial_results)} 篇"
            )

            print("=" * 60)

            print(
                "固定目标 note_id:",
                note_id,
            )

            note_dir = (
                output_root
                / note_id
            )

            metadata_path = (
                note_dir
                / "metadata.json"
            )

            # ======================================
            # 已处理过直接跳过
            # ======================================

            if metadata_path.exists():
                print(
                    "该笔记已经处理过，跳过。"
                )

                print(
                    "已有 metadata:",
                    metadata_path,
                )

                already_downloaded_count += 1
                continue

            try:
                # ==================================
                # 确保当前位于搜索页
                # ==================================

                if (
                    "/search_result"
                    not in page.url
                ):
                    print(
                        "当前不在搜索页，"
                        "尝试返回..."
                    )

                    try:
                        page.go_back(
                            wait_until=(
                                "domcontentloaded"
                            ),
                            timeout=30000,
                        )
                    except Exception:
                        pass

                    page.wait_for_timeout(
                        2000
                    )

                print(
                    "当前页面:",
                    page.url,
                )

                # ==================================
                # 精确寻找这一个 note_id
                # ==================================

                note_link = find_note_link(
                    page=page,
                    note_id=note_id,
                    max_scroll_rounds=40,
                )

                if note_link is None:
                    print(
                        "无法在搜索结果中"
                        "重新找到这篇笔记。"
                    )

                    fail_count += 1
                    continue

                href = (
                    note_link.get_attribute(
                        "href"
                    )
                )

                print(
                    "当前找到 href:",
                    href,
                )

                # ==================================
                # 点击卡片
                # ==================================

                opened = click_note_card(
                    page,
                    note_link,
                    note_id,
                )

                if not opened:
                    print(
                        "没有成功进入详情页。"
                    )

                    fail_count += 1
                    continue

                # ==================================
                # 获取详情
                # ==================================

                detail_url = page.url

                title = (
                    page.title().replace(
                        " - 小红书",
                        "",
                    )
                )

                print(
                    "标题:",
                    title,
                )

                print(
                    "详情 URL:",
                    detail_url,
                )

                # ==================================
                # 验证
                # ==================================

                if (
                    note_id
                    not in detail_url
                ):
                    print(
                        "进入的详情页与"
                        "目标 note_id 不一致。"
                    )

                    fail_count += 1

                elif "/404" in detail_url:
                    print(
                        "详情页无效。"
                    )

                    fail_count += 1

                else:
                    page.wait_for_timeout(
                        1500
                    )

                    # ==============================
                    # 提取图片
                    # ==============================

                    image_urls = (
                        extract_note_images(
                            page
                        )
                    )

                    print(
                        "正文图片数量:",
                        len(image_urls),
                    )

                    # ==============================
                    # 视频 / 无图片
                    # ==============================

                    if not image_urls:

                        print(
                            "已成功进入详情页，"
                            "但没有检测到正文图片。"
                            "暂时按视频笔记处理。"
                        )

                        note_dir.mkdir(
                            parents=True,
                            exist_ok=True,
                        )

                        metadata = {
                            "note_id": note_id,
                            "title": title,
                            "source_url": (
                                detail_url
                            ),
                            "type": "video",
                            "status": "skipped",
                            "image_count": 0,
                            "images": [],
                        }

                        metadata_path = (
                            note_dir
                            / "metadata.json"
                        )

                        with open(
                            metadata_path,
                            "w",
                            encoding="utf-8",
                        ) as f:
                            json.dump(
                                metadata,
                                f,
                                ensure_ascii=False,
                                indent=2,
                            )

                        print(
                            "视频笔记 metadata "
                            "已保存:",
                            metadata_path,
                        )

                        video_count += 1

                    else:
                        # ==========================
                        # 图文笔记
                        # ==========================

                        note_dir.mkdir(
                            parents=True,
                            exist_ok=True,
                        )

                        image_files = []

                        for (
                            image_index,
                            image_url,
                        ) in enumerate(
                            image_urls,
                            start=1,
                        ):

                            filename = (
                                f"{image_index:02d}"
                                ".webp"
                            )

                            save_path = (
                                note_dir
                                / filename
                            )

                            download_image(
                                image_url,
                                save_path,
                            )

                            image_files.append(
                                filename
                            )

                            print(
                                "已保存:",
                                save_path,
                            )

                        metadata_path = (
                            save_metadata(
                                note_dir=note_dir,
                                note_id=note_id,
                                title=title,
                                source_url=(
                                    detail_url
                                ),
                                image_files=(
                                    image_files
                                ),
                            )
                        )

                        print(
                            "metadata 已保存:",
                            metadata_path,
                        )

                        success_count += 1

                # ==================================
                # 返回搜索页
                # ==================================

                print(
                    "\n返回搜索结果页..."
                )

                try:
                    page.go_back(
                        wait_until=(
                            "domcontentloaded"
                        ),
                        timeout=30000,
                    )
                except Exception:
                    pass

                page.wait_for_timeout(
                    2000
                )

                print(
                    "返回后 URL:",
                    page.url,
                )

            except Exception as e:

                print(
                    "处理失败:",
                    repr(e),
                )

                fail_count += 1

                if "/explore/" in page.url:

                    print(
                        "尝试返回搜索页..."
                    )

                    try:
                        page.go_back(
                            timeout=30000,
                        )
                    except Exception:
                        pass

                    page.wait_for_timeout(
                        2000
                    )

        # ==========================================
        # 7. 汇总
        # ==========================================

        print("\n" + "=" * 60)
        print("批量处理完成")
        print("=" * 60)

        print(
            "本次新下载:",
            success_count,
        )

        print(
            "已处理跳过:",
            already_downloaded_count,
        )

        print(
            "视频/无正文图片:",
            video_count,
        )

        print(
            "失败:",
            fail_count,
        )

        print(
            "\n本次固定搜索结果数:",
            len(initial_results),
        )

        # ==========================================
        # 8. 生成 / 更新汇总文件夹
        # ==========================================

        build_summary_folder(
            output_root
        )

        input(
            "\n按 Enter 关闭浏览器..."
        )

        context.close()