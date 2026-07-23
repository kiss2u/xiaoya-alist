#!/usr/local/bin/python3
# pylint: disable=C0103
# pylint: disable=C0114

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__license__ = "GPLv3 <https://www.gnu.org/licenses/gpl-3.0.txt>"

import threading
import time
import os
import base64
import logging
import argparse
import sys
from io import BytesIO
from json import loads
from urllib.parse import urlencode
from urllib.request import urlopen, Request

import qrcode
from flask import Flask, render_template, jsonify
from PIL import Image


flask_app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
LAST_STATUS = 0

QRCODE_APPS = (
    "web",
    "ios",
    "115ios",
    "android",
    "115android",
    "115ipad",
    "tv",
    "qandroid",
    "wechatmini",
    "alipaymini",
    "harmony",
)


def get_qrcode_token():
    """获取登录二维码，扫码可用
    GET https://qrcodeapi.115.com/api/1.0/web/1.0/token/
    :return: dict
    """
    api = "https://qrcodeapi.115.com/api/1.0/web/1.0/token/"
    return loads(urlopen(api).read())


def get_qrcode_status(payload):
    """获取二维码的状态（未扫描、已扫描、已登录、已取消、已过期等）
    GET https://qrcodeapi.115.com/get/status/
    :param payload: 请求的查询参数，取自 `login_qrcode_token` 接口响应，有 3 个
        - uid:  str
        - time: int
        - sign: str
    :return: dict
    """
    api = "https://qrcodeapi.115.com/get/status/?" + urlencode(payload)
    return loads(urlopen(api).read())


def post_qrcode_result(uid, app="web"):
    """获取扫码登录的结果并绑定设备，返回包含 cookie 的响应。

    POST https://qrcodeapi.115.com/app/1.0/{app}/1.0/login/qrcode/

    :param uid: 二维码的 uid，取自 `login_qrcode_token` 接口响应
    :param app: 扫码绑定的设备标识，必须是 `QRCODE_APPS` 中的值
    :return: dict，包含 cookie
    """
    if app not in QRCODE_APPS:
        raise ValueError(f"不支持的扫码绑定设备: {app}")

    headers = {"User-Agent": "UPhone/1.0.0"} if app == "ios" else {}
    payload = {"account": uid}
    api = f"https://qrcodeapi.115.com/app/1.0/{app}/1.0/login/qrcode/"
    request = Request(api, data=urlencode(payload).encode("utf-8"), headers=headers, method="POST")
    return loads(urlopen(request).read())


def get_qrcode(uid: str, /) -> str:
    """获取二维码图片（注意不是链接）
    :return: 一个文件对象，可以读取
    """
    return urlopen("https://qrcodeapi.115.com/api/1.0/web/1.0/qrcode?uid=" + uid)


def qrcode_token_url(uid: str, /) -> str:
    """获取二维码图片的扫码链接
    :return: 扫码链接
    """
    return "http://115.com/scan/dg-" + uid


# pylint: disable=W0603
def poll_qrcode_status(_qrcode_token, qrcode_app):
    """
    循环等待扫码
    """
    global LAST_STATUS
    while True:
        time.sleep(1)
        resp = get_qrcode_status(_qrcode_token)
        _status = resp["data"].get("status")
        if _status == 2:
            resp = post_qrcode_result(_qrcode_token["uid"], qrcode_app)
            cookie_data = resp["data"]["cookie"]
            cookie_str = "; ".join(f"{key}={value}" for key, value in cookie_data.items())
            if sys.platform.startswith("win32"):
                with open("115_cookie.txt", "w", encoding="utf-8") as f:
                    f.write(cookie_str)
            else:
                with open("/data/115_cookie.txt", "w", encoding="utf-8") as f:
                    f.write(cookie_str)
            logging.info("扫码成功, cookie 已写入文件！")
            LAST_STATUS = 1
        elif _status in [-1, -2]:
            logging.error("扫码失败")
            LAST_STATUS = 2


@flask_app.route("/")
def index():
    """
    网页扫码首页
    """
    try:
        _qrcode_token = get_qrcode_token()["data"]
        uid = _qrcode_token["uid"]
        qrcode_image_io = get_qrcode(uid)
        qrcode_image = Image.open(qrcode_image_io)
        buffered = BytesIO()
        qrcode_image.save(buffered, format="PNG")
        qrcode_image_b64_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        threading.Thread(target=poll_qrcode_status, args=(_qrcode_token, flask_app.config["QRCODE_APP"])).start()
        return render_template("index.html", qrcode_image_b64_str=qrcode_image_b64_str)
    except Exception as e:  # pylint: disable=W0718
        logging.error("错误：%s", e)
        sys.exit(1)


@flask_app.route("/status")
def status():
    """
    扫码状态获取
    """
    if LAST_STATUS == 1:
        return jsonify({"status": "success"})
    elif LAST_STATUS == 2:
        return jsonify({"status": "failure"})
    else:
        return jsonify({"status": "unknown"})


@flask_app.route("/shutdown_server", methods=["GET"])
def shutdown():
    """
    退出进程
    """
    os._exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="115 Cookie")
    parser.add_argument("--qrcode_mode", type=str, required=True, help="扫码模式")
    parser.add_argument(
        "--qrcode_app",
        type=str,
        choices=QRCODE_APPS,
        default="alipaymini",
        help="扫码绑定设备",
    )
    args = parser.parse_args()
    if args.qrcode_mode == "web":
        flask_app.config["QRCODE_APP"] = args.qrcode_app
        flask_app.run(host="0.0.0.0", port=34256)
    elif args.qrcode_mode == "shell":
        try:
            qrcode_token = get_qrcode_token()["data"]
            threading.Thread(
                target=poll_qrcode_status,
                args=(
                    qrcode_token,
                    args.qrcode_app,
                ),
            ).start()
            qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=5, border=4)
            qr.add_data(qrcode_token_url(qrcode_token["uid"]))
            qr.make(fit=True)
            logging.info("请打开 115网盘 扫描此二维码！")
            qr.print_ascii(invert=True, tty=sys.stdout.isatty())
            while LAST_STATUS not in [1, 2]:
                time.sleep(1)
            os._exit(0)
        except Exception as e:  # pylint: disable=W0718
            logging.error("错误：%s", e)
            sys.exit(1)
    else:
        logging.error("未知的扫码模式")
        os._exit(1)
