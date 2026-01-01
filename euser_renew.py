#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EUserv 自动续期脚本
支持自动登录、验证码识别、检查到期状态、自动续期并发送 Telegram 通知
"""

from PIL import Image
import io
import ddddocr
import re
import json
import time
import base64
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from imap_tools import MailBox, AND
import sys
import os

# 兼容新版 Pillow
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

ocr = ddddocr.DdddOcr()  # 全局初始化


# ============== 配置区 ==============
# EUserv 账号信息
EUSERV_EMAIL = os.getenv("EUSERV_EMAIL")  # 德鸡登录邮箱
EUSERV_PASSWORD = os.getenv("EUSERV_PASSWORD")  #德鸡登录密码

# Telegram 配置
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")  #tg推送使用的token
TG_CHAT_ID = os.getenv("TG_CHAT_ID")  #tg推送使用的userid

#邮箱配置，用于获取pin码
IMAP_SERVER = 'imap.gmail.com'  # 如果是Gmail
EMAIL_PASS = os.getenv("EMAIL_PASS")  # IMAP服务生成的16位应用专用密码
EUSERV_PIN = '';


# ====================================

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.61 Safari/537.36"


def recognize_and_calculate(captcha_image_url, session):
    print("正在处理验证码...")
    # 方法1：尝试自动识别
    try:
        print("尝试自动识别验证码...")
        response = session.get(captcha_image_url)
        # encoded_string = base64.b64encode(response.content).decode('utf-8')
        img = Image.open(io.BytesIO(response.content)).convert('RGB')

        # img = Image.open(image_path).convert('RGB')
        
        # 颜色过滤（保留橙色文字，噪点变白）
        pixels = img.load()
        width, height = img.size
        for x in range(width):
            for y in range(height):
                r, g, b = pixels[x, y]
                if not (r > 200 and 100 < g < 220 and b < 80):  # 橙色范围，可微调
                    pixels[x, y] = (255, 255, 255)
        
        # 转灰度 + 二值化
        img = img.convert('L')
        threshold = 200  # 过滤后调高
        img = img.point(lambda x: 0 if x < threshold else 255, '1')
        
        # 去边框（可选）
        border = 10
        pixels = img.load()
        for x in range(width):
            for y in range(height):
                if x < border or x >= width - border or y < border or y >= height - border:
                    pixels[x, y] = 255
        
        output = io.BytesIO()
        img.save(output, format='PNG')
        processed_bytes = output.getvalue()
        
        # OCR 识别
        text = ocr.classification(processed_bytes).strip()
        print("OCR 识别文本:", text)  # 调试用，通常是 "6xA" 或 "6XA"
        
        # 新版解析逻辑：支持 数字 x 数字  或  数字 x 字母
        # 常见识别变体： "6xA"、"6XA"、"6 x A"、"7x8"、"7 x 8" 等
        text = text.replace(' ', '')  # 先去空格，简化
        match = re.match(r'^(\d+)[xX*×](\w)$', text)  # \w 匹配数字或字母

        if not match:
            print("无法解析格式，返回原文本:", text)
            return text  # 备用

        left = int(match.group(1))          # 左边数字
        right_str = match.group(2).upper()  # 右边字符串，转大写

        if right_str.isdigit():  # 右边是数字
            right = int(right_str)
        else:  # 右边是字母
            if 'A' <= right_str <= 'Z':
                right = ord(right_str) - ord('A') + 10
            else:
                print("右边不是有效字母，返回原文本")
                return text

        result = left * right
        print(f"{left} × {right_str} = {result}")
        return str(result)
    except Exception as e:
        print(f"⚠️  自动识别失败: {e}")

    
    # # 方法2：手动输入
    # print("\n" + "="*50)
    # print("请手动输入验证码")
    # print("="*50)
    
    # # 保存验证码图片
    # try:
    #     response = session.get(captcha_image_url)
    #     captcha_filename = 'captcha.png'
    #     with open(captcha_filename, 'wb') as f:
    #         f.write(response.content)
    #     print(f"✅ 验证码已保存到: {captcha_filename}")
    #     print(f"   请打开此文件查看验证码")
    # except Exception as e:
    #     print(f"⚠️  保存验证码失败: {e}")
    #     print(f"   请在浏览器访问: {captcha_image_url}")
    
    # # 等待用户输入
    # captcha_code = input("\n请输入验证码（如果是算术题请输入计算结果）: ").strip()
    
    # if captcha_code:
    #     print(f"✅ 您输入的验证码: {captcha_code}")
    #     return captcha_code
    # else:
    #     print("❌ 未输入验证码")
    #     return None


def get_euserv_pin():
    try:
        # 使用 MailBox 连接服务器
        with MailBox(IMAP_SERVER).login(EUSERV_EMAIL, EMAIL_PASS) as mailbox:
            # 搜索来自 no-reply@euserv.com 且包含 "PIN" 字样的最新邮件
            # reverse=True 确保从最新的邮件开始查找
            for msg in mailbox.fetch(AND(from_='no-reply@euserv.com', body='PIN'), limit=1, reverse=True):
                
                print(f"找到邮件: {msg.subject}")
                print(f"收件时间: {msg.date_str}")

                # 使用正则表达式查找 6 位数字的 PIN 码
                # \d{6} 表示匹配连续的 6 个数字
                match = re.search(r'PIN:\s*\n?(\d{6})', msg.text)
                
                if match:
                    pin = match.group(1)
                    print(f"✅ 提取到的 PIN 码为: {pin}")
                    return pin
                else:
                    # 如果格式稍有变动，尝试更宽松的匹配
                    match_fallback = re.search(r'(\d{6})', msg.text)
                    if match_fallback:
                        print(f"⚠️ 未按标准格式找到，备选匹配: {match_fallback.group(1)}")
                        return match_fallback.group(1)
                    
            print("❌ 未找到符合条件的 EUserv 邮件")
            return None

    except Exception as e:
        print(f"发生错误: {e}")
        return None

class EUserv:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.sess_id = None
        
    def login(self):
        """登录 EUserv（支持验证码）"""
        print("正在登录 EUserv...")
        
        headers = {
            'user-agent': USER_AGENT,
            'origin': 'https://www.euserv.com'
        }
        url = "https://support.euserv.com/index.iphp"
        captcha_url = "https://support.euserv.com/securimage_show.php"
        
        try:
            # 第一步：访问登录页面
            sess = self.session.get(url, headers=headers)
            sess_id_match = re.search(r'sess_id["\']?\s*[:=]\s*["\']?([a-zA-Z0-9]{30,100})["\']?', sess.text)
            if not sess_id_match:
                sess_id_match = re.search(r'sess_id=([a-zA-Z0-9]{30,100})', sess.text)
            
            if not sess_id_match:
                print("❌ 无法获取 sess_id")
                return False
            
            sess_id = sess_id_match.group(1)
            print(f"获取到 sess_id: {sess_id[:20]}...")
            
            # 第二步：访问 logo 图片
            logo_png_url = "https://support.euserv.com/pic/logo_small.png"
            self.session.get(logo_png_url, headers=headers)
            
            # 第三步：提交登录表单
            login_data = {
                'email': self.email,
                'password': self.password,
                'form_selected_language': 'en',
                'Submit': 'Login',
                'subaction': 'login',
                'sess_id': sess_id
            }
            
            response = self.session.post(url, headers=headers, data=login_data)
            response.raise_for_status()
            
            # 检查是否需要验证码
            if 'captcha' in response.text.lower():
                print("⚠️  需要验证码，正在识别...")
                
                # 识别验证码
                captcha_code = recognize_and_calculate(captcha_url, self.session)
                
                if not captcha_code:
                    print("❌ 验证码识别失败")
                    return False
                
                # 提交验证码
                captcha_data = {
                    'subaction': 'login',
                    'sess_id': sess_id,
                    'captcha_code': captcha_code
                }
                
                response = self.session.post(url, headers=headers, data=captcha_data)
                response.raise_for_status()
                
                # 再次检查是否需要验证码（识别错误的情况）
                if 'captcha' in response.text.lower():
                    print("❌ 验证码错误，登录失败")
                    return False
            
            # 检查登录是否成功
            success_checks = [
                'Hello' in response.text,
                'Confirm or change your customer data here' in response.text,
                'logout' in response.text.lower() and 'customer' in response.text.lower()
            ]
            
            if any(success_checks):
                print("✅ 登录成功")
                self.sess_id = sess_id
                return True
            else:
                print("❌ 登录失败")
                print(f"响应内容预览: {response.text[:500]}")
                return False
                
        except Exception as e:
            print(f"❌ 登录过程出现异常: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_servers(self):
        """获取服务器列表"""
        print("正在获取服务器列表...")
        
        if not self.sess_id:
            print("❌ 未登录")
            return {}
        
        url = f"https://support.euserv.com/index.iphp?sess_id={self.sess_id}"
        headers = {'user-agent': USER_AGENT, 'origin': 'https://www.euserv.com'}
        
        try:
            f = self.session.get(url=url, headers=headers)
            f.raise_for_status()
            soup = BeautifulSoup(f.text, 'html.parser')
            
            servers = {}
            for tr in soup.select('#kc2_order_customer_orders_tab_content_1 .kc2_order_table.kc2_content_table tr'):
                server_id = tr.select('.td-z1-sp1-kc')
                if not len(server_id) == 1:
                    continue
                
                action_text = tr.select('.td-z1-sp2-kc .kc2_order_action_container')[0].get_text()
                can_renew = action_text.find("Contract extension possible from") == -1
                
                server_id_text = server_id[0].get_text().strip()
                servers[server_id_text] = can_renew
            
            print(f"✅ 找到 {len(servers)} 台服务器")
            return servers
            
        except Exception as e:
            print(f"❌ 获取服务器列表失败: {e}")
            return {}
    
    def renew_server(self, order_id):
        """续期服务器"""
        print(f"正在续期服务器 {order_id}...")
        
        url = "https://support.euserv.com/index.iphp"
        headers = {
            'user-agent': USER_AGENT,
            'Host': 'support.euserv.com',
            'origin': 'https://support.euserv.com',
            'Referer': 'https://support.euserv.com/index.iphp'
        }
        
        try:
            # 选择订单
            print("步骤1: 选择订单...")
            data = {
                'Submit': 'Extend contract',
                'sess_id': self.sess_id,
                'ord_no': order_id,
                'subaction': 'choose_order',
                'show_contract_extension': '1',
                'choose_order_subaction': 'show_contract_details'
            }
            resp1 = self.session.post(url, headers=headers, data=data)
            print(f"  状态码: {resp1.status_code}")
            
            # 获取 token
            print("步骤2: 获取续期 token...")
            # data = {
            #     'sess_id': self.sess_id,
            #     'subaction': 'kc2_security_password_get_token',
            #     'prefix': 'kc2_customer_contract_details_extend_contract_',
            #     'type': '1'
            #     # 'password': self.password
            # }

            #触发发送pin码
            data = {
                'sess_id': self.sess_id,
                'subaction': 'show_kc2_security_password_dialog',
                'prefix': 'kc2_customer_contract_details_extend_contract_',
                'type': '1'
                # 'password': self.password
            }
            resp2 = self.session.post(url, headers=headers, data=data)
            resp2.raise_for_status()
            print(f"  状态码: {resp2.status_code}")
            print(f"  响应内容: {resp2.text[:500]}")
            
            # 邮箱获取pin，此处稍微等10秒，德国佬效率慢，让子弹飞一会
            print("步骤2.5: 获取pin码")
            time.sleep(3)
            EUSERV_PIN = get_euserv_pin()

            
            #验证pin，获取token
            data = {
                'sess_id': self.sess_id,
                'auth': EUSERV_PIN,
                'subaction': 'kc2_security_password_get_token',
                'prefix': 'kc2_customer_contract_details_extend_contract_',
                'type': '1',
                'ident': 'kc2_customer_contract_details_extend_contract_' + order_id
            }
            
            resp3 = self.session.post(url, headers=headers, data=data)
            print(f"  验证pin状态码: {resp3.status_code}")
            print(f"  验证pin响应: {resp3.text}")

            result = json.loads(resp3.text)
            print(f"  解析结果: {result}")
            if result.get('rs') != 'success':
                print(f"❌ 获取 token 失败: {result.get('rs', 'unknown')}")
                if 'error' in result:
                    print(f"   错误信息: {result['error']}")
                return False
            
            token = result['token']['value']
            print(f"  ✅ 获取到 token: {token[:20]}...")
            time.sleep(3)


            # 提交续期请求
            print("步骤3: 提交续期请求...")
            data = {
                'sess_id': self.sess_id,
                'ord_id': order_id,
                'subaction': 'kc2_customer_contract_details_extend_contract_term',
                'auth': token
            }
      
            resp4 = self.session.post(url, headers=headers, data=data)
            print(f"  状态码: {resp4.status_code}")
            time.sleep(3)
            
            print(f"✅ 服务器 {order_id} 续期成功")
            return True
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败: {e}")
            print(f"   原始响应: {resp2.text[:1000]}")
            return False
        except Exception as e:
            print(f"❌ 服务器 {order_id} 续期失败: {e}")
            import traceback
            traceback.print_exc()
            return False


def send_telegram(message):
    """发送 Telegram 通知"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️  未配置 Telegram")
        return
    
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=data, timeout=10)
        if response.status_code == 200:
            print("✅ Telegram 通知发送成功")
        else:
            print(f"❌ Telegram 通知失败: {response.status_code}")
    except Exception as e:
        print(f"❌ Telegram 异常: {e}")


def main():
    print("=" * 50)
    print("EUserv 自动续期脚本（支持验证码识别）")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    
    euserv = EUserv(EUSERV_EMAIL, EUSERV_PASSWORD)
    
    # 登录（最多重试3次）
    login_success = False
    for attempt in range(3):
        if attempt > 0:
            print(f"\n第 {attempt + 1} 次登录尝试...")
        
        if euserv.login():
            login_success = True
            break
        
        if attempt < 2:
            print("等待5秒后重试...")
            time.sleep(5)
    
    if not login_success:
        send_telegram("❌ EUserv 登录失败，已尝试3次")
        sys.exit(1)
    
    # 获取服务器列表
    servers = euserv.get_servers()
    
    if not servers:
        send_telegram("⚠️ 未找到任何服务器")
        sys.exit(0)
    
    # 检查并续期
    renew_results = []
    for order_id, can_renew in servers.items():
        print(f"\n检查服务器: {order_id}")
        
        if can_renew:
            print(f"⏰ 服务器 {order_id} 可以续期")
            if euserv.renew_server(order_id):
                renew_results.append(f"✅ 服务器 {order_id} 续期成功")
            else:
                renew_results.append(f"❌ 服务器 {order_id} 续期失败")
        else:
            print(f"✓ 服务器 {order_id} 暂不需要续期")
    
    # 发送通知
    if renew_results:
        message = f"<b>🔄 EUserv 续期报告</b>\n\n"
        message += f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        message += "\n".join(renew_results)
        send_telegram(message)
    else:
        print("\n✓ 所有服务器均无需续期")
        message = f"<b>✓ EUserv 检查完成</b>\n\n"
        message += f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"检查了 {len(servers)} 台服务器，均无需续期"
        send_telegram(message)
    
    print("\n" + "=" * 50)
    print("执行完成")
    print("=" * 50)


if __name__ == "__main__":
    main()