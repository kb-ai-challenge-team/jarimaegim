def test_app_imports():
    from app.main import app
    assert app.title == "자리매김 API"
