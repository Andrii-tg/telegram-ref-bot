import re


async def create_payment(amount: float, order_id: str) -> dict:
    return {
        "status": "success",
        "result": {
            "link": f"https://pay.cryptocloud.plus/pay/{order_id}"
        }
    }


def validate_address(network: str, address: str) -> bool:
    if network == "usdt_trc20":
        return address.startswith("T") and len(address) > 20
    if network == "usdt_erc20":
        return address.startswith("0x") and len(address) == 42
    if network == "ton":
        return len(address) > 30
    return False


def need_memo(network: str) -> bool:
    return network.lower() in ["xrp", "bnb", "cosmos"]
