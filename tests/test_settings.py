from pogo_auto.settings import AppConfig

def test_default_config_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    AppConfig().to_json(path)
    loaded = AppConfig.from_json(path)
    assert loaded.scan.count == 5
    assert loaded.rename.navigation_direction == "left"
