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
def webhook():
    # build a request object
    req = request.get_json(force=True)
    # fetch queryResult from json
    action =  req["queryResult"]["action"]

    if (action == "rateChoice"):
        rate = req["queryResult"]["parameters"]["rate"]
        info = "我是林憲墉開發的電影聊天機器人,您選擇的電影分級是：" + rate
        db = firestore.client()
        collection_ref = db.collection("本週新片含分級")
        docs = collection_ref.get()
        result = ""
        for doc in docs:
            dict = doc.to_dict()
            if rate in dict["rate"]:
                result += "片名：" + dict["title"] + "\n"
                result += "介紹：" + dict["hyperlink"] + "\n\n"
        info += result

    elif (action == "input.unknown"):
        instruction_text = (
            "你是一個熱心且知識豐富的專業智慧助理。"
            "對於使用者的提問，請回覆重點的關鍵字，不要重述問題。"         
        )


        ai_config = types.GenerateContentConfig(
            max_output_tokens=500, 
            system_instruction=instruction_text
        )
        response = client.models.generate_content(
            model='gemini-3.5-flash', 
            contents=req["queryResult"]["queryText"],
            config=ai_config,
        )

        if response.text:
            info = response.text
        else:
            info = "抱歉，我現在無法生成回應，請稍後再試。"




    return make_response(jsonify({"fulfillmentText": info}))

@app.route("/rate")#改全台天氣預報(降雨率)
def save_weather_to_firestore():
    # 1. 設定氣象署 API 網址與你的授權碼
    url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"

    params = {
        "Authorization": "CWA-9EB210BC-3D81-4B72-9B0C-DD6DE37E84EF",  # 你的授權碼
        "locationName": "全台天氣預報",  # 可以自行更改想查詢的縣市，例如 "台中市"、"高雄市"
    }

    # 2. 發送請求並取得 Response Body (JSON 格式)
    response = requests.get(url, params=params)

    if response.status_code == 200:
        data = response.json()

        # 3. 撥開 JSON 的外殼，找到臺北市的觀測資料
        # 結構對應：records -> location 清單 -> 第 0 個元素 (臺北市)
        location_data = data["records"]["location"][0]
        location_name = location_data["locationName"]

        # 取得天氣要素清單 (Wx, PoP, MinT, MaxT 等)
        weather_elements = location_data["weatherElement"]

        # 4. 解析各個天氣欄位 (取 time[0] 代表最近這一個時段，通常是未來 12 小時)
        # Wx (天氣現象，如：陰陣雨或雷雨)
        condition = weather_elements[0]["time"][0]["parameter"]["parameterName"]

        # PoP (降雨機率，如：70)
        pop = weather_elements[1]["time"][0]["parameter"]["parameterName"]

        # MinT (最低溫度，如：25)
        min_temp = weather_elements[2]["time"][0]["parameter"]["parameterName"]

        # MaxT (最高溫度)
        max_temp = weather_elements[4]["time"][0]["parameter"]["parameterName"]

        # 取得這個預報時段的結束時間，當作資料的更新參考
        end_time = weather_elements[0]["time"][0]["endTime"]

        # 5. 打包成準備存入 Firestore 的字典格式 (對應你原本的 doc)
        doc = {
            "location": location_name,  # 縣市名稱
            "condition": condition,  # 天氣現象
            "pop": int(pop),  # 降雨機率（轉成整數）
            "min_temp": int(min_temp),  # 最低溫（轉成整數）
            "max_temp": int(max_temp),  # 最高溫（轉成整數）
            "lastUpdate": end_time,  # 預報結束時間
        }

        # 6. 寫入 Firebase Firestore 資料庫
        db = firestore.client()
        # 集合名稱改為 "今日天氣预報"，文件 ID 使用縣市名稱 (例如: 臺北市)
        doc_ref = db.collection("今日天氣預報").document(location_name)
        doc_ref.set(doc)

        return f"【{location_name}】天氣資料已更新並存檔完畢！預報有效至：{end_time}"

    else:
        return f"連線失敗，錯誤代碼：{response.status_code}"


# 執行函式
# print(save_weather_to_firestore())
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
