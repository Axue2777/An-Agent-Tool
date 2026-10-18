inventory = {
    "机械键盘": 12,
    "无线鼠标": 0,
    "显示器": 5,
}


def get_stock(product_name: str) -> dict:
    """查询商品库存。"""
    if product_name not in inventory:
        return {
            "product_name": product_name,
            "found": False,
        }

    return {
        "product_name": product_name,
        "found": True,
        "stock": inventory[product_name],
    }


if __name__ == "__main__":
    print(get_stock("机械键盘"))
    print(get_stock("无线鼠标"))
    print(get_stock("耳机"))