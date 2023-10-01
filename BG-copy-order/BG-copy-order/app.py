from flask import Flask, request, jsonify
import requests
import time
import hmac
import hashlib
import base64
import json
import logging
from logging.handlers import RotatingFileHandler
from urllib.parse import urlencode

API_KEY = ""
SECRET_KEY = ""
PRODUCT_TYPE = "umcbl"
PASSPHRASE = ""

BASE_URL = "https://api.bitget.com"
app = Flask(__name__)

# 日志设置
log_file = 'rizhi.log'
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_handler = RotatingFileHandler(log_file, mode='a', maxBytes=5*1024*1024, 
                                  backupCount=2, encoding="utf-8", delay=0)
log_handler.setFormatter(log_formatter)
log_handler.setLevel(logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)

def get_timestamp():
    return int(time.time() * 1000)

def sign(message, secret_key):
    mac = hmac.new(bytes(secret_key, encoding='utf8'), bytes(message, encoding='utf-8'), digestmod='sha256')
    d = mac.digest()
    return base64.b64encode(d).decode()

def pre_hash(timestamp, method, request_path, body):
    return str(timestamp) + str.upper(method) + request_path + body

@app.route('/copytrade', methods=['POST'])
def copytrade():
    data = request.json

    symbol = data.get('symbol')
    is_close = data.get('is_close')

    if not all([symbol, is_close]):
        return jsonify({"error": "Symbol and is_close fields must be provided!"}), 400

    if is_close == "1":
        try:
            process_trade(data)  # 调用交易处理函数
        except Exception as e:
            logger.error(f"处理交易时出错: {e}")
            return jsonify({"error": "Error processing the trade."}), 500
        return jsonify({"message": "Successfully processed webhook data!"}), 200

    # If is_close is not "1", then we expect all other fields.
    side = data.get('side')
    stopProfitPrice = data.get('stopProfitPrice')
    stopLossPrice = data.get('stopLossPrice')
    if not all([side, stopProfitPrice, stopLossPrice]):
        return jsonify({"error": "For trades, side, stopProfitPrice, and stopLossPrice fields must be provided!"}), 400

    try:
        process_trade(data)  # 调用交易处理函数
    except Exception as e:
        logger.error(f"处理交易时出错: {e}")
        return jsonify({"error": "Error processing the trade."}), 500

    return jsonify({"message": "Successfully processed webhook data!"}), 200



def get_balance():
    logger.info("正在获取余额。")
    timestamp = str(get_timestamp())
    request_path = "/api/mix/v1/account/accounts"
    body = ""
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign(pre_hash(timestamp, "GET", request_path + f"?productType={PRODUCT_TYPE}", body), SECRET_KEY),
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "locale": "en-US",
        "Content-Type": "application/json"
    }
    logger.info(f"Sending request to {BASE_URL} with headers: {headers}")
    
    response = requests.get(BASE_URL, headers=headers)
    
    logger.info(f"Received response: {response.text}")

    response = requests.get(f'{BASE_URL}/api/mix/v1/account/accounts?productType={PRODUCT_TYPE}', headers=headers)
    response_data = response.json()
    logger.debug(f"余额API响应: {response_data}")

    if response.status_code != 200:
        logger.error(f"获取余额时出错: HTTP状态码 {response.status_code}, 响应内容: {response_data}")
        raise Exception(f"获取余额时出错: HTTP状态码 {response.status_code}")

    if "error" in response_data:
        logger.error(f"获取余额时出错: {response_data.get('error')}")
        raise Exception(f"获取余额时出错: {response_data.get('error')}")

    data = response_data["data"]
    if not isinstance(data, list) or len(data) == 0:
        logger.error("API响应中未找到数据字段或数据格式不符合预期")
        raise Exception("API响应中未找到数据字段或数据格式不符合预期")


    available = data[0].get("available")
    if available is None:
        logger.error("API响应中未找到可用数量")
        raise Exception("API响应中未找到可用数量")

    logger.info(f"可用数量: {available}")
    return str(available)

def place_order(payload):
    logger.info(f"Placing order with payload: {payload}")
    timestamp = str(get_timestamp())
    method = "POST"
    request_path = "/api/mix/v1/order/placeOrder"
    body = json.dumps(payload)
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign(pre_hash(timestamp, method, request_path, body), SECRET_KEY),
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "locale": "en-US",
        "Content-Type": "application/json"
    }
    
    logger.info(f"Sending request to {BASE_URL} with headers: {headers} and data: {json.dumps(payload)}")
    
    logger.debug(f"Sending request with headers: {headers}")

    response = requests.post(f'{BASE_URL}{request_path}', headers=headers, json=payload)
    response_data = response.json()
    logger.debug(f"Order placement API response: {response_data}")

    if response.status_code != 200 or "error" in response_data:
        logger.error(f"Error in place_order: {response_data}")
        raise Exception(f"Error in place_order: {response_data}")
    return response_data
    response = requests.get(...)
    logger.debug(f"API Response: {response.text}")


def process_trade(data):
    logger.info("Processing trade.")

    if data['is_close'] == "0":
        balance = get_balance()
        if balance is None:
            raise Exception("Failed to fetch balance")

        size = str(float(balance) * 0.20)
        payload = {
            "symbol": data["symbol"],
            "marginCoin": "USDT",
            "size": size,
            "side": data["side"],
            "orderType": "market",
        }

        response_data = place_order(payload)
        logger.debug(f"Place order response data: {response_data}")

        time.sleep(5)  # Waiting for 5 seconds before fetching the trackingNo
        trackingNo = get_trackingNo_after_order()
        
        if not trackingNo:
            logger.error("Failed to get trackingNo after 5 seconds of order placement")
            raise Exception("Failed to get trackingNo after 5 seconds of order placement")

        modify_TPSL(trackingNo, data["symbol"], data.get("stopProfitPrice"), data.get("stopLossPrice"))

    elif data['is_close'] == "1":
        trackingNo = get_current_order_trackingNo(data["symbol"])
        if not trackingNo:
            logger.error("Tracking Number not found!")
            raise Exception("Tracking Number not found!")
        close_order(data["symbol"], trackingNo)


def parse_params_to_str(params):
    return '?' + urlencode(params)

params = {
    'symbol': 'FXSUSDT_UMCBL',
    'productType': 'umcbl',  # 根据你的实际情况修改
    'pageSize': 20,
    'pageNo': 1
}
    
def get_trackingNo_after_order():
    logger.info("Fetching trackingNo after order placement")
    
    timestamp = str(get_timestamp())
    request_path = "/api/mix/v1/trace/currentTrack"  # 假设这是正确的API路径，需要你根据文档进行确认
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign(pre_hash(timestamp, "GET", request_path + parse_params_to_str(params), ''), SECRET_KEY),  # 注意，我在这里添加了参数字符串到pre_hash
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "locale": "en-US",
        "Content-Type": "application/json"
    }
    
    response = requests.get(f'{BASE_URL}{request_path}', headers=headers, params=params)  # 注意，我在这里添加了params参数
    response_data = response.json()

    if response.status_code != 200:
        logger.error(f"Failed to get trackingNo after order: HTTP status code {response.status_code}, Response content: {response_data}")
        return None
    
    data = response_data["data"]
    if not isinstance(data, list) or len(data) == 0:
        logger.error("API响应中未找到数据字段或数据格式不符合预期")
        return None
    
    trackingNo = data[0].get("trackingNo")
    if trackingNo:
        logger.info(f"Successfully fetched trackingNo: {trackingNo}")

    return trackingNo




def get_current_order_trackingNo(symbol: str):
    logger.info(f"Getting current order tracking number for symbol: {symbol}")
    
    timestamp = str(get_timestamp())
    request_path = f"/api/mix/v1/trace/currentTrack?symbol={symbol}&productType={PRODUCT_TYPE}&pageSize=20&pageNo=1"
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign(pre_hash(timestamp, "GET", request_path, ''), SECRET_KEY),
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "locale": "en-US",
        "Content-Type": "application/json"
    }
    response = requests.get(f'{BASE_URL}{request_path}', headers=headers)
    response_data = response.json()
    
    if response.status_code != 200:
        logger.error(f"Failed to get current order tracking number: HTTP status code {response.status_code}, Response content: {response_data}")
        return None
    
    orders = response_data.get("data", [])
    if not orders or "trackingNo" not in orders[0]:
        logger.error("Failed to retrieve trackingNo from the currentTrack response.")
        return None

    return orders[0]["trackingNo"]

def modify_TPSL(trackingNo: str, symbol: str, stopProfitPrice: str, stopLossPrice: str):
    logger.info(f"Modifying TP/SL for tracking number: {trackingNo}")
    timestamp = str(get_timestamp())
    request_path = "/api/mix/v1/trace/modifyTPSL"
    body = json.dumps({
        "symbol": symbol,
        "trackingNo": trackingNo,
        "stopProfitPrice": stopProfitPrice,
        "stopLossPrice": stopLossPrice
    })
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign(pre_hash(timestamp, "POST", request_path, body), SECRET_KEY),
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "locale": "en-US",
        "Content-Type": "application/json"
    }

    response = requests.post(f'{BASE_URL}{request_path}', headers=headers, data=body)
    response_data = response.json()

    if response.status_code != 200 or "error" in response_data:
        logger.error(f"Error in modify_TPSL: {response_data}")
        raise Exception(f"Error in modify_TPSL: {response_data}")


def close_order(symbol: str, trackingNo: str):
    logger.info(f"Closing order for symbol: {symbol} with tracking number: {trackingNo}")
    timestamp = str(get_timestamp())
    request_path = "/api/mix/v1/trace/closeTrackOrder"
    body = json.dumps({
        "symbol": symbol,
        "trackingNo": trackingNo
    })
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign(pre_hash(timestamp, "POST", request_path, body), SECRET_KEY),
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "locale": "en-US",
        "Content-Type": "application/json"
    }

    response = requests.post(f'{BASE_URL}{request_path}', headers=headers, data=body)
    response_data = response.json()

    if response.status_code != 200 or "error" in response_data:
        logger.error(f"Error in close_order: {response_data}")
        raise Exception(f"Error in close_order: {response_data}")

# ... [rest of your functions, if any]


if __name__ == "__main__":
    try:
        available_balance = get_balance()
        print("可用数量:", available_balance)
        app.run(debug=True, port=8080)
    except Exception as e:
        logger.error(f"错误: {e}")