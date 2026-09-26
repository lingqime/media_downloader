from pathlib import Path
import tkinter as tk
from tkinter import filedialog

from src.xhs import search_and_download_batch


def choose_output_folder():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    folder = filedialog.askdirectory(
        title="请选择图片保存文件夹"
    )

    root.destroy()
    return folder


def main():
    print("=" * 60)
    print("小红书图片批量下载工具")
    print("=" * 60)

    keyword = input("\n请输入搜索关键词：").strip()

    if not keyword:
        print("关键词不能为空。")
        input("\n按 Enter 退出...")
        return

    count_text = input(
        "请输入要处理的笔记数量（例如 10、30、50）："
    ).strip()

    try:
        max_results = int(count_text)
    except ValueError:
        print("数量必须是整数。")
        input("\n按 Enter 退出...")
        return

    if max_results <= 0:
        print("数量必须大于 0。")
        input("\n按 Enter 退出...")
        return

    print("\n请选择保存图片的文件夹...")

    output_folder = choose_output_folder()

    if not output_folder:
        print("没有选择保存文件夹，程序结束。")
        input("\n按 Enter 退出...")
        return

    output_folder = Path(output_folder)

    print("\n保存位置:")
    print(output_folder)

    search_and_download_batch(
        keyword=keyword,
        max_results=max_results,
        output_dir=output_folder,
    )


if __name__ == "__main__":
    main()
