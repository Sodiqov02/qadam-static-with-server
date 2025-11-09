from qadam_demo.server import create_app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5500, debug=True)