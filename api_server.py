import argparse
from multiprocessing import freeze_support


def main():
    # 先解析参数，--help 不需要加载模型配置或数据库。
    parser = argparse.ArgumentParser(description="Agent 本地后端")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1 到 65535 之间")

    import uvicorn
    from main import app

    # 打包运行不启用热重载，只监听本机，不暴露到局域网。
    uvicorn.run(
        app, host="127.0.0.1", port=args.port,
        reload=False, workers=1,
    )


if __name__ == "__main__":
    # 兼容 Windows 打包后的多进程启动环境。
    freeze_support()
    main()