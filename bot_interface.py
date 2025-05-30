import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)
import threading
import webbrowser
import asyncio
from flask import Flask, render_template_string, request, jsonify
from datetime import datetime
from quotexapi.stable_api import Quotex
import os

# حالة البوت العالمية
bot_thread = None
bot_running = False
bot_paused = False
current_bot = None  # سيحتوي على كائن البوت النشط

# قائمة لحفظ السجلات
log_records = []

def log(msg: str, msg_type: str = 'info'):
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    # تقليل طول الرسائل الطويلة
    if len(msg) > 150:
        msg = msg[:150] + "..."
    
    # إضافة ألوان حسب نوع الرسالة
    if msg_type == 'success':
        colored_msg = f"[{timestamp}] \\033[92m{msg}\\033[0m"  # أخضر
    elif msg_type == 'error':
        colored_msg = f"[{timestamp}] \\033[91m{msg}\\033[0m"  # أحمر
    elif msg_type == 'warning':
        colored_msg = f"[{timestamp}] \\033[93m{msg}\\033[0m"  # أصفر
    elif msg_type == 'trade_up':
        colored_msg = f"[{timestamp}] \\033[94m▲ UP: {msg}\\033[0m"  # أزرق فاتح
    elif msg_type == 'trade_down':
        colored_msg = f"[{timestamp}] \\033[95m▼ DOWN: {msg}\\033[0m"  # أرجواني
    elif msg_type == 'profit':
        colored_msg = f"[{timestamp}] \\033[92m💰 {msg}\\033[0m"  # أخضر
    elif msg_type == 'loss':
        colored_msg = f"[{timestamp}] \\033[91m💸 {msg}\\033[0m"  # أحمر
    else:
        colored_msg = f"[{timestamp}] {msg}"
    
    log_records.append(colored_msg)
    if len(log_records) > 100:
        log_records.pop(0)

app = Flask(__name__)

HTML = '''
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bot Control Panel</title>
  <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
  <style>
    :root {
      --primary-color: #4361ee;
      --secondary-color: #3f37c9;
      --accent-color: #4895ef;
      --success-color: #4cc9f0;
      --danger-color: #f72585;
      --light-color: #f8f9fa;
      --dark-color: #212529;
      --gray-color: #6c757d;
      --up-color: #3a86ff;
      --down-color: #ff006e;
      --profit-color: #38b000;
      --loss-color: #d00000;
      --pause-color: #ffaa00;
    }
    
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }
    
    body {
      font-family: 'Tajawal', Arial, sans-serif;
      background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
      color: var(--dark-color);
      line-height: 1.6;
      min-height: 100vh;
      padding: 20px;
    }
    
    .container {
      max-width: 1000px;
      margin: 0 auto;
      background-color: white;
      border-radius: 15px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
      overflow: hidden;
    }
    
    header {
      background: linear-gradient(to right, var(--primary-color), var(--secondary-color));
      color: white;
      padding: 20px;
      text-align: center;
    }
    
    h1 {
      font-size: 2rem;
      margin-bottom: 10px;
    }
    
    .status-badge {
      display: inline-block;
      padding: 5px 15px;
      border-radius: 20px;
      font-weight: bold;
      margin-top: 10px;
    }
    
    .status-running, .status-started {
      background-color: var(--success-color);
    }
    
    .status-stopped {
      background-color: var(--danger-color);
    }
    
    .status-paused {
      background-color: var(--pause-color);
    }
    
    .panel {
      padding: 30px;
    }
    
    .form-group {
      margin-bottom: 20px;
    }
    
    label {
      display: block;
      margin-bottom: 8px;
      font-weight: 500;
      color: var(--dark-color);
    }
    
    input, select {
      width: 100%;
      padding: 12px 15px;
      border: 1px solid #ddd;
      border-radius: 8px;
      font-size: 16px;
      transition: all 0.3s;
    }
    
    input:focus, select:focus {
      border-color: var(--accent-color);
      outline: none;
      box-shadow: 0 0 0 3px rgba(67, 97, 238, 0.2);
    }
    
    button {
      background: linear-gradient(to right, var(--primary-color), var(--secondary-color));
      color: white;
      border: none;
      padding: 12px 20px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 16px;
      font-weight: bold;
      width: 100%;
      transition: all 0.3s;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    
    button:hover {
      background: linear-gradient(to right, var(--secondary-color), var(--primary-color));
      transform: translateY(-2px);
      box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
    }
    
    button i {
      margin-right: 8px;
    }
    
    .logs-container {
      margin-top: 30px;
      border-top: 1px solid #eee;
      padding-top: 20px;
    }
    
    .logs-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 15px;
    }
    
    .logs-content {
      background-color: #1a1a1a;
      border-radius: 8px;
      padding: 15px;
      height: 300px;
      overflow-y: auto;
      font-family: 'Courier New', monospace;
      font-size: 14px;
      border: 1px solid #333;
      color: #e0e0e0;
    }
    
    .log-entry {
      margin-bottom: 5px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    
    .log-time {
      color: #999;
    }
    
    .log-success {
      color: var(--success-color);
    }
    
    .log-error {
      color: var(--danger-color);
    }
    
    .log-warning {
      color: #ffcc00;
    }
    
    .log-trade-up {
      color: var(--up-color);
      font-weight: bold;
    }
    
    .log-trade-down {
      color: var(--down-color);
      font-weight: bold;
    }
    
    .log-profit {
      color: var(--profit-color);
      font-weight: bold;
    }
    
    .log-loss {
      color: var(--loss-color);
      font-weight: bold;
    }
    
    .control-buttons {
      display: flex;
      gap: 10px;
      margin-top: 20px;
    }
    
    .control-buttons button {
      flex: 1;
    }
    
    .pause-btn {
      background: linear-gradient(to right, var(--pause-color), #ff9500);
    }
    
    .pause-btn:hover {
      background: linear-gradient(to right, #ff9500, var(--pause-color));
    }
    
    .loading-overlay {
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background-color: rgba(0, 0, 0, 0.7);
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      z-index: 1000;
      color: white;
      display: none;
    }
    
    .spinner {
      width: 50px;
      height: 50px;
      border: 5px solid rgba(255, 255, 255, 0.3);
      border-radius: 50%;
      border-top-color: white;
      animation: spin 1s ease-in-out infinite;
      margin-bottom: 20px;
    }
    
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    
    .notification {
      position: fixed;
      top: 20px;
      right: 20px;
      padding: 15px 20px;
      background-color: var(--success-color);
      color: white;
      border-radius: 8px;
      box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
      transform: translateX(200%);
      transition: transform 0.3s ease;
      z-index: 1000;
    }
    
    .notification.show {
      transform: translateX(0);
    }
    
    @media (max-width: 768px) {
      .container {
        border-radius: 0;
      }
      
      .panel {
        padding: 20px;
      }
      
      .control-buttons {
        flex-direction: column;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1><i class="fas fa-robot"></i> Bot Control Panel</h1>
      <div class="status-badge status-{{ status.lower().replace(' ', '-') }}">
        {{ status }}{% if is_paused %} (Paused){% endif %}
      </div>
    </header>
    
    <div class="panel">
      <form id="assetsForm" method="post" action="/load_assets">
        <div class="form-group">
          <label for="activation_code"><i class="fas fa-key"></i> Activation Code:</label>
          <input type="text" id="activation_code" name="activation_code" required>
        </div>
        
        <div class="form-group">
          <label for="email"><i class="fas fa-envelope"></i> Email:</label>
          <input type="email" id="email" name="email" required>
        </div>
        
        <div class="form-group">
          <label for="password"><i class="fas fa-lock"></i> Password:</label>
          <input type="password" id="password" name="password" required>
        </div>
        
        <div class="form-group">
          <label for="mode"><i class="fas fa-user-tag"></i> Account Type:</label>
          <select id="mode" name="mode">
            <option value="PRACTICE">Demo Account</option>
            <option value="REAL">Real Account</option>
          </select>
        </div>
        
        <button type="submit" id="loadAssetsBtn">
          <i class="fas fa-download"></i> Load Available Pairs
        </button>
      </form>

      {% if symbols %}
      <form id="startForm" method="post" action="/start" style="margin-top: 30px;">
        <input type="hidden" name="activation_code" value="{{ activation_code }}">
        <input type="hidden" name="email" value="{{ email }}">
        <input type="hidden" name="password" value="{{ password }}">
        <input type="hidden" name="mode" value="{{ mode }}">

        <div class="form-group">
          <label for="amount"><i class="fas fa-money-bill-wave"></i> Trade Amount ($):</label>
          <input type="number" step="0.01" id="amount" name="amount" required>
        </div>
        
        <div class="form-group">
          <label for="symbol"><i class="fas fa-chart-line"></i> Asset Symbol:</label>
          <select id="symbol" name="symbol" required>
            {% for sym in symbols %}
              <option value="{{ sym }}">{{ sym }}</option>
            {% endfor %}
          </select>
        </div>
        
        <button type="submit" id="startBotBtn">
          <i class="fas fa-play"></i> Start Bot
        </button>
      </form>
      {% endif %}

      {% if bot_running %}
      <div class="control-buttons">
        <form method="post" action="/pause" id="pauseForm">
          <button type="submit" class="pause-btn" id="pauseBtn" {% if is_paused %}disabled{% endif %}>
            <i class="fas fa-pause"></i> Pause Bot
          </button>
        </form>
        
        <form method="post" action="/resume" id="resumeForm">
          <button type="submit" id="resumeBtn" {% if not is_paused %}disabled{% endif %}>
            <i class="fas fa-play"></i> Resume Bot
          </button>
        </form>
      </div>
      {% endif %}

      <div class="logs-container">
        <div class="logs-header">
          <h3><i class="fas fa-clipboard-list"></i> Bot Logs</h3>
        </div>
        <div class="logs-content" id="logcontent"></div>
      </div>
    </div>
  </div>
  
  <div class="loading-overlay" id="loadingOverlay">
    <div class="spinner"></div>
    <h2 id="loadingText">جاري تحميل الأصول المتاحة...</h2>
  </div>
  
  <div class="notification" id="notification">
    <i class="fas fa-check-circle"></i> <span id="notificationText">تم التحميل بنجاح</span>
  </div>

  <script>
    // دالة لتحويل أكواد الألوان إلى كلاسات CSS
    function ansiToHtml(text) {
      const replacements = [
        { regex: /\\033\\[92m(.*?)\\033\\[0m/g, replacement: '<span class="log-success">$1</span>' },
        { regex: /\\033\\[91m(.*?)\\033\\[0m/g, replacement: '<span class="log-error">$1</span>' },
        { regex: /\\033\\[93m(.*?)\\033\\[0m/g, replacement: '<span class="log-warning">$1</span>' },
        { regex: /\\033\\[94m(.*?)\\033\\[0m/g, replacement: '<span class="log-trade-up">$1</span>' },
        { regex: /\\033\\[95m(.*?)\\033\\[0m/g, replacement: '<span class="log-trade-down">$1</span>' },
        { regex: /💰(.*?)\\033\\[0m/g, replacement: '<span class="log-profit">💰$1</span>' },
        { regex: /💸(.*?)\\033\\[0m/g, replacement: '<span class="log-loss">💸$1</span>' },
        { regex: /\[(.*?)\]/g, replacement: '<span class="log-time">[$1]</span>' }
      ];
      
      let html = text;
      replacements.forEach(r => {
        html = html.replace(r.regex, r.replacement);
      });
      
      return html;
    }

    // دالة لجلب السجلات وتحديث الـ <pre>
    async function fetchLogs() {
      try {
        const res = await fetch('/logs');
        const data = await res.json();
        const logContent = document.getElementById('logcontent');
        
        // تحويل السجلات إلى HTML مع الألوان
        const logsHtml = data.logs.map(log => {
          return `<div class="log-entry">${ansiToHtml(log)}</div>`;
        }).join('');
        
        logContent.innerHTML = logsHtml;
        logContent.scrollTop = logContent.scrollHeight;
      } catch (e) {
        console.error(e);
      }
    }
    
    // إظهار رسالة الانتظار
    function showLoading(text) {
      const overlay = document.getElementById('loadingOverlay');
      const loadingText = document.getElementById('loadingText');
      loadingText.textContent = text;
      overlay.style.display = 'flex';
    }
    
    // إخفاء رسالة الانتظار
    function hideLoading() {
      document.getElementById('loadingOverlay').style.display = 'none';
    }
    
    // إظهار الإشعار
    function showNotification(text, isSuccess = true) {
      const notification = document.getElementById('notification');
      const notificationText = document.getElementById('notificationText');
      
      notificationText.textContent = text;
      notification.style.backgroundColor = isSuccess ? '#4cc9f0' : '#f72585';
      
      notification.classList.add('show');
      
      setTimeout(() => {
        notification.classList.remove('show');
      }, 3000);
    }
    
    // جلب السجلات عند التحميل ومن ثم كل ثانيتين
    fetchLogs();
    setInterval(fetchLogs, 2000);
    
    // إضافة معالج الأحداث للنماذج
    document.getElementById('assetsForm')?.addEventListener('submit', function(e) {
      showLoading('جاري التحقق من البيانات وتحميل الأصول...');
    });
    
    document.getElementById('startForm')?.addEventListener('submit', function(e) {
      showLoading('جاري تشغيل البوت، الرجاء الانتظار...');
    });
    
    document.getElementById('pauseForm')?.addEventListener('submit', function(e) {
      showLoading('جاري إيقاف البوت مؤقتاً...');
    });
    
    document.getElementById('resumeForm')?.addEventListener('submit', function(e) {
      showLoading('جاري استئناف عمل البوت...');
    });
    
    // إخفاء رسالة الانتظار عند حدوث خطأ في الصفحة
    window.addEventListener('error', function() {
      hideLoading();
      showNotification('حدث خطأ أثناء المعالجة', false);
    });
  </script>
</body>
</html>
'''

@app.route('/', methods=['GET'])
def index():
    status = "Running" if bot_running else "Stopped"
    if bot_running and bot_paused:
        status = "Paused"
    return render_template_string(HTML,
        status=status,
        symbols=None,
        bot_running=bot_running,
        is_paused=bot_paused
    )

@app.route('/load_assets', methods=['POST'])
def load_assets():
    global bot_running, bot_paused
    
    activation_code = request.form['activation_code']
    email = request.form['email']
    password = request.form['password']
    mode = request.form['mode']

    client = Quotex(email=email, password=password, lang="en")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    async def connect_and_fetch():
        while True:
            if await client.connect(): break
            await asyncio.sleep(1)
        client.change_account(mode)
        assets = await client.get_all_assets()
        return [a for a in assets if isinstance(a, str)]
    symbols = loop.run_until_complete(connect_and_fetch())
    loop.close()

    status = "Stopped"
    return render_template_string(HTML,
        status=status,
        logs=log_records,
        symbols=symbols,
        activation_code=activation_code,
        email=email,
        password=password,
        mode=mode,
        bot_running=bot_running,
        is_paused=bot_paused
    )

@app.route('/start', methods=['POST'])
def start_route():
    global bot_thread, bot_running, bot_paused, current_bot
    
    config = {
        'activation_code': request.form['activation_code'],
        'email': request.form['email'],
        'password': request.form['password'],
        'mode': request.form['mode'],
        'amount': float(request.form['amount']),
        'symbol': request.form['symbol'],
        'logger': log
    }
    
    if not bot_running:
        from bot import TradingBot
        current_bot = TradingBot(config)
        bot_thread = threading.Thread(
            target=current_bot.run,
            daemon=True
        )
        bot_thread.start()
        bot_running = True
        bot_paused = False
        status = "Started"
        log("تم تشغيل البوت بنجاح", "success")
    else:
        status = "Already Running"
    
    return render_template_string(HTML,
        status=status,
        symbols=None,
        bot_running=bot_running,
        is_paused=bot_paused
    )

@app.route('/pause', methods=['POST'])
def pause_bot():
    global bot_paused, current_bot
    
    if current_bot:
        current_bot.pause()
        bot_paused = True
        log("تم إيقاف البوت مؤقتاً", "warning")
        return jsonify(success=True, message="Bot paused")
    else:
        return jsonify(success=False, message="No active bot to pause")

@app.route('/resume', methods=['POST'])
def resume_bot():
    global bot_paused, current_bot
    
    if current_bot:
        current_bot.resume()
        bot_paused = False
        log("تم استئناف عمل البوت", "success")
        return jsonify(success=True, message="Bot resumed")
    else:
        return jsonify(success=False, message="No active bot to resume")

@app.route('/logs', methods=['GET'])
def get_logs():
    return jsonify(logs=log_records)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)