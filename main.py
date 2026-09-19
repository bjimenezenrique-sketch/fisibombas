import threading
import os
import bot
import web

def run_web():
    port = int(os.environ.get("PORT", 5000))
    web.app.run(host="0.0.0.0", port=port, use_reloader=False)

if __name__ == '__main__':
    # Start web server in a separate thread
    web_thread = threading.Thread(target=run_web)
    web_thread.daemon = True
    web_thread.start()
    
    # Start Telegram bot in the main thread
    bot.main()
