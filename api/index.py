import os
import json
import random
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, make_response, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
import pytz
from datetime import datetime
from firebase_admin import firestore
from flask import Flask, request, jsonify, make_response
from google import genai
from google.genai import types


app = Flask(__name__)
def init_firebase():
    if not firebase_admin._apps:
        firebase_config = os.getenv('FIREBASE_CONFIG')
        if firebase_config:
            try:
                cred_dict = json.loads(firebase_config)
                if "private_key" in cred_dict:
                    cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
            except Exception as e:
                print(f"Firebase Config Error: {e}")
        elif os.path.exists('serviceAccountKey.json'):
            cred = credentials.Certificate('serviceAccountKey.json')
            firebase_admin.initialize_app(cred)
        else:
            print("Warning: No Firebase credentials found.")
init_firebase()
client = genai.Client()
@app.route('/ask', methods=['GET', 'POST']) 
def ask():
    if request.method == "POST":
        user_prompt = request.form.get('prompt', '')
        if not user_prompt:
            return "請輸入內容", 400
        try:
            response = client.models.generate_content(
                model='gemini-3.5-flash',
                contents=user_prompt,
            )
            return response.text
        except Exception as e:
            return f"發生錯誤: {str(e)}", 500

    else:    
        # 當使用者直接打開網頁 (GET) 時，顯示輸入框畫面
        return render_template("ask.html")
@app.route("/test")
def test():

    db = firestore.client()

    docs = db.collection("今日天氣預報").get()

    result = ""

    for doc in docs:
        result += str(doc.to_dict()) + "<br><br>"

    return result

@app.route("/AI")
def AI():
    # 每次使用者拜訪該路徑時，直接使用全域的 client 呼叫模型
    response = client.models.generate_content(
        model='gemini-3.5-flash',
        contents='我想查詢靜宜大學資管系的評價？',
    )
    
    # 回傳生成的文字
    return response.text


@app.route("/webhook", methods=["POST"])
# 假設 client 已經在外部初始化（例如：client = genai.Client()）

def webhook():
    # 初始化預設回覆，避免極端狀況下變數未定義
    info = "抱歉，系統處理時發生錯誤。"
    
    try:
        # 建立 request 物件並取得 action
        req = request.get_json(force=True)
        action = req.get("queryResult", {}).get("action", "")

        # -------------------------------------------------------------
        # 行為一：撈取 Firestore 的「今日天氣預報」
        # -------------------------------------------------------------
        if action == "weatherQuery" or action == "rateChoice":

    # 從 Dialogflow 取得使用者想查詢的城市名稱
    city = req["queryResult"]["parameters"].get("city", "")

    # 統一格式
    city = city.replace("台", "臺")

    # 補上「市」
    if city and not city.endswith("市"):
        city += "市"

    info = f"我是林憲墉開發的天氣聊天機器人，正在為您查詢【{city}】的今日天氣預報：\n\n"

    db = firestore.client()
    collection_ref = db.collection("今日天氣預報")

    print(f"查詢城市: {city}")

    docs = list(
        collection_ref.where(
            "location",
            "==",
            city
        ).get()
    )

    print(f"找到資料筆數: {len(docs)}")

    result = ""

    for doc in docs:

        doc_data = doc.to_dict()

        location = doc_data.get("location", "暫無資料")
        condition = doc_data.get("condition", "暫無資料")
        max_temp = doc_data.get("max_temp", "?")
        min_temp = doc_data.get("min_temp", "?")
        pop = doc_data.get("pop", "?")
        comfort = doc_data.get("comfort", "暫無資料")

        result += f"📍 地區：{location}\n"
        result += f"☁️ 狀況：{condition}\n"
        result += f"🌡️ 氣溫：{min_temp}°C ~ {max_temp}°C\n"
        result += f"☔ 降雨機率：{pop}%\n"
        result += f"👕 舒適度：{comfort}\n\n"

    if not result:
        result = (
            f"抱歉，目前資料庫中找不到【{city}】的天氣預報資料。"
        )

    info += result

        # -------------------------------------------------------------
        # 行為二：當機器人聽不懂時 (input.unknown)，調用 Gemini AI
        # -------------------------------------------------------------
        elif action == "input.unknown":
            instruction_text = (
                "你是一個熱心且知識豐富的專業智慧助理。"
                "對於使用者的提問，請回覆重點的關鍵字，不要重述問題。"         
            )

            ai_config = types.GenerateContentConfig(
                max_output_tokens=500, 
                system_instruction=instruction_text
            )
            
            # 呼叫 Gemini AI 產生回覆
            query_text = req["queryResult"].get("queryText", "")
            response = client.models.generate_content(
                model='gemini-3.5-flash', 
                contents=query_text,
                config=ai_config,
            )

            if response.text:
                info = response.text
            else:
                info = "抱歉，我現在無法生成回應，請稍後再試。"
                
        else:
            info = "機器人收到了未知的 Action 請求。"

    except Exception as e:
        info = f"後端 Webhook 發生錯誤：{str(e)}"

    return make_response(jsonify({"fulfillmentText": info}))
@app.route("/rate")
def save_weather_to_firestore():

    url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"

    params = {
        "Authorization": os.getenv(
            "CWA_API_KEY",
            "CWA-9EB210BC-3D81-4B72-9B0C-DD6DE37E84EF"
        )
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=15
        )

        response.raise_for_status()

    except requests.exceptions.RequestException as e:
        return f"中央氣象署 API 連線失敗：{e}"

    try:
        data = response.json()
    except Exception:
        return "API 回傳資料不是合法 JSON"

    locations = data.get("records", {}).get("location", [])

    if not locations:
        return "查無天氣資料"

    db = firestore.client()
    batch = db.batch()

    taiwan_tz = pytz.timezone("Asia/Taipei")

    success_count = 0
    fail_count = 0

    for location_data in locations:

        try:

            location_name = location_data["locationName"]

            weather_elements = location_data["weatherElement"]

            element_dict = {
                element["elementName"]: element
                for element in weather_elements
            }

            required = ["Wx", "PoP", "MinT", "CI", "MaxT"]

            if not all(item in element_dict for item in required):
                print(f"{location_name} 缺少必要欄位")
                fail_count += 1
                continue

            wx_data = element_dict["Wx"]["time"][0]

            start_time = wx_data["startTime"]
            end_time = wx_data["endTime"]

            condition = element_dict["Wx"]["time"][0]["parameter"]["parameterName"]
            pop = element_dict["PoP"]["time"][0]["parameter"]["parameterName"]
            min_temp = element_dict["MinT"]["time"][0]["parameter"]["parameterName"]
            comfort = element_dict["CI"]["time"][0]["parameter"]["parameterName"]
            max_temp = element_dict["MaxT"]["time"][0]["parameter"]["parameterName"]

            def safe_int(value):
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return 0

            doc = {
                "location": location_name,
                "condition": condition,
                "pop": safe_int(pop),
                "min_temp": safe_int(min_temp),
                "max_temp": safe_int(max_temp),
                "comfort": comfort,
                "startTime": start_time,
                "endTime": end_time,
                "lastUpdate": datetime.now(
                    taiwan_tz
                ).strftime("%Y-%m-%d %H:%M:%S")
            }

            doc_ref = db.collection(
                "今日天氣預報"
            ).document(location_name)

            batch.set(doc_ref, doc)

            success_count += 1

        except Exception as e:

            print(
                f"{location_data.get('locationName','未知縣市')} 處理失敗：{e}"
            )

            fail_count += 1

    try:

        batch.commit()

    except Exception as e:

        return f"Firestore 寫入失敗：{e}"

    return (
        f"天氣資料更新完成<br>"
        f"成功：{success_count} 個縣市<br>"
        f"失敗：{fail_count} 個縣市"
    )
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/weather", methods=["GET", "POST"])
def weather_query():
    result_text = ""
    if request.method == "POST":
        city = request.form.get("city", "")
        if city:
            city = city.replace("台", "臺")
            url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001?Authorization=rdec-key-123-45678-011121314&format=JSON&locationName={city}"
            try:
                response = requests.get(url, verify=False)
                data = json.loads(response.text)
                if data["records"]["location"]:
                    weather_element = data["records"]["location"][0]["weatherElement"]
                    weather = weather_element[0]["time"][0]["parameter"]["parameterName"]
                    rain = weather_element[1]["time"][0]["parameter"]["parameterName"]
                    result_text = f"{city} 目前天氣預報：<br>{weather}，降雨機率：{rain}%"
                else:
                    result_text = "找不到該縣市，請輸入正確名稱（如：臺中市）。"
            except Exception as e:
                result_text = f"連線錯誤：{e}"
    return render_template("weather.html", result=result_text)

@app.route("/road")
def road():
    R = ""
    url = "https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=a1b899c0-511f-4e3d-b22b-814982a97e41"
    Data = requests.get(url, verify=False)
    JsonData = json.loads(Data.text)
    for item in JsonData:
        R += item["路口名稱"] + ",總共發生" + item["總件數"] + "件事故<br>"
    return R

@app.route("/movie3", methods=["GET", "POST"])
def movie3():
    db = firestore.client()
    results = []
    keyword = ""
    if request.method == "POST":
        keyword = request.form.get("keyword")
        collection_ref = db.collection("電影2A")
        docs = collection_ref.get()
        for doc in docs:
            movie = doc.to_dict()
            if keyword in movie["title"]:
                results.append({
                    "title": movie["title"],
                    "picture": movie["picture"],
                    "hyperlink": movie["hyperlink"],
                    "showDate": movie["showDate"],
                    "showLength": movie["showLength"],
                    "lastUpdate": movie["lastUpdate"]
                })
    return render_template("movie3.html", results=results, keyword=keyword)

@app.route("/movie2")
def movie2():
    url = "http://www.atmovies.com.tw/movie/next/"
    Data = requests.get(url)
    Data.encoding = "utf-8"
    sp = BeautifulSoup(Data.text, "html.parser")
    result = sp.select(".filmListAllX li")
    lastUpdate = sp.find("div", class_="smaller09").text[5:]

    for item in result:
        picture = item.find("img").get("src").replace(" ", "")
        title = item.find("div", class_="filmtitle").text
        movie_id = item.find("div", class_="filmtitle").find("a").get("href").replace("/", "").replace("movie", "")
        hyperlink = "http://www.atmovies.com.tw" + item.find("div", class_="filmtitle").find("a").get("href")
        show = item.find("div", class_="runtime").text.replace("上映日期：", "")
        show = show.replace("片長：", "")
        show = show.replace("分", "")
        showDate = show[0:10]
        showLength = show[13:]

        doc = {
            "title": title,
            "picture": picture,
            "hyperlink": hyperlink,
            "showDate": showDate,
            "showLength": showLength,
            "lastUpdate": lastUpdate
        }

        db = firestore.client()
        doc_ref = db.collection("電影2A").document(movie_id)
        doc_ref.set(doc)    
    return "近期上映電影已爬蟲及存檔完畢，網站最近更新日期為：" + lastUpdate 

@app.route("/movie1")
def movie1():
    R = ""
    url = "https://www.atmovies.com.tw/movie/next/"
    Data = requests.get(url)
    Data.encoding = "utf-8"
    sp = BeautifulSoup(Data.text, "html.parser")
    result = sp.select(".filmListAllX li")
    for item in result:
        introduce = "https://www.atmovies.com.tw" + item.find("a").get("href")
        R += "<a href=" + introduce + ">" + item.find("img").get("alt") + "</a><br>"
        post = "https://www.atmovies.com.tw" + item.find("img").get("src")
        R += "<img src=" + post + "> </img><br><br>" 
    return R    

@app.route("/spider1")
def spider1():
    R = ""
    url = "https://www1.pu.edu.tw/~tcyang/course.html"
    Data = requests.get(url)
    Data.encoding = "utf-8"
    sp = BeautifulSoup(Data.text, "html.parser")
    result = sp.select(".team-box a")
    for i in result:
        R += i.text + i.get("href") + "<br>" 
    return R

@app.route("/search", methods=["GET", "POST"])
def search():
    db = firestore.client()
    results = []
    keyword = ""
    if request.method == "POST":
        keyword = request.form.get("keyword")
        collection_ref = db.collection("靜宜資管2026a")
        docs = collection_ref.get()
        for doc in docs:
            user = doc.to_dict()
            if keyword in user["name"]:
                results.append({
                    "name": user["name"],
                    "lab": user["lab"]
                })
    return render_template("search.html", results=results, keyword=keyword)

@app.route("/read2")
def read2():
    Result = ""
    keyword = "楊"
    db = firestore.client()
    collection_ref = db.collection("靜宜資管2026B")    
    docs = collection_ref.get()
    for doc in docs: 
        teacher = doc.to_dict()
        if keyword in teacher["name"]:        
            Result += str(teacher) + "<br>"
    if Result == "":
        Result = "抱歉,查無此關鍵字姓名之老師資料"    
    return Result

@app.route("/read")
def read():
    Result = ""
    db = firestore.client()
    collection_ref = db.collection("靜宜資管2026B")    
    docs = collection_ref.order_by("lab", direction=firestore.Query.DESCENDING).get()
    for doc in docs:         
        Result += str(doc.to_dict()) + "<br>"    
    return Result

@app.route("/mis")
def course():
    return "<h1>資訊管理導論</h1><a href=/>返回首頁</a>"

@app.route("/about")
def about():
    return render_template("mis2a.html")

@app.route("/welcome", methods=["GET"])
def welcome():
    user = request.values.get("u")
    d = request.values.get("d")
    c = request.values.get("c")    
    return render_template("welcome.html", name=user, dep=d, course=c)

@app.route("/account", methods=["GET", "POST"])
def account():
    if request.method == "POST":
        user = request.form["user"]
        pwd = request.form["pwd"]
        result = "您輸入的帳號是：" + user + "; 密碼為：" + pwd 
        return result
    else:
        return render_template("account.html")

@app.route("/math", methods=["GET", "POST"])
def math():
    if request.method == "POST":
        x = int(request.form["x"])
        opt = request.form["opt"]
        y = int(request.form["y"])      
        result = "您輸入的是：" + str(x) + opt + str(y)
        
        if (opt == "/" and y == 0):
            result += "，除數不能為0"
        else:
            match opt:
                case "+":
                    r = x + y
                case "-":
                    r = x - y
                case "*":
                    r = x * y
                case "/":
                    r = x / y
                case _:
                    return "未知運算符號"
            result += "=" + str(r) + "<br><a href=/>返回首頁</a>"          
        return result
    else:
        return render_template("math.html")

@app.route('/cup', methods=["GET"])
def cup():
    action = request.values.get("action")
    result = None
    if action == 'toss':
        x1 = random.randint(0, 1)
        x2 = random.randint(0, 1)
        if x1 != x2:
            msg = "聖筊：表示神明允許、同意，或行事會順利。"
        elif x1 == 0:
            msg = "笑筊：表示神明一笑、不解，或者考慮中，行事狀況不明。"
        else:
            msg = "陰筊：表示神明否定、憤怒，或者不宜行事。"
            
        result = {
            "cup1": "/static/" + str(x1) + ".jpg",
            "cup2": "/static/" + str(x2) + ".jpg",
            "message": msg
        }
    return render_template('cup.html', result=result)

@app.route("/math2", methods=["GET", "POST"])
def math2():
    result = None
    if request.method == "POST":
        x = int(request.form.get("x"))
        opt = request.form.get("opt")
        y = int(request.form.get("y"))
        match opt:
            case "∧":
                result = x ** y
            case "√":
                if y != 0:
                    result = x ** (1/y)
                else:
                    result = "數學上不存在「0 次方根」"
            case _:
                result = "請輸入∧(次方)或√(根號)"
    return render_template("math2.html", result=result)

@app.route("/today")
def today():
    now = datetime.now()
    return render_template("today.html", datetime=str(now))
@app.route("/webdemo")
def webdemo():
    return render_template("webdemo.html")


if __name__ == "__main__":
    app.run(debug=True)
