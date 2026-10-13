from flask import Flask

app = Flask(__name__)

@app.route('/')
def hello_world():
    return "<body style='background-color: lightgreen;'><h1>Hello from Pikmin Bloom Helper! 🌸🌱</h1><p>Deployment is live and working!</p></body>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)